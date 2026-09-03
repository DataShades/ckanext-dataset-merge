from __future__ import annotations

from typing import Any

import pytest

import ckan.plugins.toolkit as tk
from ckan import model
from ckan.lib import files, uploader
from ckan.tests.helpers import call_action

from ckanext.scheming_dynamic.model import (
    SchemingSchemaPin,
    SchemingSchemaVersion,
)

from ckanext.dataset_merge import merge


def _create_merge_schema(
    schema_type: str,
    dataset_fields: list[dict[str, Any]] | None = None,
    resource_fields: list[dict[str, Any]] | None = None,
) -> SchemingSchemaVersion:
    return SchemingSchemaVersion.create(
        "dataset",
        schema_type,
        {
            "about": "Merge compatibility test schema",
            "dataset_type": schema_type,
            "dataset_fields": dataset_fields or [{"field_name": "notes"}],
            "resource_fields": resource_fields or [{"field_name": "url"}],
        },
    )


def _assert_migration_required(result: dict[str, Any], reason: str) -> None:
    assert result["compatible"] is False
    assert result["migration_required"] is True
    assert result["reason"] == reason
    assert result["message"] == merge.MIGRATION_REQUIRED_MESSAGE


@pytest.mark.ckan_config(
    "ckan.plugins",
    "dataset_merge scheming_datasets scheming_dynamic",
)
@pytest.mark.usefixtures(
    "with_plugins",
    "merge_clean_db",
    "reset_dynamic_schema_sync",
    "with_request_context",
)
class TestMergeCompatibility:
    def test_matching_schema_type_and_version_are_compatible(
        self,
        package_factory: Any,
    ):
        """Datasets pinned to the same exact schema version can be merged."""
        _create_merge_schema("contract-notice")
        base = package_factory(type="contract-notice")
        source = package_factory(type="contract-notice")

        result = call_action(
            "merge_compatibility",
            base_id=base["id"],
            source_id=source["id"],
        )

        assert result == {
            "compatible": True,
            "migration_required": False,
            "reason": None,
            "message": None,
            "base": {
                "id": base["id"],
                "schema_type": "contract-notice",
                "schema_version": 1,
            },
            "source": {
                "id": source["id"],
                "schema_type": "contract-notice",
                "schema_version": 1,
            },
        }

    def test_different_schema_types_require_migration(
        self,
        package_factory: Any,
    ):
        """Datasets using different schema types cannot be merged."""
        _create_merge_schema("contract-notice")
        _create_merge_schema("contract-award")
        base = package_factory(type="contract-notice")
        source = package_factory(type="contract-award")

        result = call_action(
            "merge_compatibility",
            base_id=base["id"],
            source_id=source["id"],
        )

        _assert_migration_required(result, "schema_type_mismatch")

    def test_different_schema_versions_require_migration(
        self,
        package_factory: Any,
    ):
        """Datasets using different versions of one schema cannot be merged."""
        schema = _create_merge_schema("contract-notice")
        base = package_factory(type="contract-notice")
        call_action(
            "scheming_schema_update",
            schema_type=schema.schema_type,
            definition={
                **schema.definition,
                "dataset_fields": [{"field_name": "title"}],
            },
        )
        source = package_factory(type="contract-notice")

        result = call_action(
            "merge_compatibility",
            base_id=base["id"],
            source_id=source["id"],
        )

        _assert_migration_required(result, "schema_version_mismatch")

    def test_missing_schema_pin_requires_migration(
        self,
        package_factory: Any,
    ):
        """An unpinned dataset has no exact version to compare."""
        _create_merge_schema("contract-notice")
        base = package_factory(type="contract-notice")
        source = package_factory(type="contract-notice")
        source_pin = SchemingSchemaPin.get("dataset", source["id"])
        assert source_pin
        model.Session.delete(source_pin)
        model.Session.commit()

        result = call_action(
            "merge_compatibility",
            base_id=base["id"],
            source_id=source["id"],
        )

        _assert_migration_required(result, "schema_pin_missing")

    def test_dataset_cannot_be_compared_with_itself(
        self,
        package_factory: Any,
    ):
        """Base and source must identify different datasets."""
        _create_merge_schema("contract-notice")
        base = package_factory(type="contract-notice")

        result = call_action(
            "merge_compatibility",
            base_id=base["id"],
            source_id=base["id"],
        )

        assert result["compatible"] is False
        assert result["migration_required"] is False
        assert result["reason"] == "same_dataset"
        assert result["message"] == merge.SAME_DATASET_MESSAGE

    def test_both_dataset_ids_are_required(self, package_factory: Any):
        """The compatibility boundary rejects incomplete requests."""
        _create_merge_schema("contract-notice")
        base = package_factory(type="contract-notice")

        with pytest.raises(tk.ValidationError) as error:
            call_action("merge_compatibility", base_id=base["id"])

        assert "source_id" in error.value.error_dict


