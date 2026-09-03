"""Views of the merge plugin.

Four routes drive the dataset merge workflow:

- ``merge.select_search`` / ``merge.select_card`` — HTMX fragments behind the
  "start merge" modal that pick the two datasets and show compatibility.
- ``merge.review`` — the full review page where the surviving dataset's final
  metadata and resources are chosen and the merge is applied.
- ``merge.cleanup`` — retry page for soft-deleting the source when that step
  failed after the base was already updated.
"""

from __future__ import annotations

import logging
from typing import Any

from flask import Blueprint, Response, make_response
from flask.views import MethodView

import ckan.plugins.toolkit as tk
from ckan import types

from ckanext.dataset_merge import const

__all__ = ["bp"]

bp = Blueprint("merge", __name__)
log = logging.getLogger(__name__)


@bp.errorhandler(tk.ObjectNotFound)
def not_found_handler(error: tk.ObjectNotFound) -> tuple[str, int]:
    """Generic handler for ObjectNotFound exception."""
    return (
        tk.render(
            "error_document_template.html",
            {
                "code": 404,
                "content": tk._(f"Object not found: {error.message}"),
                "name": "Not found",
            },
        ),
        404,
    )


@bp.errorhandler(tk.NotAuthorized)
def not_authorized_handler(error: tk.NotAuthorized) -> tuple[str, int]:
    """Generic handler for NotAuthorized exception."""
    return (
        tk.render(
            "error_document_template.html",
            {
                "code": 403,
                "content": error.message or tk._("Not authorized to view this page"),
                "name": "Not authorized",
            },
        ),
        403,
    )


@bp.get("/dataset/merge/select/search/<role>")
def select_search(role: str) -> str | tuple[str, int]:
    """Search datasets the current user can edit for one merge side."""
    if role not in {"base", "source"}:
        return "", 404

    query = tk.request.args.get(f"{role}_query", "").strip()
    datasets: list[dict[str, Any]] = []

    if len(query) >= const.MERGE_SEARCH_MIN_LENGTH:
        context = types.Context(user=tk.current_user.name)

        # CKAN's quoted multi-word autocomplete query does not match an incomplete final title word.
        query_words = query.split()
        autocomplete_query = query_words[-1]
        if len(autocomplete_query) < const.MERGE_SEARCH_MIN_LENGTH:
            autocomplete_query = query_words[0]

        candidates = tk.get_action("package_autocomplete")(
            context,
            {
                "q": autocomplete_query,
                "limit": const.MERGE_AUTOCOMPLETE_LIMIT,
            },
        )
        query_lower = query.lower()

        for candidate in candidates:
            if query_lower not in candidate["name"].lower() and query_lower not in candidate["title"].lower():
                continue

            try:
                tk.check_access("package_update", tk.fresh_context(context), {"id": candidate["name"]})
                dataset = tk.get_action("package_show")(tk.fresh_context(context), {"id": candidate["name"]})
            except (tk.NotAuthorized, tk.ObjectNotFound):
                continue

            if dataset["id"] in {
                tk.request.args.get("base_id"),
                tk.request.args.get("source_id"),
            }:
                continue

            datasets.append(dataset)

            if len(datasets) == const.MERGE_SEARCH_LIMIT:
                break

    return tk.render(
        "merge/selector/search_results.html",
        {"datasets": datasets, "query": query, "role": role},
    )


@bp.get("/dataset/merge/select/card/<role>")
def select_card(role: str) -> Response | tuple[str, int]:
    """Select or clear one dataset and refresh merge compatibility."""
    if role not in {"base", "source"}:
        return "", 404

    context = types.Context(user=tk.current_user.name)
    dataset_id = tk.request.args.get("dataset_id")
    base_id = tk.request.args.get("base_id") or None
    source_id = tk.request.args.get("source_id") or None
    dataset = None
    selection_error = None

    if role == "base":
        base_id = None
        other_id = source_id
    else:
        source_id = None
        other_id = base_id

    if dataset_id and dataset_id == other_id:
        selection_error = tk._("Choose two different datasets to merge.")
    elif dataset_id:
        try:
            tk.check_access("package_update", tk.fresh_context(context), {"id": dataset_id})
            dataset = tk.get_action("package_show")(tk.fresh_context(context), {"id": dataset_id})
        except (tk.NotAuthorized, tk.ObjectNotFound):
            selection_error = tk._("You can only select datasets that you are allowed to edit.")

    if dataset:
        if role == "base":
            base_id = dataset["id"]
        else:
            source_id = dataset["id"]

    compatibility = None
    compatibility_error = None

    if base_id and source_id:
        try:
            compatibility = tk.get_action("merge_compatibility")(
                context,
                {"base_id": base_id, "source_id": source_id},
            )
        except (tk.NotAuthorized, tk.ObjectNotFound, tk.ValidationError):
            compatibility_error = tk._("The selected datasets are no longer available for this merge.")

    return make_response(
        tk.render(
            "merge/selector/card_response.html",
            {
                "role": role,
                "dataset": dataset,
                "selection_error": selection_error,
                "base_id": base_id,
                "source_id": source_id,
                "compatibility": compatibility,
                "compatibility_error": compatibility_error,
            },
        )
    )


