"""Tests for base handler and ImportContext functionality."""

from pathlib import Path
from unittest.mock import Mock

from lib.config import ImportConfig
from lib.handlers.base import ImportContext
from lib.models import Card, Dashboard, DatabaseMap, ImportReport, Manifest, ManifestMeta
from lib.remapping import IDMapper, QueryRemapper


def create_test_context(
    cards: list[Card] | None = None,
    dashboards: list[Dashboard] | None = None,
    collection_items_response: dict | None = None,
) -> ImportContext:
    """Create a test ImportContext with mocked dependencies."""
    manifest = Manifest(
        meta=ManifestMeta(
            source_url="https://source.example.com",
            export_timestamp="2025-01-01T00:00:00",
            tool_version="1.0.0",
            cli_args={},
        ),
        databases={1: "Test DB"},
        cards=cards or [],
        dashboards=dashboards or [],
    )

    config = ImportConfig(
        target_url="https://target.example.com",
        export_dir="/tmp/export",
        db_map_path="/tmp/db_map.json",
        target_session_token="test-token",
    )

    db_map = DatabaseMap(by_id={"1": 10}, by_name={"Test DB": 10})
    id_mapper = IDMapper(manifest, db_map)
    id_mapper.set_collection_mapping(1, 100)

    mock_client = Mock()
    if collection_items_response is not None:
        mock_client.get_collection_items.return_value = collection_items_response
    else:
        mock_client.get_collection_items.return_value = {"data": []}

    return ImportContext(
        config=config,
        client=mock_client,
        manifest=manifest,
        export_dir=Path("/tmp/export"),
        id_mapper=id_mapper,
        query_remapper=QueryRemapper(id_mapper),
        report=ImportReport(),
        target_collections=[],
    )


class TestImportContextPrefetch:
    """Tests for ImportContext prefetch functionality."""

    def test_prefetch_collection_items_with_cards(self):
        """Test prefetching collection items when manifest has cards."""
        cards = [
            Card(
                id=1,
                name="Card 1",
                collection_id=1,
                database_id=1,
                file_path="cards/card1.json",
            )
        ]
        context = create_test_context(cards=cards)

        context.prefetch_collection_items()

        assert context._collection_items_prefetched is True
        # Should have called get_collection_items for the target collection (100)
        context.client.get_collection_items.assert_called()

    def test_prefetch_collection_items_with_dashboards(self):
        """Test prefetching collection items when manifest has dashboards."""
        dashboards = [
            Dashboard(
                id=1,
                name="Dashboard 1",
                collection_id=1,
                file_path="dashboards/dash1.json",
            )
        ]
        context = create_test_context(dashboards=dashboards)

        context.prefetch_collection_items()

        assert context._collection_items_prefetched is True
        context.client.get_collection_items.assert_called()

    def test_prefetch_collection_items_empty_manifest(self):
        """Test prefetching when manifest has no cards or dashboards."""
        context = create_test_context()

        context.prefetch_collection_items()

        assert context._collection_items_prefetched is True
        # Should not call get_collection_items when no items to prefetch
        context.client.get_collection_items.assert_not_called()

    def test_prefetch_collection_items_only_once(self):
        """Test that prefetching only happens once."""
        cards = [
            Card(
                id=1,
                name="Card 1",
                collection_id=1,
                database_id=1,
                file_path="cards/card1.json",
            )
        ]
        context = create_test_context(cards=cards)

        context.prefetch_collection_items()
        first_call_count = context.client.get_collection_items.call_count

        context.prefetch_collection_items()
        second_call_count = context.client.get_collection_items.call_count

        # Should not call again
        assert first_call_count == second_call_count

    def test_prefetch_handles_api_error(self):
        """Test that prefetch handles API errors gracefully."""
        cards = [
            Card(
                id=1,
                name="Card 1",
                collection_id=1,
                database_id=1,
                file_path="cards/card1.json",
            )
        ]
        context = create_test_context(cards=cards)
        context.client.get_collection_items.side_effect = Exception("API error")

        # Should not raise
        context.prefetch_collection_items()

        assert context._collection_items_prefetched is True
        # Cache should have empty list for the failed collection
        assert len(context._collection_items_cache.get(100, [])) == 0


