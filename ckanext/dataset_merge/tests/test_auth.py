"""Tests for ckanext.dataset_merge.logic.auth."""

from __future__ import annotations

from typing import Any

import pytest

import ckan.model as model
import ckan.plugins.toolkit as tk
from ckan.tests.helpers import call_auth


@pytest.fixture
def merge_auth_clean_db(reset_db: Any):
    """Reset core CKAN tables used by merge authorization tests."""
    reset_db()


@pytest.mark.ckan_config("ckan.plugins", "dataset_merge")
@pytest.mark.usefixtures("with_plugins", "merge_auth_clean_db")
@pytest.mark.parametrize(
    "action",
    [
        "merge_compatibility",
        "merge_metadata_comparison",
        "merge_resolve_decisions",
        "merge_apply_to_base",
        "merge_cleanup_source",
    ],
)
class TestMergeAuthorization:
    def test_anonymous_access_is_rejected(
        self,
        action: str,
        package_factory: Any,
    ):
        """Anonymous users cannot call merge actions."""
        base = package_factory()
        source = package_factory()

        with pytest.raises(tk.NotAuthorized):
            call_auth(
                action,
                context={"model": model, "user": ""},
                base_id=base["id"],
                source_id=source["id"],
            )

    def test_user_must_edit_both_datasets(
        self,
        action: str,
        organization_factory: Any,
        package_factory: Any,
        user_factory: Any,
    ):
        """Edit access to the base alone is insufficient."""
        user = user_factory()
        base_org = organization_factory(
            users=[{"name": user["name"], "capacity": "editor"}],
        )
        source_org = organization_factory()
        base = package_factory(owner_org=base_org["id"])
        source = package_factory(owner_org=source_org["id"])

        with pytest.raises(tk.NotAuthorized):
            call_auth(
                action,
                context={"model": model, "user": user["name"]},
                base_id=base["id"],
                source_id=source["id"],
            )

    def test_user_with_required_dataset_access_is_authorized(
        self,
        action: str,
        organization_factory: Any,
        package_factory: Any,
        user_factory: Any,
    ):
        """An editor of both datasets can call merge actions."""
        user = user_factory()
        membership = [{"name": user["name"], "capacity": "editor"}]
        base_org = organization_factory(users=membership)
        source_org = organization_factory(users=membership)
        base = package_factory(owner_org=base_org["id"])
        source = package_factory(owner_org=source_org["id"])

        assert call_auth(
            action,
            context={"model": model, "user": user["name"]},
            base_id=base["id"],
            source_id=source["id"],
        )
