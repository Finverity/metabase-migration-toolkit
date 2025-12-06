"""ID remapping logic for database, table, and field IDs.

This module handles the complex task of remapping instance-specific IDs
(databases, tables, fields) from source to target Metabase instances.
"""

import copy
import logging
from typing import Any

from lib.client import MetabaseAPIError, MetabaseClient
from lib.models import DatabaseMap, Manifest

logger = logging.getLogger("metabase_migration")


class IDRemapper:
    """Handles remapping of database, table, and field IDs between Metabase instances."""

    def __init__(
        self,
        client: MetabaseClient,
        manifest: Manifest,
        db_map: DatabaseMap,
    ) -> None:
        """Initialize the ID remapper.

        Args:
            client: Metabase API client for the target instance
            manifest: Export manifest containing source metadata
            db_map: Database mapping configuration
        """
        self.client = client
        self.manifest = manifest
        self.db_map = db_map

        # Mappings: (source_db_id, source_table_id) -> target_table_id
        self._table_map: dict[tuple[int, int], int] = {}
        # Mappings: (source_db_id, source_field_id) -> target_field_id
        self._field_map: dict[tuple[int, int], int] = {}
        # Cache of target database metadata: db_id -> {tables: [...], fields: [...]}
        self._target_db_metadata: dict[int, dict[str, Any]] = {}

    def resolve_db_id(self, source_db_id: int) -> int | None:
        """Resolve a source database ID to a target database ID.

        Args:
            source_db_id: Database ID from the source instance

        Returns:
            Target database ID, or None if not mapped
        """
        # by_id takes precedence (db_map.json uses string keys for JSON compatibility)
        if str(source_db_id) in self.db_map.by_id:
            return self.db_map.by_id[str(source_db_id)]

        # Look up database name using integer key
        source_db_name = self.manifest.databases.get(source_db_id)
        if source_db_name and source_db_name in self.db_map.by_name:
            return self.db_map.by_name[source_db_name]

        return None

    def build_table_and_field_mappings(self) -> None:
        """Build mappings between source and target table/field IDs.

        This is necessary because table and field IDs are instance-specific.
        We match tables and fields by name within the same database.
        """
        logger.info("Building table and field ID mappings...")

        try:
            for source_db_id, source_db_name in self.manifest.databases.items():
                target_db_id = self.resolve_db_id(source_db_id)
                if not target_db_id:
                    logger.debug(f"Skipping table mapping for unmapped database {source_db_id}")
                    continue

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
                target_tables_by_name = {t["name"]: t for t in target_metadata.get("tables", [])}
                target_fields_by_table_id = {}
                for table in target_metadata.get("tables", []):
                    target_fields_by_table_id[table["id"]] = {
                        f["name"]: f for f in table.get("fields", [])
                    }

                logger.debug(
                    f"Mapping tables from source DB {source_db_id} ({source_db_name}) "
                    f"to target DB {target_db_id}"
                )
                logger.debug(
                    f"  Source has {len(source_tables)} tables, "
                    f"target has {len(target_tables_by_name)} tables"
                )

                # Map each source table to target table by name
                for source_table in source_tables:
                    source_table_id = source_table["id"]
                    source_table_name = source_table["name"]

                    if source_table_name in target_tables_by_name:
                        target_table = target_tables_by_name[source_table_name]
                        target_table_id = target_table["id"]

                        mapping_key = (source_db_id, source_table_id)
                        self._table_map[mapping_key] = target_table_id

                        logger.debug(
                            f"  Mapped table '{source_table_name}': "
                            f"{source_table_id} (source) -> {target_table_id} (target)"
                        )

                        # Map fields within this table
                        source_fields = source_table.get("fields", [])
                        target_fields = target_fields_by_table_id.get(target_table_id, {})

                        for source_field in source_fields:
                            source_field_id = source_field["id"]
                            source_field_name = source_field["name"]

                            if source_field_name in target_fields:
                                target_field = target_fields[source_field_name]
                                target_field_id = target_field["id"]

                                field_mapping_key = (source_db_id, source_field_id)
                                self._field_map[field_mapping_key] = target_field_id

                                logger.debug(
                                    f"    Mapped field '{source_field_name}': "
                                    f"{source_field_id} (source) -> {target_field_id} (target)"
                                )
                    else:
                        logger.warning(
                            f"  Table '{source_table_name}' (ID: {source_table_id}) "
                            f"not found in target database {target_db_id}. "
                            f"Cards using this table may fail to import."
                        )

        except Exception as e:
            logger.warning(f"Failed to build table and field mappings: {e}", exc_info=True)

    def remap_field_ids_recursively(self, data: Any, source_db_id: int) -> Any:
        """Recursively remap field IDs in any data structure.

        This handles field references in all MBQL clauses including:
        - Filters: ["and", ["=", ["field", 201, {...}], "CUSTOMER"]]
        - Aggregations: ["sum", ["field", 5, None]]
        - Breakouts: [["field", 3, {"temporal-unit": "month"}]]
        - Order-by: [["asc", ["field", 10]]]
        - Fields: [["field", 100], ["field", 200]]
        - Expressions: {"+": [["field", 10], 5]}
        - Dashboard parameter targets: ["dimension", ["field", 3, {...}]]
        - Dashboard parameter value_field: ["field", 10, None]

        Args:
            data: Data structure to process (can be list, dict, or primitive)
            source_db_id: Source database ID for field lookup

        Returns:
            Data structure with remapped field IDs
        """
        if data is None:
            return data

        # Handle lists (most MBQL clauses are lists)
        if isinstance(data, list):
            if len(data) == 0:
                return data

            # Check if this is a field reference: ["field", field_id, {...}]
            # or ["field-id", field_id] (older format)
            if len(data) >= 2 and data[0] in ("field", "field-id"):
                source_field_id = data[1]
                if isinstance(source_field_id, int):
                    mapping_key = (source_db_id, source_field_id)
                    if mapping_key in self._field_map:
                        target_field_id = self._field_map[mapping_key]
                        result = list(data)
                        result[1] = target_field_id
                        logger.debug(
                            f"Remapped field ID from {source_field_id} to {target_field_id}"
                        )
                        return result
                    else:
                        logger.warning(
                            f"No field ID mapping found for source field {source_field_id} "
                            f"in database {source_db_id}. Keeping original field ID - this may cause issues."
                        )
                return data

            # Recursively process all items in the list
            return [self.remap_field_ids_recursively(item, source_db_id) for item in data]

        # Handle dictionaries
        if isinstance(data, dict):
            return {
                key: self.remap_field_ids_recursively(value, source_db_id)
                for key, value in data.items()
            }

        # Primitive values (strings, numbers, booleans, None) - return as-is
        return data

    def remap_card_query(self, card_data: dict, card_map: dict[int, int]) -> tuple[dict, bool]:
        """Remap database ID, table IDs, field IDs, and card references in a card's query.

        Args:
            card_data: Card data dictionary
            card_map: Mapping of source card IDs to target card IDs

        Returns:
            Tuple of (remapped_card_data, success_flag)

        Raises:
            ValueError: If database ID cannot be resolved
        """
        data = copy.deepcopy(card_data)
        query = data.get("dataset_query", {})

        source_db_id = data.get("database_id") or query.get("database")
        if not source_db_id:
            return data, False

        target_db_id = self.resolve_db_id(source_db_id)
        if not target_db_id:
            raise ValueError(
                f"FATAL: Unmapped database ID {source_db_id} found during card import. "
                f"This should have been caught by validation."
            )

        # Always set the database field in dataset_query
        query["database"] = target_db_id
        if "database_id" in data:
            data["database_id"] = target_db_id

        # Remap table_id at the card level (if present)
        if "table_id" in data and isinstance(data["table_id"], int):
            source_table_id = data["table_id"]
            mapping_key = (source_db_id, source_table_id)
            if mapping_key in self._table_map:
                target_table_id = self._table_map[mapping_key]
                data["table_id"] = target_table_id
                logger.debug(f"Remapped table_id from {source_table_id} to {target_table_id}")
            else:
                logger.warning(
                    f"No table ID mapping found for source table {source_table_id} "
                    f"in database {source_db_id}. Keeping original table_id - this may cause issues."
                )

        # Remap card references and table IDs in source-table
        inner_query = query.get("query", {})
        if inner_query:
            self._remap_source_table(inner_query, source_db_id, card_map)
            self._remap_joins(inner_query, source_db_id, card_map)
            self._remap_query_clauses(inner_query, source_db_id)

        # Remap field IDs and table IDs in result_metadata
        self._remap_result_metadata(data, source_db_id)

        # Remap field IDs in visualization_settings
        if "visualization_settings" in data:
            data["visualization_settings"] = self.remap_field_ids_recursively(
                data["visualization_settings"], source_db_id
            )

        return data, True

    def _remap_source_table(
        self, inner_query: dict, source_db_id: int, card_map: dict[int, int]
    ) -> None:
        """Remap source-table references (card or table IDs)."""
        source_table = inner_query.get("source-table")
        if isinstance(source_table, str) and source_table.startswith("card__"):
            try:
                source_card_id = int(source_table.replace("card__", ""))
                if source_card_id in card_map:
                    inner_query["source-table"] = f"card__{card_map[source_card_id]}"
                    logger.debug(
                        f"Remapped source-table from card__{source_card_id} "
                        f"to card__{card_map[source_card_id]}"
                    )
            except ValueError:
                logger.warning(f"Invalid card reference format: {source_table}")
        elif isinstance(source_table, int):
            mapping_key = (source_db_id, source_table)
            if mapping_key in self._table_map:
                target_table_id = self._table_map[mapping_key]
                inner_query["source-table"] = target_table_id
                logger.debug(f"Remapped source-table from {source_table} to {target_table_id}")
            else:
                logger.warning(
                    f"No table ID mapping found for source table {source_table} "
                    f"in database {source_db_id}. Keeping original table ID - this may cause issues."
                )

    def _remap_joins(self, inner_query: dict, source_db_id: int, card_map: dict[int, int]) -> None:
        """Remap card references and table IDs in joins."""
        joins = inner_query.get("joins", [])
        for join in joins:
            join_source_table = join.get("source-table")
            if isinstance(join_source_table, str) and join_source_table.startswith("card__"):
                try:
                    source_card_id = int(join_source_table.replace("card__", ""))
                    if source_card_id in card_map:
                        join["source-table"] = f"card__{card_map[source_card_id]}"
                        logger.debug(
                            f"Remapped join source-table from card__{source_card_id} "
                            f"to card__{card_map[source_card_id]}"
                        )
                except ValueError:
                    logger.warning(f"Invalid card reference in join: {join_source_table}")
            elif isinstance(join_source_table, int):
                mapping_key = (source_db_id, join_source_table)
                if mapping_key in self._table_map:
                    target_table_id = self._table_map[mapping_key]
                    join["source-table"] = target_table_id
                    logger.debug(
                        f"Remapped join source-table from {join_source_table} to {target_table_id}"
                    )

    def _remap_query_clauses(self, inner_query: dict, source_db_id: int) -> None:
        """Remap field IDs in all query clauses."""
        for key in ["filter", "aggregation", "breakout", "order-by", "fields", "expressions"]:
            if key in inner_query:
                inner_query[key] = self.remap_field_ids_recursively(inner_query[key], source_db_id)

    def _remap_result_metadata(self, data: dict, source_db_id: int) -> None:
        """Remap field IDs and table IDs in result_metadata."""
        if "result_metadata" not in data or not isinstance(data["result_metadata"], list):
            return

        remapped_metadata = []
        for metadata_item in data["result_metadata"]:
            if isinstance(metadata_item, dict):
                metadata_copy = metadata_item.copy()

                # Remap field_ref if present: ["field", field_id, {...}]
                if "field_ref" in metadata_copy:
                    metadata_copy["field_ref"] = self.remap_field_ids_recursively(
                        metadata_copy["field_ref"], source_db_id
                    )

                # Remap the direct field ID if present
                if "id" in metadata_copy and isinstance(metadata_copy["id"], int):
                    field_id = metadata_copy["id"]
                    mapping_key = (source_db_id, field_id)
                    if mapping_key in self._field_map:
                        metadata_copy["id"] = self._field_map[mapping_key]
                        logger.debug(
                            f"Remapped result_metadata field ID from {field_id} "
                            f"to {self._field_map[mapping_key]}"
                        )

                # Remap table_id if present
                if "table_id" in metadata_copy and isinstance(metadata_copy["table_id"], int):
                    table_id = metadata_copy["table_id"]
                    mapping_key = (source_db_id, table_id)
                    if mapping_key in self._table_map:
                        metadata_copy["table_id"] = self._table_map[mapping_key]
                        logger.debug(
                            f"Remapped result_metadata table ID from {table_id} "
                            f"to {self._table_map[mapping_key]}"
                        )

                remapped_metadata.append(metadata_copy)
            else:
                remapped_metadata.append(metadata_item)

        data["result_metadata"] = remapped_metadata

    @property
    def table_map(self) -> dict[tuple[int, int], int]:
        """Get the table ID mapping."""
        return self._table_map

    @property
    def field_map(self) -> dict[tuple[int, int], int]:
        """Get the field ID mapping."""
        return self._field_map
