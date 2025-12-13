"""Base handler class and shared context for entity handlers."""

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from lib.client import MetabaseClient
from lib.config import ImportConfig
from lib.models import ImportReport, Manifest
from lib.remapping.id_mapper import IDMapper
from lib.remapping.query_remapper import QueryRemapper

logger = logging.getLogger("metabase_migration")

# Default number of parallel workers for prefetching
DEFAULT_PREFETCH_WORKERS = 5


@dataclass
class ImportContext:
    """Shared context for import operations.

    Contains all the state and utilities needed by handlers during import.
    """

    config: ImportConfig
    client: MetabaseClient
    manifest: Manifest
    export_dir: Path
    id_mapper: IDMapper
    query_remapper: QueryRemapper
    report: ImportReport

    # Target instance caches
    target_collections: list[dict[str, Any]] = field(default_factory=list)

    # Collection items cache: collection_id -> list of items
    # This eliminates N+1 queries when checking for existing cards/dashboards
    _collection_items_cache: dict[int | str, list[dict[str, Any]]] = field(default_factory=dict)
    _collection_items_prefetched: bool = field(default=False)

    def get_conflict_strategy(self) -> Literal["skip", "overwrite", "rename"]:
        """Returns the configured conflict resolution strategy."""
        return self.config.conflict_strategy

    def should_include_archived(self) -> bool:
        """Returns whether archived items should be included."""
        return self.config.include_archived

    def prefetch_collection_items(self, max_workers: int = DEFAULT_PREFETCH_WORKERS) -> None:
        """Pre-fetches all collection items for O(1) conflict lookup.

        This eliminates N+1 API calls when checking for existing cards/dashboards.
        Items are fetched in parallel for all target collections that will be used.

        Args:
            max_workers: Maximum number of parallel workers for fetching.
        """
        if self._collection_items_prefetched:
            logger.debug("Collection items already prefetched, skipping")
            return

        # Determine which collections we need to prefetch
        # We need items from collections where cards/dashboards will be imported
        collections_to_fetch: set[int | str] = set()

        # Add target collections for all cards
        for card in self.manifest.cards:
            target_coll = self.id_mapper.resolve_collection_id(card.collection_id)
            collections_to_fetch.add(target_coll if target_coll is not None else "root")

        # Add target collections for all dashboards
        for dashboard in self.manifest.dashboards:
            target_coll = self.id_mapper.resolve_collection_id(dashboard.collection_id)
            collections_to_fetch.add(target_coll if target_coll is not None else "root")

        if not collections_to_fetch:
            logger.debug("No collections to prefetch")
            self._collection_items_prefetched = True
            return

        logger.info(f"Pre-fetching items from {len(collections_to_fetch)} target collections...")

        def fetch_collection_items(coll_id: int | str) -> tuple[int | str, list[dict]]:
            """Fetch items for a single collection."""
            try:
                response = self.client.get_collection_items(coll_id)
                return coll_id, response.get("data", [])
            except Exception as e:
                logger.warning(f"Failed to prefetch items for collection {coll_id}: {e}")
                return coll_id, []

        # Parallel fetch using ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(fetch_collection_items, coll_id): coll_id
                for coll_id in collections_to_fetch
            }

            for future in as_completed(futures):
                coll_id, items = future.result()
                self._collection_items_cache[coll_id] = items

        self._collection_items_prefetched = True
        total_items = sum(len(items) for items in self._collection_items_cache.values())
        logger.info(
            f"Pre-fetched {total_items} items from {len(self._collection_items_cache)} collections"
        )

    def find_existing_card(self, name: str, collection_id: int | None) -> dict[str, Any] | None:
        """Finds an existing card by name in a collection using cached data.

        Args:
            name: Card name to find.
            collection_id: Target collection ID.

        Returns:
            The existing card dict or None.
        """
        cache_key: int | str = collection_id if collection_id is not None else "root"

        # If not prefetched, fall back to API call (for backwards compatibility)
        if not self._collection_items_prefetched:
            logger.debug(f"Cache miss for collection {cache_key}, falling back to API call")
            try:
                response = self.client.get_collection_items(cache_key)
                items = response.get("data", [])
                # Cache the result for future lookups
                self._collection_items_cache[cache_key] = items
            except Exception as e:
                logger.warning(f"Failed to fetch items for collection {cache_key}: {e}")
                return None
        else:
            items = self._collection_items_cache.get(cache_key, [])

        for item in items:
            if item.get("model") in ("card", "dataset") and item.get("name") == name:
                return item  # type: ignore[no-any-return]
        return None

    def find_existing_dashboard(
        self, name: str, collection_id: int | None
    ) -> dict[str, Any] | None:
        """Finds an existing dashboard by name in a collection using cached data.

        Args:
            name: Dashboard name to find.
            collection_id: Target collection ID.

        Returns:
            The existing dashboard dict or None.
        """
        cache_key: int | str = collection_id if collection_id is not None else "root"

        # If not prefetched, fall back to API call (for backwards compatibility)
        if not self._collection_items_prefetched:
            logger.debug(f"Cache miss for collection {cache_key}, falling back to API call")
            try:
                response = self.client.get_collection_items(cache_key)
                items = response.get("data", [])
                # Cache the result for future lookups
                self._collection_items_cache[cache_key] = items
            except Exception as e:
                logger.warning(f"Failed to fetch items for collection {cache_key}: {e}")
                return None
        else:
            items = self._collection_items_cache.get(cache_key, [])

        for item in items:
            if item.get("model") == "dashboard" and item.get("name") == name:
                return item  # type: ignore[no-any-return]
        return None

    def add_to_collection_cache(self, collection_id: int | None, item: dict[str, Any]) -> None:
        """Adds a newly created item to the collection cache.

        This keeps the cache up-to-date when new items are created during import.

        Args:
            collection_id: The collection ID where the item was created.
            item: The item dict (must have 'id', 'name', 'model' keys).
        """
        cache_key: int | str = collection_id if collection_id is not None else "root"
        if cache_key not in self._collection_items_cache:
            self._collection_items_cache[cache_key] = []
        self._collection_items_cache[cache_key].append(item)


class BaseHandler:
    """Base class for entity handlers.

    Provides common functionality for all entity handlers.
    """

    def __init__(self, context: ImportContext) -> None:
        """Initialize the handler with the import context.

        Args:
            context: The shared import context.
        """
        self.context = context
        self.client = context.client
        self.id_mapper = context.id_mapper
        self.query_remapper = context.query_remapper
        self.report = context.report
        self.logger = logger

    def _add_report_item(
        self,
        entity_type: Literal["collection", "card", "dashboard"],
        status: Literal["created", "updated", "skipped", "failed"],
        source_id: int,
        target_id: int | None,
        name: str,
        reason: str | None = None,
    ) -> None:
        """Adds an item to the import report.

        Args:
            entity_type: Type of entity (collection, card, dashboard).
            status: Result status.
            source_id: Source entity ID.
            target_id: Target entity ID (None if failed).
            name: Entity name.
            reason: Optional reason for skip/failure.
        """
        from lib.models import ImportReportItem

        self.report.add(
            ImportReportItem(
                entity_type=entity_type,
                status=status,
                source_id=source_id,
                target_id=target_id,
                name=name,
                reason=reason,
            )
        )