@pytest.mark.ckan_config(
    "ckan.plugins",
    "dataset_merge scheming_datasets scheming_dynamic",
)
@pytest.mark.usefixtures(
    "with_plugins",
    "merge_clean_db",
    "reset_dynamic_schema_sync",
    "with_request_context",
)
class TestMergeMetadataComparison:
    def test_compares_fields_from_the_exact_pinned_schema(
        self,
        organization_factory: Any,
    ):
        """Compare metadata using the schema version pinned to the datasets."""
        schema = _create_merge_schema(
            "contract-notice",
            [
                {"field_name": "title", "label": "Title"},
                {"field_name": "name", "label": "URL"},
                {"field_name": "owner_org", "label": "Organization"},
                {"field_name": "base_only", "label": "Base only"},
                {"field_name": "source_only", "label": "Source only"},
                {"field_name": "same_value", "label": "Same value"},
                {"field_name": "empty_value", "label": "Empty value"},
                {"field_name": "type", "label": "Dataset type"},
            ],
        )
        assert tk.h.dynamic_scheming_get_entity_schema(schema.schema_type)
        base_org = organization_factory()
        source_org = organization_factory()
        base = call_action(
            "package_create",
            type="contract-notice",
            name="base-dataset",
            title="Base title",
            owner_org=base_org["id"],
            base_only="From A",
            same_value="Same",
        )
        source = call_action(
            "package_create",
            type="contract-notice",
            name="source-dataset",
            title="Source title",
            owner_org=source_org["id"],
            source_only="From B",
            same_value="Same",
        )
        call_action(
            "scheming_schema_update",
            schema_type=schema.schema_type,
            definition={
                **schema.definition,
                "dataset_fields": [
                    {"field_name": "head_only", "label": "HEAD only"},
                ],
            },
        )

        result = call_action(
            "merge_metadata_comparison",
            base_id=base["id"],
            source_id=source["id"],
        )

        assert result["compatibility"]["compatible"] is True
        fields = {field["field_name"]: field for field in result["metadata_fields"]}
        assert list(fields) == [
            "title",
            "name",
            "owner_org",
            "base_only",
            "source_only",
            "same_value",
            "empty_value",
        ]
        assert fields["title"]["state"] == "conflict"
        assert fields["name"]["base_value"] == "base-dataset"
        assert fields["name"]["source_value"] == "source-dataset"
        assert fields["owner_org"] == {
            "field_name": "owner_org",
            "label": "Organization",
            "base_value": base_org["id"],
            "source_value": source_org["id"],
            "state": "conflict",
            "combinable": False,
            "combined_value": None,
        }
        assert fields["base_only"]["state"] == "base_only"
        assert fields["source_only"]["state"] == "source_only"
        assert fields["same_value"]["state"] == "same"
        assert fields["empty_value"]["state"] == "empty"
        assert "head_only" not in fields
        assert "type" not in fields

    def test_groups_resource_candidates_by_dataset(self):
        """Keep resource candidates ordered and grouped by their dataset."""
        schema = _create_merge_schema(
            "contract-notice",
            resource_fields=[
                {"field_name": "url"},
                {"field_name": "name"},
                {"field_name": "description"},
                {"field_name": "reference"},
            ],
        )
        assert tk.h.dynamic_scheming_get_entity_schema(schema.schema_type)
        base = call_action(
            "package_create",
            type="contract-notice",
            name="base-dataset",
            title="Base title",
        )
        source = call_action(
            "package_create",
            type="contract-notice",
            name="source-dataset",
            title="Source title",
        )
        base_resource_1 = call_action(
            "resource_create",
            package_id=base["id"],
            url="https://example.com/a1.csv",
            name="A1",
            reference="base-one",
        )
        base_resource_2 = call_action(
            "resource_create",
            package_id=base["id"],
            url="https://example.com/a2.csv",
            name="A2",
        )
        source_resource = call_action(
            "resource_create",
            package_id=source["id"],
            url="https://example.com/b1.csv",
            name="B1",
            reference="source-one",
        )

        result = call_action(
            "merge_metadata_comparison",
            base_id=base["id"],
            source_id=source["id"],
        )

        resources = result["resources"]
        assert [resource["id"] for resource in resources["base"]] == [
            base_resource_1["id"],
            base_resource_2["id"],
        ]
        assert [resource["id"] for resource in resources["source"]] == [
            source_resource["id"],
        ]
        assert resources["base"][0]["reference"] == "base-one"
        assert resources["source"][0]["reference"] == "source-one"

    def test_incompatible_datasets_have_no_metadata_comparison(
        self,
        package_factory: Any,
    ):
        """Return no candidate content when the schema versions differ."""
        schema = _create_merge_schema("contract-notice")
        base = package_factory(type="contract-notice")
        call_action(
            "scheming_schema_update",
            schema_type=schema.schema_type,
            definition={
                **schema.definition,
                "dataset_fields": [{"field_name": "title"}],
            },
        )
        source = package_factory(type="contract-notice")

        result = call_action(
            "merge_metadata_comparison",
            base_id=base["id"],
            source_id=source["id"],
        )

        _assert_migration_required(result["compatibility"], "schema_version_mismatch")
        assert result["metadata_fields"] == []
        assert result["resources"] == {"base": [], "source": []}


