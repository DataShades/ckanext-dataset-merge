"""Type definitions shared across the merge plugin.

These describe the shapes returned by :mod:`ckanext.dataset_merge.merge` and,
through the action layer, exposed to the views and templates.
"""

from __future__ import annotations

from typing import Any, Literal, TypedDict

CompatibilityReason = Literal[
    "same_dataset",
    "type_mismatch",
    "schema_pin_missing",
    "schema_type_mismatch",
    "schema_version_mismatch",
]
MetadataValueState = Literal[
    "empty",
    "base_only",
    "source_only",
    "same",
    "conflict",
]


class DatasetSchemaIdentity(TypedDict):
    """The dynamic-schema identity relevant to merge eligibility."""

    id: str
    schema_type: str
    schema_version: int | None


class MergeCompatibilityResult(TypedDict):
    """Compatibility result returned to the merge workflow."""

    compatible: bool
    migration_required: bool
    reason: CompatibilityReason | None
    message: str | None
    base: DatasetSchemaIdentity
    source: DatasetSchemaIdentity


class MetadataComparisonField(TypedDict):
    """One schema-defined metadata field from both datasets."""

    field_name: str
    label: str
    base_value: Any
    source_value: Any
    state: MetadataValueState


class MergeMetadataComparisonResult(TypedDict):
    """Compatibility and metadata candidates for the merge form."""

    compatibility: MergeCompatibilityResult
    metadata_fields: list[MetadataComparisonField]
    resources: dict[str, list[dict[str, Any]]]


class ResolvedMergeDecisions(TypedDict):
    """Metadata and resource selections ready for a later merge action."""

    metadata: dict[str, Any]
    resources: dict[str, list[str]]


class ApplyMergeToBaseResult(TypedDict):
    """Updated base plus the source that still requires cleanup."""

    base: dict[str, Any]
    source_id: str
    cleanup_required: bool


class MergeCleanupResult(TypedDict):
    """Result of soft-deleting the source dataset."""

    base_id: str
    source_id: str
    cleanup_required: bool
