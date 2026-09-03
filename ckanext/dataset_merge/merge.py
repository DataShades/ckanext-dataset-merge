from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse
from uuid import uuid4

from werkzeug.datastructures import FileStorage

import ckan.plugins as p
import ckan.plugins.toolkit as tk
from ckan import logic, model
from ckan.lib import files, uploader
from ckan.types import Context

from ckanext.dataset_merge.types import (
    ApplyMergeToBaseResult,
    CompatibilityReason,
    DatasetSchemaIdentity,
    MergeCleanupResult,
    MergeCompatibilityResult,
    MergeMetadataComparisonResult,
    MetadataComparisonField,
    MetadataValueState,
    ResolvedMergeDecisions,
)

MIGRATION_REQUIRED_MESSAGE = tk._("Migrate both datasets to the same schema type and exact version before merging.")
SAME_DATASET_MESSAGE = tk._("Choose two different datasets to merge.")
SAME_TYPE_MESSAGE = tk._("Both datasets must be the same type to merge.")
MERGE_PACKAGE_UPDATE_FLAG = "_merge_package_update"


def _dynamic_schemas_enabled() -> bool:
    """Report whether the optional ``scheming_dynamic`` plugin is active."""
    return p.plugin_loaded("scheming_dynamic")


def check_merge_compatibility(
    context: Context,
    base_id: str,
    source_id: str,
) -> MergeCompatibilityResult:
    """Compare two visible datasets to decide whether they can be merged.

    With ``scheming_dynamic`` active and at least one dataset pinned to a
    schema version, both datasets must share the exact same pinned schema
    type and version. Otherwise the datasets only have to be the same
    dataset type.
    """
    base = _get_schema_identity(context, base_id)
    source = _get_schema_identity(context, source_id)

    if source_id == base_id:
        return _incompatible(
            base,
            source,
            reason="same_dataset",
            message=SAME_DATASET_MESSAGE,
            migration_required=False,
        )

    if base["schema_version"] is not None or source["schema_version"] is not None:
        return _pinned_schema_compatibility(base, source)

    if base["schema_type"] != source["schema_type"]:
        return _incompatible(
            base,
            source,
            reason="type_mismatch",
            message=SAME_TYPE_MESSAGE,
            migration_required=False,
        )

    return _compatible(base, source)


def _pinned_schema_compatibility(
    base: DatasetSchemaIdentity,
    source: DatasetSchemaIdentity,
) -> MergeCompatibilityResult:
    """Require an exact pinned schema type + version match on both datasets."""
    if base["schema_version"] is None or source["schema_version"] is None:
        return _migration_required(base, source, "schema_pin_missing")

    if base["schema_type"] != source["schema_type"]:
        return _migration_required(base, source, "schema_type_mismatch")

    if base["schema_version"] != source["schema_version"]:
        return _migration_required(base, source, "schema_version_mismatch")

    return _compatible(base, source)


def compare_merge_metadata(
    context: Context,
    base_id: str,
    source_id: str,
) -> MergeMetadataComparisonResult:
    """Compare schema-defined metadata without changing either dataset."""
    compatibility = check_merge_compatibility(context, base_id, source_id)
    if not compatibility["compatible"]:
        return {
            "compatibility": compatibility,
            "metadata_fields": [],
            "resources": {"base": [], "source": []},
        }

    base = _get_dataset(context, base_id)
    source = _get_dataset(context, source_id)
    schema = _get_entity_schema(base)

    fields = [
        _compare_metadata_field(field, base, source)
        for field in schema["dataset_fields"]
        if field["field_name"] != "type"
    ]
    return {
        "compatibility": compatibility,
        "metadata_fields": fields,
        "resources": {
            "base": base["resources"],
            "source": source["resources"],
        },
    }


