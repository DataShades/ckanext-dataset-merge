"""The merge plugin entry point.

Provides a guided workflow for merging two datasets: one dataset (A) keeps its
identity, history and (when ``scheming_dynamic`` is active) its schema pin,
while selected metadata and resources from a second dataset (B) are folded in
and B is soft-deleted.
"""

from __future__ import annotations

import ckan.plugins as p
import ckan.plugins.toolkit as tk
from ckan.common import CKANConfig


@tk.blanket.actions
@tk.blanket.auth_functions
@tk.blanket.blueprints
class DatasetMergePlugin(p.SingletonPlugin):
    """Dataset merge workflow."""

    p.implements(p.IConfigurer)

    # IConfigurer
    def update_config(self, config_: CKANConfig):
        """Register the plugin's templates and assets."""
        tk.add_template_directory(config_, "templates")
        tk.add_resource("assets", "merge")
