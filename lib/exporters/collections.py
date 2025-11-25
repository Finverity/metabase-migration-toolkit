"""Collection export logic.

This module handles traversing and exporting collections from the source
Metabase instance.
"""

import logging
from pathlib import Path
from typing import Any

from tqdm import tqdm

from lib.client import MetabaseAPIError, MetabaseClient
from lib.config import ExportConfig
from lib.exporters.cards import CardExporter
from lib.exporters.dashboards import DashboardExporter
from lib.models import Collection, Manifest
from lib.utils import sanitize_filename, write_json_file

logger = logging.getLogger("metabase_migration")


class CollectionExporter:
    """Handles traversing and exporting collections."""

    def __init__(
        self,
        client: MetabaseClient,
        manifest: Manifest,
        export_dir: Path,
        config: ExportConfig,
        card_exporter: CardExporter,
        dashboard_exporter: DashboardExporter,
    ):
        """Initialize the CollectionExporter.

        Args:
            client: Metabase API client
            manifest: Manifest object to populate with collection data
            export_dir: Base directory for exports
            config: Export configuration
            card_exporter: CardExporter instance
            dashboard_exporter: DashboardExporter instance
        """
        self.client = client
        self.manifest = manifest
        self.export_dir = export_dir
        self.config = config
        self.card_exporter = card_exporter
        self.dashboard_exporter = dashboard_exporter
        self._collection_path_map: dict[int, str] = {}
        self._processed_collections: set[int] = set()

    @property
    def collection_path_map(self) -> dict[int, str]:
        """Get the collection path map."""
        return self._collection_path_map

    def export_collections(self, collection_tree: list[dict]) -> None:
        """Export all collections from the collection tree.

        Args:
            collection_tree: List of collection dictionaries from the API
        """
        self._traverse_collections(collection_tree)

    def _traverse_collections(
        self, collections: list[dict], parent_path: str = "", parent_id: int | None = None
    ) -> None:
        """Recursively traverse the collection tree and process each collection.

        Args:
            collections: List of collection dictionaries
            parent_path: Path of the parent collection
            parent_id: ID of the parent collection
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
        """Fetch and process all items (cards, dashboards, models) in a single collection.

        Args:
            collection_id: ID of the collection (can be "root" or an integer)
            base_path: Base path for exporting items
        """
        try:
            # Include 'dataset' to fetch models (Metabase models are returned as model='dataset')
            params = {
                "models": ["card", "dashboard", "dataset"],
                "archived": self.config.include_archived,
            }
            items_response = self.client.get_collection_items(collection_id, params)
            items = items_response.get("data", [])

            if not items:
                logger.debug(f"No items found in collection {collection_id}")
                return

            for item in items:
                model = item.get("model")
                # Both 'card' and 'dataset' (models) are exported as cards
                if model in ("card", "dataset"):
                    self.card_exporter.export_card_with_dependencies(item["id"], base_path)
                elif model == "dashboard" and self.config.include_dashboards:
                    self.dashboard_exporter.export_dashboard(item["id"], base_path)

        except MetabaseAPIError as e:
            logger.error(f"Failed to process items for collection {collection_id}: {e}")
