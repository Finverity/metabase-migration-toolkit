"""Permissions import logic.

This module handles importing permissions from the export manifest to the
target Metabase instance, including data permissions and collection permissions.
"""

import logging
from pathlib import Path
from typing import Any

from lib.client import MetabaseClient
from lib.id_remapping import IDRemapper
from lib.models import ImportReport, ImportReportItem, Manifest

logger = logging.getLogger("metabase_migration")


class PermissionsImporter:
    """Handles importing permissions to a target Metabase instance."""

    def __init__(
        self,
        client: MetabaseClient,
        manifest: Manifest,
        id_remapper: IDRemapper,
        report: ImportReport,
        export_dir: Path,
        collection_map: dict[int, int],
    ) -> None:
        """Initialize the permissions importer.

        Args:
            client: Metabase API client for the target instance
            manifest: Export manifest
            id_remapper: ID remapper for database IDs
            report: Import report for tracking results
            export_dir: Directory containing exported files
            collection_map: Mapping of source to target collection IDs
        """
        self.client = client
        self.manifest = manifest
        self.id_remapper = id_remapper
        self.report = report
        self.export_dir = export_dir
        self.collection_map = collection_map

    def import_permissions(self) -> None:
        """Import permissions from the manifest."""
        if not self.manifest.permission_groups:
            logger.info("No permission groups found in export, skipping permissions import.")
            return

        try:
            logger.info("Importing permissions...")

            # Remap data permissions (database permissions)
            if self.manifest.permissions_graph:
                # The permissions_graph should have a "groups" key
                groups = self.manifest.permissions_graph.get("groups", {})
                if groups:
                    remapped_groups = self._remap_permissions_graph(groups)
                    if remapped_groups:
                        self.client.update_permissions_graph({"groups": remapped_groups})
                        logger.info("✅ Data permissions imported successfully")
                        self.report.add(
                            ImportReportItem(
                                "permissions", "success", None, None, "Data Permissions", None
                            )
                        )

            # Remap collection permissions
            if self.manifest.collection_permissions_graph:
                remapped_collection_perms = self._remap_collection_permissions_graph(
                    self.manifest.collection_permissions_graph
                )
                if remapped_collection_perms:
                    self.client.update_collection_permissions_graph(remapped_collection_perms)
                    logger.info("✅ Collection permissions imported successfully")
                    self.report.add(
                        ImportReportItem(
                            "permissions", "success", None, None, "Collection Permissions", None
                        )
                    )

        except Exception as e:
            logger.error(f"Failed to import permissions: {e}", exc_info=True)
            self.report.add(
                ImportReportItem("permissions", "failed", None, None, "Permissions", str(e))
            )

    def _remap_permissions_graph(self, groups: dict[str, Any]) -> dict[str, Any]:
        """Remap database IDs in the permissions graph.

        Args:
            groups: Permissions graph groups

        Returns:
            Remapped permissions graph
        """
        remapped_groups = {}

        for group_id, group_perms in groups.items():
            remapped_group_perms = {}

            for db_id_str, db_perms in group_perms.items():
                # Skip non-database keys
                if not db_id_str.isdigit():
                    remapped_group_perms[db_id_str] = db_perms
                    continue

                source_db_id = int(db_id_str)
                target_db_id = self.id_remapper.resolve_db_id(source_db_id)

                if target_db_id is None:
                    logger.warning(
                        f"Skipping permissions for unmapped database {source_db_id} "
                        f"in group {group_id}"
                    )
                    continue

                # Remap the database ID in the permissions structure
                remapped_group_perms[str(target_db_id)] = db_perms

            remapped_groups[group_id] = remapped_group_perms

        return remapped_groups

    def _remap_collection_permissions_graph(
        self, collection_permissions: dict[str, Any]
    ) -> dict[str, Any]:
        """Remap collection IDs in the collection permissions graph.

        Args:
            collection_permissions: Collection permissions graph

        Returns:
            Remapped collection permissions graph
        """
        remapped_perms = {}

        for group_id, group_perms in collection_permissions.items():
            remapped_group_perms = {}

            for coll_id_str, coll_perms in group_perms.items():
                # Handle special "root" collection
                if coll_id_str == "root":
                    remapped_group_perms["root"] = coll_perms
                    continue

                # Skip non-collection keys
                if not coll_id_str.isdigit():
                    remapped_group_perms[coll_id_str] = coll_perms
                    continue

                source_coll_id = int(coll_id_str)
                target_coll_id = self.collection_map.get(source_coll_id)

                if target_coll_id is None:
                    logger.warning(
                        f"Skipping permissions for unmapped collection {source_coll_id} "
                        f"in group {group_id}"
                    )
                    continue

                # Remap the collection ID in the permissions structure
                remapped_group_perms[str(target_coll_id)] = coll_perms

            remapped_perms[group_id] = remapped_group_perms

        return remapped_perms