@pytest.mark.ckan_config(
    "ckan.plugins",
    "dataset_merge scheming_datasets scheming_dynamic",
)
@pytest.mark.usefixtures(
    "with_plugins",
    "merge_clean_db",
    "reset_dynamic_schema_sync",
    "with_request_context",
)
class TestResolveMergeDecisions:
    def test_resolves_metadata_and_resources_without_changing_datasets(self):
        """Resolve user choices into an ordered, side-effect-free payload."""
        schema = _create_merge_schema(
            "contract-notice",
            [
                {"field_name": "title", "label": "Title"},
                {"field_name": "name", "label": "URL"},
                {"field_name": "base_only", "label": "Base only"},
                {"field_name": "source_only", "label": "Source only"},
                {"field_name": "same_value", "label": "Same value"},
                {"field_name": "empty_value", "label": "Empty value"},
                {"field_name": "type", "label": "Dataset type"},
            ],
        )
        assert tk.h.dynamic_scheming_get_entity_schema(schema.schema_type)
        base = call_action(
            "package_create",
            type=schema.schema_type,
            name="base-dataset",
            title="Base title",
            base_only="From A",
            same_value="Same",
        )
        source = call_action(
            "package_create",
            type=schema.schema_type,
            name="source-dataset",
            title="Source title",
            source_only="From B",
            same_value="Same",
        )
        kept_base_resource = call_action(
            "resource_create",
            package_id=base["id"],
            url="https://example.com/a1.csv",
            name="A1",
        )
        call_action(
            "resource_create",
            package_id=base["id"],
            url="https://example.com/a2.csv",
            name="A2",
        )
        kept_source_resource = call_action(
            "resource_create",
            package_id=source["id"],
            url="https://example.com/b1.csv",
            name="B1",
        )

        result = call_action(
            "merge_resolve_decisions",
            base_id=base["id"],
            source_id=source["id"],
            metadata_choices={"title": "source"},
            resource_ids=[
                kept_source_resource["id"],
                kept_base_resource["id"],
            ],
        )

        assert result["metadata"] == {
            "title": "Source title",
            "name": "base-dataset",
            "base_only": "From A",
            "source_only": "From B",
            "same_value": "Same",
            "empty_value": None,
        }
        assert result["resources"] == {
            "base": [kept_base_resource["id"]],
            "source": [kept_source_resource["id"]],
        }
        assert call_action("package_show", id=base["id"])["title"] == "Base title"
        assert call_action("package_show", id=source["id"])["title"] == "Source title"

    @pytest.mark.parametrize(
        "metadata_choices",
        [
            {"unknown": "base"},
            {"same_value": "source"},
            {"title": "invalid"},
        ],
    )
    def test_rejects_invalid_metadata_choices(
        self,
        metadata_choices: dict[str, str],
    ):
        """Accept choices only for real conflicting fields and dataset sides."""
        schema = _create_merge_schema(
            "contract-notice",
            [
                {"field_name": "title", "label": "Title"},
                {"field_name": "same_value", "label": "Same value"},
            ],
        )
        assert tk.h.dynamic_scheming_get_entity_schema(schema.schema_type)
        base = call_action(
            "package_create",
            type=schema.schema_type,
            name="base-dataset",
            title="Base title",
            same_value="Same",
        )
        source = call_action(
            "package_create",
            type=schema.schema_type,
            name="source-dataset",
            title="Source title",
            same_value="Same",
        )

        with pytest.raises(tk.ValidationError) as error:
            call_action(
                "merge_resolve_decisions",
                base_id=base["id"],
                source_id=source["id"],
                metadata_choices=metadata_choices,
                resource_ids=[],
            )

        assert "metadata_choices" in error.value.error_dict

    def test_rejects_resource_ids_outside_the_dataset_pair(self):
        """Selected resources must belong to the base or source dataset."""
        schema = _create_merge_schema("contract-notice")
        assert tk.h.dynamic_scheming_get_entity_schema(schema.schema_type)
        base = call_action("package_create", type=schema.schema_type, name="base-dataset")
        source = call_action("package_create", type=schema.schema_type, name="source-dataset")
        unrelated = call_action("package_create", type=schema.schema_type, name="unrelated-dataset")
        unrelated_resource = call_action(
            "resource_create",
            package_id=unrelated["id"],
            url="https://example.com/unrelated.csv",
        )

        with pytest.raises(tk.ValidationError) as error:
            call_action(
                "merge_resolve_decisions",
                base_id=base["id"],
                source_id=source["id"],
                metadata_choices={},
                resource_ids=[unrelated_resource["id"]],
            )

        assert "resource_ids" in error.value.error_dict

    def test_rejects_incompatible_datasets(self):
        """Do not resolve decisions for datasets requiring migration."""
        schema = _create_merge_schema("contract-notice")
        base = call_action("package_create", type=schema.schema_type, name="base-dataset")
        call_action(
            "scheming_schema_update",
            schema_type=schema.schema_type,
            definition={
                **schema.definition,
                "dataset_fields": [{"field_name": "title"}],
            },
        )
        source = call_action("package_create", type=schema.schema_type, name="source-dataset")

        with pytest.raises(tk.ValidationError) as error:
            call_action(
                "merge_resolve_decisions",
                base_id=base["id"],
                source_id=source["id"],
                metadata_choices={},
                resource_ids=[],
            )

        assert error.value.error_dict["source_id"] == [merge.MIGRATION_REQUIRED_MESSAGE]


