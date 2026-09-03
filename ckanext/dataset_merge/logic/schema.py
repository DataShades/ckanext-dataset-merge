from __future__ import annotations

from ckan import types
from ckan.logic.schema import validator_args


@validator_args
def merge_compatibility(
    not_empty: types.Validator,
    unicode_safe: types.Validator,
    package_id_or_name_exists: types.Validator,
) -> types.Schema:
    """Schema for merge_compatibility."""
    return {
        "base_id": [not_empty, unicode_safe, package_id_or_name_exists],
        "source_id": [not_empty, unicode_safe, package_id_or_name_exists],
    }


@validator_args
def merge_decisions(
    ignore_missing: types.Validator,
    convert_to_json_if_string: types.Validator,
    dict_only: types.Validator,
    list_of_strings: types.Validator,
) -> types.Schema:
    """Schema for merge_resolve_decisions."""
    schema = merge_compatibility()
    schema.update(
        {
            "metadata_choices": [ignore_missing, convert_to_json_if_string, dict_only],
            "resource_ids": [ignore_missing, list_of_strings],
        }
    )
    return schema
