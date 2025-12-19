"""ID mapping between source and target Metabase instances.

Manages mappings for database, table, field, collection, and card IDs.
"""

import logging
from typing import Any

from lib.client import MetabaseAPIError, MetabaseClient
from lib.models import DatabaseMap, Manifest

logger = logging.getLogger("metabase_migration")


class IDMapper:
    """Manages ID mappings between source and target Metabase instances."""

    def __init__(
        self,
        manifest: Manifest,
        db_map: DatabaseMap,
        client: MetabaseClient | None = None,
    ) -> None:
        """Initialize the IDMapper.

        Args:
            manifest: The export manifest containing source metadata.
            db_map: Database ID mapping configuration.
            client: Optional MetabaseClient for fetching target metadata.
        """
        self.manifest = manifest
        self.db_map = db_map
        self.client = client

        # ID mappings: source_id -> target_id
        self._collection_map: dict[int, int] = {}
        self._card_map: dict[int, int] = {}
        self._dashboard_map: dict[int, int] = {}
        self._group_map: dict[int, int] = {}

        # Table and field mappings: (source_db_id, source_id) -> target_id
        self._table_map: dict[tuple[int, int], int] = {}
        self._field_map: dict[tuple[int, int], int] = {}

        # Cache of target database metadata
        self._target_db_metadata: dict[int, dict[str, Any]] = {}

    # --- Property accessors for maps ---

    @property
    def collection_map(self) -> dict[int, int]:
        """Returns the collection ID mapping."""
        return self._collection_map

    @property
    def card_map(self) -> dict[int, int]:
        """Returns the card ID mapping."""
        return self._card_map

    @property
    def dashboard_map(self) -> dict[int, int]:
        """Returns the dashboard ID mapping."""
        return self._dashboard_map

    @property
    def group_map(self) -> dict[int, int]:
        """Returns the permission group ID mapping."""
        return self._group_map

    @property
    def table_map(self) -> dict[tuple[int, int], int]:
        """Returns the table ID mapping."""
        return self._table_map

    @property
    def field_map(self) -> dict[tuple[int, int], int]:
        """Returns the field ID mapping."""
        return self._field_map

    # --- Map setters ---

    def set_collection_mapping(self, source_id: int, target_id: int) -> None:
        """Sets a collection ID mapping."""
        self._collection_map[source_id] = target_id

    def set_card_mapping(self, source_id: int, target_id: int) -> None:
        """Sets a card ID mapping."""
        self._card_map[source_id] = target_id

    def set_dashboard_mapping(self, source_id: int, target_id: int) -> None:
        """Sets a dashboard ID mapping."""
        self._dashboard_map[source_id] = target_id

    def set_group_mapping(self, source_id: int, target_id: int) -> None:
        """Sets a permission group ID mapping."""
        self._group_map[source_id] = target_id

    # --- Database ID resolution ---

    def resolve_db_id(self, source_db_id: int) -> int | None:
        """Resolves a source database ID to a target database ID.

        Args:
            source_db_id: The source database ID.

        Returns:
            The target database ID, or None if not mapped.
        """
        # by_id takes precedence (db_map.json uses string keys for JSON compatibility)
        if str(source_db_id) in self.db_map.by_id:
            return self.db_map.by_id[str(source_db_id)]

        # Look up database name using integer key
        source_db_name = self.manifest.databases.get(source_db_id)
        if source_db_name and source_db_name in self.db_map.by_name:
            return self.db_map.by_name[source_db_name]

        return None

    def resolve_table_id(self, source_db_id: int, source_table_id: int) -> int | None:
        """Resolves a source table ID to a target table ID.

        Args:
            source_db_id: The source database ID.
            source_table_id: The source table ID.

        Returns:
            The target table ID, or None if not mapped.
        """
        mapping_key = (source_db_id, source_table_id)
        return self._table_map.get(mapping_key)

    def resolve_field_id(self, source_db_id: int, source_field_id: int) -> int | None:
        """Resolves a source field ID to a target field ID.

        Args:
            source_db_id: The source database ID.
            source_field_id: The source field ID.

        Returns:
            The target field ID, or None if not mapped.
        """
        mapping_key = (source_db_id, source_field_id)
        return self._field_map.get(mapping_key)

    def resolve_collection_id(self, source_collection_id: int | None) -> int | None:
        """Resolves a source collection ID to a target collection ID.

        Args:
            source_collection_id: The source collection ID.

        Returns:
            The target collection ID, or None if not mapped or source is None.
        """
        if source_collection_id is None:
            return None
        return self._collection_map.get(source_collection_id)

    def resolve_card_id(self, source_card_id: int) -> int | None:
        """Resolves a source card ID to a target card ID.

        Args:
            source_card_id: The source card ID.

        Returns:
            The target card ID, or None if not mapped.
        """
        return self._card_map.get(source_card_id)

    def resolve_dashboard_id(self, source_dashboard_id: int) -> int | None:
        """Resolves a source dashboard ID to a target dashboard ID.

        Args:
            source_dashboard_id: The source dashboard ID.

        Returns:
            The target dashboard ID, or None if not mapped.
        """
        return self._dashboard_map.get(source_dashboard_id)

    # --- Build table and field mappings ---

    def build_table_and_field_mappings(self) -> None:
        """Builds mappings between source and target table/field IDs.

        This matches tables by name within the same database.
        Requires a MetabaseClient to be set.
        """
        if not self.client:
            logger.warning("No MetabaseClient set, cannot build table/field mappings")
            return

        logger.info("Building table and field ID mappings...")

        for source_db_id, _source_db_name in self.manifest.databases.items():
            target_db_id = self.resolve_db_id(source_db_id)
            if not target_db_id:
                logger.debug(f"Skipping table mapping for unmapped database {source_db_id}")
                continue

            # Get source database metadata from manifest
            source_metadata = self.manifest.database_metadata.get(source_db_id, {})
            source_tables = source_metadata.get("tables", [])

            if not source_tables:
                logger.debug(
                    f"No table metadata available for source database {source_db_id}. "
                    f"Table ID remapping will not work."
                )
                continue

            # Fetch target database metadata
            if target_db_id not in self._target_db_metadata:
                logger.debug(f"Fetching metadata for target database {target_db_id}...")
                try:
                    target_metadata_response = self.client.get_database_metadata(target_db_id)
                    self._target_db_metadata[target_db_id] = target_metadata_response
                except MetabaseAPIError as e:
                    logger.warning(
                        f"Failed to fetch metadata for target database {target_db_id}: {e}. "
                        f"Table ID remapping will not work for this database."
                    )
                    continue

            target_metadata = self._target_db_metadata[target_db_id]
            self._map_tables_and_fields(source_db_id, source_tables, target_db_id, target_metadata)

    def _map_tables_and_fields(
        self,
        source_db_id: int,
        source_tables: list[dict[str, Any]],
        target_db_id: int,
        target_metadata: dict[str, Any],
    ) -> None:
        """Maps tables and fields from source to target by name matching.

        Args:
            source_db_id: Source database ID.
            source_tables: List of source table metadata.
            target_db_id: Target database ID.
            target_metadata: Target database metadata.
        """
        # Build lookup maps for target
        target_tables_by_name = {t["name"]: t for t in target_metadata.get("tables", [])}
        target_fields_by_table_id: dict[int, dict[str, dict[str, Any]]] = {}
        for table in target_metadata.get("tables", []):
            target_fields_by_table_id[table["id"]] = {f["name"]: f for f in table.get("fields", [])}

        logger.debug(f"Mapping tables from source DB {source_db_id} to target DB {target_db_id}")
        logger.debug(
            f"  Source has {len(source_tables)} tables, "
            f"target has {len(target_tables_by_name)} tables"
        )

        for source_table in source_tables:
            source_table_id = source_table["id"]
            source_table_name = source_table["name"]

            if source_table_name in target_tables_by_name:
                target_table = target_tables_by_name[source_table_name]
                target_table_id = target_table["id"]

                # Store the table mapping
                mapping_key = (source_db_id, source_table_id)
                self._table_map[mapping_key] = target_table_id

                logger.debug(
                    f"  Mapped table '{source_table_name}': "
                    f"{source_table_id} -> {target_table_id}"
                )

                # Map fields within this table
                self._map_fields(
                    source_db_id,
                    source_table.get("fields", []),
                    target_table_id,
                    target_fields_by_table_id.get(target_table_id, {}),
                )
            else:
                logger.warning(
                    f"  Table '{source_table_name}' (ID: {source_table_id}) "
                    f"not found in target database {target_db_id}. "
                    f"Cards using this table may fail to import."
                )

    def _map_fields(
        self,
        source_db_id: int,
        source_fields: list[dict[str, Any]],
        target_table_id: int,
        target_fields: dict[str, dict[str, Any]],
    ) -> None:
        """Maps fields from source to target by name matching.

        Args:
            source_db_id: Source database ID.
            source_fields: List of source field metadata.
            target_table_id: Target table ID.
            target_fields: Target fields lookup by name.
        """
        for source_field in source_fields:
            source_field_id = source_field["id"]
            source_field_name = source_field["name"]

            if source_field_name in target_fields:
                target_field = target_fields[source_field_name]
                target_field_id = target_field["id"]

                # Store the field mapping
                field_mapping_key = (source_db_id, source_field_id)
                self._field_map[field_mapping_key] = target_field_id

                logger.debug(
                    f"    Mapped field '{source_field_name}': "
                    f"{source_field_id} -> {target_field_id}"
                )