@pytest.mark.ckan_config(
    "ckan.plugins",
    "dataset_merge scheming_datasets scheming_dynamic",
)
@pytest.mark.usefixtures(
    "with_plugins",
    "merge_clean_db",
    "reset_dynamic_schema_sync",
    "with_request_context",
)
class TestApplyMergeToBase:
    def test_updates_all_selected_content_and_leaves_source_for_cleanup(
        self,
        organization_factory: Any,
    ):
        """Update A completely while leaving B available for later cleanup."""
        schema = _create_merge_schema(
            "contract-notice",
            [
                {"field_name": "title", "label": "Title"},
                {"field_name": "name", "label": "URL"},
                {"field_name": "notes", "label": "Description"},
                {
                    "field_name": "owner_org",
                    "label": "Organization",
                    "preset": "dataset_organization",
                },
                {"field_name": "type", "label": "Dataset type"},
            ],
            [
                {"field_name": "url", "label": "URL"},
                {"field_name": "name", "label": "Name"},
                {"field_name": "description", "label": "Description"},
            ],
        )
        assert tk.h.dynamic_scheming_get_entity_schema(schema.schema_type)
        base_org = organization_factory(title="Base organization")
        source_org = organization_factory(title="Source organization")
        base = call_action(
            "package_create",
            type=schema.schema_type,
            name="base-dataset",
            title="Base title",
            notes="Base notes",
            owner_org=base_org["id"],
        )
        source = call_action(
            "package_create",
            type=schema.schema_type,
            name="source-dataset",
            title="Source title",
            notes="Source notes",
            owner_org=source_org["id"],
        )
        kept_base_resource = call_action(
            "resource_create",
            package_id=base["id"],
            url="https://example.com/a1.csv",
            name="A1",
        )
        call_action(
            "resource_create",
            package_id=base["id"],
            url="https://example.com/a2.csv",
            name="A2",
        )
        source_resource = call_action(
            "resource_create",
            package_id=source["id"],
            url="https://example.com/b1.csv",
            name="B1",
            description="Copied from B",
        )
        pin_version = SchemingSchemaPin.get("dataset", base["id"]).version

        result = call_action(
            "merge_apply_to_base",
            base_id=base["id"],
            source_id=source["id"],
            metadata_choices={
                "title": "source",
                "notes": "source",
                "owner_org": "source",
            },
            resource_ids=[kept_base_resource["id"], source_resource["id"]],
        )

        updated = call_action("package_show", id=base["id"])
        assert result["base"] == updated
        assert result["source_id"] == source["id"]
        assert result["cleanup_required"] is True
        assert updated["id"] == base["id"]
        assert updated["name"] == "base-dataset"
        assert updated["title"] == "Source title"
        assert updated["notes"] == "Source notes"
        assert updated["owner_org"] == source_org["id"]
        assert [resource["id"] for resource in updated["resources"][:1]] == [kept_base_resource["id"]]
        cloned = updated["resources"][1]
        assert cloned["id"] != source_resource["id"]
        assert cloned["package_id"] == base["id"]
        assert cloned["url"] == source_resource["url"]
        assert cloned["name"] == "B1"
        assert cloned["description"] == "Copied from B"
        unchanged_source = call_action("package_show", id=source["id"])
        assert unchanged_source["name"] == "source-dataset"
        assert unchanged_source["state"] == "active"
        assert SchemingSchemaPin.get("dataset", base["id"]).version == pin_version

    def test_clones_an_uploaded_source_resource_with_a_fresh_id(
        self,
        create_with_upload: Any,
    ):
        """Copy uploaded bytes instead of pointing A at B's resource file."""
        schema = _create_merge_schema(
            "contract-notice",
            [
                {"field_name": "name", "label": "URL"},
                {"field_name": "type", "label": "Dataset type"},
            ],
            [
                {"field_name": "url", "label": "URL"},
                {"field_name": "name", "label": "Name"},
            ],
        )
        assert tk.h.dynamic_scheming_get_entity_schema(schema.schema_type)
        base = call_action("package_create", type=schema.schema_type, name="base-dataset")
        source = call_action("package_create", type=schema.schema_type, name="source-dataset")
        source_resource = create_with_upload(
            b"source upload contents",
            "source.txt",
            package_id=source["id"],
            url="https://example.com/source.txt",
            name="Source upload",
        )

        result = call_action(
            "merge_apply_to_base",
            base_id=base["id"],
            source_id=source["id"],
            metadata_choices={},
            resource_ids=[source_resource["id"]],
        )

        cloned = result["base"]["resources"][0]
        assert cloned["id"] != source_resource["id"]
        assert cloned["url_type"] == "upload"
        upload = uploader.get_resource_uploader(dict(cloned))
        assert upload.storage
        content = upload.storage.content(files.FileData(upload.get_path(cloned["id"])))
        assert content == b"source upload contents"
        assert call_action("package_show", id=source["id"])["resources"][0]["id"] == source_resource["id"]

    def test_hands_source_slug_to_base_without_deleting_source(self):
        """Move B to a temporary slug before giving its original slug to A."""
        schema = _create_merge_schema(
            "contract-notice",
            [
                {"field_name": "title", "label": "Title"},
                {"field_name": "name", "label": "URL"},
                {"field_name": "type", "label": "Dataset type"},
            ],
        )
        assert tk.h.dynamic_scheming_get_entity_schema(schema.schema_type)
        base = call_action(
            "package_create",
            type=schema.schema_type,
            name="base-dataset",
            title="Base title",
        )
        source = call_action(
            "package_create",
            type=schema.schema_type,
            name="source-dataset",
            title="Source title",
        )
        source_pin_version = SchemingSchemaPin.get("dataset", source["id"]).version

        result = call_action(
            "merge_apply_to_base",
            base_id=base["id"],
            source_id=source["id"],
            metadata_choices={"title": "source", "name": "source"},
            resource_ids=[],
        )

        assert result["base"]["id"] == base["id"]
        assert result["base"]["name"] == "source-dataset"
        assert result["base"]["title"] == "Source title"
        temporary_source = call_action("package_show", id=source["id"])
        assert temporary_source["name"].startswith("merge-source-")
        assert temporary_source["name"] != "source-dataset"
        assert temporary_source["state"] == "active"
        assert SchemingSchemaPin.get("dataset", source["id"]).version == source_pin_version

    @pytest.mark.ckan_config("ckan.auth.allow_dataset_collaborators", True)
    def test_failed_base_update_restores_source_slug(
        self,
        organization_factory: Any,
        user_factory: Any,
    ):
        """Restore B's slug when normal CKAN validation rejects A's update."""
        schema = _create_merge_schema(
            "contract-notice",
            [
                {"field_name": "name", "label": "URL"},
                {
                    "field_name": "owner_org",
                    "label": "Organization",
                    "preset": "dataset_organization",
                },
                {"field_name": "type", "label": "Dataset type"},
            ],
        )
        assert tk.h.dynamic_scheming_get_entity_schema(schema.schema_type)
        user = user_factory()
        base_org = organization_factory(users=[{"name": user["name"], "capacity": "editor"}])
        source_org = organization_factory()
        base = call_action(
            "package_create",
            type=schema.schema_type,
            name="base-dataset",
            owner_org=base_org["id"],
        )
        source = call_action(
            "package_create",
            type=schema.schema_type,
            name="source-dataset",
            owner_org=source_org["id"],
        )
        call_action(
            "package_collaborator_create",
            id=source["id"],
            user_id=user["id"],
            capacity="editor",
        )

        with pytest.raises(tk.ValidationError) as error:
            call_action(
                "merge_apply_to_base",
                context={"user": user["name"], "ignore_auth": False},
                base_id=base["id"],
                source_id=source["id"],
                metadata_choices={"name": "source", "owner_org": "source"},
                resource_ids=[],
            )

        assert "owner_org" in error.value.error_dict
        unchanged_base = call_action("package_show", id=base["id"])
        restored_source = call_action("package_show", id=source["id"])
        assert unchanged_base["name"] == "base-dataset"
        assert unchanged_base["owner_org"] == base_org["id"]
        assert restored_source["name"] == "source-dataset"
        assert restored_source["owner_org"] == source_org["id"]
        assert restored_source["state"] == "active"


