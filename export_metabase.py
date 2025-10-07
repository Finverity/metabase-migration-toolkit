"""
Metabase Export Tool

This script connects to a source Metabase instance, traverses its collections,
and exports cards (questions) and dashboards into a structured directory layout.
It produces a `manifest.json` file that indexes the exported content, which is
used by the import script.
"""

import dataclasses
import datetime
import sys
from pathlib import Path
from typing import Any

from tqdm import tqdm

from lib.client import MetabaseAPIError, MetabaseClient
from lib.config import ExportConfig, get_export_args
from lib.models import Card, Collection, Dashboard, Manifest, ManifestMeta
from lib.utils import (
    TOOL_VERSION,
    calculate_checksum,
    sanitize_filename,
    setup_logging,
    write_json_file,
)

# Initialize logger
logger = setup_logging(__name__)


class MetabaseExporter:
    """Handles the logic for exporting content from a Metabase instance."""

    def __init__(self, config: ExportConfig):
        self.config = config
        self.client = MetabaseClient(
            base_url=config.source_url,
            username=config.source_username,
            password=config.source_password,
            session_token=config.source_session_token,
            personal_token=config.source_personal_token,
        )
        self.export_dir = Path(config.export_dir)
        self.manifest = self._initialize_manifest()
        self._collection_path_map: dict[int, str] = {}
        self._processed_collections: set[int] = set()
        self._exported_cards: set[int] = set()  # Track exported cards to prevent duplicates
        self._dependency_chain: list[int] = (
            []
        )  # Track current dependency chain for circular detection

    def _initialize_manifest(self) -> Manifest:
        """Initializes the manifest with metadata."""
        cli_args = dataclasses.asdict(self.config)
        # Redact secrets from the manifest
        for secret in ["source_password", "source_session_token", "source_personal_token"]:
            if cli_args.get(secret):
                cli_args[secret] = "********"

        meta = ManifestMeta(
            source_url=self.config.source_url,
            export_timestamp=datetime.datetime.utcnow().isoformat(),
            tool_version=TOOL_VERSION,
            cli_args=cli_args,
        )
        return Manifest(meta=meta)

    def run_export(self):
        """Main entry point to start the export process."""
        logger.info(f"Starting Metabase export from {self.config.source_url}")
        logger.info(f"Export directory: {self.export_dir.resolve()}")

        self.export_dir.mkdir(parents=True, exist_ok=True)

        try:
            logger.info("Fetching source databases...")
            self._fetch_and_store_databases()

            logger.info("Fetching collection tree...")
            collection_tree = self.client.get_collections_tree(
                params={"archived": self.config.include_archived}
            )

            # Filter tree if root_collection_ids are specified
            if self.config.root_collection_ids:
                collection_tree = [
                    c for c in collection_tree if c.get("id") in self.config.root_collection_ids
                ]
                logger.info(
                    f"Export restricted to root collections: {self.config.root_collection_ids}"
                )

            if not collection_tree:
                logger.warning("No collections found to export.")
                return

            # Process collections recursively
            self._traverse_collections(collection_tree)

            # Write the final manifest file
            manifest_path = self.export_dir / "manifest.json"
            logger.info(f"Writing manifest to {manifest_path}")
            write_json_file(self.manifest, manifest_path)

            # Print summary
            logger.info("=" * 80)
            logger.info("Export Summary:")
            logger.info(f"  Collections: {len(self.manifest.collections)}")
            logger.info(f"  Cards: {len(self.manifest.cards)}")
            logger.info(f"  Dashboards: {len(self.manifest.dashboards)}")
            logger.info(f"  Databases: {len(self.manifest.databases)}")
            logger.info("=" * 80)
            logger.info("Export completed successfully.")
            sys.exit(0)

        except MetabaseAPIError as e:
            logger.error(f"A Metabase API error occurred: {e}", exc_info=True)
            sys.exit(1)
        except Exception as e:
            logger.error(f"An unexpected error occurred: {e}", exc_info=True)
            sys.exit(2)

    def _fetch_and_store_databases(self):
        """Fetches all databases from the source and adds them to the manifest."""
        databases_response = self.client.get_databases()

        # Handle different response formats
        if isinstance(databases_response, dict) and "data" in databases_response:
            databases = databases_response["data"]
        elif isinstance(databases_response, list):
            databases = databases_response
        else:
            logger.error(f"Unexpected databases response format: {type(databases_response)}")
            logger.debug(f"Response: {databases_response}")
            databases = []

        self.manifest.databases = {db["id"]: db["name"] for db in databases}
        logger.info(f"Found {len(self.manifest.databases)} databases.")

    def _traverse_collections(
        self, collections: list[dict], parent_path: str = "", parent_id: int | None = None
    ):
        """Recursively traverses the collection tree and processes each collection."""
        for collection_data in tqdm(collections, desc="Processing Collections"):
            collection_id = collection_data.get("id")

            # Skip personal collections unless explicitly included
            if collection_data.get("personal_owner_id") and collection_id not in (
                self.config.root_collection_ids or []
            ):
                logger.info(
                    f"Skipping personal collection '{collection_data['name']}' (ID: {collection_id})"
                )
                continue

            # Handle "root" collection which is a special case
            if isinstance(collection_id, str) and collection_id == "root":
                logger.info("Processing root collection content...")
                current_path = "collections"
                self._process_collection_items("root", current_path)
            elif isinstance(collection_id, int):
                if collection_id in self._processed_collections:
                    continue
                self._processed_collections.add(collection_id)

                sanitized_name = sanitize_filename(collection_data["name"])
                current_path = f"{parent_path}/{sanitized_name}".lstrip("/")
                self._collection_path_map[collection_id] = current_path

                # Extract parent_id from location field if not provided
                # Location format: "/24/25/" means parent is 25, grandparent is 24
                actual_parent_id = parent_id
                if actual_parent_id is None and collection_data.get("location"):
                    location = collection_data["location"].strip("/")
                    if location:
                        parts = location.split("/")
                        if len(parts) > 0:
                            try:
                                actual_parent_id = int(parts[-1])
                            except (ValueError, IndexError):
                                pass

                collection_obj = Collection(
                    id=collection_id,
                    name=collection_data["name"],
                    description=collection_data.get("description"),
                    slug=collection_data.get("slug"),
                    parent_id=actual_parent_id,
                    personal_owner_id=collection_data.get("personal_owner_id"),
                    path=current_path,
                )
                self.manifest.collections.append(collection_obj)

                # Write collection metadata file
                collection_meta_path = self.export_dir / current_path / "_collection.json"
                write_json_file(collection_data, collection_meta_path)

                logger.info(
                    f"Processing collection '{collection_data['name']}' (ID: {collection_id})"
                )
                self._process_collection_items(collection_id, current_path)

                # Recurse into children, passing current collection_id as parent
                if "children" in collection_data and collection_data["children"]:
                    self._traverse_collections(
                        collection_data["children"], current_path, collection_id
                    )

    def _process_collection_items(self, collection_id: Any, base_path: str):
        """Fetches and processes all items (cards, dashboards) in a single collection."""
        try:
            params = {"models": ["card", "dashboard"], "archived": self.config.include_archived}
            items_response = self.client.get_collection_items(collection_id, params)
            items = items_response.get("data", [])

            if not items:
                logger.debug(f"No items found in collection {collection_id}")
                return

            for item in items:
                model = item.get("model")
                if model == "card":
                    self._export_card_with_dependencies(item["id"], base_path)
                elif model == "dashboard" and self.config.include_dashboards:
                    self._export_dashboard(item["id"], base_path)

        except MetabaseAPIError as e:
            logger.error(f"Failed to process items for collection {collection_id}: {e}")

    @staticmethod
    def _extract_card_dependencies(card_data: dict) -> set[int]:
        """
        Extracts card IDs that this card depends on (references in source-table).
        Returns a set of card IDs that must be exported before this card.
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

    def _export_card_with_dependencies(
        self, card_id: int, base_path: str, dependency_chain: list[int] | None = None
    ):
        """
        Exports a card and recursively exports all its dependencies.

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
            dependencies = self._extract_card_dependencies(card_data)

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
                            if dep_collection_id and dep_collection_id in self._collection_path_map:
                                dep_base_path = self._collection_path_map[dep_collection_id]
                            else:
                                # Use a special "dependencies" folder for cards outside the export scope
                                dep_base_path = "dependencies"
                                logger.info(
                                    f"     Card {dep_id} is outside export scope, placing in '{dep_base_path}' folder"
                                )

                            # Check if dependency is archived
                            if (
                                dep_card_data.get("archived", False)
                                and not self.config.include_archived
                            ):
                                logger.warning(
                                    f"     Card {dep_id} is archived but --include-archived not set. Exporting anyway due to dependency."
                                )

                            # Recursively export the dependency
                            self._export_card_with_dependencies(
                                dep_id, dep_base_path, current_chain
                            )

                        except MetabaseAPIError as e:
                            logger.error(f"     Failed to fetch dependency card {dep_id}: {e}")
                            logger.warning(
                                f"     Card {card_id} may fail to import due to missing dependency {dep_id}"
                            )

            # Now export the card itself
            self._export_card(card_id, base_path, card_data)

        except MetabaseAPIError as e:
            logger.error(f"Failed to fetch card {card_id} for dependency analysis: {e}")

    def _export_card(self, card_id: int, base_path: str, card_data: dict | None = None):
        """
        Exports a single card.

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

            card_obj = Card(
                id=card_id,
                name=card_data["name"],
                collection_id=card_data.get("collection_id"),
                database_id=db_id,
                file_path=file_path_str,
                checksum=checksum,
                archived=card_data.get("archived", False),
            )
            self.manifest.cards.append(card_obj)

            # Mark as exported
            self._exported_cards.add(card_id)

            logger.info(f"  -> Exported Card: '{card_data['name']}' (ID: {card_id})")

        except MetabaseAPIError as e:
            logger.error(f"Failed to export card ID {card_id}: {e}")
        except Exception as e:
            logger.error(f"An unexpected error occurred while exporting card ID {card_id}: {e}")

    def _export_dashboard(self, dashboard_id: int, base_path: str):
        """Exports a single dashboard."""
        try:
            logger.debug(f"Exporting dashboard ID {dashboard_id}")
            dashboard_data = self.client.get_dashboard(dashboard_id)

            dash_slug = sanitize_filename(dashboard_data["name"])
            file_path_str = f"{base_path}/dashboards/dash_{dashboard_id}_{dash_slug}.json"
            file_path = self.export_dir / file_path_str

            write_json_file(dashboard_data, file_path)
            checksum = calculate_checksum(file_path)

            # Extract card IDs from dashcards
            card_ids = []
            if dashboard_data.get("dashcards"):
                for dashcard in dashboard_data["dashcards"]:
                    if dashcard.get("card_id"):
                        card_ids.append(dashcard["card_id"])

            dashboard_obj = Dashboard(
                id=dashboard_id,
                name=dashboard_data["name"],
                collection_id=dashboard_data.get("collection_id"),
                ordered_cards=card_ids,
                file_path=file_path_str,
                checksum=checksum,
                archived=dashboard_data.get("archived", False),
            )
            self.manifest.dashboards.append(dashboard_obj)
            logger.info(f"  -> Exported Dashboard: '{dashboard_data['name']}' (ID: {dashboard_id})")

        except MetabaseAPIError as e:
            logger.error(f"Failed to export dashboard ID {dashboard_id}: {e}")
        except Exception as e:
            logger.error(
                f"An unexpected error occurred while exporting dashboard ID {dashboard_id}: {e}"
            )


def main() -> None:
    """Main entry point for the export tool."""
    config = get_export_args()
    setup_logging(config.log_level)
    exporter = MetabaseExporter(config)
    exporter.run_export()


if __name__ == "__main__":
    main()
