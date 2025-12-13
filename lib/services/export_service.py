"""Export service for orchestrating Metabase content export."""

import datetime
import logging
from pathlib import Path
from typing import Any

from tqdm import tqdm

from lib.client import MetabaseAPIError, MetabaseClient
from lib.config import ExportConfig
from lib.models import Card, Collection, Dashboard, Manifest, ManifestMeta, PermissionGroup
from lib.utils import (
    TOOL_VERSION,
    calculate_checksum,
    sanitize_filename,
    write_json_file,
)

logger = logging.getLogger("metabase_migration")


class ExportService:
    """Orchestrates the export of Metabase content to an export package."""

    def __init__(self, config: ExportConfig) -> None:
        """Initialize the ExportService with the given configuration.

        Args:
            config: The export configuration.
        """
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
        """Initializes the manifest with metadata.

        Returns:
            A new Manifest object with metadata.
        """
        cli_args = self.config.model_dump()
        # Redact secrets from the manifest
        for secret in ["source_password", "source_session_token", "source_personal_token"]:
            if cli_args.get(secret):
                cli_args[secret] = "********"

        # Convert MetabaseVersion enum to string for CLI args
        if "metabase_version" in cli_args:
            cli_args["metabase_version"] = str(cli_args["metabase_version"])

        meta = ManifestMeta(
            source_url=self.config.source_url,
            export_timestamp=datetime.datetime.now(datetime.timezone.utc).isoformat(),
            tool_version=TOOL_VERSION,
            cli_args=cli_args,
            metabase_version=str(self.config.metabase_version),
        )
        return Manifest(meta=meta)

    def run_export(self) -> None:
        """Main entry point to start the export process."""
        logger.info(f"Starting Metabase export from {self.config.source_url}")
        logger.info(f"Export directory: {self.export_dir.resolve()}")

        self.export_dir.mkdir(parents=True, exist_ok=True)

        try:
            logger.info("Fetching source databases...")
            self._fetch_and_store_databases()

            logger.info("Fetching collection tree...")
            # Metabase API expects lowercase string "true"/"false" for archived param
            archived_str = "true" if self.config.include_archived else "false"
            collection_tree = self.client.get_collections_tree(params={"archived": archived_str})

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

            # Export permissions if requested
            if self.config.include_permissions:
                logger.info("Exporting permissions...")
                self._export_permissions()

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
            if self.config.include_permissions:
                logger.info(f"  Permission Groups: {len(self.manifest.permission_groups)}")
            logger.info("=" * 80)
            logger.info("Export completed successfully.")

        except MetabaseAPIError as e:
            logger.error(f"A Metabase API error occurred: {e}", exc_info=True)
            raise
        except Exception as e:
            logger.error(f"An unexpected error occurred: {e}", exc_info=True)
            raise

    def _fetch_and_store_databases(self) -> None:
        """Fetches all databases from the source and adds them to the manifest."""
        databases_response = self.client.get_databases()

        # Handle different response formats
        if isinstance(databases_response, dict) and "data" in databases_response:
            databases = databases_response["data"]
        elif isinstance(databases_response, list):
            databases = databases_response
        else:
            logger.error(f"Unexpected databases response format: {type(databases_response)}")
            databases = []

        self.manifest.databases = {db["id"]: db["name"] for db in databases}
        logger.info(f"Found {len(self.manifest.databases)} databases.")

        # Fetch and store metadata for each database (tables and fields)
        logger.info("Fetching database metadata (tables and fields)...")
        for db in databases:
            db_id = db["id"]
            try:
                metadata = self.client.get_database_metadata(db_id)

                # Store simplified metadata: only id and name for tables and fields
                simplified_metadata = {
                    "tables": [
                        {
                            "id": table["id"],
                            "name": table["name"],
                            "fields": [
                                {"id": field["id"], "name": field["name"]}
                                for field in table.get("fields", [])
                            ],
                        }
                        for table in metadata.get("tables", [])
                    ]
                }
                self.manifest.database_metadata[db_id] = simplified_metadata
            except Exception as e:
                logger.warning(f"Failed to fetch metadata for database {db_id}: {e}")
                # Continue with other databases

    def _traverse_collections(
        self, collections: list[dict], parent_path: str = "", parent_id: int | None = None
    ) -> None:
        """Recursively traverses the collection tree and processes each collection.

        Args:
            collections: List of collection dictionaries to process.
            parent_path: The parent path for the current collection.
            parent_id: The parent collection ID.
        """
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
                                # If parsing fails, keep actual_parent_id as None
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

    def _process_collection_items(self, collection_id: Any, base_path: str) -> None:
        """Fetches and processes all items (cards, dashboards, models) in a single collection.

        Args:
            collection_id: The collection ID to process.
            base_path: The base path for the export.
        """
        try:
            # Include 'dataset' to fetch models (Metabase models are returned as model='dataset')
            # Metabase API expects lowercase string "true"/"false" for archived param
            # Use pinned_state="all" to get both pinned and non-pinned items
            archived_str = "true" if self.config.include_archived else "false"
            params = {
                "models": ["card", "dashboard", "dataset"],
                "archived": archived_str,
                "pinned_state": "all",
            }
            items_response = self.client.get_collection_items(collection_id, params)
            items = items_response.get("data", [])

            if not items:
                return

            for item in items:
                model = item.get("model")
                item_type = item.get("type")
                # Both 'card' and 'dataset' (models) are exported as cards
                if model in ("card", "dataset"):
                    # Determine if this is a model from collection listing
                    # Check both 'model' field (dataset) and 'type' field (model)
                    is_model_hint = model == "dataset" or item_type == "model"
                    self._export_card_with_dependencies(
                        item["id"], base_path, is_model_hint=is_model_hint
                    )
                elif model == "dashboard" and self.config.include_dashboards:
                    self._export_dashboard(item["id"], base_path)

        except MetabaseAPIError as e:
            logger.error(f"Failed to process items for collection {collection_id}: {e}")

    @staticmethod
    def _extract_card_dependencies(card_data: dict) -> set[int]:
        """Extracts card IDs that this card depends on (references in source-table).

        Args:
            card_data: The card data dictionary.

        Returns:
            A set of card IDs that must be exported before this card.
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
        self,
        card_id: int,
        base_path: str,
        is_model_hint: bool = False,
        dependency_chain: list[int] | None = None,
    ) -> None:
        """Exports a card and recursively exports all its dependencies.

        Args:
            card_id: The ID of the card to export.
            base_path: The base path for the export.
            is_model_hint: Hint from collection listing that this is a model (model='dataset').
            dependency_chain: List of card IDs in the current dependency chain (for circular detection).
        """
        # Skip if already exported
        if card_id in self._exported_cards:
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
                                dep_id, dep_base_path, dependency_chain=current_chain
                            )

                        except MetabaseAPIError as e:
                            logger.error(f"     Failed to fetch dependency card {dep_id}: {e}")
                            logger.warning(
                                f"     Card {card_id} may fail to import due to missing dependency {dep_id}"
                            )

            # Now export the card itself
            self._export_card(card_id, base_path, card_data, is_model_hint)

        except MetabaseAPIError as e:
            logger.error(f"Failed to fetch card {card_id} for dependency analysis: {e}")

    def _export_card(
        self,
        card_id: int,
        base_path: str,
        card_data: dict | None = None,
        is_model_hint: bool = False,
    ) -> None:
        """Exports a single card.

        Args:
            card_id: The ID of the card to export.
            base_path: The base path for the export.
            card_data: Optional pre-fetched card data (to avoid redundant API calls).
            is_model_hint: Hint from collection listing that this is a model (model='dataset').
        """
        # Skip if already exported
        if card_id in self._exported_cards:
            return

        try:
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
            # Priority: 1. type="model" (Metabase 0.49+)
            #           2. dataset=True (older versions)
            #           3. is_model_hint from collection listing (model='dataset')
            card_type = card_data.get("type")
            card_dataset = card_data.get("dataset")
            is_model = card_type == "model" or card_dataset is True or is_model_hint

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

    def _export_dashboard(self, dashboard_id: int, base_path: str) -> None:
        """Exports a single dashboard.

        Args:
            dashboard_id: The ID of the dashboard to export.
            base_path: The base path for the export.
        """
        try:
            dashboard_data = self.client.get_dashboard(dashboard_id)
        except MetabaseAPIError as e:
            # Metabase API returns 404 for archived dashboards even when include_archived=True
            # The /collection/items endpoint returns them, but /dashboard/{id} doesn't allow fetching them
            if e.status_code == 404 and "archived" in str(e).lower():
                logger.warning(
                    f"  -> Skipping archived dashboard ID {dashboard_id} "
                    f"(Metabase API does not allow fetching archived dashboards)"
                )
                return
            # Re-raise other errors
            raise

        try:

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

            # Extract card IDs from dashboard parameters (filters with values from cards)
            if dashboard_data.get("parameters"):
                for param in dashboard_data["parameters"]:
                    if "values_source_config" in param and isinstance(
                        param["values_source_config"], dict
                    ):
                        source_card_id = param["values_source_config"].get("card_id")
                        if source_card_id and source_card_id not in card_ids:
                            card_ids.append(source_card_id)
                            logger.info(
                                f"     Dashboard parameter '{param.get('name')}' references card {source_card_id} - will be exported as dependency"
                            )

            # Export all card dependencies
            for card_id in card_ids:
                if card_id not in self._exported_cards:
                    logger.info(
                        f"     Exporting card {card_id} (required by dashboard {dashboard_id})"
                    )
                    try:
                        # Fetch the card to determine its collection
                        card_data = self.client.get_card(card_id)
                        card_collection_id = card_data.get("collection_id")

                        # Determine the base path for the card
                        if card_collection_id and card_collection_id in self._collection_path_map:
                            card_base_path = self._collection_path_map[card_collection_id]
                        else:
                            # Use a special "dependencies" folder for cards outside the export scope
                            card_base_path = "dependencies"
                            logger.info(
                                f"        Card {card_id} is outside export scope, placing in '{card_base_path}' folder"
                            )

                        # Export the card with its dependencies
                        self._export_card_with_dependencies(card_id, card_base_path)

                    except MetabaseAPIError as e:
                        logger.error(f"        Failed to export card {card_id}: {e}")
                        logger.warning(
                            f"        Dashboard {dashboard_id} may fail to import due to missing card {card_id}"
                        )

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

    def _export_permissions(self) -> None:
        """Exports permission groups and permissions graphs."""
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
