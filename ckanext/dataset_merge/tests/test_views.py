"""Tests for ckanext.dataset_merge.views.

Here you define functional tests that verify page rendering process. It's also
possible to test views using cypress.

Pytest performs better when you want to something on server side befor the
assertion. Cypress should be preferred when you only test user interaction with
frontend without executing arbitrary python code.
"""

from typing import Any

import bs4
import pytest

import ckan.plugins.toolkit as tk
from ckan import model
from ckan.tests.helpers import CKANTestApp, call_action

from ckanext.scheming_dynamic.model import SchemingSchemaVersion

from ckanext.dataset_merge import merge

TEST_BASE_URL = "https://test.ckan.net"


def _create_merge_schema(
    schema_type: str,
    dataset_fields: list[dict[str, Any]] | None = None,
) -> SchemingSchemaVersion:
    return SchemingSchemaVersion.create(
        "dataset",
        schema_type,
        {
            "about": "Merge view test schema",
            "dataset_type": schema_type,
            "dataset_fields": dataset_fields
            or [
                {"field_name": "title", "label": "Title"},
                {"field_name": "name", "label": "URL"},
                {"field_name": "notes", "label": "Description"},
                {"field_name": "owner_org", "label": "Organization"},
            ],
            "resource_fields": [
                {"field_name": "url"},
                {"field_name": "name"},
            ],
        },
    )


def _merge_review_url(base: dict[str, Any], source: dict[str, Any]) -> str:
    return tk.url_for(
        "merge.review",
        base_id=base["id"],
        source_id=source["id"],
    )


@pytest.fixture
def merge_review_datasets(
    app: CKANTestApp,
    sysadmin_factory: Any,
) -> dict[str, Any]:
    """Create and sign in a sysadmin for a standard merge review pair."""
    schema = _create_merge_schema(
        "contract-notice",
        [
            {"field_name": "title", "label": "Title"},
            {"field_name": "name", "label": "URL"},
        ],
    )
    assert tk.h.dynamic_scheming_get_entity_schema(schema.schema_type)
    user = sysadmin_factory()
    context = {"user": user["name"]}
    base = call_action(
        "package_create",
        context=context,
        type=schema.schema_type,
        name="base-dataset",
        title="Base title",
    )
    source = call_action(
        "package_create",
        context=context,
        type=schema.schema_type,
        name="source-dataset",
        title="Source title",
    )
    app.set_session_user(user["id"])
    return {"base": base, "source": source, "context": context}


# blueprints are registered when the plugin is enabled, so `with_plugins` is a
# mandatory fixture for any view test.
@pytest.mark.ckan_config("ckan.plugins", "harvest dataset_merge")
@pytest.mark.usefixtures("with_plugins", "clean_db", "clean_index")
def test_merge_selector_finds_partial_multiword_title(
    app: CKANTestApp,
    migrate_db_for: Any,
    sysadmin_factory: Any,
):
    """Find an editable dataset when its title query ends mid-word."""
    migrate_db_for("harvest")
    user = sysadmin_factory()
    dataset = call_action(
        "package_create",
        context={"user": user["name"]},
        name="north-district-road-maintenance",
        title="North District Road Maintenance",
    )
    app.set_session_user(user["id"])

    response = app.get(
        tk.url_for(
            "merge.select_search",
            role="base",
            base_query="North Distr",
        ),
        base_url=TEST_BASE_URL,
    )
    page = bs4.BeautifulSoup(response.body)

    assert response.status_code == 200
    assert page.select_one(".merge-select__result-title").text.strip() == dataset["title"]


