"""Permissions export logic.

This module handles exporting permission groups and permissions graphs from the
source Metabase instance.
"""

import logging

from lib.client import MetabaseAPIError, MetabaseClient
from lib.models import Manifest, PermissionGroup

logger = logging.getLogger("metabase_migration")


class PermissionsExporter:
    """Handles exporting permissions."""

    def __init__(self, client: MetabaseClient, manifest: Manifest):
        """Initialize the PermissionsExporter.

        Args:
            client: Metabase API client
            manifest: Manifest object to populate with permissions data
        """
        self.client = client
        self.manifest = manifest

    def export_permissions(self) -> None:
        """Export permission groups and permissions graphs."""
        try:
            # Fetch permission groups
            logger.info("Fetching permission groups...")
            groups_data = self.client.get_permission_groups()

            # Filter out built-in groups that shouldn't be exported
            # We'll keep all groups but mark built-in ones
            for group in groups_data:
                group_obj = PermissionGroup(
                    id=group["id"], name=group["name"], member_count=group.get("member_count", 0)
                )
                self.manifest.permission_groups.append(group_obj)
                logger.debug(
                    f"  -> Exported permission group: '{group['name']}' (ID: {group['id']})"
                )

            logger.info(f"Exported {len(self.manifest.permission_groups)} permission groups")

            # Fetch data permissions graph
            logger.info("Fetching data permissions graph...")
            self.manifest.permissions_graph = self.client.get_permissions_graph()
            logger.info("Data permissions graph exported")

            # Fetch collection permissions graph
            logger.info("Fetching collection permissions graph...")
            self.manifest.collection_permissions_graph = (
                self.client.get_collection_permissions_graph()
            )
            logger.info("Collection permissions graph exported")

        except MetabaseAPIError as e:
            logger.error(f"Failed to export permissions: {e}")
            logger.warning(
                "Permissions export failed. The export will continue without permissions data."
            )
        except Exception as e:
            logger.error(f"An unexpected error occurred while exporting permissions: {e}")
            logger.warning(
                "Permissions export failed. The export will continue without permissions data."
            )
