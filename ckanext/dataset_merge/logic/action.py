from __future__ import annotations

from typing import Any

import ckan.plugins.toolkit as tk
from ckan.logic import validate
from ckan.types import Action, Context

from ckanext.dataset_merge import merge, types

from . import schema


@tk.chained_action
def package_update(
    next_action: Action,
    context: Context,
    data_dict: dict[str, Any],
) -> Any:
    """Wrap the merge's ID-only result so package update signal listeners receive a mapping."""
    merge_update = data_dict.pop(merge.MERGE_PACKAGE_UPDATE_FLAG, False)
    result = next_action(context, data_dict)
    if merge_update and isinstance(result, str):
        return {"id": result}
    return result


@tk.side_effect_free
@validate(schema.merge_compatibility)
def merge_compatibility(
    context: Context,
    data_dict: dict[str, Any],
) -> types.MergeCompatibilityResult:
    """Report whether two datasets are eligible to be merged."""
    tk.check_access("merge_compatibility", context, data_dict)

    return merge.check_merge_compatibility(context, data_dict["base_id"], data_dict["source_id"])


@tk.side_effect_free
@validate(schema.merge_compatibility)
def merge_metadata_comparison(
    context: Context,
    data_dict: dict[str, Any],
) -> types.MergeMetadataComparisonResult:
    """Return side-by-side metadata from the datasets' schema."""
    tk.check_access("merge_metadata_comparison", context, data_dict)

    return merge.compare_merge_metadata(context, data_dict["base_id"], data_dict["source_id"])


@tk.side_effect_free
@validate(schema.merge_decisions)
def merge_resolve_decisions(
    context: Context,
    data_dict: dict[str, Any],
) -> types.ResolvedMergeDecisions:
    """Resolve merge choices without changing either dataset."""
    tk.check_access("merge_resolve_decisions", context, data_dict)

    return merge.resolve_merge_decisions(
        context,
        data_dict["base_id"],
        data_dict["source_id"],
        data_dict.get("metadata_choices", {}),
        data_dict.get("resource_ids", []),
    )


@validate(schema.merge_decisions)
def merge_apply_to_base(
    context: Context,
    data_dict: dict[str, Any],
) -> types.ApplyMergeToBaseResult:
    """Apply selected content to the base and leave the source untouched."""
    tk.check_access("merge_apply_to_base", context, data_dict)

    return merge.apply_merge_to_base(
        context,
        data_dict["base_id"],
        data_dict["source_id"],
        data_dict.get("metadata_choices", {}),
        data_dict.get("resource_ids", []),
    )


@validate(schema.merge_compatibility)
def merge_cleanup_source(
    context: Context,
    data_dict: dict[str, Any],
) -> types.MergeCleanupResult:
    """Soft-delete the source after the base has been updated."""
    tk.check_access("merge_cleanup_source", context, data_dict)

    return merge.cleanup_merge_source(context, data_dict["base_id"], data_dict["source_id"])
