from __future__ import annotations

from typing import Any

import pytest

from ckan.tests.helpers import call_action

from ckanext.scheming_dynamic.model import SchemingSchemaVersion

from ckanext.dataset_merge import merge


@pytest.mark.ckan_config(
    "ckan.plugins",
    "datastore scheming_datasets scheming_dynamic xloader dataset_merge",
)
@pytest.mark.usefixtures(
    "with_plugins",
    "merge_clean_db",
    "reset_dynamic_schema_sync",
    "with_request_context",
)
def test_merge_drops_a_base_resource_with_xloader_enabled(
    create_with_upload: Any,
) -> None:
    """Replace A's resource with B's uploaded CSV while XLoader is active."""
    schema = SchemingSchemaVersion.create(
        "dataset",
        "contract-notice",
        {
            "about": "XLoader merge regression schema",
            "dataset_type": "contract-notice",
            "dataset_fields": [
                {"field_name": "name", "label": "URL"},
                {"field_name": "type", "label": "Dataset type"},
            ],
            "resource_fields": [
                {"field_name": "url", "label": "URL"},
                {"field_name": "name", "label": "Name"},
            ],
        },
    )
    base = call_action("package_create", type=schema.schema_type, name="base-dataset")
    source = call_action("package_create", type=schema.schema_type, name="source-dataset")
    call_action(
        "resource_create",
        package_id=base["id"],
        url="https://example.com/base-document",
        name="Base document",
    )
    source_resource = create_with_upload(
        b"id,name\n1,Example\n",
        "source.csv",
        package_id=source["id"],
        url="https://example.com/source.csv",
        name="Source CSV",
        format="CSV",
    )
    context: dict[str, Any] = {"user": "127.0.0.1", "ignore_auth": True}

    result = merge.apply_merge_to_base(
        context,
        base["id"],
        source["id"],
        metadata_choices={},
        resource_ids=[source_resource["id"]],
    )

    assert [resource["name"] for resource in result["base"]["resources"]] == ["Source CSV"]
    cloned = result["base"]["resources"][0]
    assert cloned["id"] != source_resource["id"]
    assert cloned["url_type"] == "upload"
    assert call_action("resource_show", id=cloned["id"])["package_id"] == base["id"]
    assert call_action("resource_view_list", id=cloned["id"]) == []