class ReviewView(MethodView):
    """Choose the surviving dataset's final metadata and resources, then merge."""

    def _context(self) -> types.Context:
        return types.Context(user=tk.current_user.name)

    def get(self, base_id: str, source_id: str) -> str:
        """Show the merge review choices for two datasets."""
        return self._render(base_id, source_id)

    def post(self, base_id: str, source_id: str) -> str | Response:
        """Apply the confirmed merge, then soft-delete the source."""
        if tk.request.form.get("confirm_merge") != "1":
            tk.h.flash_error(tk._("Review the final dataset preview and confirm the merge before continuing."))
            return self._render(base_id, source_id)

        context = self._context()
        data_dict: dict[str, Any] = {
            "base_id": base_id,
            "source_id": source_id,
            "metadata_choices": {
                key.removeprefix("metadata_"): value
                for key, value in tk.request.form.items()
                if key.startswith("metadata_")
            },
            "resource_ids": tk.request.form.getlist("resource_ids"),
        }

        try:
            result = tk.get_action("merge_apply_to_base")(context, data_dict)
        except tk.ValidationError as error:
            for field, message in error.error_summary.items():
                tk.h.flash_error(f"{field}: {message}")
            return self._render(base_id, source_id)

        try:
            tk.get_action("merge_cleanup_source")(
                context,
                {
                    "base_id": result["base"]["id"],
                    "source_id": result["source_id"],
                },
            )
        except Exception:  # noqa: BLE001
            log.exception("Dataset merge cleanup failed for source %s", result["source_id"])
            tk.h.flash_error(
                tk._("Dataset A was updated successfully, but Dataset B could not be deleted. Retry cleanup below.")
            )
            return tk.redirect_to(
                "merge.cleanup",
                base_id=result["base"]["id"],
                source_id=result["source_id"],
            )

        tk.h.flash_success(tk._("Datasets merged successfully. Dataset B was deleted."))
        return tk.redirect_to(f"{result['base']['type']}.read", id=result["base"]["name"])

    def _render(self, base_id: str, source_id: str) -> str:
        context = self._context()

        try:
            base = tk.get_action("package_show")(tk.fresh_context(context), {"id": base_id})
            source = tk.get_action("package_show")(tk.fresh_context(context), {"id": source_id})

            comparison = tk.get_action("merge_metadata_comparison")(
                context,
                {"base_id": base["id"], "source_id": source["id"]},
            )
        except (tk.ObjectNotFound, tk.ValidationError) as error:
            raise tk.ObjectNotFound(tk._("Dataset not found")) from error

        return tk.render(
            "merge/review.html",
            {
                "comparison": comparison,
                "base": base,
                "source": source,
            },
        )


class CleanupView(MethodView):
    """Show or retry cleanup after Dataset A was updated."""

    def _context(self) -> types.Context:
        return types.Context(user=tk.current_user.name)

    def get(self, base_id: str, source_id: str) -> str:
        """Show the cleanup retry page."""
        return self._render(base_id, source_id)

    def post(self, base_id: str, source_id: str) -> Response:
        """Retry soft-deleting the source dataset."""
        context = self._context()

        try:
            tk.get_action("merge_cleanup_source")(context, {"base_id": base_id, "source_id": source_id})
        except Exception:  # noqa: BLE001
            log.exception("Dataset merge cleanup retry failed for source %s", source_id)
            tk.h.flash_error(tk._("Dataset B could not be deleted. Dataset A remains merged; try cleanup again."))
            return tk.redirect_to(
                "merge.cleanup",
                base_id=base_id,
                source_id=source_id,
            )

        base = tk.get_action("package_show")(tk.fresh_context(context), {"id": base_id})
        tk.h.flash_success(tk._("Dataset cleanup completed. Dataset B was deleted."))
        return tk.redirect_to(f"{base['type']}.read", id=base["name"])

    def _render(self, base_id: str, source_id: str) -> str:
        context = self._context()
        return tk.render(
            "merge/cleanup.html",
            {
                "base": tk.get_action("package_show")(tk.fresh_context(context), {"id": base_id}),
                "source": tk.get_action("package_show")(tk.fresh_context(context), {"id": source_id}),
            },
        )


bp.add_url_rule(
    "/dataset/merge/<base_id>/<source_id>",
    view_func=ReviewView.as_view("review"),
)
bp.add_url_rule(
    "/dataset/merge/<base_id>/<source_id>/cleanup",
    view_func=CleanupView.as_view("cleanup"),
)
