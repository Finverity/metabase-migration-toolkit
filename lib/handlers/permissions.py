"""Permissions handler for Metabase migration."""

import logging
from typing import Any

from lib.client import MetabaseAPIError
from lib.constants import BUILTIN_PERMISSION_GROUPS
from lib.handlers.base import BaseHandler, ImportContext

logger = logging.getLogger("metabase_migration")


class PermissionsHandler(BaseHandler):
    """Handles import of permission groups and permissions graphs."""

    def __init__(self, context: ImportContext) -> None:
        """Initialize the permissions handler."""
        super().__init__(context)

    def import_permissions(self) -> None:
        """Imports permission groups and applies permissions graphs."""
        try:
            # Map permission groups
            logger.info("Mapping permission groups...")
            self._map_permission_groups()

            if not self.id_mapper.group_map:
                logger.warning("No permission groups could be mapped. Skipping permissions import.")
                return

            # Apply data permissions
            data_perms_applied = self._apply_data_permissions()

            # Apply collection permissions
            collection_perms_applied = self._apply_collection_permissions()

            # Log summary
            self._log_summary(data_perms_applied, collection_perms_applied)

        except Exception as e:
            logger.error(f"Failed to import permissions: {e}", exc_info=True)
            logger.warning("Permissions import failed. Continuing without permissions...")

    def _map_permission_groups(self) -> None:
        """Maps permission groups from source to target."""
        target_groups = self.client.get_permission_groups()
        target_groups_by_name = {g["name"]: g for g in target_groups}

        for source_group in self.context.manifest.permission_groups:
            if source_group.name in target_groups_by_name:
                target_group = target_groups_by_name[source_group.name]
                self.id_mapper.set_group_mapping(source_group.id, target_group["id"])
                logger.info(
                    f"  -> Mapped group '{source_group.name}': "
                    f"source ID {source_group.id} -> target ID {target_group['id']}"
                )
            elif source_group.name not in BUILTIN_PERMISSION_GROUPS:
                logger.warning(
                    f"  -> Group '{source_group.name}' (ID: {source_group.id}) "
                    f"not found on target. Permissions for this group will be skipped."
                )
            else:
                logger.warning(f"  -> Built-in group '{source_group.name}' not found. Unexpected.")

    def _apply_data_permissions(self) -> bool:
        """Applies the data permissions graph.

        Returns:
            True if permissions were applied successfully.
        """
        if not self.context.manifest.permissions_graph:
            return False

        logger.info("Applying data permissions...")
        remapped_permissions = self._remap_permissions_graph(
            self.context.manifest.permissions_graph
        )

        if not remapped_permissions:
            logger.info("No data permissions to apply (all databases unmapped)")
            return False

        try:
            self.client.update_permissions_graph(remapped_permissions)
            logger.info("Data permissions applied successfully")
            return True
        except MetabaseAPIError as e:
            logger.error(f"Failed to apply data permissions: {e}")
            logger.warning("Continuing without data permissions...")
            return False

    def _apply_collection_permissions(self) -> bool:
        """Applies the collection permissions graph.

        Returns:
            True if permissions were applied successfully.
        """
        if not self.context.manifest.collection_permissions_graph:
            return False

        logger.info("Applying collection permissions...")
        remapped_permissions = self._remap_collection_permissions_graph(
            self.context.manifest.collection_permissions_graph
        )

        if not remapped_permissions:
            logger.info("No collection permissions to apply (all collections unmapped)")
            return False

        try:
            self.client.update_collection_permissions_graph(remapped_permissions)
            logger.info("Collection permissions applied successfully")
            return True
        except MetabaseAPIError as e:
            logger.error(f"Failed to apply collection permissions: {e}")
            logger.warning("Continuing without collection permissions...")
            return False

    def _remap_permissions_graph(self, source_graph: dict[str, Any]) -> dict[str, Any]:
        """Remaps database and group IDs in the permissions graph.

        Args:
            source_graph: The source permissions graph.

        Returns:
            The remapped permissions graph.
        """
        if not source_graph or "groups" not in source_graph:
            return {}

        # Get current revision from target
        current_revision = self._get_current_permissions_revision()
        remapped_graph: dict[str, Any] = {"revision": current_revision, "groups": {}}

        unmapped_databases: set[int] = set()

        for source_group_id_str, group_perms in source_graph.get("groups", {}).items():
            source_group_id = int(source_group_id_str)

            if source_group_id not in self.id_mapper.group_map:
                logger.debug(f"Skipping permissions for unmapped group ID {source_group_id}")
                continue

            target_group_id = self.id_mapper.group_map[source_group_id]
            remapped_group_perms = {}

            for source_db_id_str, db_perms in group_perms.items():
                source_db_id = int(source_db_id_str)
                target_db_id = self.id_mapper.resolve_db_id(source_db_id)

                if target_db_id:
                    remapped_group_perms[str(target_db_id)] = db_perms
                    logger.debug(
                        f"Remapped database permissions: group {target_group_id}, "
                        f"DB {source_db_id} -> {target_db_id}"
                    )
                else:
                    unmapped_databases.add(source_db_id)

            if remapped_group_perms:
                remapped_graph["groups"][str(target_group_id)] = remapped_group_perms

        if unmapped_databases:
            db_names = [
                f"{db_id} ({self.context.manifest.databases.get(db_id, 'unknown')})"
                for db_id in sorted(unmapped_databases)
            ]
            logger.warning(
                f"Skipped permissions for {len(unmapped_databases)} database(s) "
                f"not found in db_map.json: {', '.join(db_names)}"
            )

        return remapped_graph if remapped_graph["groups"] else {}

    def _remap_collection_permissions_graph(self, source_graph: dict[str, Any]) -> dict[str, Any]:
        """Remaps collection and group IDs in the collection permissions graph.

        Args:
            source_graph: The source collection permissions graph.

        Returns:
            The remapped collection permissions graph.
        """
        if not source_graph or "groups" not in source_graph:
            return {}

        # Get current revision from target
        current_revision = self._get_current_collection_permissions_revision()
        remapped_graph: dict[str, Any] = {"revision": current_revision, "groups": {}}

        unmapped_collections: set[int] = set()

        for source_group_id_str, group_perms in source_graph.get("groups", {}).items():
            source_group_id = int(source_group_id_str)

            if source_group_id not in self.id_mapper.group_map:
                logger.debug(
                    f"Skipping collection permissions for unmapped group ID {source_group_id}"
                )
                continue

            target_group_id = self.id_mapper.group_map[source_group_id]
            remapped_group_perms = {}

            for source_coll_id_str, coll_perms in group_perms.items():
                if source_coll_id_str == "root":
                    remapped_group_perms["root"] = coll_perms
                    continue

                source_coll_id = int(source_coll_id_str)
                target_coll_id = self.id_mapper.resolve_collection_id(source_coll_id)

                if target_coll_id:
                    remapped_group_perms[str(target_coll_id)] = coll_perms
                    logger.debug(
                        f"Remapped collection permissions: group {target_group_id}, "
                        f"collection {source_coll_id} -> {target_coll_id}"
                    )
                else:
                    unmapped_collections.add(source_coll_id)

            if remapped_group_perms:
                remapped_graph["groups"][str(target_group_id)] = remapped_group_perms

        if unmapped_collections:
            logger.info(
                f"Skipped permissions for {len(unmapped_collections)} collection(s) "
                f"not included in the export: {sorted(unmapped_collections)}"
            )

        return remapped_graph if remapped_graph["groups"] else {}

    def _get_current_permissions_revision(self) -> int:
        """Gets the current permissions graph revision from target."""
        try:
            current_graph = self.client.get_permissions_graph()
            revision: int = current_graph.get("revision", 0)
            logger.debug(f"Using current permissions revision: {revision}")
            return revision
        except Exception as e:
            logger.warning(f"Could not fetch current permissions revision: {e}. Using 0.")
            return 0

    def _get_current_collection_permissions_revision(self) -> int:
        """Gets the current collection permissions graph revision from target."""
        try:
            current_graph = self.client.get_collection_permissions_graph()
            revision: int = current_graph.get("revision", 0)
            logger.debug(f"Using current collection permissions revision: {revision}")
            return revision
        except Exception as e:
            logger.warning(
                f"Could not fetch current collection permissions revision: {e}. Using 0."
            )
            return 0

    def _log_summary(self, data_perms_applied: bool, collection_perms_applied: bool) -> None:
        """Logs the permissions import summary."""
        logger.info("=" * 60)
        logger.info("Permissions Import Summary:")
        logger.info(f"  Groups mapped: {len(self.id_mapper.group_map)}")
        logger.info(f"  Data permissions: {'Applied' if data_perms_applied else 'Not applied'}")
        logger.info(
            f"  Collection permissions: "
            f"{'Applied' if collection_perms_applied else 'Not applied'}"
        )
        logger.info("=" * 60)
