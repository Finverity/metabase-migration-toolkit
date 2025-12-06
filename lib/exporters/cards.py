"""Card export logic.

This module handles exporting cards (questions and models) from the source
Metabase instance, including dependency resolution.
"""

import logging
from pathlib import Path

from lib.client import MetabaseAPIError, MetabaseClient
from lib.models import Card, Manifest
from lib.utils import calculate_checksum, sanitize_filename, write_json_file

logger = logging.getLogger("metabase_migration")


class CardExporter:
    """Handles exporting cards with dependency resolution."""

    def __init__(
        self,
        client: MetabaseClient,
        manifest: Manifest,
        export_dir: Path,
        collection_path_map: dict[int, str],
    ):
        """Initialize the CardExporter.

        Args:
            client: Metabase API client
            manifest: Manifest object to populate with card data
            export_dir: Base directory for exports
            collection_path_map: Mapping of collection IDs to their paths
        """
        self.client = client
        self.manifest = manifest
        self.export_dir = export_dir
        self.collection_path_map = collection_path_map
        self._exported_cards: set[int] = set()

    @property
    def exported_cards(self) -> set[int]:
        """Get the set of exported card IDs."""
        return self._exported_cards

    @staticmethod
    def extract_card_dependencies(card_data: dict) -> set[int]:
        """Extract card IDs that this card depends on (references in source-table).

        Args:
            card_data: Card data dictionary

        Returns:
            Set of card IDs that must be exported before this card
        """
        dependencies = set()

        # Check for card references in dataset_query
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

    def export_card_with_dependencies(
        self, card_id: int, base_path: str, dependency_chain: list[int] | None = None
    ) -> None:
        """Export a card and recursively export all its dependencies.

        Args:
            card_id: The ID of the card to export
            base_path: The base path for the export
            dependency_chain: List of card IDs in the current dependency chain (for circular detection)
        """
        # Skip if already exported
        if card_id in self._exported_cards:
            logger.debug(f"Card {card_id} already exported, skipping")
            return

        # Initialize dependency chain if not provided
        if dependency_chain is None:
            dependency_chain = []

        # Check for circular dependencies
        if card_id in dependency_chain:
            chain_str = " -> ".join(str(c) for c in dependency_chain + [card_id])
            logger.warning(f"Circular dependency detected: {chain_str}. Breaking cycle.")
            return

        # Add to current chain
        current_chain = dependency_chain + [card_id]

        try:
            logger.debug(f"Fetching card {card_id} to check dependencies")
            card_data = self.client.get_card(card_id)

            # Extract dependencies
            dependencies = self.extract_card_dependencies(card_data)

            if dependencies:
                logger.info(
                    f"Card {card_id} ('{card_data.get('name', 'Unknown')}') depends on cards: {sorted(dependencies)}"
                )

                # Recursively export dependencies first
                for dep_id in sorted(dependencies):
                    if dep_id not in self._exported_cards:
                        logger.info(
                            f"  -> Exporting dependency: Card {dep_id} (required by Card {card_id})"
                        )

                        # Try to fetch the dependency card to determine its collection
                        try:
                            dep_card_data = self.client.get_card(dep_id)
                            dep_collection_id = dep_card_data.get("collection_id")

                            # Determine the base path for the dependency
                            if dep_collection_id and dep_collection_id in self.collection_path_map:
                                dep_base_path = self.collection_path_map[dep_collection_id]
                            else:
                                # Use a special "dependencies" folder for cards outside the export scope
                                dep_base_path = "dependencies"
                                logger.info(
                                    f"     Card {dep_id} is outside export scope, placing in '{dep_base_path}' folder"
                                )

                            # Recursively export the dependency
                            self.export_card_with_dependencies(dep_id, dep_base_path, current_chain)

                        except MetabaseAPIError as e:
                            logger.error(f"     Failed to fetch dependency card {dep_id}: {e}")
                            logger.warning(
                                f"     Card {card_id} may fail to import due to missing dependency {dep_id}"
                            )

            # Now export the card itself
            self.export_card(card_id, base_path, card_data)

        except MetabaseAPIError as e:
            logger.error(f"Failed to fetch card {card_id} for dependency analysis: {e}")

    def export_card(self, card_id: int, base_path: str, card_data: dict | None = None) -> None:
        """Export a single card.

        Args:
            card_id: The ID of the card to export
            base_path: The base path for the export
            card_data: Optional pre-fetched card data (to avoid redundant API calls)
        """
        # Skip if already exported
        if card_id in self._exported_cards:
            logger.debug(f"Card {card_id} already exported, skipping")
            return

        try:
            logger.debug(f"Exporting card ID {card_id}")

            # Fetch card data if not provided
            if card_data is None:
                card_data = self.client.get_card(card_id)

            if not card_data.get("dataset_query"):
                logger.warning(
                    f"Card ID {card_id} ('{card_data['name']}') has no dataset_query. Skipping."
                )
                return

            db_id = card_data.get("database_id") or card_data["dataset_query"].get("database")
            if db_id is None:
                logger.warning(
                    f"Card ID {card_id} ('{card_data['name']}') has no database ID. Skipping."
                )
                return

            card_slug = sanitize_filename(card_data["name"])
            file_path_str = f"{base_path}/cards/card_{card_id}_{card_slug}.json"
            file_path = self.export_dir / file_path_str

            write_json_file(card_data, file_path)
            checksum = calculate_checksum(file_path)

            # Check if this card is a model (dataset)
            is_model = card_data.get("dataset", False)

            card_obj = Card(
                id=card_id,
                name=card_data["name"],
                collection_id=card_data.get("collection_id"),
                database_id=db_id,
                file_path=file_path_str,
                checksum=checksum,
                archived=card_data.get("archived", False),
                dataset=is_model,
            )
            self.manifest.cards.append(card_obj)

            # Mark as exported
            self._exported_cards.add(card_id)

            # Log with model/question distinction
            item_type = "Model" if is_model else "Card"
            logger.info(f"  -> Exported {item_type}: '{card_data['name']}' (ID: {card_id})")

        except MetabaseAPIError as e:
            logger.error(f"Failed to export card ID {card_id}: {e}")
        except Exception as e:
            logger.error(f"An unexpected error occurred while exporting card ID {card_id}: {e}")
