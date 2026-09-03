from __future__ import annotations

from typing import Any

import ckan.plugins.toolkit as tk
from ckan.types import Context


def merge_compatibility(
    context: Context,
    data_dict: dict[str, Any],
) -> dict[str, bool]:
    """Require update access to both datasets."""
    try:
        tk.check_access(
            "package_update",
            tk.fresh_context(context),
            {"id": data_dict["base_id"]}
        )
        tk.check_access(
            "package_update",
            tk.fresh_context(context),
            {"id": data_dict["source_id"]}
        )
    except tk.NotAuthorized:
        return {"success": False}

    return {"success": True}


def merge_metadata_comparison(
    context: Context,
    data_dict: dict[str, Any],
) -> dict[str, bool]:
    """Use the same dataset access rule as merge compatibility."""
    return merge_compatibility(context, data_dict)


def merge_resolve_decisions(
    context: Context,
    data_dict: dict[str, Any],
) -> dict[str, bool]:
    """Use the same dataset access rule as merge compatibility."""
    return merge_compatibility(context, data_dict)


def merge_apply_to_base(
    context: Context,
    data_dict: dict[str, Any],
) -> dict[str, bool]:
    """Use the same dataset access rule as merge compatibility."""
    return merge_compatibility(context, data_dict)


def merge_cleanup_source(
    context: Context,
    data_dict: dict[str, Any],
) -> dict[str, bool]:
    """Require update access to A and delete access to B."""
    try:
        tk.check_access(
            "package_update",
            tk.fresh_context(context),
            {"id": data_dict["base_id"]}
        )
        tk.check_access(
            "package_delete",
            tk.fresh_context(context),
            {"id": data_dict["source_id"]}
        )
    except tk.NotAuthorized:
        return {"success": False}

    return {"success": True}