@pytest.mark.ckan_config("ckan.plugins", "dataset_merge")
@pytest.mark.usefixtures(
    "with_plugins",
    "clean_db",
)
class TestCleanupMergeSource:
    def test_soft_deletes_source_without_changing_updated_base(
        self,
        package_factory: Any,
    ):
        """Complete cleanup while preserving the result already applied to A."""
        base = package_factory(title="Final base title")
        source = package_factory()
        updated_base = call_action("package_show", id=base["id"])

        result = call_action(
            "merge_cleanup_source",
            base_id=base["id"],
            source_id=source["id"],
        )

        assert result == {
            "base_id": base["id"],
            "source_id": source["id"],
            "cleanup_required": False,
        }
        assert model.Package.get(source["id"]).state == "deleted"
        assert call_action("package_show", id=base["id"]) == updated_base

    def test_authorization_failure_keeps_both_datasets_and_can_be_retried(
        self,
        organization_factory: Any,
        package_factory: Any,
        user_factory: Any,
    ):
        """A failed cleanup can retry deletion without applying the merge again."""
        user = user_factory()
        base_org = organization_factory(users=[{"name": user["name"], "capacity": "editor"}])
        source_org = organization_factory()
        base = package_factory(
            title="Base title",
            owner_org=base_org["id"],
        )
        source = package_factory(owner_org=source_org["id"])
        updated_base = call_action("package_show", id=base["id"])

        with pytest.raises(tk.NotAuthorized):
            call_action(
                "merge_cleanup_source",
                context={"user": user["name"], "ignore_auth": False},
                base_id=base["id"],
                source_id=source["id"],
            )

        assert model.Package.get(source["id"]).state == "active"
        assert call_action("package_show", id=base["id"]) == updated_base

        result = call_action(
            "merge_cleanup_source",
            base_id=base["id"],
            source_id=source["id"],
        )

        assert result["cleanup_required"] is False
        assert model.Package.get(source["id"]).state == "deleted"
        assert call_action("package_show", id=base["id"]) == updated_base

    def test_rejects_base_as_cleanup_source(self, package_factory: Any):
        """Never allow the surviving dataset to be deleted as its own source."""
        dataset = package_factory()

        with pytest.raises(tk.ValidationError) as error:
            call_action(
                "merge_cleanup_source",
                base_id=dataset["id"],
                source_id=dataset["id"],
            )

        assert error.value.error_dict["source_id"] == [merge.SAME_DATASET_MESSAGE]
        assert model.Package.get(dataset["id"]).state == "active"


