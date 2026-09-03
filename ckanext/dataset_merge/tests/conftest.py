from __future__ import annotations

from typing import Any

import pytest


@pytest.fixture
def merge_clean_db(reset_db: Any, migrate_db_for: Any):
    """Create the dynamic-schema tables used by the dynamic-mode merge tests."""
    reset_db()
    migrate_db_for("scheming_dynamic")


@pytest.fixture
def reset_dynamic_schema_sync():
    """Keep the dynamic-schema process cache isolated between tests."""
    from ckanext.scheming_dynamic import sync

    sync.reset()