@pytest.mark.ckan_config(
    "ckan.plugins",
    "dataset_merge scheming_datasets scheming_dynamic",
)
@pytest.mark.usefixtures(
    "with_plugins",
    "merge_clean_db",
    "reset_dynamic_schema_sync",
)
class TestMergeReview:
    def test_long_metadata_values_have_independent_expand_controls(
        self,
        app: CKANTestApp,
        sysadmin_factory: Any,
    ):
        """Keep the full value available without expanding the other card."""
        schema = _create_merge_schema("contract-notice")
        user = sysadmin_factory()
        context = {"user": user["name"]}
        base_notes = "Short base description"
        source_notes = " ".join(["Long source description"] * 20)
        base = call_action(
            "package_create",
            context=context,
            type=schema.schema_type,
            name="base-dataset",
            title="Base title",
            notes=base_notes,
        )
        source = call_action(
            "package_create",
            context=context,
            type=schema.schema_type,
            name="source-dataset",
            title="Source title",
            notes=source_notes,
        )
        app.set_session_user(user["id"])

        response = app.get(_merge_review_url(base, source), base_url=TEST_BASE_URL)
        page = bs4.BeautifulSoup(response.body)
        notes = page.select_one('[data-field-name="notes"]')

        assert notes
        value_ids = set()
        for source_name, expected_value in [("base", base_notes), ("source", source_notes)]:
            option = notes.select_one(f'.merge-review__value-option[data-source="{source_name}"]')
            card = option.select_one(".merge-review__value-card")
            value = card.select_one("[data-merge-value]")
            toggle = option.select_one("[data-merge-value-toggle]")

            assert value.text.strip() == expected_value
            assert toggle.text.strip() == "Show full value"
            assert toggle["aria-controls"] == value["id"]
            assert toggle["aria-expanded"] == "false"
            assert toggle.has_attr("hidden")
            assert toggle.find_parent("label") is None
            assert toggle.find_parent(class_="merge-review__value-card") is None
            value_ids.add(value["id"])

        assert len(value_ids) == 2

    def test_shows_phase_two_controls(
        self,
        app: CKANTestApp,
        organization_factory: Any,
        sysadmin_factory: Any,
    ):
        """Show interactive metadata choices and resource candidates."""
        schema = _create_merge_schema("contract-notice")
        assert tk.h.dynamic_scheming_get_entity_schema(schema.schema_type)
        user = sysadmin_factory()
        context = {"user": user["name"]}
        base_org = organization_factory(title="Base organization")
        source_org = organization_factory(title="Source organization")
        base = call_action(
            "package_create",
            context=context,
            type=schema.schema_type,
            name="base-dataset",
            title="Base title",
            notes="Base description",
            owner_org=base_org["id"],
        )
        source = call_action(
            "package_create",
            context=context,
            type=schema.schema_type,
            name="source-dataset",
            title="Source title",
            notes="Base description",
            owner_org=source_org["id"],
        )
        call_action(
            "resource_create",
            context=context,
            package_id=base["id"],
            url="https://example.com/base.csv",
            name="Base resource",
        )
        call_action(
            "resource_create",
            context=context,
            package_id=source["id"],
            url="https://example.com/source.csv",
            name="Source resource",
        )
        app.set_session_user(user["id"])

        response = app.get(
            _merge_review_url(base, source),
            base_url=TEST_BASE_URL,
        )
        page = bs4.BeautifulSoup(response.body)

        assert response.status_code == 200
        review = page.select_one('form[data-module="merge-review"]')
        assert review
        assert review["method"] == "post"
        assert review.select_one('input[type="hidden"]')
        assert page.select_one('[data-merge-dataset="base"] h2').text.strip() == "Base title"
        assert page.select_one('[data-merge-dataset="source"] h2').text.strip() == "Source title"

        title = page.select_one('[data-field-name="title"]')
        assert title.name == "fieldset"
        assert title.select_one("legend").text.strip() == "Choose the final value for Title"
        assert len(title.select('input[type="radio"]')) == 2
        assert title.select_one('input[value="base"]').has_attr("checked")
        assert not title.select_one('input[value="source"]').has_attr("checked")
        assert title.select_one('[data-source="base"] [data-merge-value]').text.strip() == "Base title"
        assert title.select_one('[data-source="source"] [data-merge-value]').text.strip() == "Source title"
        for radio in title.select('input[type="radio"]'):
            assert page.select_one(f'label[for="{radio["id"]}"]')

        owner_org = page.select_one('[data-field-name="owner_org"]')
        assert len(owner_org.select('input[type="radio"]')) == 2
        assert "Base organization" in owner_org.select_one('[data-source="base"]').text
        assert "Source organization" in owner_org.select_one('[data-source="source"]').text

        resources = page.select('input[data-merge-resource][type="checkbox"]')
        assert len(resources) == 2
        assert all(resource.has_attr("checked") for resource in resources)
        assert all(resource["name"] == "resource_ids" for resource in resources)
        assert "Base resource" in page.select_one('[data-resource-source="base"]').text
        assert "Source resource" in page.select_one('[data-resource-source="source"]').text
        assert len(page.select('.merge-review__resource-icon svg[viewBox="0 0 24 24"]')) == 2
        for resource in resources:
            assert page.select_one(f'label[for="{resource["id"]}"]')

        assert len(page.select("[data-merge-filter]")) == 4
        assert page.select_one("[data-merge-sticky]")
        assert "identity (ID), history and schema pin" in page.select_one(".merge-review__intro").text
        assert "identity, URL" not in page.select_one(".merge-review__intro").text
        assert "3 conflicting fields" in page.select_one("[data-conflict-count]").text
        assert "0 of 3 conflicts use Dataset B · 3 use Dataset A" in page.select_one("[data-decision-summary]").text
        assert "2 of 2 resources kept" in page.select_one("[data-resource-summary]").text
        preview_button = page.select_one("[data-merge-preview-open]")
        assert preview_button["type"] == "button"
        assert not preview_button.has_attr("disabled")
        preview = page.select_one("dialog[data-merge-preview-modal]")
        assert preview
        assert preview.select_one("[data-merge-preview-metadata]")
        assert preview.select_one("[data-merge-preview-resources]")
        assert preview.select_one("[data-merge-preview-close]")["type"] == "button"
        confirm = preview.select_one("[data-merge-preview-confirm]")
        assert confirm["type"] == "submit"
        assert confirm["name"] == "confirm_merge"
        assert confirm["value"] == "1"

    def test_requires_preview_confirmation_before_applying(
        self,
        app: CKANTestApp,
        merge_review_datasets: dict[str, Any],
    ):
        """Do not mutate either dataset without explicit modal confirmation."""
        base = merge_review_datasets["base"]
        source = merge_review_datasets["source"]

        response = app.post(
            _merge_review_url(base, source),
            data={"metadata_title": "source"},
            base_url=TEST_BASE_URL,
        )
        page = bs4.BeautifulSoup(response.body)

        assert response.status_code == 200
        assert "preview" in page.select_one(".flash-messages .alert").text.lower()
        assert call_action("package_show", id=base["id"])["title"] == "Base title"
        assert model.Package.get(source["id"]).state == "active"

    def test_successful_submission_updates_base_and_deletes_source(
        self,
        app: CKANTestApp,
        merge_review_datasets: dict[str, Any],
    ):
        """Complete the merge by soft-deleting B after A is updated."""
        base = merge_review_datasets["base"]
        source = merge_review_datasets["source"]
        context = merge_review_datasets["context"]
        base_resource = call_action(
            "resource_create",
            context=context,
            package_id=base["id"],
            url="https://example.com/base.csv",
            name="Base resource",
        )
        source_resource = call_action(
            "resource_create",
            context=context,
            package_id=source["id"],
            url="https://example.com/source.csv",
            name="Source resource",
        )
        response = app.post(
            _merge_review_url(base, source),
            data={
                "confirm_merge": "1",
                "metadata_title": "source",
                "resource_ids": [source_resource["id"]],
            },
            base_url=TEST_BASE_URL,
            follow_redirects=False,
        )

        assert response.status_code == 302
        updated = call_action("package_show", id=base["id"])
        assert response.headers["location"].endswith(f"/{updated['type']}/{updated['name']}")
        assert updated["title"] == "Source title"
        assert len(updated["resources"]) == 1
        assert updated["resources"][0]["id"] not in {base_resource["id"], source_resource["id"]}
        assert updated["resources"][0]["name"] == "Source resource"
        assert model.Package.get(source["id"]).state == "deleted"

    def test_failed_cleanup_shows_partial_state_and_retry_only_deletes_source(
        self,
        app: CKANTestApp,
        merge_review_datasets: dict[str, Any],
        monkeypatch: pytest.MonkeyPatch,
    ):
        """Keep merged A after failure and retry only B's soft-delete."""
        base = merge_review_datasets["base"]
        source = merge_review_datasets["source"]

        original_delete = model.Package.delete

        def fail_source_delete(package: model.Package) -> None:
            if package.id == source["id"]:
                raise RuntimeError
            original_delete(package)

        monkeypatch.setattr(model.Package, "delete", fail_source_delete)
        response = app.post(
            _merge_review_url(base, source),
            data={"confirm_merge": "1", "metadata_title": "source"},
            base_url=TEST_BASE_URL,
            follow_redirects=False,
        )
        monkeypatch.setattr(model.Package, "delete", original_delete)

        cleanup_url = tk.url_for(
            "merge.cleanup",
            base_id=base["id"],
            source_id=source["id"],
        )
        assert response.status_code == 302
        assert response.headers["location"].endswith(cleanup_url)
        merged_base = call_action("package_show", id=base["id"])
        assert merged_base["title"] == "Source title"
        assert model.Package.get(source["id"]).state == "active"

        pending = app.get(cleanup_url, base_url=TEST_BASE_URL)
        page = bs4.BeautifulSoup(pending.body)
        assert pending.status_code == 200
        assert page.select_one("[data-merge-cleanup-pending]")
        assert "Dataset A was updated successfully" in page.text
        assert "Dataset B is still active" in page.text
        assert page.select_one(".merge-review__cleanup-panel")
        assert page.select_one('[data-merge-dataset="source"].is-cleanup-pending')
        retry_form = page.select_one("form[data-merge-cleanup-retry]")
        assert retry_form["method"] == "post"
        assert retry_form.select_one('input[type="hidden"]')

        retry = app.post(
            cleanup_url,
            base_url=TEST_BASE_URL,
            follow_redirects=False,
        )

        assert retry.status_code == 302
        assert model.Package.get(source["id"]).state == "deleted"
        assert call_action("package_show", id=base["id"]) == merged_base

    def test_invalid_submission_shows_error_without_changing_datasets(
        self,
        app: CKANTestApp,
        merge_review_datasets: dict[str, Any],
    ):
        """Render action validation errors and leave A and B unchanged."""
        base = merge_review_datasets["base"]
        source = merge_review_datasets["source"]

        response = app.post(
            _merge_review_url(base, source),
            data={"confirm_merge": "1", "metadata_title": "neither"},
            base_url=TEST_BASE_URL,
        )
        page = bs4.BeautifulSoup(response.body)

        assert response.status_code == 200
        assert "Metadata choices must identify" in page.select_one(".flash-messages .alert").text
        assert call_action("package_show", id=base["id"])["title"] == "Base title"
        assert model.Package.get(source["id"]).state == "active"

    def test_automatically_handles_non_conflicting_values(
        self,
        app: CKANTestApp,
        sysadmin_factory: Any,
    ):
        """Render A-only, B-only, same, and empty values without choices."""
        schema = _create_merge_schema(
            "contract-notice",
            [
                {"field_name": "title", "label": "Title"},
                {"field_name": "name", "label": "URL"},
                {"field_name": "base_only", "label": "Base only"},
                {"field_name": "source_only", "label": "Source only"},
                {"field_name": "shared", "label": "Shared"},
                {"field_name": "empty", "label": "Empty"},
            ],
        )
        assert tk.h.dynamic_scheming_get_entity_schema(schema.schema_type)
        user = sysadmin_factory()
        context = {"user": user["name"]}
        base = call_action(
            "package_create",
            context=context,
            type=schema.schema_type,
            name="base-dataset",
            title="Base title",
            base_only="Base value",
            shared="Shared value",
        )
        source = call_action(
            "package_create",
            context=context,
            type=schema.schema_type,
            name="source-dataset",
            title="Source title",
            source_only="Source value",
            shared="Shared value",
        )
        app.set_session_user(user["id"])

        response = app.get(
            _merge_review_url(base, source),
            base_url=TEST_BASE_URL,
        )
        page = bs4.BeautifulSoup(response.body)

        base_only = page.select_one('[data-field-name="base_only"]')
        assert base_only["data-value-state"] == "base_only"
        assert base_only.select_one('[data-source="base"] [data-merge-value]').text.strip() == "Base value"
        assert base_only.select('input[type="radio"]') == []

        source_only = page.select_one('[data-field-name="source_only"]')
        assert source_only["data-value-state"] == "source_only"
        assert source_only.select_one('[data-source="source"] [data-merge-value]').text.strip() == "Source value"
        assert source_only.select('input[type="radio"]') == []

        shared = page.select_one('[data-field-name="shared"]')
        assert shared["data-value-state"] == "same"
        assert "Shared value" in shared.text
        assert shared.select('input[type="radio"]') == []

        empty = page.select_one('[data-field-name="empty"]')
        assert empty["data-value-state"] == "empty"
        assert "No value on either dataset" in empty.text
        assert empty.select('input[type="radio"]') == []

    def test_shows_migration_required_message(
        self,
        app: CKANTestApp,
        package_factory: Any,
        sysadmin_factory: Any,
    ):
        """Explain why datasets with different versions cannot merge."""
        schema = _create_merge_schema("contract-notice")
        base = package_factory(type=schema.schema_type)
        call_action(
            "scheming_schema_update",
            schema_type=schema.schema_type,
            definition={
                **schema.definition,
                "dataset_fields": [{"field_name": "title"}],
            },
        )
        source = package_factory(type=schema.schema_type)
        user = sysadmin_factory()
        app.set_session_user(user["id"])

        response = app.get(
            _merge_review_url(base, source),
            base_url=TEST_BASE_URL,
        )
        page = bs4.BeautifulSoup(response.body)

        assert response.status_code == 200
        assert page.select_one("[data-merge-incompatible]").text.strip() == merge.MIGRATION_REQUIRED_MESSAGE
        assert page.select_one('[data-schema-source="base"]').text.strip().endswith("version 1")
        assert page.select_one('[data-schema-source="source"]').text.strip().endswith("version 2")

    def test_requires_update_access_to_both_datasets(
        self,
        app: CKANTestApp,
        organization_factory: Any,
        package_factory: Any,
        user_factory: Any,
    ):
        """Deny the review page unless both datasets can be updated."""
        schema = _create_merge_schema("contract-notice")
        user = user_factory()
        base_org = organization_factory(users=[{"name": user["name"], "capacity": "editor"}])
        source_org = organization_factory()
        base = package_factory(type=schema.schema_type, owner_org=base_org["id"])
        source = package_factory(type=schema.schema_type, owner_org=source_org["id"])
        app.set_session_user(user["id"])

        response = app.get(
            _merge_review_url(base, source),
            base_url=TEST_BASE_URL,
            follow_redirects=False,
        )

        assert response.status_code == 403