@pytest.mark.ckan_config("ckan.plugins", "scheming_datasets dataset_merge")
@pytest.mark.ckan_config(
    "scheming.dataset_schemas",
    "ckanext.dataset_merge.tests:data/merge_static_a.yaml ckanext.dataset_merge.tests:data/merge_static_b.yaml",
)
@pytest.mark.usefixtures("with_plugins", "clean_db", "with_request_context")
class TestMergeCompatibilityWithoutDynamicSchemas:
    """Compatibility falls back to a dataset-type match when scheming_dynamic is off."""

    def test_same_type_is_compatible(self):
        """Two datasets of the same type merge without a schema pin."""
        base = call_action("package_create", type="merge-test-a", name="base-dataset", title="Base")
        source = call_action("package_create", type="merge-test-a", name="source-dataset", title="Source")

        result = call_action(
            "merge_compatibility",
            base_id=base["id"],
            source_id=source["id"],
        )

        assert result["compatible"] is True
        assert result["migration_required"] is False
        assert result["reason"] is None
        assert result["base"]["schema_version"] is None

    def test_different_type_is_incompatible_without_migration(self):
        """Datasets of different types cannot merge and no migration is offered."""
        base = call_action("package_create", type="merge-test-a", name="base-dataset", title="Base")
        source = call_action("package_create", type="merge-test-b", name="source-dataset", title="Source")

        result = call_action(
            "merge_compatibility",
            base_id=base["id"],
            source_id=source["id"],
        )

        assert result["compatible"] is False
        assert result["migration_required"] is False
        assert result["reason"] == "type_mismatch"
        assert result["message"] == merge.SAME_TYPE_MESSAGE

    def test_metadata_comparison_uses_the_static_schema(self):
        """Field discovery uses the live scheming schema when no pin exists."""
        base = call_action("package_create", type="merge-test-a", name="base-dataset", title="Base", notes="Base notes")
        source = call_action(
            "package_create", type="merge-test-a", name="source-dataset", title="Source", notes="Source notes"
        )

        comparison = call_action(
            "merge_metadata_comparison",
            base_id=base["id"],
            source_id=source["id"],
        )

        fields = {field["field_name"]: field for field in comparison["metadata_fields"]}
        assert fields["notes"]["state"] == "conflict"
        assert fields["title"]["state"] == "conflict"