def resolve_merge_decisions(
    context: Context,
    base_id: str,
    source_id: str,
    metadata_choices: dict[str, str],
    resource_ids: list[str],
) -> ResolvedMergeDecisions:
    """Resolve submitted choices without changing either dataset."""
    comparison = compare_merge_metadata(context, base_id, source_id)
    compatibility = comparison["compatibility"]
    if not compatibility["compatible"]:
        message = compatibility["message"] or MIGRATION_REQUIRED_MESSAGE
        raise tk.ValidationError({"source_id": [message]})

    _validate_metadata_choices(comparison["metadata_fields"], metadata_choices)
    selected_resource_ids = set(resource_ids)
    available_resource_ids = {
        resource["id"] for resources in comparison["resources"].values() for resource in resources
    }
    if selected_resource_ids - available_resource_ids:
        raise tk.ValidationError({"resource_ids": [tk._("A selected resource does not belong to either dataset.")]})

    return {
        "metadata": {
            field["field_name"]: _selected_metadata_value(field, metadata_choices)
            for field in comparison["metadata_fields"]
        },
        "resources": {
            source_name: [resource["id"] for resource in resources if resource["id"] in selected_resource_ids]
            for source_name, resources in comparison["resources"].items()
        },
    }


def apply_merge_to_base(
    context: Context,
    base_id: str,
    source_id: str,
    metadata_choices: dict[str, str],
    resource_ids: list[str],
) -> ApplyMergeToBaseResult:
    """Apply the final selected content to A without deleting B."""
    decisions = resolve_merge_decisions(
        context,
        base_id,
        source_id,
        metadata_choices,
        resource_ids,
    )
    base = _get_dataset(context, base_id)
    source = _get_dataset(context, source_id)
    base_resources = {resource["id"]: resource for resource in base["resources"]}
    source_resources = {resource["id"]: resource for resource in source["resources"]}
    resources = [base_resources[resource_id] for resource_id in decisions["resources"]["base"]]
    resources.extend(
        _clone_source_resource(source_resources[resource_id]) for resource_id in decisions["resources"]["source"]
    )

    compatibility = check_merge_compatibility(context, base_id, source_id)
    if not compatibility["compatible"]:
        raise tk.ValidationError({"source_id": [compatibility["message"] or MIGRATION_REQUIRED_MESSAGE]})

    handoff_source_name = decisions["metadata"].get("name") == source["name"]

    # CKAN extension hooks can fail after package_update has flushed changes.
    try:
        if handoff_source_name:
            _patch_dataset_name(context, source_id, f"merge-source-{uuid4()}")

        updated = _update_base_dataset(
            context,
            {
                **base,
                **decisions["metadata"],
                "resources": resources,
            },
        )
    except Exception:  # noqa: BLE001
        model.Session.rollback()
        if handoff_source_name:
            _patch_dataset_name(context, source_id, source["name"])
        raise
    return {
        "base": updated,
        "source_id": source["id"],
        "cleanup_required": True,
    }


def _update_base_dataset(
    context: Context,
    data_dict: dict[str, Any],
) -> dict[str, Any]:
    """Update A without exposing deleted resources to XLoader before commit."""
    if not p.plugin_loaded("xloader"):
        return tk.get_action("package_update")(
            logic.fresh_context(context),
            data_dict,
        )

    package_id = data_dict["id"]
    logic.index_update_package(logic.fresh_context(context), package_id)
    tk.get_action("package_update")(
        logic.fresh_context(
            context,
            defer_commit=True,
            return_id_only=True,
        ),
        {**data_dict, MERGE_PACKAGE_UPDATE_FLAG: True},
    )
    model.repo.commit()
    logic.index_update_package(logic.fresh_context(context), package_id)
    return _get_dataset(context, package_id)


