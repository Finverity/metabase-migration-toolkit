"""Query remapping logic for Metabase MBQL queries.

Handles remapping of database, table, field, and card IDs within
MBQL query structures. Supports both v56 (MBQL 4) and v57 (MBQL 5) formats.
"""

import copy
import logging
import re
from typing import Any

from lib.constants import (
    CARD_REF_PREFIX,
    FIELD_CONTAINING_CLAUSES,
    FIELD_REF_TYPES,
    JOINS_KEY,
    LIB_TYPE_KEY,
    NATIVE_CARD_REF_FULL_PATTERN,
    NATIVE_KEY,
    QUERY_KEY,
    SOURCE_TABLE_KEY,
    STAGES_KEY,
    TEMPLATE_TAGS_KEY,
    V57_BASE_TYPE,
    V57_FIELD_CONTAINING_CLAUSES,
    V57_LIB_UUID,
    V57_SOURCE_CARD_KEY,
)
from lib.remapping.id_mapper import IDMapper

logger = logging.getLogger("metabase_migration")


class QueryRemapper:
    """Handles remapping of IDs within MBQL queries and card data."""

    def __init__(self, id_mapper: IDMapper) -> None:
        """Initialize the QueryRemapper.

        Args:
            id_mapper: The IDMapper instance for resolving IDs.
        """
        self.id_mapper = id_mapper

    def remap_card_data(self, card_data: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        """Remaps database, table, field, and card IDs in card data.

        Handles both MBQL and native SQL queries, including:
        - Database ID remapping
        - Table ID remapping
        - Field ID remapping
        - Card references in MBQL (card__123 format)
        - Card references in native SQL ({{#123-model-name}} format)
        - Template tags with card-id remapping

        Args:
            card_data: The original card data dictionary.

        Returns:
            A tuple of (remapped_data, success). Success is False if the
            card has no database reference.

        Raises:
            ValueError: If the database ID cannot be mapped.
        """
        data = copy.deepcopy(card_data)
        query = data.get("dataset_query", {})

        source_db_id = data.get("database_id") or query.get("database")
        if not source_db_id:
            return data, False

        target_db_id = self.id_mapper.resolve_db_id(source_db_id)
        if not target_db_id:
            raise ValueError(
                f"FATAL: Unmapped database ID {source_db_id} found during card import. "
                "This should have been caught by validation."
            )

        # Set database ID in query and at top level
        query["database"] = target_db_id
        if "database_id" in data:
            data["database_id"] = target_db_id

        # Remap table_id at the card level
        self._remap_card_table_id(data, source_db_id)

        # Check if this is a native query (v56 or v57 format)
        is_native_query = self._is_native_query(query)

        if is_native_query:
            # Remap native query card references (SQL and template-tags)
            self._remap_native_query_in_place(query)
        else:
            # Remap MBQL query (source-table, joins, field IDs)
            self._remap_mbql_query(query, source_db_id)

        # Remap result_metadata
        if "result_metadata" in data:
            data["result_metadata"] = self._remap_result_metadata(
                data["result_metadata"], source_db_id
            )

        # Remap visualization_settings
        if "visualization_settings" in data:
            data["visualization_settings"] = self.remap_field_ids_recursively(
                data["visualization_settings"], source_db_id
            )

        return data, True

    def _is_native_query(self, dataset_query: dict[str, Any]) -> bool:
        """Determines if a query is a native SQL query.

        Args:
            dataset_query: The dataset_query dictionary.

        Returns:
            True if this is a native query, False for MBQL queries.
        """
        # v56 format: check "type" field
        if dataset_query.get("type") == "native":
            return True

        # v57 format: check stages for native stage type
        stages = dataset_query.get(STAGES_KEY, [])
        if stages and isinstance(stages, list):
            for stage in stages:
                if isinstance(stage, dict):
                    lib_type = stage.get(LIB_TYPE_KEY, "")
                    if lib_type == "mbql.stage/native":
                        return True
                    # Also check if native key exists with a string value
                    if isinstance(stage.get(NATIVE_KEY), str):
                        return True

        return False

    def _remap_mbql_query(self, dataset_query: dict[str, Any], source_db_id: int) -> None:
        """Remaps an MBQL query (source-table, joins, field IDs).

        Args:
            dataset_query: The dataset_query dictionary to modify in place.
            source_db_id: The source database ID for field lookups.
        """
        # Check for v57 MBQL 5 format with stages
        stages = dataset_query.get(STAGES_KEY, [])
        if stages and isinstance(stages, list):
            for stage in stages:
                if isinstance(stage, dict):
                    self._remap_source_table(stage, source_db_id)
                    self._remap_joins(stage, source_db_id)
                    self._remap_query_clauses(stage, source_db_id)
        else:
            # v56 MBQL 4 format
            inner_query = dataset_query.get(QUERY_KEY, {})
            if inner_query:
                self._remap_source_table(inner_query, source_db_id)
                self._remap_joins(inner_query, source_db_id)
                self._remap_query_clauses(inner_query, source_db_id)

    def _remap_native_query_in_place(self, dataset_query: dict[str, Any]) -> None:
        """Remaps native query card references in place.

        Args:
            dataset_query: The dataset_query dictionary to modify in place.
        """
        # Check query format (v57 uses lib/type and stages, v56 uses type)
        if LIB_TYPE_KEY in dataset_query or STAGES_KEY in dataset_query:
            # v57 MBQL 5 format with stages
            self._remap_native_query_v57(dataset_query)
        else:
            # v56 MBQL 4 format
            self._remap_native_query_v56(dataset_query)

    def _remap_card_table_id(self, data: dict[str, Any], source_db_id: int) -> None:
        """Remaps the table_id field at the card level."""
        if "table_id" not in data or not isinstance(data["table_id"], int):
            return

        source_table_id = data["table_id"]
        target_table_id = self.id_mapper.resolve_table_id(source_db_id, source_table_id)

        if target_table_id:
            data["table_id"] = target_table_id
            logger.debug(f"Remapped table_id from {source_table_id} to {target_table_id}")
        else:
            logger.warning(
                f"No table ID mapping found for source table {source_table_id} "
                f"in database {source_db_id}. Keeping original table_id."
            )

    def _remap_source_table(self, query: dict[str, Any], source_db_id: int) -> None:
        """Remaps the source-table and source-card fields in a query.

        Handles both v56 and v57 formats:
        - v56: source-table can be int (table ID) or string ("card__123")
        - v57: source-table is int (table ID), source-card is int (card ID)
        """
        # v57 format: source-card (integer card ID)
        source_card = query.get(V57_SOURCE_CARD_KEY)
        if source_card is not None and isinstance(source_card, int):
            target_card_id = self.id_mapper.resolve_card_id(source_card)
            if target_card_id:
                query[V57_SOURCE_CARD_KEY] = target_card_id
                logger.debug(f"Remapped v57 source-card from {source_card} to {target_card_id}")
            else:
                logger.warning(
                    f"No card mapping found for v57 source-card {source_card}. "
                    f"Keeping original card ID."
                )

        # v56 format (or v57 for tables): source-table
        source_table = query.get(SOURCE_TABLE_KEY)
        if source_table is None:
            return

        if isinstance(source_table, str) and source_table.startswith(CARD_REF_PREFIX):
            # v56 Card reference: "card__123"
            self._remap_card_reference(query, SOURCE_TABLE_KEY, source_table)
        elif isinstance(source_table, int):
            # Table ID (both v56 and v57)
            target_table_id = self.id_mapper.resolve_table_id(source_db_id, source_table)
            if target_table_id:
                query[SOURCE_TABLE_KEY] = target_table_id
                logger.debug(f"Remapped source-table from {source_table} to {target_table_id}")
            else:
                logger.warning(
                    f"No table ID mapping found for source table {source_table} "
                    f"in database {source_db_id}. Keeping original table ID."
                )

    def _remap_card_reference(self, container: dict[str, Any], key: str, card_ref: str) -> None:
        """Remaps a card reference string (e.g., 'card__123')."""
        try:
            source_card_id = int(card_ref.replace(CARD_REF_PREFIX, ""))
            target_card_id = self.id_mapper.resolve_card_id(source_card_id)
            if target_card_id:
                container[key] = f"{CARD_REF_PREFIX}{target_card_id}"
                logger.debug(
                    f"Remapped {key} from card__{source_card_id} to card__{target_card_id}"
                )
        except ValueError:
            logger.warning(f"Invalid card reference format: {card_ref}")

    def _remap_joins(self, query: dict[str, Any], source_db_id: int) -> None:
        """Remaps source-table and source-card references in join clauses.

        Handles both v56 and v57 join formats:
        - v56: {"joins": [{"source-table": 123 or "card__123", ...}]}
        - v57: {"joins": [{"source-card": 123, ...}]} or nested stages
        """
        joins = query.get(JOINS_KEY, [])
        for join in joins:
            # v57: Check for nested stages in join
            if STAGES_KEY in join and isinstance(join[STAGES_KEY], list):
                for join_stage in join[STAGES_KEY]:
                    if isinstance(join_stage, dict):
                        self._remap_source_table(join_stage, source_db_id)
                        # Also remap field IDs in join conditions within stages
                        self._remap_query_clauses(join_stage, source_db_id)
                # Also remap condition at join level if present
                if "condition" in join:
                    join["condition"] = self.remap_field_ids_recursively(
                        join["condition"], source_db_id
                    )
                continue

            # v57: Check for source-card (integer card ID)
            source_card = join.get(V57_SOURCE_CARD_KEY)
            if source_card is not None and isinstance(source_card, int):
                target_card_id = self.id_mapper.resolve_card_id(source_card)
                if target_card_id:
                    join[V57_SOURCE_CARD_KEY] = target_card_id
                    logger.debug(
                        f"Remapped v57 join source-card from {source_card} to {target_card_id}"
                    )

            # v56 format: source-table directly in join
            join_source_table = join.get(SOURCE_TABLE_KEY)
            if join_source_table is not None:
                if isinstance(join_source_table, str) and join_source_table.startswith(
                    CARD_REF_PREFIX
                ):
                    self._remap_card_reference(join, SOURCE_TABLE_KEY, join_source_table)
                elif isinstance(join_source_table, int):
                    target_table_id = self.id_mapper.resolve_table_id(
                        source_db_id, join_source_table
                    )
                    if target_table_id:
                        join[SOURCE_TABLE_KEY] = target_table_id
                        logger.debug(
                            f"Remapped join source-table from {join_source_table} "
                            f"to {target_table_id}"
                        )

            # Remap condition field IDs
            if "condition" in join:
                join["condition"] = self.remap_field_ids_recursively(
                    join["condition"], source_db_id
                )

    def _remap_query_clauses(self, query: dict[str, Any], source_db_id: int) -> None:
        """Remaps field IDs in query clauses (filter, aggregation, etc.).

        Handles both v56 and v57 key names:
        - v56: "filter" (singular)
        - v57: "filters" (plural)
        """
        # Process v56 clauses
        for key in FIELD_CONTAINING_CLAUSES:
            if key in query:
                query[key] = self.remap_field_ids_recursively(query[key], source_db_id)

        # Process v57 clauses (different key names)
        for key in V57_FIELD_CONTAINING_CLAUSES:
            if key in query and key not in FIELD_CONTAINING_CLAUSES:
                query[key] = self.remap_field_ids_recursively(query[key], source_db_id)

    def _remap_result_metadata(self, metadata: list[Any], source_db_id: int) -> list[Any]:
        """Remaps field and table IDs in result_metadata."""
        if not isinstance(metadata, list):
            return metadata

        remapped_metadata = []
        for item in metadata:
            if not isinstance(item, dict):
                remapped_metadata.append(item)
                continue

            item_copy = item.copy()

            # Remap field_ref
            if "field_ref" in item_copy:
                item_copy["field_ref"] = self.remap_field_ids_recursively(
                    item_copy["field_ref"], source_db_id
                )

            # Remap direct field ID
            if "id" in item_copy and isinstance(item_copy["id"], int):
                target_field_id = self.id_mapper.resolve_field_id(source_db_id, item_copy["id"])
                if target_field_id:
                    logger.debug(
                        f"Remapped result_metadata field ID from {item_copy['id']} "
                        f"to {target_field_id}"
                    )
                    item_copy["id"] = target_field_id

            # Remap table_id
            if "table_id" in item_copy and isinstance(item_copy["table_id"], int):
                target_table_id = self.id_mapper.resolve_table_id(
                    source_db_id, item_copy["table_id"]
                )
                if target_table_id:
                    logger.debug(
                        f"Remapped result_metadata table ID from {item_copy['table_id']} "
                        f"to {target_table_id}"
                    )
                    item_copy["table_id"] = target_table_id

            remapped_metadata.append(item_copy)

        return remapped_metadata

    def remap_field_ids_recursively(self, data: Any, source_db_id: int) -> Any:
        """Recursively remaps field IDs in any data structure.

        Handles field references in all MBQL clauses including:
        - Filters: ["and", ["=", ["field", 201, {...}], "CUSTOMER"]]
        - Aggregations: ["sum", ["field", 5, None]]
        - Breakouts: [["field", 3, {"temporal-unit": "month"}]]
        - Order-by: [["asc", ["field", 10]]]
        - Fields: [["field", 100], ["field", 200]]
        - Expressions: {"+": [["field", 10], 5]}
        - Dashboard parameter targets: ["dimension", ["field", 3, {...}]]
        - Dashboard parameter value_field: ["field", 10, None]

        Args:
            data: The data structure to remap (can be list, dict, or primitive).
            source_db_id: The source database ID for field lookups.

        Returns:
            The remapped data structure.
        """
        if data is None:
            return data

        # Handle lists (most MBQL clauses are lists)
        if isinstance(data, list):
            return self._remap_list(data, source_db_id)

        # Handle dictionaries
        if isinstance(data, dict):
            return {
                key: self.remap_field_ids_recursively(value, source_db_id)
                for key, value in data.items()
            }

        # Primitive values - return as-is
        return data

    def _remap_list(self, data: list[Any], source_db_id: int) -> list[Any]:
        """Remaps field IDs in a list structure.

        Handles both v56 and v57 field reference formats:
        - v56: ["field", field_id, {...}] where field_id is int at index 1
        - v57: ["field", {metadata}, field_id] where field_id is int at index 2
        - v57: ["field", field_id, {metadata}] same as v56 but with more metadata
        """
        if len(data) == 0:
            return data

        # Check if this is a field reference: ["field", ...]
        if len(data) >= 2 and data[0] in FIELD_REF_TYPES:
            # v57 format: ["field", {metadata_dict}, field_id]
            # Metadata dict contains lib/uuid, base-type, effective-type, etc.
            if (
                len(data) >= 3
                and isinstance(data[1], dict)
                and (V57_LIB_UUID in data[1] or V57_BASE_TYPE in data[1])
                and isinstance(data[2], int)
            ):
                source_field_id = data[2]
                target_field_id = self.id_mapper.resolve_field_id(source_db_id, source_field_id)
                if target_field_id:
                    result = list(data)
                    result[2] = target_field_id
                    logger.debug(
                        f"Remapped v57 field ID from {source_field_id} to {target_field_id}"
                    )
                    return result
                else:
                    logger.warning(
                        f"No field ID mapping found for v57 source field {source_field_id} "
                        f"in database {source_db_id}. Keeping original field ID."
                    )
                return data

            # v56 format (or v57 with field_id at index 1): ["field", field_id, {...}]
            source_field_id = data[1]
            if isinstance(source_field_id, int):
                target_field_id = self.id_mapper.resolve_field_id(source_db_id, source_field_id)
                if target_field_id:
                    result = list(data)
                    result[1] = target_field_id
                    logger.debug(f"Remapped field ID from {source_field_id} to {target_field_id}")
                    return result
                else:
                    logger.warning(
                        f"No field ID mapping found for source field {source_field_id} "
                        f"in database {source_db_id}. Keeping original field ID."
                    )
            return data

        # Recursively process all items in the list
        return [self.remap_field_ids_recursively(item, source_db_id) for item in data]

    def remap_dashboard_parameters(
        self, parameters: list[dict[str, Any]], manifest_cards: list[Any]
    ) -> list[dict[str, Any]]:
        """Remaps card and field IDs in dashboard parameters.

        Args:
            parameters: List of dashboard parameter dictionaries.
            manifest_cards: List of cards from the manifest for database ID lookup.

        Returns:
            List of remapped parameter dictionaries.
        """
        remapped_parameters = []

        for param in parameters:
            param_copy = param.copy()

            # Check for values_source_config with card_id
            if "values_source_config" in param_copy and isinstance(
                param_copy["values_source_config"], dict
            ):
                self._remap_parameter_source_config(param_copy, manifest_cards)

            remapped_parameters.append(param_copy)

        return remapped_parameters

    def _remap_parameter_source_config(
        self, param: dict[str, Any], manifest_cards: list[Any]
    ) -> None:
        """Remaps a parameter's values_source_config."""
        config = param["values_source_config"]
        source_card_id = config.get("card_id")

        if not source_card_id:
            return

        target_card_id = self.id_mapper.resolve_card_id(source_card_id)
        if target_card_id:
            config["card_id"] = target_card_id
            logger.debug(f"Remapped parameter card_id {source_card_id} -> {target_card_id}")

            # Remap field IDs in value_field
            if "value_field" in config:
                source_db_id = self._find_card_database_id(source_card_id, manifest_cards)
                if source_db_id:
                    config["value_field"] = self.remap_field_ids_recursively(
                        config["value_field"], source_db_id
                    )
                else:
                    logger.warning(
                        f"Could not determine database ID for card {source_card_id}. "
                        f"Field IDs in value_field will not be remapped."
                    )
        else:
            # Card not found, remove values_source_config
            logger.warning(
                f"Dashboard parameter '{param.get('name')}' references missing "
                f"card {source_card_id}. Importing without values_source_config."
            )
            del param["values_source_config"]
            if "values_source_type" in param:
                del param["values_source_type"]

    def _find_card_database_id(self, card_id: int, manifest_cards: list[Any]) -> int | None:
        """Finds the database_id for a card from the manifest."""
        for card in manifest_cards:
            if card.id == card_id:
                db_id: int | None = card.database_id
                return db_id
        return None

    def remap_dashcard_parameter_mappings(
        self,
        parameter_mappings: list[dict[str, Any]],
        source_db_id: int | None,
    ) -> list[dict[str, Any]]:
        """Remaps card and field IDs in dashcard parameter mappings.

        Args:
            parameter_mappings: List of parameter mapping dictionaries.
            source_db_id: The source database ID for the dashcard's card.

        Returns:
            List of remapped parameter mapping dictionaries.
        """
        remapped_mappings = []

        for mapping in parameter_mappings:
            clean_mapping = mapping.copy()

            # Remap card_id
            if "card_id" in clean_mapping:
                source_card_id = clean_mapping["card_id"]
                target_card_id = self.id_mapper.resolve_card_id(source_card_id)
                if target_card_id:
                    clean_mapping["card_id"] = target_card_id

            # Remap field IDs in target
            if "target" in clean_mapping and source_db_id:
                clean_mapping["target"] = self.remap_field_ids_recursively(
                    clean_mapping["target"], source_db_id
                )

            remapped_mappings.append(clean_mapping)

        return remapped_mappings

    # =========================================================================
    # Native Query Card Reference Remapping
    # =========================================================================

    def remap_native_query(self, card_data: dict[str, Any]) -> dict[str, Any]:
        """Remaps card references in native SQL queries.

        Handles both v56 (MBQL 4) and v57 (MBQL 5) query formats:
        - SQL query text: {{#123-model-name}} -> {{#456-model-name}}
        - Template tags with type "card": card-id remapping

        Args:
            card_data: The card data dictionary with dataset_query.

        Returns:
            The card data with remapped native query references.
        """
        data = copy.deepcopy(card_data)
        dataset_query = data.get("dataset_query", {})

        # Check query format (v57 uses lib/type and stages, v56 uses type)
        if LIB_TYPE_KEY in dataset_query:
            # v57 MBQL 5 format with stages
            self._remap_native_query_v57(dataset_query)
        else:
            # v56 MBQL 4 format
            self._remap_native_query_v56(dataset_query)

        return data

    def _remap_native_query_v56(self, dataset_query: dict[str, Any]) -> None:
        """Remaps native query card references in v56 (MBQL 4) format.

        v56 structure:
        {
            "type": "native",
            "native": {
                "query": "SELECT * FROM {{#123-model}}",
                "template-tags": {
                    "123-model": {"type": "card", "card-id": 123, ...}
                }
            }
        }

        Args:
            dataset_query: The dataset_query dictionary to modify in place.
        """
        native = dataset_query.get(NATIVE_KEY)
        if not isinstance(native, dict):
            return

        # Remap SQL query string
        query_str = native.get("query")
        if isinstance(query_str, str):
            native["query"] = self._remap_sql_card_references(query_str)

        # Remap template-tags
        template_tags = native.get(TEMPLATE_TAGS_KEY)
        if isinstance(template_tags, dict):
            native[TEMPLATE_TAGS_KEY] = self._remap_template_tags(template_tags)

    def _remap_native_query_v57(self, dataset_query: dict[str, Any]) -> None:
        """Remaps native query card references in v57 (MBQL 5) format.

        v57 structure:
        {
            "lib/type": "mbql/query",
            "stages": [
                {
                    "lib/type": "mbql.stage/native",
                    "native": "SELECT * FROM {{#123-model}}",
                    "template-tags": {
                        "123-model": {"type": "card", "card-id": 123, ...}
                    }
                }
            ]
        }

        Args:
            dataset_query: The dataset_query dictionary to modify in place.
        """
        stages = dataset_query.get(STAGES_KEY, [])
        if not isinstance(stages, list):
            return

        for stage in stages:
            if not isinstance(stage, dict):
                continue

            # In v57, native SQL is stored directly in "native" as a string
            native_sql = stage.get(NATIVE_KEY)
            if isinstance(native_sql, str):
                stage[NATIVE_KEY] = self._remap_sql_card_references(native_sql)

            # Remap template-tags at stage level
            template_tags = stage.get(TEMPLATE_TAGS_KEY)
            if isinstance(template_tags, dict):
                stage[TEMPLATE_TAGS_KEY] = self._remap_template_tags(template_tags)

    def _remap_sql_card_references(self, sql: str) -> str:
        """Remaps card references in a SQL query string.

        Replaces {{#old_id-name}} with {{#new_id-name}} using the card_id_map.

        Args:
            sql: The SQL query string.

        Returns:
            The SQL string with remapped card references.
        """

        def replace_card_ref(match: re.Match[str]) -> str:
            source_card_id = int(match.group(1))
            suffix = match.group(2)  # Includes the hyphen and name, e.g., "-model-name"

            target_card_id = self.id_mapper.resolve_card_id(source_card_id)
            if target_card_id:
                logger.debug(
                    f"Remapped SQL card reference from {{{{#{source_card_id}{suffix}}}}} "
                    f"to {{{{#{target_card_id}{suffix}}}}}"
                )
                return f"{{{{#{target_card_id}{suffix}}}}}"
            else:
                logger.warning(
                    f"No card mapping found for card reference {{{{#{source_card_id}{suffix}}}}}. "
                    f"Keeping original reference."
                )
                return match.group(0)

        return re.sub(NATIVE_CARD_REF_FULL_PATTERN, replace_card_ref, sql)

    def _remap_template_tags(self, template_tags: dict[str, Any]) -> dict[str, Any]:
        """Remaps card references in template-tags.

        Updates both the tag names and the card-id values for card-type tags.

        Args:
            template_tags: The template-tags dictionary.

        Returns:
            A new dictionary with remapped template tags.
        """
        remapped_tags: dict[str, Any] = {}

        for tag_name, tag_data in template_tags.items():
            if not isinstance(tag_data, dict):
                remapped_tags[tag_name] = tag_data
                continue

            # Check if this is a card-type template tag
            if tag_data.get("type") == "card":
                source_card_id = tag_data.get("card-id")
                if source_card_id is not None:
                    target_card_id = self.id_mapper.resolve_card_id(source_card_id)
                    if target_card_id:
                        # Update the card-id
                        tag_data_copy = tag_data.copy()
                        tag_data_copy["card-id"] = target_card_id

                        # Update the tag name if it contains the old card ID
                        new_tag_name = self._remap_tag_name(
                            tag_name, source_card_id, target_card_id
                        )

                        # Update the "name" field inside the tag data if present
                        if "name" in tag_data_copy:
                            tag_data_copy["name"] = self._remap_tag_name(
                                tag_data_copy["name"], source_card_id, target_card_id
                            )

                        # Update display-name if it references the old ID
                        if "display-name" in tag_data_copy:
                            tag_data_copy["display-name"] = self._remap_tag_name(
                                tag_data_copy["display-name"], source_card_id, target_card_id
                            )

                        remapped_tags[new_tag_name] = tag_data_copy
                        logger.debug(
                            f"Remapped template tag '{tag_name}' -> '{new_tag_name}' "
                            f"(card-id {source_card_id} -> {target_card_id})"
                        )
                        continue
                    else:
                        logger.warning(
                            f"No card mapping found for template tag '{tag_name}' "
                            f"with card-id {source_card_id}. Keeping original."
                        )

            # Non-card tags or unmapped card tags - keep as-is
            remapped_tags[tag_name] = tag_data

        return remapped_tags

    def _remap_tag_name(self, tag_name: str, source_card_id: int, target_card_id: int) -> str:
        """Remaps a template tag name by replacing the old card ID with the new one.

        Tag names follow these patterns:
        - v56 format: "123-model-name" where 123 is the card ID
        - v57 format: "#123-model-name" where #123 is the card ID with hash prefix
        - display-name format: "#123 Model Name" where #123 is followed by space

        Args:
            tag_name: The original tag name.
            source_card_id: The source card ID.
            target_card_id: The target card ID.

        Returns:
            The tag name with the card ID replaced.
        """
        # Pattern matches tag names with optional # prefix, followed by card ID and separator
        # Group 1 captures the optional # prefix to preserve it in replacement
        # Group 2 captures the separator (hyphen or space) to preserve it in replacement
        pattern = rf"^(#?){source_card_id}([-\s])"
        match = re.match(pattern, tag_name)
        if match:
            prefix = match.group(1)  # Either "#" or ""
            separator = match.group(2)  # Either "-" or " "
            return re.sub(pattern, f"{prefix}{target_card_id}{separator}", tag_name)
        return tag_name

    # =========================================================================
    # Dashcard Visualization Settings Remapping
    # =========================================================================

    def remap_dashcard_visualization_settings(
        self,
        viz_settings: dict[str, Any],
        source_db_id: int | None,
    ) -> dict[str, Any]:
        """Remaps card and dashboard IDs in dashcard visualization_settings.

        Handles:
        - click_behavior.targetId for question/dashboard links
        - visualization.columnValuesMapping for Visualizer dashcards (card:ID format)
        - link.entity.id for link cards

        Args:
            viz_settings: The visualization_settings dictionary.
            source_db_id: The source database ID for field lookups.

        Returns:
            The remapped visualization_settings dictionary.
        """
        if not viz_settings:
            return viz_settings

        result = copy.deepcopy(viz_settings)

        # Remap click_behavior
        if "click_behavior" in result:
            result["click_behavior"] = self._remap_click_behavior(result["click_behavior"])

        # Remap column-level click behaviors (for table visualizations)
        # These are stored as column_settings.{column_key}.click_behavior
        if "column_settings" in result and isinstance(result["column_settings"], dict):
            for col_key, col_settings in result["column_settings"].items():
                if isinstance(col_settings, dict) and "click_behavior" in col_settings:
                    result["column_settings"][col_key]["click_behavior"] = (
                        self._remap_click_behavior(col_settings["click_behavior"])
                    )

        # Remap Visualizer columnValuesMapping (card:ID format)
        if "visualization" in result and isinstance(result["visualization"], dict):
            result["visualization"] = self._remap_visualizer_definition(result["visualization"])

        # Remap link card entity
        if "link" in result and isinstance(result["link"], dict):
            result["link"] = self._remap_link_card_settings(result["link"])

        # Remap field IDs in visualization settings
        if source_db_id:
            result = self.remap_field_ids_recursively(result, source_db_id)

        return result

    def _remap_click_behavior(self, click_behavior: dict[str, Any]) -> dict[str, Any]:
        """Remaps card and dashboard IDs in click_behavior.

        Handles:
        - type: "link", linkType: "question" -> remap targetId as card ID
        - type: "link", linkType: "dashboard" -> remap targetId as dashboard ID

        Args:
            click_behavior: The click_behavior dictionary.

        Returns:
            The remapped click_behavior dictionary.
        """
        if not isinstance(click_behavior, dict):
            return click_behavior

        result = copy.deepcopy(click_behavior)

        if result.get("type") == "link" and "targetId" in result:
            link_type = result.get("linkType")
            target_id = result["targetId"]

            if link_type == "question" and isinstance(target_id, int):
                new_target_id = self.id_mapper.resolve_card_id(target_id)
                if new_target_id:
                    result["targetId"] = new_target_id
                    logger.debug(
                        f"Remapped click_behavior targetId (question) "
                        f"from {target_id} to {new_target_id}"
                    )
                else:
                    logger.warning(
                        f"No card mapping found for click_behavior targetId {target_id}. "
                        f"Keeping original."
                    )

            elif link_type == "dashboard" and isinstance(target_id, int):
                new_target_id = self.id_mapper.resolve_dashboard_id(target_id)
                if new_target_id:
                    result["targetId"] = new_target_id
                    logger.debug(
                        f"Remapped click_behavior targetId (dashboard) "
                        f"from {target_id} to {new_target_id}"
                    )
                else:
                    logger.warning(
                        f"No dashboard mapping found for click_behavior targetId {target_id}. "
                        f"Keeping original."
                    )

        return result

    def _remap_visualizer_definition(self, visualization: dict[str, Any]) -> dict[str, Any]:
        """Remaps card IDs in Visualizer definition.

        The Visualizer stores card references in columnValuesMapping as:
        - sourceId: "card:123" where 123 is the card ID

        Args:
            visualization: The visualization definition dictionary.

        Returns:
            The remapped visualization dictionary.
        """
        if not isinstance(visualization, dict):
            return visualization

        result = copy.deepcopy(visualization)

        # Remap columnValuesMapping
        column_values_mapping = result.get("columnValuesMapping")
        if isinstance(column_values_mapping, dict):
            result["columnValuesMapping"] = self._remap_column_values_mapping(column_values_mapping)

        return result

    def _remap_column_values_mapping(self, mapping: dict[str, Any]) -> dict[str, Any]:
        """Remaps card IDs in columnValuesMapping.

        The mapping contains entries like:
        {
            "column_name": [
                {"sourceId": "card:123", "name": "col", "originalName": "col"}
            ]
        }

        Args:
            mapping: The columnValuesMapping dictionary.

        Returns:
            The remapped mapping dictionary.
        """
        result: dict[str, Any] = {}

        for key, value in mapping.items():
            if isinstance(value, list):
                remapped_list: list[Any] = []
                for item in value:
                    if isinstance(item, dict) and "sourceId" in item:
                        remapped_item = self._remap_visualizer_source_id(item)
                        remapped_list.append(remapped_item)
                    elif isinstance(item, str) and item.startswith("$_card:"):
                        # Handle data source name references: $_card:123_name
                        remapped_list.append(self._remap_data_source_name_ref(item))
                    else:
                        remapped_list.append(item)
                result[key] = remapped_list
            else:
                result[key] = value

        return result

    def _remap_visualizer_source_id(self, item: dict[str, Any]) -> dict[str, Any]:
        """Remaps a single Visualizer column reference.

        Args:
            item: A column reference dict with sourceId like "card:123".

        Returns:
            The remapped column reference.
        """
        result = item.copy()
        source_id = result.get("sourceId", "")

        if isinstance(source_id, str) and source_id.startswith("card:"):
            try:
                card_id = int(source_id.replace("card:", ""))
                new_card_id = self.id_mapper.resolve_card_id(card_id)
                if new_card_id:
                    result["sourceId"] = f"card:{new_card_id}"
                    logger.debug(
                        f"Remapped Visualizer sourceId from card:{card_id} to card:{new_card_id}"
                    )
                else:
                    logger.warning(
                        f"No card mapping found for Visualizer sourceId card:{card_id}. "
                        f"Keeping original."
                    )
            except ValueError:
                logger.warning(f"Invalid Visualizer sourceId format: {source_id}")

        return result

    def _remap_data_source_name_ref(self, ref: str) -> str:
        """Remaps a Visualizer data source name reference.

        Format: $_card:123_name -> $_card:456_name

        Args:
            ref: The data source name reference string.

        Returns:
            The remapped reference string.
        """
        # Pattern: $_card:123_name
        pattern = r"^\$_card:(\d+)_name$"
        match = re.match(pattern, ref)
        if match:
            card_id = int(match.group(1))
            new_card_id = self.id_mapper.resolve_card_id(card_id)
            if new_card_id:
                new_ref = f"$_card:{new_card_id}_name"
                logger.debug(f"Remapped data source name ref from {ref} to {new_ref}")
                return new_ref
            else:
                logger.warning(
                    f"No card mapping found for data source name ref {ref}. Keeping original."
                )
        return ref

    def _remap_link_card_settings(self, link: dict[str, Any]) -> dict[str, Any]:
        """Remaps entity IDs in link card settings.

        Link cards can link to:
        - Cards (model: "card" or "question")
        - Dashboards (model: "dashboard")
        - Other entities

        Args:
            link: The link settings dictionary.

        Returns:
            The remapped link settings.
        """
        if not isinstance(link, dict):
            return link

        result = copy.deepcopy(link)
        entity = result.get("entity")

        if not isinstance(entity, dict) or "restricted" in entity:
            return result

        entity_id = entity.get("id")
        model = entity.get("model")

        if not isinstance(entity_id, int):
            return result

        if model in ("card", "question", "model", "metric"):
            new_id = self.id_mapper.resolve_card_id(entity_id)
            if new_id:
                result["entity"]["id"] = new_id
                logger.debug(f"Remapped link card entity id ({model}) from {entity_id} to {new_id}")
            else:
                logger.warning(
                    f"No card mapping found for link card entity id {entity_id}. "
                    f"Keeping original."
                )

        elif model == "dashboard":
            new_id = self.id_mapper.resolve_dashboard_id(entity_id)
            if new_id:
                result["entity"]["id"] = new_id
                logger.debug(
                    f"Remapped link card entity id (dashboard) from {entity_id} to {new_id}"
                )
            else:
                logger.warning(
                    f"No dashboard mapping found for link card entity id {entity_id}. "
                    f"Keeping original."
                )

        return result