@pytest.mark.ckan_config("ckan.plugins", "scheming_datasets dataset_merge")
@pytest.mark.ckan_config(
    "scheming.dataset_schemas",
    "ckanext.dataset_merge.tests:data/merge_static_a.yaml ckanext.dataset_merge.tests:data/merge_static_b.yaml",
)
@pytest.mark.usefixtures("with_plugins", "clean_db", "with_request_context")
class TestMergeTags:
    """``package_show`` exposes tags under ``tags``, never ``tag_string``."""

    def test_comparison_reads_tags_from_the_tags_list(self):
        """A schema ``tag_string`` field is compared using the ``tags`` list."""
        base = call_action(
            "package_create",
            type="merge-test-a",
            name="base-dataset",
            title="Base",
            tag_string="alpha,shared",
        )
        source = call_action(
            "package_create",
            type="merge-test-a",
            name="source-dataset",
            title="Source",
            tag_string="beta,shared",
        )

        comparison = call_action(
            "merge_metadata_comparison",
            base_id=base["id"],
            source_id=source["id"],
        )

        fields = {field["field_name"]: field for field in comparison["metadata_fields"]}
        assert "tag_string" not in fields
        tags = fields["tags"]
        assert tags["state"] == "conflict"
        assert tags["base_value"] == [{"name": "alpha"}, {"name": "shared"}]
        assert tags["source_value"] == [{"name": "beta"}, {"name": "shared"}]
        assert tags["combinable"] is True
        assert tags["combined_value"] == [{"name": "alpha"}, {"name": "beta"}, {"name": "shared"}]

    def test_matching_tags_are_reported_as_same(self):
        """Identical tag sets (order aside) are not a conflict."""
        base = call_action(
            "package_create",
            type="merge-test-a",
            name="base-dataset",
            title="Base",
            tag_string="one,two",
        )
        source = call_action(
            "package_create",
            type="merge-test-a",
            name="source-dataset",
            title="Source",
            tag_string="two,one",
        )

        comparison = call_action(
            "merge_metadata_comparison",
            base_id=base["id"],
            source_id=source["id"],
        )

        tags = next(f for f in comparison["metadata_fields"] if f["field_name"] == "tags")
        assert tags["state"] == "same"

    def test_missing_tags_on_one_side_are_source_only(self):
        """Tags present on just one dataset fill the gap automatically."""
        base = call_action("package_create", type="merge-test-a", name="base-dataset", title="Base")
        source = call_action(
            "package_create",
            type="merge-test-a",
            name="source-dataset",
            title="Source",
            tag_string="beta",
        )

        comparison = call_action(
            "merge_metadata_comparison",
            base_id=base["id"],
            source_id=source["id"],
        )

        tags = next(f for f in comparison["metadata_fields"] if f["field_name"] == "tags")
        assert tags["state"] == "source_only"

    def test_apply_keeps_the_chosen_side_tags(self):
        """Picking Dataset B's tags replaces Dataset A's on merge."""
        base = call_action(
            "package_create",
            type="merge-test-a",
            name="base-dataset",
            title="Base",
            tag_string="alpha,shared",
        )
        source = call_action(
            "package_create",
            type="merge-test-a",
            name="source-dataset",
            title="Source",
            tag_string="beta,shared",
        )

        call_action(
            "merge_apply_to_base",
            base_id=base["id"],
            source_id=source["id"],
            metadata_choices={"tags": "source"},
            resource_ids=[],
        )

        updated = call_action("package_show", id=base["id"])
        assert sorted(tag["name"] for tag in updated["tags"]) == ["beta", "shared"]

    def test_apply_combines_both_tag_sets_by_default(self):
        """With no explicit choice, a tag conflict keeps the union of both sides."""
        base = call_action(
            "package_create",
            type="merge-test-a",
            name="base-dataset",
            title="Base",
            tag_string="alpha,shared",
        )
        source = call_action(
            "package_create",
            type="merge-test-a",
            name="source-dataset",
            title="Source",
            tag_string="beta,shared",
        )

        call_action(
            "merge_apply_to_base",
            base_id=base["id"],
            source_id=source["id"],
            metadata_choices={},
            resource_ids=[],
        )

        updated = call_action("package_show", id=base["id"])
        assert sorted(tag["name"] for tag in updated["tags"]) == ["alpha", "beta", "shared"]

    def test_apply_combines_both_tag_sets_when_chosen(self):
        """An explicit ``both`` choice unions the two tag sets."""
        base = call_action(
            "package_create",
            type="merge-test-a",
            name="base-dataset",
            title="Base",
            tag_string="alpha,shared",
        )
        source = call_action(
            "package_create",
            type="merge-test-a",
            name="source-dataset",
            title="Source",
            tag_string="beta,shared",
        )

        call_action(
            "merge_apply_to_base",
            base_id=base["id"],
            source_id=source["id"],
            metadata_choices={"tags": "both", "title": "base"},
            resource_ids=[],
        )

        updated = call_action("package_show", id=base["id"])
        assert sorted(tag["name"] for tag in updated["tags"]) == ["alpha", "beta", "shared"]

    def test_both_is_rejected_for_a_non_combinable_field(self):
        """``both`` is only valid for combinable fields such as tags."""
        base = call_action(
            "package_create", type="merge-test-a", name="base-dataset", title="Base", tag_string="shared"
        )
        source = call_action(
            "package_create", type="merge-test-a", name="source-dataset", title="Source", tag_string="shared"
        )

        with pytest.raises(tk.ValidationError):
            call_action(
                "merge_apply_to_base",
                base_id=base["id"],
                source_id=source["id"],
                metadata_choices={"title": "both"},
                resource_ids=[],
            )