def cleanup_merge_source(
    context: Context,
    base_id: str,
    source_id: str,
) -> MergeCleanupResult:
    """Soft-delete B without repeating any part of the merge."""
    base = _get_dataset(context, base_id)
    source = _get_dataset(context, source_id)
    if base["id"] == source["id"]:
        raise tk.ValidationError({"source_id": [SAME_DATASET_MESSAGE]})

    try:
        tk.get_action("package_delete")(
            logic.fresh_context(context),
            {"id": source["id"]},
        )
    except Exception:  # noqa: BLE001
        model.Session.rollback()
        raise

    return {
        "base_id": base["id"],
        "source_id": source["id"],
        "cleanup_required": False,
    }


def _patch_dataset_name(context: Context, dataset_id: str, name: str) -> None:
    tk.get_action("package_patch")(
        logic.fresh_context(context),
        {"id": dataset_id, "name": name},
    )


def _get_schema_identity(
    context: Context,
    dataset_id: str,
) -> DatasetSchemaIdentity:
    dataset = _get_dataset(context, dataset_id)
    return {
        "id": dataset["id"],
        "schema_type": dataset["type"],
        "schema_version": _get_pin_version(dataset["id"]),
    }


def _get_dataset(context: Context, dataset_id: str) -> dict[str, Any]:
    return tk.get_action("package_show")(
        logic.fresh_context(context),
        {"id": dataset_id},
    )


def _get_entity_schema(dataset: dict[str, Any]) -> dict[str, Any]:
    """Return the dataset's scheming schema, honoring a dynamic-schema pin.

    Falls back to the live ``scheming`` schema when ``scheming_dynamic`` is
    not installed.
    """
    if _dynamic_schemas_enabled():
        return tk.h.dynamic_scheming_get_entity_schema(
            dataset["type"],
            "dataset",
            dataset["id"],
        )
    return tk.h.scheming_get_schema("dataset", dataset["type"])


# Schema fields whose value ``package_show`` exposes under the ``tags`` list
# rather than under the schema field name itself.
TAG_FIELD_NAMES = frozenset({"tag_string", "tags"})


def _compare_metadata_field(
    field: dict[str, Any],
    base: dict[str, Any],
    source: dict[str, Any],
) -> MetadataComparisonField:
    field_name = field["field_name"]
    label = tk.h.scheming_language_text(field.get("label", field_name))

    if field_name in TAG_FIELD_NAMES:
        return _compare_tag_field(label, base, source)

    base_value = base.get(field_name)
    source_value = source.get(field_name)
    return {
        "field_name": field_name,
        "label": label,
        "base_value": base_value,
        "source_value": source_value,
        "state": _metadata_value_state(base_value, source_value),
        "combinable": False,
        "combined_value": None,
    }


def _compare_tag_field(
    label: str,
    base: dict[str, Any],
    source: dict[str, Any],
) -> MetadataComparisonField:
    """Compare tags.

    ``package_show`` never populates ``tag_string``; it returns a ``tags`` list
    of dicts (each carrying a dataset-specific ``id``). Read the names from
    there, compare on the name sets, and hand ``package_update`` a clean
    ``{"name": ...}`` list under the ``tags`` key.

    Tags are a set, so a conflict also offers a "both" choice that keeps the
    union of the two tag sets (and that union is the default).
    """
    base_value = _tag_list(base)
    source_value = _tag_list(source)
    return {
        "field_name": "tags",
        "label": label,
        "base_value": base_value,
        "source_value": source_value,
        "state": _metadata_value_state(
            [tag["name"] for tag in base_value],
            [tag["name"] for tag in source_value],
        ),
        "combinable": True,
        "combined_value": _combine_tag_lists(base_value, source_value),
    }


def _tag_list(dataset: dict[str, Any]) -> list[dict[str, str]]:
    """Return a dataset's tags as name-only dicts, ordered by name."""
    tags = dataset.get("tags") or []
    return [{"name": tag["name"]} for tag in sorted(tags, key=lambda tag: tag["name"])]


def _combine_tag_lists(*tag_lists: list[dict[str, str]]) -> list[dict[str, str]]:
    """Union of several tag lists, de-duplicated by name and ordered by name."""
    names = {tag["name"] for tags in tag_lists for tag in tags}
    return [{"name": name} for name in sorted(names)]


