"""Card import logic with dependency resolution.

This module handles importing cards (questions and models) from the export
manifest to the target Metabase instance, including topological sorting for
dependencies and comprehensive error handling.
"""

import logging
import re
from pathlib import Path

from tqdm import tqdm

from lib.client import MetabaseAPIError, MetabaseClient
from lib.conflict_resolution import ConflictResolver
from lib.id_remapping import IDRemapper
from lib.models import Card, ImportReport, ImportReportItem, Manifest
from lib.utils import clean_for_create, read_json_file

logger = logging.getLogger("metabase_migration")


class CardImporter:
    """Handles importing cards (questions and models) to a target Metabase instance."""

    def __init__(
        self,
        client: MetabaseClient,
        manifest: Manifest,
        id_remapper: IDRemapper,
        conflict_resolver: ConflictResolver,
        report: ImportReport,
        export_dir: Path,
        collection_map: dict[int, int],
        include_archived: bool = False,
    ) -> None:
        """Initialize the card importer.

        Args:
            client: Metabase API client for the target instance
            manifest: Export manifest containing cards
            id_remapper: ID remapper for database/table/field IDs
            conflict_resolver: Conflict resolution handler
            report: Import report for tracking results
            export_dir: Directory containing exported files
            collection_map: Mapping of source to target collection IDs
            include_archived: Whether to include archived cards
        """
        self.client = client
        self.manifest = manifest
        self.id_remapper = id_remapper
        self.conflict_resolver = conflict_resolver
        self.report = report
        self.export_dir = export_dir
        self.collection_map = collection_map
        self.include_archived = include_archived

        # Mapping from source card ID to target card ID
        self._card_map: dict[int, int] = {}

    def import_cards(self) -> dict[int, int]:
        """Import all cards from the manifest in dependency order.

        Returns:
            Mapping of source card IDs to target card IDs
        """
        # Filter cards based on archived status
        cards_to_import = [
            card for card in self.manifest.cards if not card.archived or self.include_archived
        ]

        # Count models vs questions
        model_count = sum(1 for card in cards_to_import if card.dataset)
        question_count = len(cards_to_import) - model_count

        # Sort cards in topological order (dependencies first)
        logger.info("Analyzing card dependencies...")
        sorted_cards = self._topological_sort_cards(cards_to_import)
        logger.info(
            f"Importing {len(sorted_cards)} cards ({model_count} models, "
            f"{question_count} questions) in dependency order..."
        )

        for card in tqdm(sorted_cards, desc="Importing Cards"):
            try:
                self._import_single_card(card)
            except MetabaseAPIError as e:
                self._handle_api_error(card, e)
            except Exception as e:
                logger.error(
                    f"Failed to import card '{card.name}' (ID: {card.id}): {e}", exc_info=True
                )
                self.report.add(
                    ImportReportItem("card", "failed", card.id, None, card.name, str(e))
                )

        return self._card_map

    def _import_single_card(self, card: Card) -> None:
        """Import a single card.

        Args:
            card: Card to import
        """
        card_data = read_json_file(self.export_dir / card.file_path)

        # Check for missing dependencies
        deps = self._extract_card_dependencies(card_data)
        missing_deps = []
        for dep_id in deps:
            if dep_id not in self._card_map:
                dep_in_export = any(c.id == dep_id for c in self.manifest.cards)
                if not dep_in_export:
                    missing_deps.append(dep_id)

        if missing_deps:
            error_msg = (
                f"Card depends on missing cards: {missing_deps}. "
                f"These cards are not in the export."
            )
            logger.error(f"Skipping card '{card.name}' (ID: {card.id}): {error_msg}")
            self.report.add(ImportReportItem("card", "failed", card.id, None, card.name, error_msg))
            return

        # Remap database and card references
        card_data, remapped = self.id_remapper.remap_card_query(card_data, self._card_map)
        if not remapped:
            raise ValueError("Card does not have a database reference.")

        # Remap collection
        target_collection_id = (
            self.collection_map.get(card.collection_id) if card.collection_id else None
        )
        card_data["collection_id"] = target_collection_id

        # Handle conflicts
        existing_card = self.conflict_resolver.find_existing_card_in_collection(
            card.name, target_collection_id
        )

        if existing_card:
            self._handle_existing_card(card, card_data, existing_card, target_collection_id)
        else:
            self._create_new_card(card, card_data)

    def _handle_existing_card(
        self, card: Card, card_data: dict, existing_card: dict, target_collection_id: int | None
    ) -> None:
        """Handle an existing card based on conflict strategy.

        Args:
            card: Source card
            card_data: Card data with remapped IDs
            existing_card: Existing target card
            target_collection_id: Target collection ID
        """
        if self.conflict_resolver.should_skip(existing_card):
            self._card_map[card.id] = existing_card["id"]
            self.report.add(
                ImportReportItem(
                    "card",
                    "skipped",
                    card.id,
                    existing_card["id"],
                    card.name,
                    "Already exists (skipped)",
                )
            )
            logger.debug(
                f"Skipped card '{card.name}' - already exists with ID {existing_card['id']}"
            )

        elif self.conflict_resolver.should_overwrite(existing_card):
            payload = clean_for_create(card_data)
            updated_card = self.client.update_card(existing_card["id"], payload)
            self._card_map[card.id] = updated_card["id"]
            self.report.add(
                ImportReportItem("card", "updated", card.id, updated_card["id"], card.name)
            )

            is_model = card_data.get("dataset", False)
            item_type = "Model" if is_model else "Card"
            logger.debug(f"Updated {item_type} '{card.name}' (ID: {updated_card['id']})")

        elif self.conflict_resolver.should_rename(existing_card):
            card_data["name"] = self.conflict_resolver.generate_unique_name(
                card.name, target_collection_id, "card"
            )
            logger.info(f"Renamed card '{card.name}' to '{card_data['name']}' to avoid conflict")
            self._create_new_card(card, card_data)

    def _create_new_card(self, card: Card, card_data: dict) -> None:
        """Create a new card.

        Args:
            card: Source card
            card_data: Card data with remapped IDs
        """
        payload = clean_for_create(card_data)
        new_card = self.client.create_card(payload)
        self._card_map[card.id] = new_card["id"]
        self.report.add(
            ImportReportItem(
                "card", "created", card.id, new_card["id"], card_data.get("name", card.name)
            )
        )

        is_model = card_data.get("dataset", False)
        item_type = "Model" if is_model else "Card"
        logger.debug(
            f"Successfully imported {item_type} '{card_data.get('name', card.name)}' "
            f"{card.id} -> {new_card['id']}"
        )

    def _extract_card_dependencies(self, card_data: dict) -> set[int]:
        """Extract card IDs that this card depends on.

        Args:
            card_data: Card data dictionary

        Returns:
            Set of card IDs that must be imported before this card
        """
        dependencies = set()

        dataset_query = card_data.get("dataset_query", {})
        query = dataset_query.get("query", {})

        # Check source-table for card references (format: "card__123")
        source_table = query.get("source-table")
        if isinstance(source_table, str) and source_table.startswith("card__"):
            try:
                card_id = int(source_table.replace("card__", ""))
                dependencies.add(card_id)
            except ValueError:
                logger.warning(f"Invalid card reference format: {source_table}")

        # Recursively check joins for card references
        joins = query.get("joins", [])
        for join in joins:
            join_source_table = join.get("source-table")
            if isinstance(join_source_table, str) and join_source_table.startswith("card__"):
                try:
                    card_id = int(join_source_table.replace("card__", ""))
                    dependencies.add(card_id)
                except ValueError:
                    logger.warning(f"Invalid card reference in join: {join_source_table}")

        return dependencies

    def _topological_sort_cards(self, cards: list[Card]) -> list[Card]:
        """Sort cards in topological order so dependencies are imported first.

        Args:
            cards: List of cards to sort

        Returns:
            Sorted list of cards with dependencies first
        """
        card_map = {card.id: card for card in cards}

        # Build dependency graph
        dependencies = {}
        for card in cards:
            try:
                card_data = read_json_file(self.export_dir / card.file_path)
                deps = self._extract_card_dependencies(card_data)
                # Only keep dependencies that are in our export
                dependencies[card.id] = deps & set(card_map.keys())
            except Exception as e:
                logger.warning(f"Failed to extract dependencies for card {card.id}: {e}")
                dependencies[card.id] = set()

        # Perform topological sort using Kahn's algorithm
        sorted_cards = []
        in_degree = {card.id: 0 for card in cards}

        # Calculate in-degrees
        for card_id, deps in dependencies.items():
            for dep_id in deps:
                if dep_id in in_degree:
                    in_degree[card_id] += 1

        # Queue of cards with no dependencies
        queue = [card_id for card_id, degree in in_degree.items() if degree == 0]

        while queue:
            queue.sort()
            card_id = queue.pop(0)
            sorted_cards.append(card_map[card_id])

            # Reduce in-degree for dependent cards
            for other_id, deps in dependencies.items():
                if card_id in deps and other_id in in_degree:
                    in_degree[other_id] -= 1
                    if in_degree[other_id] == 0:
                        queue.append(other_id)

        # Check for circular dependencies or missing dependencies
        if len(sorted_cards) < len(cards):
            remaining = [
                card_map[card_id]
                for card_id in card_map.keys()
                if card_id not in [c.id for c in sorted_cards]
            ]
            logger.warning(f"Found {len(remaining)} cards with circular or missing dependencies")

            # Log details about missing dependencies
            for card in remaining:
                card_data = read_json_file(self.export_dir / card.file_path)
                deps = self._extract_card_dependencies(card_data)
                missing_deps = deps - set(card_map.keys())
                if missing_deps:
                    logger.warning(
                        f"Card {card.id} ('{card.name}') depends on missing cards: {missing_deps}"
                    )

            sorted_cards.extend(remaining)

        return sorted_cards

    def _handle_api_error(self, card: Card, error: MetabaseAPIError) -> None:
        """Handle API errors with detailed error messages.

        Args:
            card: Card that failed to import
            error: API error that occurred
        """
        error_msg = str(error)

        # Check for missing card reference errors
        if "does not exist" in error_msg and "Card" in error_msg:
            match = re.search(r"Card (\d+) does not exist", error_msg)
            if match:
                missing_card_id = int(match.group(1))
                logger.error("=" * 80)
                logger.error("❌ MISSING CARD DEPENDENCY ERROR!")
                logger.error("=" * 80)
                logger.error(f"Failed to import card '{card.name}' (ID: {card.id})")
                logger.error(
                    f"The card references another card (ID: {missing_card_id}) "
                    f"that doesn't exist in the target instance."
                )
                logger.error("")
                logger.error("This usually means:")
                logger.error(f"1. Card {missing_card_id} was not included in the export")
                logger.error(f"2. Card {missing_card_id} failed to import earlier")
                logger.error(
                    f"3. Card {missing_card_id} is archived and --include-archived "
                    f"was not used during export"
                )
                logger.error("")
                logger.error("SOLUTIONS:")
                logger.error(f"1. Re-export with card {missing_card_id} included")
                logger.error(
                    "2. If the card is archived, use --include-archived flag during export"
                )
                logger.error("3. Manually create or import the missing card first")
                logger.error("=" * 80)
                self.report.add(
                    ImportReportItem(
                        "card",
                        "failed",
                        card.id,
                        None,
                        card.name,
                        f"Missing dependency: card {missing_card_id}",
                    )
                )
                return

        # Check for table ID constraint violation
        elif "fk_report_card_ref_table_id" in error_msg.lower() or (
            "table_id" in error_msg.lower() and "not present in table" in error_msg.lower()
        ):
            match = re.search(r"table_id\)=\((\d+)\)", error_msg)
            table_id = match.group(1) if match else "unknown"

            logger.error("=" * 80)
            logger.error("❌ TABLE ID MAPPING ERROR DETECTED!")
            logger.error("=" * 80)
            logger.error(f"Failed to import card '{card.name}' (ID: {card.id})")
            logger.error(
                f"The card references table ID {table_id} that doesn't exist "
                f"in the target Metabase instance."
            )
            logger.error("")
            logger.error(
                "This is a known limitation: Table IDs are instance-specific "
                "and cannot be directly migrated."
            )
            logger.error("")
            logger.error("CAUSE:")
            logger.error("The source and target Metabase instances have different table metadata.")
            logger.error("This happens when:")
            logger.error("1. The databases haven't been synced in the target instance")
            logger.error("2. The database schemas are different between source and target")
            logger.error("3. The table was removed or renamed in the target database")
            logger.error("")
            logger.error("SOLUTIONS:")
            logger.error("1. Ensure the target database is properly synced in Metabase")
            logger.error(
                "2. Go to Admin > Databases > [Your Database] > 'Sync database schema now'"
            )
            logger.error("3. Verify the table exists in the target database")
            logger.error("4. If using GUI queries, consider converting to native SQL queries")
            logger.error("")
            logger.error(f"Error details: {error_msg}")
            logger.error("=" * 80)
            self.report.add(
                ImportReportItem(
                    "card",
                    "failed",
                    card.id,
                    None,
                    card.name,
                    f"Table ID {table_id} not found in target",
                )
            )
            return

        # Generic error handling
        logger.error(f"Failed to import card '{card.name}' (ID: {card.id}): {error}", exc_info=True)
        self.report.add(ImportReportItem("card", "failed", card.id, None, card.name, str(error)))

    @property
    def card_map(self) -> dict[int, int]:
        """Get the card ID mapping."""
        return self._card_map
