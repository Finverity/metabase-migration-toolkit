"""Conflict resolution logic for handling duplicate items during import.

This module provides utilities for detecting and resolving conflicts when
importing items that already exist in the target instance.
"""

import logging
from typing import Any, Literal

from lib.client import MetabaseClient

logger = logging.getLogger("metabase_migration")


class ConflictResolver:
    """Handles conflict detection and resolution for import operations."""

    def __init__(
        self,
        client: MetabaseClient,
        conflict_strategy: Literal["skip", "overwrite", "rename"] = "skip",
    ) -> None:
        """Initialize the conflict resolver.

        Args:
            client: Metabase API client
            conflict_strategy: Strategy for handling conflicts
        """
        self.client = client
        self.conflict_strategy = conflict_strategy

    def find_existing_card_in_collection(
        self, name: str, collection_id: int | None
    ) -> dict[Any, Any] | None:
        """Find an existing card or model by name in a specific collection.

        Args:
            name: The name of the card to find
            collection_id: The collection ID to search in (None for root collection)

        Returns:
            The card dict if found, None otherwise
        """
        try:
            coll_id: int | str = "root" if collection_id is None else collection_id
            items = self.client.get_collection_items(coll_id)

            # Filter for cards (model='card' or 'dataset') with matching name
            for item in items.get("data", []):
                if item.get("model") in ("card", "dataset") and item.get("name") == name:
                    return item  # type: ignore[no-any-return]
            return None
        except Exception as e:
            logger.warning(f"Failed to check for existing card '{name}': {e}")
            return None

    def find_existing_dashboard_in_collection(
        self, name: str, collection_id: int | None
    ) -> dict[Any, Any] | None:
        """Find an existing dashboard by name in a specific collection.

        Args:
            name: The name of the dashboard to find
            collection_id: The collection ID to search in (None for root collection)

        Returns:
            The dashboard dict if found, None otherwise
        """
        try:
            coll_id: int | str = "root" if collection_id is None else collection_id
            items = self.client.get_collection_items(coll_id)

            # Filter for dashboards (model='dashboard') with matching name
            for item in items.get("data", []):
                if item.get("model") == "dashboard" and item.get("name") == name:
                    return item  # type: ignore[no-any-return]
            return None
        except Exception as e:
            logger.warning(f"Failed to check for existing dashboard '{name}': {e}")
            return None

    def generate_unique_name(
        self, base_name: str, collection_id: int | None, item_type: Literal["card", "dashboard"]
    ) -> str:
        """Generate a unique name by appending a number if needed.

        Args:
            base_name: The original name
            collection_id: The collection to check for conflicts
            item_type: Either 'card' or 'dashboard'

        Returns:
            A unique name that doesn't conflict with existing items
        """
        # Try the base name first
        if item_type == "card":
            existing = self.find_existing_card_in_collection(base_name, collection_id)
        else:
            existing = self.find_existing_dashboard_in_collection(base_name, collection_id)

        if not existing:
            return base_name

        # Try appending numbers until we find a unique name
        counter = 1
        while True:
            new_name = f"{base_name} ({counter})"
            if item_type == "card":
                existing = self.find_existing_card_in_collection(new_name, collection_id)
            else:
                existing = self.find_existing_dashboard_in_collection(new_name, collection_id)

            if not existing:
                return new_name
            counter += 1

    def should_skip(self, existing_item: dict | None) -> bool:
        """Check if an item should be skipped based on conflict strategy.

        Args:
            existing_item: The existing item dict, or None if not found

        Returns:
            True if the item should be skipped
        """
        return existing_item is not None and self.conflict_strategy == "skip"

    def should_overwrite(self, existing_item: dict | None) -> bool:
        """Check if an item should be overwritten based on conflict strategy.

        Args:
            existing_item: The existing item dict, or None if not found

        Returns:
            True if the item should be overwritten
        """
        return existing_item is not None and self.conflict_strategy == "overwrite"

    def should_rename(self, existing_item: dict | None) -> bool:
        """Check if an item should be renamed based on conflict strategy.

        Args:
            existing_item: The existing item dict, or None if not found

        Returns:
            True if the item should be renamed
        """
        return existing_item is not None and self.conflict_strategy == "rename"
