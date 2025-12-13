"""Card handler for Metabase migration."""

import logging
import re
from typing import Any

from tqdm import tqdm

from lib.client import MetabaseAPIError
from lib.constants import (
    CARD_REF_PREFIX,
    CONFLICT_OVERWRITE,
    CONFLICT_RENAME,
    CONFLICT_SKIP,
    JOINS_KEY,
    NATIVE_CARD_REF_PATTERN,
    NATIVE_KEY,
    QUERY_KEY,
    SOURCE_TABLE_KEY,
    STAGES_KEY,
    TEMPLATE_TAGS_KEY,
)
from lib.handlers.base import BaseHandler, ImportContext
from lib.models import Card
from lib.utils import clean_for_create, read_json_file

logger = logging.getLogger("metabase_migration")


class CardHandler(BaseHandler):
    """Handles import of cards (questions and models)."""

    def __init__(self, context: ImportContext) -> None:
        """Initialize the card handler."""
        super().__init__(context)

    def import_cards(self, cards: list[Card]) -> None:
        """Imports all cards in dependency order.

        Args:
            cards: List of cards to import.
        """
        # Filter based on archived status
        cards_to_import = [
            card for card in cards if not card.archived or self.context.should_include_archived()
        ]

        # Count models vs questions for logging
        model_count = sum(1 for card in cards_to_import if card.dataset)
        question_count = len(cards_to_import) - model_count

        # Sort cards in topological order (dependencies first)
        logger.info("Analyzing card dependencies...")
        sorted_cards = self._topological_sort_cards(cards_to_import)
        logger.info(
            f"Importing {len(sorted_cards)} cards "
            f"({model_count} models, {question_count} questions) in dependency order..."
        )

        for card in tqdm(sorted_cards, desc="Importing Cards"):
            self._import_single_card(card)

    def _import_single_card(self, card: Card) -> None:
        """Imports a single card.

        Args:
            card: The card to import.
        """
        try:
            card_data = read_json_file(self.context.export_dir / card.file_path)

            # Check for missing dependencies
            deps = self._extract_card_dependencies(card_data)
            missing_deps = self._check_missing_dependencies(deps, card)
            if missing_deps:
                error_msg = (
                    f"Card depends on missing cards: {missing_deps}. "
                    "These cards are not in the export."
                )
                logger.error(f"Skipping card '{card.name}' (ID: {card.id}): {error_msg}")
                self._add_report_item("card", "failed", card.id, None, card.name, error_msg)
                return

            # Remap database and card references
            card_data, remapped = self.query_remapper.remap_card_data(card_data)
            if not remapped:
                raise ValueError("Card does not have a database reference.")

            # Remap collection
            target_collection_id = self.id_mapper.resolve_collection_id(card.collection_id)
            card_data["collection_id"] = target_collection_id

            # Handle conflicts using cached collection items lookup
            existing_card = self.context.find_existing_card(card.name, target_collection_id)

            if existing_card:
                self._handle_existing_card(card, card_data, existing_card, target_collection_id)
            else:
                self._create_card(card, card_data)

        except MetabaseAPIError as e:
            self._handle_api_error(card, e)
        except Exception as e:
            logger.error(
                f"Failed to import card '{card.name}' (ID: {card.id}): {e}",
                exc_info=True,
            )
            self._add_report_item("card", "failed", card.id, None, card.name, str(e))

    def _handle_existing_card(
        self,
        card: Card,
        card_data: dict[str, Any],
        existing_card: dict[str, Any],
        target_collection_id: int | None,
    ) -> None:
        """Handles conflict when card already exists.

        Args:
            card: The source card.
            card_data: The card data to import.
            existing_card: The existing target card.
            target_collection_id: The target collection ID.
        """
        strategy = self.context.get_conflict_strategy()

        if strategy == CONFLICT_SKIP:
            self.id_mapper.set_card_mapping(card.id, existing_card["id"])
            self._add_report_item(
                "card",
                "skipped",
                card.id,
                existing_card["id"],
                card.name,
                "Already exists (skipped)",
            )
            logger.debug(
                f"Skipped card '{card.name}' - already exists with ID {existing_card['id']}"
            )

        elif strategy == CONFLICT_OVERWRITE:
            payload = clean_for_create(card_data)
            updated_card = self.client.update_card(existing_card["id"], payload)
            self.id_mapper.set_card_mapping(card.id, updated_card["id"])
            self._add_report_item("card", "updated", card.id, updated_card["id"], card.name)
            is_model = card_data.get("dataset", False)
            item_type = "Model" if is_model else "Card"
            logger.debug(f"Updated {item_type} '{card.name}' (ID: {updated_card['id']})")

        elif strategy == CONFLICT_RENAME:
            new_name = self._generate_unique_card_name(card.name, target_collection_id)
            card_data["name"] = new_name
            logger.info(f"Renamed card '{card.name}' to '{new_name}' to avoid conflict")
            self._create_card(card, card_data)

    def _create_card(self, card: Card, card_data: dict[str, Any]) -> None:
        """Creates a new card.

        Args:
            card: The source card.
            card_data: The card data to create.
        """
        payload = clean_for_create(card_data)
        new_card = self.client.create_card(payload)
        self.id_mapper.set_card_mapping(card.id, new_card["id"])
        self._add_report_item(
            "card", "created", card.id, new_card["id"], card_data.get("name", card.name)
        )

        # Add to collection cache to keep it up-to-date for conflict detection
        is_model = card_data.get("dataset", False)
        self.context.add_to_collection_cache(
            card_data.get("collection_id"),
            {
                "id": new_card["id"],
                "name": card_data.get("name", card.name),
                "model": "dataset" if is_model else "card",
            },
        )

        item_type = "Model" if is_model else "Card"
        logger.debug(
            f"Successfully imported {item_type} '{card_data.get('name', card.name)}' "
            f"{card.id} -> {new_card['id']}"
        )

    def _generate_unique_card_name(self, base_name: str, collection_id: int | None) -> str:
        """Generates a unique card name by appending a number.

        Uses cached collection items for O(1) lookup.

        Args:
            base_name: The original name.
            collection_id: The collection ID.

        Returns:
            A unique name.
        """
        counter = 1
        while True:
            new_name = f"{base_name} ({counter})"
            if not self.context.find_existing_card(new_name, collection_id):
                return new_name
            counter += 1

    def _check_missing_dependencies(self, deps: set[int], card: Card) -> list[int]:
        """Checks for dependencies that are missing.

        Args:
            deps: Set of dependency card IDs.
            card: The card being imported.

        Returns:
            List of missing dependency IDs.
        """
        missing_deps = []
        for dep_id in deps:
            if self.id_mapper.resolve_card_id(dep_id) is None:
                # Check if the dependency is in the export but not yet imported
                dep_in_export = any(c.id == dep_id for c in self.context.manifest.cards)
                if not dep_in_export:
                    missing_deps.append(dep_id)
        return missing_deps

    def _handle_api_error(self, card: Card, error: MetabaseAPIError) -> None:
        """Handles API errors during card import.

        Args:
            card: The card that failed.
            error: The API error.
        """
        error_msg = str(error)

        # Check for missing card reference errors
        if "does not exist" in error_msg and "Card" in error_msg:
            match = re.search(r"Card (\d+) does not exist", error_msg)
            if match:
                missing_card_id = int(match.group(1))
                self._log_missing_card_error(card, missing_card_id)
                self._add_report_item(
                    "card",
                    "failed",
                    card.id,
                    None,
                    card.name,
                    f"Missing dependency: card {missing_card_id}",
                )
                return

        # Check for table ID constraint violation
        if "fk_report_card_ref_table_id" in error_msg.lower() or (
            "table_id" in error_msg.lower() and "not present in table" in error_msg.lower()
        ):
            match = re.search(r"table_id\)=\((\d+)\)", error_msg)
            table_id = match.group(1) if match else "unknown"
            self._log_table_id_error(card, table_id, error_msg)
            self._add_report_item(
                "card",
                "failed",
                card.id,
                None,
                card.name,
                f"Table ID {table_id} not found in target",
            )
            return

        # Other API errors
        logger.error(
            f"Failed to import card '{card.name}' (ID: {card.id}): {error}",
            exc_info=True,
        )
        self._add_report_item("card", "failed", card.id, None, card.name, str(error))

    def _log_missing_card_error(self, card: Card, missing_card_id: int) -> None:
        """Logs detailed error for missing card dependency."""
        logger.error("=" * 80)
        logger.error("MISSING CARD DEPENDENCY ERROR!")
        logger.error("=" * 80)
        logger.error(f"Failed to import card '{card.name}' (ID: {card.id})")
        logger.error(
            f"The card references another card (ID: {missing_card_id}) "
            "that doesn't exist in the target instance."
        )
        logger.error("")
        logger.error("This usually means:")
        logger.error(f"1. Card {missing_card_id} was not included in the export")
        logger.error(f"2. Card {missing_card_id} failed to import earlier")
        logger.error(f"3. Card {missing_card_id} is archived and --include-archived was not used")
        logger.error("=" * 80)

    def _log_table_id_error(self, card: Card, table_id: str, error_msg: str) -> None:
        """Logs detailed error for table ID mapping failure."""
        logger.error("=" * 80)
        logger.error("TABLE ID MAPPING ERROR DETECTED!")
        logger.error("=" * 80)
        logger.error(f"Failed to import card '{card.name}' (ID: {card.id})")
        logger.error(
            f"The card references table ID {table_id} that doesn't exist "
            "in the target Metabase instance."
        )
        logger.error("")
        logger.error("SOLUTIONS:")
        logger.error("1. Ensure the target database is properly synced in Metabase")
        logger.error("2. Go to Admin > Databases > [Your Database] > 'Sync database schema now'")
        logger.error("3. Verify the table exists in the target database")
        logger.error(f"Error details: {error_msg}")
        logger.error("=" * 80)

    # --- Dependency resolution ---

    @staticmethod
    def _extract_card_dependencies(card_data: dict[str, Any]) -> set[int]:
        """Extracts card IDs that this card depends on.

        Handles both MBQL and native SQL queries:
        - MBQL: card__123 references in source-table and joins
        - Native SQL: {{#123-model-name}} references in SQL and template-tags
        - v57 MBQL 5 format with stages

        Args:
            card_data: The card data dictionary.

        Returns:
            Set of card IDs this card depends on.
        """
        dependencies: set[int] = set()

        dataset_query = card_data.get("dataset_query", {})

        # Check for v57 MBQL 5 format (has stages)
        stages = dataset_query.get(STAGES_KEY, [])
        if stages and isinstance(stages, list):
            for stage in stages:
                if not isinstance(stage, dict):
                    continue

                # Extract MBQL dependencies from stage
                CardHandler._extract_mbql_deps_from_query(stage, dependencies)

                # Extract native query dependencies from stage (v57 format)
                native_sql = stage.get(NATIVE_KEY)
                if isinstance(native_sql, str):
                    CardHandler._extract_native_sql_deps(native_sql, dependencies)

                # Extract template-tags dependencies
                template_tags = stage.get(TEMPLATE_TAGS_KEY, {})
                CardHandler._extract_template_tag_deps(template_tags, dependencies)
        else:
            # v56 MBQL 4 format
            query = dataset_query.get(QUERY_KEY, {})
            if query:
                CardHandler._extract_mbql_deps_from_query(query, dependencies)

            # Check native queries (v56 format)
            native = dataset_query.get(NATIVE_KEY)
            if isinstance(native, dict):
                # Native SQL query string
                native_sql = native.get("query")
                if isinstance(native_sql, str):
                    CardHandler._extract_native_sql_deps(native_sql, dependencies)

                # Template-tags
                template_tags = native.get(TEMPLATE_TAGS_KEY, {})
                CardHandler._extract_template_tag_deps(template_tags, dependencies)

        return dependencies

    @staticmethod
    def _extract_mbql_deps_from_query(query: dict[str, Any], dependencies: set[int]) -> None:
        """Extracts card dependencies from an MBQL query dict.

        Args:
            query: The query dictionary (either v56 query or v57 stage).
            dependencies: Set to add found card IDs to.
        """
        # Check source-table for card references
        source_table = query.get(SOURCE_TABLE_KEY)
        if isinstance(source_table, str) and source_table.startswith(CARD_REF_PREFIX):
            try:
                card_id = int(source_table.replace(CARD_REF_PREFIX, ""))
                dependencies.add(card_id)
            except ValueError:
                logger.warning(f"Invalid card reference format: {source_table}")

        # Check joins for card references
        for join in query.get(JOINS_KEY, []):
            join_source_table = join.get(SOURCE_TABLE_KEY)
            if isinstance(join_source_table, str) and join_source_table.startswith(CARD_REF_PREFIX):
                try:
                    card_id = int(join_source_table.replace(CARD_REF_PREFIX, ""))
                    dependencies.add(card_id)
                except ValueError:
                    logger.warning(f"Invalid card reference in join: {join_source_table}")

    @staticmethod
    def _extract_native_sql_deps(sql: str, dependencies: set[int]) -> None:
        """Extracts card IDs from native SQL query references.

        Finds {{#123-model-name}} patterns in SQL.

        Args:
            sql: The SQL query string.
            dependencies: Set to add found card IDs to.
        """
        # Pattern: {{#123-model-name}} - extract the card ID
        matches = re.findall(NATIVE_CARD_REF_PATTERN, sql)
        for card_id_str in matches:
            try:
                card_id = int(card_id_str)
                dependencies.add(card_id)
            except ValueError:
                logger.warning(f"Invalid card ID in SQL reference: {card_id_str}")

    @staticmethod
    def _extract_template_tag_deps(template_tags: dict[str, Any], dependencies: set[int]) -> None:
        """Extracts card IDs from template-tags with type "card".

        Args:
            template_tags: The template-tags dictionary.
            dependencies: Set to add found card IDs to.
        """
        if not isinstance(template_tags, dict):
            return

        for _tag_name, tag_data in template_tags.items():
            if isinstance(tag_data, dict) and tag_data.get("type") == "card":
                card_id = tag_data.get("card-id")
                if card_id is not None:
                    dependencies.add(card_id)

    def _topological_sort_cards(self, cards: list[Card]) -> list[Card]:
        """Sorts cards in topological order so dependencies are imported first.

        Args:
            cards: List of cards to sort.

        Returns:
            Sorted list of cards.
        """
        # Build a map of card ID to card object
        card_map = {card.id: card for card in cards}

        # Build dependency graph
        dependencies: dict[int, set[int]] = {}
        for card in cards:
            try:
                card_data = read_json_file(self.context.export_dir / card.file_path)
                deps = self._extract_card_dependencies(card_data)
                # Only keep dependencies that are in our export
                dependencies[card.id] = deps & set(card_map.keys())
            except Exception as e:
                logger.warning(f"Failed to extract dependencies for card {card.id}: {e}")
                dependencies[card.id] = set()

        # Perform topological sort using Kahn's algorithm
        sorted_cards: list[Card] = []
        in_degree: dict[int, int] = {card.id: 0 for card in cards}

        # Calculate in-degrees
        for card_id, deps in dependencies.items():
            for dep_id in deps:
                if dep_id in in_degree:
                    in_degree[card_id] += 1

        # Queue of cards with no dependencies
        queue = [card_id for card_id, degree in in_degree.items() if degree == 0]

        while queue:
            queue.sort()  # Ensure deterministic order
            card_id = queue.pop(0)
            sorted_cards.append(card_map[card_id])

            # Reduce in-degree for dependent cards
            for other_id, deps in dependencies.items():
                if card_id in deps and other_id in in_degree:
                    in_degree[other_id] -= 1
                    if in_degree[other_id] == 0:
                        queue.append(other_id)

        # Handle circular dependencies
        if len(sorted_cards) < len(cards):
            remaining = [
                card_map[card_id]
                for card_id in card_map.keys()
                if card_id not in [c.id for c in sorted_cards]
            ]
            logger.warning(f"Found {len(remaining)} cards with circular or missing dependencies")
            sorted_cards.extend(remaining)

        return sorted_cards