def _default_choice(field: MetadataComparisonField) -> str:
    """The pre-selected side for a conflict: ``both`` for combinable fields."""
    return "both" if field["combinable"] else "base"


def _validate_metadata_choices(
    fields: list[MetadataComparisonField],
    choices: dict[str, str],
) -> None:
    conflicts = {field["field_name"]: field for field in fields if field["state"] == "conflict"}
    for field_name, choice in choices.items():
        field = conflicts.get(field_name)
        allowed = {"base", "source", "both"} if field and field["combinable"] else {"base", "source"}
        if field is None or choice not in allowed:
            raise tk.ValidationError(
                {"metadata_choices": [tk._("Metadata choices must identify a conflicting field and dataset side.")]}
            )


def _selected_metadata_value(
    field: MetadataComparisonField,
    choices: dict[str, str],
) -> Any:
    if field["state"] != "conflict":
        return field["source_value"] if field["state"] == "source_only" else field["base_value"]

    choice = choices.get(field["field_name"], _default_choice(field))
    if choice == "both":
        return field["combined_value"]
    return field["source_value"] if choice == "source" else field["base_value"]


def _clone_source_resource(resource: dict[str, Any]) -> dict[str, Any]:
    excluded = {
        "id",
        "package_id",
        "position",
        "created",
        "cache_last_updated",
        "cache_url",
        "datastore_active",
        "datastore_contains_all_records",
    }
    clone = {key: value for key, value in resource.items() if key not in excluded}
    if resource.get("url_type") == "upload":
        clone["upload"] = _copy_uploaded_file(resource)
    return clone


def _copy_uploaded_file(resource: dict[str, Any]) -> FileStorage:
    resource_upload: Any = uploader.get_resource_uploader(dict(resource))
    location = resource_upload.get_path(resource["id"])
    storage = getattr(resource_upload, "storage", None)
    content = storage.content(files.FileData(location)) if storage else Path(location).read_bytes()

    filename = unquote(Path(urlparse(resource["url"]).path).name) or "resource"
    return FileStorage(BytesIO(content), filename=filename)


def _metadata_value_state(
    base_value: Any,
    source_value: Any,
) -> MetadataValueState:
    base_empty = _is_empty(base_value)
    source_empty = _is_empty(source_value)
    if base_empty and source_empty:
        return "empty"
    if source_empty:
        return "base_only"
    if base_empty:
        return "source_only"
    if base_value == source_value:
        return "same"
    return "conflict"


def _is_empty(value: Any) -> bool:
    return value is None or value in ("", [], {})


def _get_pin_version(dataset_id: str) -> int | None:
    if not _dynamic_schemas_enabled():
        return None
    return tk.h.dynamic_scheming_get_entity_pin_version("dataset", dataset_id)


def _compatible(
    base: DatasetSchemaIdentity,
    source: DatasetSchemaIdentity,
) -> MergeCompatibilityResult:
    return {
        "compatible": True,
        "migration_required": False,
        "reason": None,
        "message": None,
        "base": base,
        "source": source,
    }


def _migration_required(
    base: DatasetSchemaIdentity,
    source: DatasetSchemaIdentity,
    reason: CompatibilityReason,
) -> MergeCompatibilityResult:
    return _incompatible(
        base,
        source,
        reason=reason,
        message=MIGRATION_REQUIRED_MESSAGE,
        migration_required=True,
    )


def _incompatible(
    base: DatasetSchemaIdentity,
    source: DatasetSchemaIdentity,
    *,
    reason: CompatibilityReason,
    message: str,
    migration_required: bool,
) -> MergeCompatibilityResult:
    return {
        "compatible": False,
        "migration_required": migration_required,
        "reason": reason,
        "message": message,
        "base": base,
        "source": source,
    }
