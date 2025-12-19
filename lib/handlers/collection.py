"""Collection handler for Metabase migration."""

import logging
from typing import Any

from tqdm import tqdm

from lib.constants import CONFLICT_OVERWRITE, CONFLICT_RENAME, CONFLICT_SKIP
from lib.handlers.base import BaseHandler, ImportContext
from lib.models import Collection
from lib.utils import clean_for_create, sanitize_filename

logger = logging.getLogger("metabase_migration")


class CollectionHandler(BaseHandler):
    """Handles import of collections."""

    def __init__(self, context: ImportContext) -> None:
        """Initialize the collection handler."""
        super().__init__(context)
        self._flat_target_collections: list[dict[str, Any]] = []

    def import_collections(self, collections: list[Collection]) -> None:
        """Imports all collections from the manifest.

        Args:
            collections: List of collections to import.
        """
        sorted_collections = sorted(collections, key=lambda c: c.path)

        # Flatten the collection tree for easier lookup
        self._flat_target_collections = self._flatten_collection_tree(
            self.context.target_collections
        )

        logger.debug(f"Total target collections (flattened): {len(self._flat_target_collections)}")

        for collection in tqdm(sorted_collections, desc="Importing Collections"):
            self._import_single_collection(collection)

    def _import_single_collection(self, collection: Collection) -> None:
        """Imports a single collection.

        Args:
            collection: The collection to import.
        """
        try:
            target_parent_id = self.id_mapper.resolve_collection_id(collection.parent_id)

            # Check for existing collection on target
            existing_coll = self._find_existing_collection(collection.name, target_parent_id)

            if existing_coll:
                self._handle_existing_collection(collection, existing_coll, target_parent_id)
            else:
                self._create_collection(collection, collection.name, target_parent_id)

        except Exception as e:
            logger.error(f"Failed to import collection '{collection.name}': {e}")
            self._add_report_item(
                "collection", "failed", collection.id, None, collection.name, str(e)
            )

    def _find_existing_collection(self, name: str, parent_id: int | None) -> dict[str, Any] | None:
        """Finds an existing collection by name and parent.

        Args:
            name: Collection name to find.
            parent_id: Target parent collection ID.

        Returns:
            The existing collection dict or None.
        """
        for tc in self._flat_target_collections:
            if tc["name"] == name and tc.get("parent_id") == parent_id:
                return tc
        return None

    def _handle_existing_collection(
        self,
        collection: Collection,
        existing_coll: dict[str, Any],
        target_parent_id: int | None,
    ) -> None:
        """Handles conflict when collection already exists.

        Args:
            collection: The source collection.
            existing_coll: The existing target collection.
            target_parent_id: The target parent collection ID.
        """
        strategy = self.context.get_conflict_strategy()

        if strategy == CONFLICT_SKIP:
            self.id_mapper.set_collection_mapping(collection.id, existing_coll["id"])
            self._add_report_item(
                "collection",
                "skipped",
                collection.id,
                existing_coll["id"],
                collection.name,
                "Already exists (skipped)",
            )
            logger.debug(
                f"Skipped collection '{collection.name}' - already exists "
                f"with ID {existing_coll['id']}"
            )

        elif strategy == CONFLICT_OVERWRITE:
            update_payload = {
                "name": collection.name,
                "description": collection.description,
                "parent_id": target_parent_id,
            }
            updated_coll = self.client.update_collection(
                existing_coll["id"], clean_for_create(update_payload)
            )
            self.id_mapper.set_collection_mapping(collection.id, updated_coll["id"])
            self._add_report_item(
                "collection",
                "updated",
                collection.id,
                updated_coll["id"],
                collection.name,
            )
            logger.debug(f"Updated collection '{collection.name}' (ID: {updated_coll['id']})")

        elif strategy == CONFLICT_RENAME:
            # Generate unique name and create new collection
            new_name = self._generate_unique_collection_name(collection.name, target_parent_id)
            logger.info(f"Renamed collection '{collection.name}' to '{new_name}' to avoid conflict")
            self._create_collection(collection, new_name, target_parent_id)

    def _create_collection(
        self,
        collection: Collection,
        name: str,
        parent_id: int | None,
    ) -> None:
        """Creates a new collection.

        Args:
            collection: The source collection.
            name: The name for the new collection.
            parent_id: The parent collection ID.
        """
        payload = {
            "name": name,
            "description": collection.description,
            "parent_id": parent_id,
        }

        new_coll = self.client.create_collection(clean_for_create(payload))
        self.id_mapper.set_collection_mapping(collection.id, new_coll["id"])
        self._add_report_item("collection", "created", collection.id, new_coll["id"], name)
        logger.debug(f"Created collection '{name}' (ID: {new_coll['id']})")

    def _generate_unique_collection_name(self, base_name: str, parent_id: int | None) -> str:
        """Generates a unique collection name by appending a number.

        Args:
            base_name: The original name.
            parent_id: The parent collection ID.

        Returns:
            A unique name.
        """
        counter = 1
        while True:
            new_name = f"{base_name} ({counter})"
            # Check if this name exists
            name_exists = False
            for tc in self.client.get_collections_tree(params={"archived": True}):
                if tc["name"] == new_name and tc.get("parent_id") == parent_id:
                    name_exists = True
                    break
            if not name_exists:
                return new_name
            counter += 1

    def _flatten_collection_tree(
        self, collections: list[dict[str, Any]], parent_id: int | None = None
    ) -> list[dict[str, Any]]:
        """Recursively flattens a collection tree into a list.

        Args:
            collections: The collection tree.
            parent_id: The parent collection ID.

        Returns:
            A flat list of collections.
        """
        flat_list = []
        for coll in collections:
            # Skip root collection (special case)
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

    @staticmethod
    def find_collection_by_path(
        collections: list[dict[str, Any]], source_path: str
    ) -> dict[str, Any] | None:
        """Finds a collection by its sanitized path.

        Args:
            collections: The target collection tree.
            source_path: The source collection path.

        Returns:
            The matching collection or None.
        """
        path_parts = source_path.replace("collections/", "").split("/")

        current_parent_id = None
        found_collection = None

        for part in path_parts:
            found_match_at_level = False
            for target_coll in collections:
                if (
                    sanitize_filename(target_coll["name"]) == part
                    and target_coll.get("parent_id") == current_parent_id
                ):
                    found_collection = target_coll
                    current_parent_id = target_coll["id"]
                    found_match_at_level = True
                    collections = found_collection.get("children", [])
                    break
            if not found_match_at_level:
                return None
        return found_collection
