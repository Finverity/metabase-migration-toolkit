"""Collection import logic.

This module handles importing collections from the export manifest to the
target Metabase instance, including conflict resolution and hierarchy management.
"""

import logging
from typing import Any

from tqdm import tqdm

from lib.client import MetabaseClient
from lib.conflict_resolution import ConflictResolver
from lib.models import Collection, ImportReport, ImportReportItem, Manifest
from lib.utils import clean_for_create

logger = logging.getLogger("metabase_migration")


class CollectionImporter:
    """Handles importing collections to a target Metabase instance."""

    def __init__(
        self,
        client: MetabaseClient,
        manifest: Manifest,
        conflict_resolver: ConflictResolver,
        report: ImportReport,
    ) -> None:
        """Initialize the collection importer.

        Args:
            client: Metabase API client for the target instance
            manifest: Export manifest containing collections
            conflict_resolver: Conflict resolution handler
            report: Import report for tracking results
        """
        self.client = client
        self.manifest = manifest
        self.conflict_resolver = conflict_resolver
        self.report = report

        # Mapping from source collection ID to target collection ID
        self._collection_map: dict[int, int] = {}
        # Cache of existing collections on the target instance
        self._target_collections: list[dict[str, Any]] = []

    def import_collections(self) -> dict[int, int]:
        """Import all collections from the manifest.

        Returns:
            Mapping of source collection IDs to target collection IDs
        """
        logger.info("Fetching existing collections from target...")
        self._target_collections = self.client.get_collections_tree(params={"archived": True})

        sorted_collections = sorted(self.manifest.collections, key=lambda c: c.path)
        flat_target_collections = self._flatten_collection_tree(self._target_collections)

        logger.debug(f"Total target collections (flattened): {len(flat_target_collections)}")
        logger.debug("Target collections:")
        for tc in flat_target_collections:
            logger.debug(f"  - '{tc['name']}' (ID: {tc['id']}, parent_id: {tc.get('parent_id')})")

        for collection in tqdm(sorted_collections, desc="Importing Collections"):
            try:
                self._import_single_collection(collection, flat_target_collections)
            except Exception as e:
                logger.error(f"Failed to import collection '{collection.name}': {e}")
                self.report.add(
                    ImportReportItem(
                        "collection", "failed", collection.id, None, collection.name, str(e)
                    )
                )

        return self._collection_map

    def _import_single_collection(
        self, collection: Collection, flat_target_collections: list[dict]
    ) -> None:
        """Import a single collection.

        Args:
            collection: Collection to import
            flat_target_collections: Flattened list of target collections
        """
        target_parent_id = (
            self._collection_map.get(collection.parent_id) if collection.parent_id else None
        )

        # Check for existing collection on target
        existing_coll = self._find_existing_collection(
            collection.name, target_parent_id, flat_target_collections
        )

        logger.debug(
            f"Looking for: name='{collection.name}', target_parent_id={target_parent_id}, "
            f"source_parent_id={collection.parent_id}"
        )

        if existing_coll:
            self._handle_existing_collection(collection, existing_coll, target_parent_id)
        else:
            self._create_new_collection(collection, target_parent_id, existing_coll)

    def _find_existing_collection(
        self, name: str, target_parent_id: int | None, flat_target_collections: list[dict]
    ) -> dict | None:
        """Find an existing collection by name and parent ID.

        Args:
            name: Collection name
            target_parent_id: Parent collection ID
            flat_target_collections: Flattened list of target collections

        Returns:
            Existing collection dict or None
        """
        for tc in flat_target_collections:
            if tc["name"] == name and tc.get("parent_id") == target_parent_id:
                logger.debug(f"  ✓ MATCH! Using existing ID: {tc['id']}")
                return tc
        logger.debug("  ✗ No match found, will create new collection")
        return None

    def _handle_existing_collection(
        self, collection: Collection, existing_coll: dict, target_parent_id: int | None
    ) -> None:
        """Handle an existing collection based on conflict strategy.

        Args:
            collection: Source collection
            existing_coll: Existing target collection
            target_parent_id: Target parent collection ID
        """
        if self.conflict_resolver.should_skip(existing_coll):
            self._collection_map[collection.id] = existing_coll["id"]
            self.report.add(
                ImportReportItem(
                    "collection",
                    "skipped",
                    collection.id,
                    existing_coll["id"],
                    collection.name,
                    "Already exists (skipped)",
                )
            )
            logger.debug(
                f"Skipped collection '{collection.name}' - already exists with ID {existing_coll['id']}"
            )

        elif self.conflict_resolver.should_overwrite(existing_coll):
            update_payload = {
                "name": collection.name,
                "description": collection.description,
                "parent_id": target_parent_id,
            }
            updated_coll = self.client.update_collection(
                existing_coll["id"], clean_for_create(update_payload)
            )
            self._collection_map[collection.id] = updated_coll["id"]
            self.report.add(
                ImportReportItem(
                    "collection",
                    "updated",
                    collection.id,
                    updated_coll["id"],
                    collection.name,
                )
            )
            logger.debug(f"Updated collection '{collection.name}' (ID: {updated_coll['id']})")

    def _create_new_collection(
        self, collection: Collection, target_parent_id: int | None, existing_coll: dict | None
    ) -> None:
        """Create a new collection.

        Args:
            collection: Source collection
            target_parent_id: Target parent collection ID
            existing_coll: Existing collection (for rename strategy)
        """
        collection_name = collection.name

        # Handle rename strategy
        if existing_coll and self.conflict_resolver.should_rename(existing_coll):
            collection_name = self._generate_unique_collection_name(
                collection.name, target_parent_id
            )
            logger.info(
                f"Renamed collection '{collection.name}' to '{collection_name}' to avoid conflict"
            )

        payload = {
            "name": collection_name,
            "description": collection.description,
            "parent_id": target_parent_id,
        }

        new_coll = self.client.create_collection(clean_for_create(payload))
        self._collection_map[collection.id] = new_coll["id"]
        self.report.add(
            ImportReportItem(
                "collection", "created", collection.id, new_coll["id"], collection_name
            )
        )
        logger.debug(f"Created collection '{collection_name}' (ID: {new_coll['id']})")

    def _generate_unique_collection_name(self, base_name: str, target_parent_id: int | None) -> str:
        """Generate a unique collection name.

        Args:
            base_name: Original collection name
            target_parent_id: Target parent collection ID

        Returns:
            Unique collection name
        """
        counter = 1
        while True:
            new_name = f"{base_name} ({counter})"
            # Check if this name exists
            name_exists = False
            for tc in self.client.get_collections_tree(params={"archived": True}):
                if tc["name"] == new_name and tc.get("parent_id") == target_parent_id:
                    name_exists = True
                    break
            if not name_exists:
                return new_name
            counter += 1

    def _flatten_collection_tree(
        self, collections: list[dict], parent_id: int | None = None
    ) -> list[dict]:
        """Recursively flatten a collection tree into a list.

        Args:
            collections: Collection tree
            parent_id: Parent collection ID

        Returns:
            Flattened list of collections
        """
        flat_list = []
        for coll in collections:
            # Skip root collection (it's a special case)
            if coll.get("id") == "root":
                if "children" in coll:
                    flat_list.extend(self._flatten_collection_tree(coll["children"], None))
                continue

            # Add current collection with its parent_id
            flat_coll = {
                "id": coll["id"],
                "name": coll["name"],
                "parent_id": parent_id,
            }
            flat_list.append(flat_coll)

            # Recursively process children
            if "children" in coll and coll["children"]:
                flat_list.extend(self._flatten_collection_tree(coll["children"], coll["id"]))

        return flat_list

    @property
    def collection_map(self) -> dict[int, int]:
        """Get the collection ID mapping."""
        return self._collection_map