class TestImportContextFindExisting:
    """Tests for finding existing cards and dashboards."""

    def test_find_existing_card_from_cache(self):
        """Test finding existing card from prefetched cache."""
        context = create_test_context(
            collection_items_response={
                "data": [
                    {"id": 1, "name": "Existing Card", "model": "card"},
                    {"id": 2, "name": "Another Card", "model": "card"},
                ]
            }
        )
        # Prefetch to populate cache
        context._collection_items_cache[100] = [
            {"id": 1, "name": "Existing Card", "model": "card"},
        ]
        context._collection_items_prefetched = True

        result = context.find_existing_card("Existing Card", 100)

        assert result is not None
        assert result["id"] == 1
        assert result["name"] == "Existing Card"

    def test_find_existing_card_not_found(self):
        """Test finding card that doesn't exist."""
        context = create_test_context()
        context._collection_items_cache[100] = []
        context._collection_items_prefetched = True

        result = context.find_existing_card("Non-existent Card", 100)

        assert result is None

    def test_find_existing_card_fallback_to_api(self):
        """Test finding card when cache is not prefetched."""
        context = create_test_context(
            collection_items_response={
                "data": [
                    {"id": 1, "name": "Existing Card", "model": "card"},
                ]
            }
        )

        result = context.find_existing_card("Existing Card", 100)

        assert result is not None
        assert result["id"] == 1
        # Should cache the result
        assert 100 in context._collection_items_cache

    def test_find_existing_card_with_root_collection(self):
        """Test finding card in root collection (None)."""
        context = create_test_context()
        context._collection_items_cache["root"] = [
            {"id": 1, "name": "Root Card", "model": "card"},
        ]
        context._collection_items_prefetched = True

        result = context.find_existing_card("Root Card", None)

        assert result is not None
        assert result["name"] == "Root Card"

    def test_find_existing_dashboard_from_cache(self):
        """Test finding existing dashboard from prefetched cache."""
        context = create_test_context()
        context._collection_items_cache[100] = [
            {"id": 1, "name": "Existing Dashboard", "model": "dashboard"},
        ]
        context._collection_items_prefetched = True

        result = context.find_existing_dashboard("Existing Dashboard", 100)

        assert result is not None
        assert result["id"] == 1
        assert result["model"] == "dashboard"

    def test_find_existing_dashboard_not_found(self):
        """Test finding dashboard that doesn't exist."""
        context = create_test_context()
        context._collection_items_cache[100] = []
        context._collection_items_prefetched = True

        result = context.find_existing_dashboard("Non-existent Dashboard", 100)

        assert result is None

    def test_find_existing_dashboard_fallback_to_api(self):
        """Test finding dashboard when cache is not prefetched."""
        context = create_test_context(
            collection_items_response={
                "data": [
                    {"id": 1, "name": "Dashboard", "model": "dashboard"},
                ]
            }
        )

        result = context.find_existing_dashboard("Dashboard", 100)

        assert result is not None
        context.client.get_collection_items.assert_called_with(100)


class TestImportContextCacheManagement:
    """Tests for cache management methods."""

    def test_add_to_collection_cache_new_collection(self):
        """Test adding item to cache for new collection."""
        context = create_test_context()

        context.add_to_collection_cache(100, {"id": 1, "name": "New Card", "model": "card"})

        assert 100 in context._collection_items_cache
        assert len(context._collection_items_cache[100]) == 1
        assert context._collection_items_cache[100][0]["name"] == "New Card"

    def test_add_to_collection_cache_existing_collection(self):
        """Test adding item to cache for existing collection."""
        context = create_test_context()
        context._collection_items_cache[100] = [{"id": 1, "name": "Existing Card", "model": "card"}]

        context.add_to_collection_cache(100, {"id": 2, "name": "New Card", "model": "card"})

        assert len(context._collection_items_cache[100]) == 2

    def test_add_to_collection_cache_root_collection(self):
        """Test adding item to cache for root collection (None)."""
        context = create_test_context()

        context.add_to_collection_cache(None, {"id": 1, "name": "Root Card", "model": "card"})

        assert "root" in context._collection_items_cache
        assert len(context._collection_items_cache["root"]) == 1


class TestImportContextAccessors:
    """Tests for ImportContext accessor methods."""

    def test_get_conflict_strategy(self):
        """Test get_conflict_strategy returns configured strategy."""
        context = create_test_context()

        assert context.get_conflict_strategy() == "skip"  # Default

    def test_should_include_archived(self):
        """Test should_include_archived returns configured value."""
        context = create_test_context()

        assert context.should_include_archived() is False  # Default
