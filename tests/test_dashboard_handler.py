"""
Unit tests for lib/handlers/dashboard.py

Tests for the DashboardHandler class covering dashboard import, dashcard handling,
conflict resolution, and error scenarios.
"""

import json
from unittest.mock import Mock, patch

import pytest

from lib.config import ImportConfig
from lib.handlers.base import ImportContext
from lib.handlers.dashboard import DashboardHandler
from lib.models_core import Card, Dashboard, ImportReport, Manifest
from lib.remapping.id_mapper import IDMapper
from lib.remapping.query_remapper import QueryRemapper


@pytest.fixture
def mock_client():
    """Create a mock MetabaseClient."""
    client = Mock()
    client.base_url = "https://target.example.com"
    return client


@pytest.fixture
def mock_id_mapper():
    """Create a mock IDMapper."""
    mapper = Mock(spec=IDMapper)
    mapper.card_map = {}
    mapper.collection_map = {}
    mapper.resolve_card_id.return_value = 999
    mapper.resolve_collection_id.return_value = 100
    mapper.resolve_db_id.return_value = None  # Default to None, tests can override
    return mapper


@pytest.fixture
def mock_query_remapper():
    """Create a mock QueryRemapper."""
    remapper = Mock(spec=QueryRemapper)
    remapper.remap_dashboard_parameters.return_value = []
    remapper.remap_dashcard_parameter_mappings.return_value = []
    remapper.remap_dashcard_visualization_settings.side_effect = lambda x, _: x
    remapper.remap_card_data.return_value = ({}, True)  # Return (remapped_data, success)
    return remapper


@pytest.fixture
def mock_manifest():
    """Create a mock Manifest."""
    manifest = Mock(spec=Manifest)
    manifest.cards = [
        Card(
            id=1,
            name="Test Card",
            file_path="cards/test_card.json",
            collection_id=10,
            database_id=1,
            archived=False,
            dataset=False,
        ),
    ]
    return manifest


@pytest.fixture
def mock_config():
    """Create a mock ImportConfig."""
    config = Mock(spec=ImportConfig)
    config.conflict_strategy = "skip"
    config.include_archived = False
    config.dry_run = False
    return config


@pytest.fixture
def mock_report():
    """Create a mock ImportReport."""
    report = Mock(spec=ImportReport)
    report.add = Mock()
    return report


@pytest.fixture
def import_context(
    mock_config,
    mock_client,
    mock_manifest,
    mock_id_mapper,
    mock_query_remapper,
    mock_report,
    tmp_path,
):
    """Create a real ImportContext for testing."""
    # Create a real ImportContext to test its methods
    context = ImportContext(
        config=mock_config,
        client=mock_client,
        manifest=mock_manifest,
        export_dir=tmp_path,
        id_mapper=mock_id_mapper,
        query_remapper=mock_query_remapper,
        report=mock_report,
        target_collections=[],
    )
    return context


@pytest.fixture
def sample_dashboard_data():
    """Create sample dashboard data."""
    return {
        "id": 1,
        "name": "Test Dashboard",
        "description": "A test dashboard",
        "collection_id": 10,
        "parameters": [],
        "dashcards": [
            {
                "id": 1,
                "card_id": 1,
                "row": 0,
                "col": 0,
                "size_x": 6,
                "size_y": 4,
                "visualization_settings": {},
                "parameter_mappings": [],
            }
        ],
    }


class TestDashboardHandlerInit:
    """Tests for DashboardHandler initialization."""

    def test_init(self, import_context):
        """Test handler initialization."""
        handler = DashboardHandler(import_context)
        assert handler.context == import_context
        assert handler.client == import_context.client
        assert handler.id_mapper == import_context.id_mapper


class TestFindExistingDashboard:
    """Tests for finding existing dashboards via ImportContext."""

    def test_find_existing_dashboard_found(self, import_context, mock_client):
        """Test finding an existing dashboard via context."""
        mock_client.get_collection_items.return_value = {
            "data": [
                {"id": 999, "model": "dashboard", "name": "Test Dashboard"},
                {"id": 1000, "model": "dashboard", "name": "Other Dashboard"},
            ]
        }

        # Use context.find_existing_dashboard (not prefetched, falls back to API)
        result = import_context.find_existing_dashboard("Test Dashboard", 100)

        assert result is not None
        assert result["id"] == 999

    def test_find_existing_dashboard_not_found(self, import_context, mock_client):
        """Test when dashboard is not found."""
        mock_client.get_collection_items.return_value = {
            "data": [{"id": 999, "model": "dashboard", "name": "Other Dashboard"}]
        }

        result = import_context.find_existing_dashboard("Test Dashboard", 100)

        assert result is None

    def test_find_existing_dashboard_in_root(self, import_context, mock_client):
        """Test finding dashboard in root collection."""
        mock_client.get_collection_items.return_value = {"data": []}

        import_context.find_existing_dashboard("Test Dashboard", None)

        mock_client.get_collection_items.assert_called_once_with("root")

    def test_find_existing_dashboard_handles_exception(self, import_context, mock_client):
        """Test handling of exception when finding dashboard."""
        mock_client.get_collection_items.side_effect = Exception("API Error")

        result = import_context.find_existing_dashboard("Test Dashboard", 100)

        assert result is None

    def test_find_existing_dashboard_ignores_cards(self, import_context, mock_client):
        """Test that cards are ignored when searching for dashboards."""
        mock_client.get_collection_items.return_value = {
            "data": [
                {"id": 999, "model": "card", "name": "Test Dashboard"},  # Card, not dashboard
            ]
        }

        result = import_context.find_existing_dashboard("Test Dashboard", 100)

        assert result is None

    def test_find_existing_dashboard_uses_cache(self, import_context, mock_client):
        """Test that find_existing_dashboard uses cache when prefetched."""
        # Pre-populate the cache
        import_context._collection_items_cache[100] = [
            {"id": 999, "model": "dashboard", "name": "Cached Dashboard"}
        ]
        import_context._collection_items_prefetched = True

        result = import_context.find_existing_dashboard("Cached Dashboard", 100)

        # Should NOT call the API - data is cached
        mock_client.get_collection_items.assert_not_called()
        assert result is not None
        assert result["id"] == 999


class TestHandleExistingDashboard:
    """Tests for conflict handling when dashboard exists."""

    def test_skip_strategy(self, import_context, mock_config):
        """Test skip conflict strategy."""
        mock_config.conflict_strategy = "skip"

        handler = DashboardHandler(import_context)
        dash = Dashboard(
            id=1,
            name="Test",
            file_path="test.json",
            collection_id=10,
            archived=False,
        )
        existing = {"id": 999, "name": "Test"}

        result = handler._handle_existing_dashboard(dash, existing, 100)

        assert result is None  # Skipped

    def test_overwrite_strategy(self, import_context, mock_config):
        """Test overwrite conflict strategy."""
        mock_config.conflict_strategy = "overwrite"

        handler = DashboardHandler(import_context)
        dash = Dashboard(
            id=1,
            name="Test",
            file_path="test.json",
            collection_id=10,
            archived=False,
        )
        existing = {"id": 999, "name": "Test"}

        result = handler._handle_existing_dashboard(dash, existing, 100)

        assert result is not None
        assert result[0] == 999  # Dashboard ID
        assert result[1] == "Test"  # Name
        assert result[2] == "updated"  # Action

    def test_rename_strategy(self, import_context, mock_config, mock_client):
        """Test rename conflict strategy."""
        mock_config.conflict_strategy = "rename"
        mock_client.get_collection_items.return_value = {"data": []}

        handler = DashboardHandler(import_context)
        dash = Dashboard(
            id=1,
            name="Test",
            file_path="test.json",
            collection_id=10,
            archived=False,
        )
        existing = {"id": 999, "name": "Test"}

        result = handler._handle_existing_dashboard(dash, existing, 100)

        assert result is not None
        assert result[0] is None  # New dashboard to be created
        assert result[1] == "Test (1)"  # Renamed
        assert result[2] == "created"  # Action


class TestGenerateUniqueDashboardName:
    """Tests for unique dashboard name generation."""

    def test_generate_unique_name(self, import_context, mock_client):
        """Test generating unique name when conflict exists."""
        # First call returns existing dashboard, second call returns empty
        mock_client.get_collection_items.side_effect = [
            {"data": [{"model": "dashboard", "name": "Test (1)"}]},
            {"data": []},
        ]

        handler = DashboardHandler(import_context)
        result = handler._generate_unique_dashboard_name("Test", 100)

        assert result == "Test (2)"

    def test_generate_unique_name_first_try(self, import_context, mock_client):
        """Test when first unique name works."""
        mock_client.get_collection_items.return_value = {"data": []}

        handler = DashboardHandler(import_context)
        result = handler._generate_unique_dashboard_name("Test", 100)

        assert result == "Test (1)"


class TestPrepareDashcards:
    """Tests for dashcard preparation."""

    def test_prepare_dashcards_basic(self, import_context, mock_id_mapper):
        """Test basic dashcard preparation."""
        dashcards = [
            {
                "id": 1,
                "card_id": 1,
                "row": 0,
                "col": 0,
                "size_x": 6,
                "size_y": 4,
            }
        ]

        handler = DashboardHandler(import_context)
        result = handler._prepare_dashcards(dashcards)

        assert len(result) == 1
        assert result[0]["id"] == -1
        assert result[0]["card_id"] == 999  # Mapped

    def test_prepare_dashcards_unmapped_card(self, import_context, mock_id_mapper):
        """Test dashcard with unmapped card_id."""
        mock_id_mapper.resolve_card_id.return_value = None

        dashcards = [
            {
                "id": 1,
                "card_id": 1,
                "row": 0,
                "col": 0,
                "size_x": 6,
                "size_y": 4,
            }
        ]

        handler = DashboardHandler(import_context)
        result = handler._prepare_dashcards(dashcards)

        assert len(result) == 0  # Skipped

    def test_prepare_dashcards_with_visualization_settings(self, import_context):
        """Test dashcard with visualization_settings preserved."""
        dashcards = [
            {
                "id": 1,
                "card_id": 1,
                "row": 0,
                "col": 0,
                "size_x": 6,
                "size_y": 4,
                "visualization_settings": {"graph.dimensions": ["x"]},
            }
        ]

        handler = DashboardHandler(import_context)
        result = handler._prepare_dashcards(dashcards)

        assert len(result) == 1
        assert result[0]["visualization_settings"] == {"graph.dimensions": ["x"]}

    def test_prepare_dashcards_with_parameter_mappings(self, import_context, mock_query_remapper):
        """Test dashcard with parameter_mappings."""
        mock_query_remapper.remap_dashcard_parameter_mappings.return_value = [
            {"parameter_id": "abc", "target": ["field", 100]}
        ]

        dashcards = [
            {
                "id": 1,
                "card_id": 1,
                "row": 0,
                "col": 0,
                "size_x": 6,
                "size_y": 4,
                "parameter_mappings": [{"parameter_id": "abc", "target": ["field", 1]}],
            }
        ]

        handler = DashboardHandler(import_context)
        result = handler._prepare_dashcards(dashcards)

        assert len(result) == 1
        assert "parameter_mappings" in result[0]

    def test_prepare_dashcards_with_series(self, import_context, mock_id_mapper):
        """Test dashcard with series."""
        mock_id_mapper.resolve_card_id.side_effect = lambda x: x + 100

        dashcards = [
            {
                "id": 1,
                "card_id": 1,
                "row": 0,
                "col": 0,
                "size_x": 6,
                "size_y": 4,
                "series": [{"id": 2}, {"id": 3}],
            }
        ]

        handler = DashboardHandler(import_context)
        result = handler._prepare_dashcards(dashcards)

        assert len(result) == 1
        assert result[0]["series"] == [{"id": 102}, {"id": 103}]

    def test_prepare_dashcards_text_card_no_card_id(self, import_context):
        """Test dashcard without card_id (text card)."""
        dashcards = [
            {
                "id": 1,
                "row": 0,
                "col": 0,
                "size_x": 6,
                "size_y": 2,
                "visualization_settings": {"text": "Hello"},
            }
        ]

        handler = DashboardHandler(import_context)
        result = handler._prepare_dashcards(dashcards)

        assert len(result) == 1
        assert "card_id" not in result[0]

    def test_prepare_dashcards_removes_excluded_fields(self, import_context):
        """Test that excluded fields are removed from dashcards."""
        dashcards = [
            {
                "id": 1,
                "card_id": 1,
                "row": 0,
                "col": 0,
                "size_x": 6,
                "size_y": 4,
                "entity_id": "abc123",  # Should be excluded
                "created_at": "2024-01-01",  # Should be excluded
            }
        ]

        handler = DashboardHandler(import_context)
        result = handler._prepare_dashcards(dashcards)

        assert len(result) == 1
        assert "entity_id" not in result[0]
        assert "created_at" not in result[0]


class TestGetDashcardDatabaseId:
    """Tests for getting dashcard database ID."""

    def test_get_dashcard_database_id_found(self, import_context, mock_manifest):
        """Test getting database ID when card is found."""
        mock_manifest.cards = [
            Card(
                id=1,
                name="Test Card",
                file_path="cards/test_card.json",
                collection_id=10,
                database_id=5,
                archived=False,
                dataset=False,
            ),
        ]

        handler = DashboardHandler(import_context)
        result = handler._get_dashcard_database_id({"card_id": 1})

        assert result == 5

    def test_get_dashcard_database_id_not_found(self, import_context, mock_manifest):
        """Test getting database ID when card is not found."""
        mock_manifest.cards = []

        handler = DashboardHandler(import_context)
        result = handler._get_dashcard_database_id({"card_id": 999})

        assert result is None

    def test_get_dashcard_database_id_no_card_id(self, import_context):
        """Test getting database ID when dashcard has no card_id."""
        handler = DashboardHandler(import_context)
        result = handler._get_dashcard_database_id({})

        assert result is None


class TestRemapSeries:
    """Tests for series remapping."""

    def test_remap_series_success(self, import_context, mock_id_mapper):
        """Test successful series remapping."""
        mock_id_mapper.resolve_card_id.side_effect = lambda x: x + 100

        handler = DashboardHandler(import_context)
        series = [{"id": 1}, {"id": 2}]

        result = handler._remap_series(series)

        assert result == [{"id": 101}, {"id": 102}]

    def test_remap_series_unmapped(self, import_context, mock_id_mapper):
        """Test series with unmapped card."""
        mock_id_mapper.resolve_card_id.side_effect = lambda x: None if x == 2 else x + 100

        handler = DashboardHandler(import_context)
        series = [{"id": 1}, {"id": 2}]

        result = handler._remap_series(series)

        assert result == [{"id": 101}]  # Only card 1 included

    def test_remap_series_empty(self, import_context):
        """Test remapping empty series."""
        handler = DashboardHandler(import_context)
        result = handler._remap_series([])

        assert result == []

    def test_remap_series_invalid_format(self, import_context):
        """Test remapping series with invalid format."""
        handler = DashboardHandler(import_context)
        series = ["invalid", 123, None]

        result = handler._remap_series(series)

        assert result == []


class TestRemapEmbeddedCard:
    """Tests for _remap_embedded_card (Visualize another way feature)."""

    def test_remap_embedded_card_remaps_card_id(self, import_context, mock_id_mapper):
        """Test that card.id is remapped correctly."""
        mock_id_mapper.resolve_card_id.return_value = 999

        handler = DashboardHandler(import_context)
        embedded_card = {
            "id": 41,
            "name": "My Question",
            "display": "funnel",
            "visualization_settings": {"funnel.type": "bar"},
        }

        result = handler._remap_embedded_card(embedded_card, source_db_id=1)

        assert result is not None
        assert result["id"] == 999  # Remapped from 41 to 999
        assert result["name"] == "My Question"
        assert result["display"] == "funnel"

    def test_remap_embedded_card_remaps_database_id(self, import_context, mock_id_mapper):
        """Test that database_id is remapped correctly."""
        mock_id_mapper.resolve_card_id.return_value = 999
        mock_id_mapper.resolve_db_id.return_value = 50

        handler = DashboardHandler(import_context)
        embedded_card = {
            "id": 41,
            "database_id": 5,
            "display": "table",
        }

        result = handler._remap_embedded_card(embedded_card, source_db_id=5)

        assert result is not None
        assert result["database_id"] == 50  # Remapped from 5 to 50

    def test_remap_embedded_card_removes_immutable_fields(self, import_context, mock_id_mapper):
        """Test that immutable fields are removed."""
        mock_id_mapper.resolve_card_id.return_value = 999

        handler = DashboardHandler(import_context)
        embedded_card = {
            "id": 41,
            "display": "bar",
            "creator_id": 1,
            "creator": {"id": 1, "email": "admin@test.com"},
            "created_at": "2024-01-01T00:00:00Z",
            "updated_at": "2024-01-15T00:00:00Z",
            "public_uuid": "abc123",
            "can_write": True,
            "entity_id": "xyz789",
        }

        result = handler._remap_embedded_card(embedded_card, source_db_id=1)

        assert result is not None
        assert "creator_id" not in result
        assert "creator" not in result
        assert "created_at" not in result
        assert "updated_at" not in result
        assert "public_uuid" not in result
        assert "can_write" not in result
        assert "entity_id" not in result

    def test_remap_embedded_card_keeps_unmapped_card_id(self, import_context, mock_id_mapper):
        """Test that unmapped card.id keeps original value with warning."""
        mock_id_mapper.resolve_card_id.return_value = None

        handler = DashboardHandler(import_context)
        embedded_card = {
            "id": 41,
            "display": "funnel",
        }

        result = handler._remap_embedded_card(embedded_card, source_db_id=1)

        # Should keep original ID when no mapping found
        assert result is not None
        assert result["id"] == 41

    def test_remap_embedded_card_no_id_field(self, import_context):
        """Test embedded card without id field (edge case)."""
        handler = DashboardHandler(import_context)
        embedded_card = {
            "display": "scalar",
            "visualization_settings": {"scalar.field": "count"},
        }

        result = handler._remap_embedded_card(embedded_card, source_db_id=1)

        assert result is not None
        assert "id" not in result
        assert result["display"] == "scalar"


class TestPrepareDashcardsWithEmbeddedCard:
    """Tests for _prepare_single_dashcard with embedded card (Visualize another way)."""

    def test_prepare_dashcard_with_embedded_card(self, import_context, mock_id_mapper):
        """Test dashcard with embedded card is processed correctly."""
        mock_id_mapper.resolve_card_id.return_value = 999

        handler = DashboardHandler(import_context)
        dashcard = {
            "id": 1,
            "card_id": 41,
            "row": 0,
            "col": 0,
            "size_x": 6,
            "size_y": 4,
            "card": {
                "id": 41,
                "name": "My Question - Funnel View",
                "display": "funnel",
                "visualization_settings": {"funnel.type": "bar"},
            },
        }

        result = handler._prepare_single_dashcard(dashcard, temp_id=-1)

        assert result is not None
        assert result["card_id"] == 999  # card_id remapped
        assert "card" in result  # embedded card preserved
        assert result["card"]["id"] == 999  # card.id remapped

    def test_prepare_dashcard_embedded_card_without_card_id(
        self, import_context, mock_id_mapper, mock_manifest
    ):
        """Test dashcard with only embedded card (no card_id) is processed.

        This tests the edge case where 'Visualize another way' might store
        card info only in the card field.
        """
        mock_id_mapper.resolve_card_id.return_value = 999
        mock_manifest.cards = []  # No cards in manifest

        handler = DashboardHandler(import_context)
        dashcard = {
            "id": 1,
            "row": 0,
            "col": 0,
            "size_x": 6,
            "size_y": 4,
            "card": {
                "id": 41,
                "database_id": 5,
                "display": "funnel",
            },
        }

        result = handler._prepare_single_dashcard(dashcard, temp_id=-1)

        assert result is not None
        assert "card_id" not in result  # No card_id to remap
        assert "card" in result
        assert result["card"]["id"] == 999  # card.id remapped


class TestGetDashcardDatabaseIdWithEmbeddedCard:
    """Tests for _get_dashcard_database_id with embedded card."""

    def test_get_database_id_from_embedded_card_database_id(self, import_context, mock_manifest):
        """Test getting database_id from embedded card's database_id field."""
        mock_manifest.cards = []

        handler = DashboardHandler(import_context)
        dashcard = {
            "card": {
                "id": 41,
                "database_id": 5,
            }
        }

        result = handler._get_dashcard_database_id(dashcard)

        assert result == 5

    def test_get_database_id_from_embedded_card_dataset_query(self, import_context, mock_manifest):
        """Test getting database_id from embedded card's dataset_query.database."""
        mock_manifest.cards = []

        handler = DashboardHandler(import_context)
        dashcard = {
            "card": {
                "id": 41,
                "dataset_query": {
                    "database": 10,
                    "type": "query",
                },
            }
        }

        result = handler._get_dashcard_database_id(dashcard)

        assert result == 10

    def test_get_database_id_from_embedded_card_manifest_lookup(
        self, import_context, mock_manifest
    ):
        """Test getting database_id from manifest via embedded card.id."""
        mock_manifest.cards = [
            Card(
                id=41,
                name="Test Card",
                file_path="cards/test.json",
                collection_id=10,
                database_id=15,
                archived=False,
                dataset=False,
            ),
        ]

        handler = DashboardHandler(import_context)
        dashcard = {
            "card": {
                "id": 41,
                # No database_id or dataset_query
            }
        }

        result = handler._get_dashcard_database_id(dashcard)

        assert result == 15  # From manifest


class TestPrepareTabsForImport:
    """Tests for _prepare_tabs_for_import (dashboard tab migration)."""

    def test_prepare_tabs_empty(self, import_context):
        """Test with no tabs returns empty lists."""
        handler = DashboardHandler(import_context)
        tabs_to_create, tab_mapping = handler._prepare_tabs_for_import([])
        assert tabs_to_create == []
        assert tab_mapping == {}

    def test_prepare_tabs_success(self, import_context):
        """Test successful tab preparation with negative IDs and mapping."""
        handler = DashboardHandler(import_context)
        source_tabs = [
            {"id": 8, "name": "Home", "position": 0},
            {"id": 9, "name": "Analytics", "position": 1},
        ]

        tabs_to_create, tab_mapping = handler._prepare_tabs_for_import(source_tabs)

        # Should create tabs with negative IDs
        assert len(tabs_to_create) == 2
        assert tabs_to_create[0] == {"id": -1, "name": "Home", "position": 0}
        assert tabs_to_create[1] == {"id": -2, "name": "Analytics", "position": 1}

        # Should map source tab IDs to negative temp IDs
        assert tab_mapping == {8: -1, 9: -2}

    def test_prepare_tabs_preserves_position(self, import_context):
        """Test that tab positions are preserved during preparation."""
        handler = DashboardHandler(import_context)
        # Tabs in non-sequential order
        source_tabs = [
            {"id": 20, "name": "Second", "position": 1},
            {"id": 10, "name": "First", "position": 0},
        ]

        tabs_to_create, tab_mapping = handler._prepare_tabs_for_import(source_tabs)

        # Positions should be preserved
        assert tabs_to_create[0]["position"] == 1  # Second tab
        assert tabs_to_create[1]["position"] == 0  # First tab
        # Mapping should be based on order in source_tabs
        assert tab_mapping == {20: -1, 10: -2}


class TestPrepareDashcardsWithTabs:
    """Tests for _prepare_single_dashcard with tab ID remapping."""

    def test_remap_dashboard_tab_id(self, import_context, mock_id_mapper):
        """Test that dashboard_tab_id is remapped correctly."""
        mock_id_mapper.resolve_card_id.return_value = 999

        handler = DashboardHandler(import_context)
        dashcard = {
            "id": 1,
            "card_id": 41,
            "row": 0,
            "col": 0,
            "size_x": 6,
            "size_y": 4,
            "dashboard_tab_id": 8,
        }
        tab_mapping = {8: 100, 9: 101}

        result = handler._prepare_single_dashcard(dashcard, temp_id=-1, tab_mapping=tab_mapping)

        assert result is not None
        assert result["dashboard_tab_id"] == 100  # Remapped from 8 to 100

    def test_remap_dashboard_tab_id_no_mapping(self, import_context, mock_id_mapper):
        """Test dashboard_tab_id when tab mapping doesn't contain the ID."""
        mock_id_mapper.resolve_card_id.return_value = 999

        handler = DashboardHandler(import_context)
        dashcard = {
            "id": 1,
            "card_id": 41,
            "row": 0,
            "col": 0,
            "size_x": 6,
            "size_y": 4,
            "dashboard_tab_id": 8,
        }
        tab_mapping = {99: 100}  # Doesn't contain source tab ID 8

        result = handler._prepare_single_dashcard(dashcard, temp_id=-1, tab_mapping=tab_mapping)

        assert result is not None
        # Should keep original tab ID when mapping not found
        assert result["dashboard_tab_id"] == 8

    def test_dashboard_tab_id_null(self, import_context, mock_id_mapper):
        """Test dashcard with null dashboard_tab_id."""
        mock_id_mapper.resolve_card_id.return_value = 999

        handler = DashboardHandler(import_context)
        dashcard = {
            "id": 1,
            "card_id": 41,
            "row": 0,
            "col": 0,
            "size_x": 6,
            "size_y": 4,
            "dashboard_tab_id": None,
        }

        result = handler._prepare_single_dashcard(dashcard, temp_id=-1, tab_mapping={8: 100})

        assert result is not None
        # dashboard_tab_id should not be in result when source is None
        assert "dashboard_tab_id" not in result

    def test_dashboard_tab_id_no_tab_mapping(self, import_context, mock_id_mapper):
        """Test dashcard with dashboard_tab_id but no tab mapping provided."""
        mock_id_mapper.resolve_card_id.return_value = 999

        handler = DashboardHandler(import_context)
        dashcard = {
            "id": 1,
            "card_id": 41,
            "row": 0,
            "col": 0,
            "size_x": 6,
            "size_y": 4,
            "dashboard_tab_id": 8,
        }

        # No tab_mapping provided (None)
        result = handler._prepare_single_dashcard(dashcard, temp_id=-1, tab_mapping=None)

        assert result is not None
        # Should keep original tab ID when no mapping
        assert result["dashboard_tab_id"] == 8


class TestBuildUpdatePayload:
    """Tests for building dashboard update payload."""

    def test_build_update_payload_basic(self, import_context):
        """Test basic update payload building."""
        handler = DashboardHandler(import_context)
        payload = {
            "description": "Test description",
            "cache_ttl": 3600,
        }

        result = handler._build_update_payload("Test", payload, [], [])

        assert result["name"] == "Test"
        assert result["description"] == "Test description"
        assert result["cache_ttl"] == 3600

    def test_build_update_payload_with_dashcards(self, import_context):
        """Test payload with dashcards."""
        handler = DashboardHandler(import_context)
        dashcards = [{"id": -1, "card_id": 999}]

        result = handler._build_update_payload("Test", {}, [], dashcards)

        assert "dashcards" in result
        assert len(result["dashcards"]) == 1

    def test_build_update_payload_with_display_settings(self, import_context):
        """Test payload with display settings."""
        handler = DashboardHandler(import_context)
        payload = {
            "width": "full",
            "auto_apply_filters": True,
        }

        result = handler._build_update_payload("Test", payload, [], [])

        assert result["width"] == "full"
        assert result["auto_apply_filters"] is True

    def test_build_update_payload_removes_none_values(self, import_context):
        """Test that None values are removed from payload."""
        handler = DashboardHandler(import_context)
        payload = {
            "description": None,
            "cache_ttl": None,
        }

        result = handler._build_update_payload("Test", payload, [], [])

        assert "description" not in result
        assert "cache_ttl" not in result


class TestImportSingleDashboard:
    """Tests for importing a single dashboard."""

    def test_import_dashboard_success(self, import_context, mock_client, tmp_path):
        """Test successful dashboard import."""
        dash_file = tmp_path / "test_dashboard.json"
        dash_file.write_text(
            json.dumps(
                {
                    "name": "Test Dashboard",
                    "description": "A test dashboard",
                    "collection_id": 10,
                    "parameters": [],
                    "dashcards": [],
                }
            )
        )

        mock_client.get_collection_items.return_value = {"data": []}
        mock_client.create_dashboard.return_value = {"id": 1000, "name": "Test Dashboard"}
        mock_client.update_dashboard.return_value = {"id": 1000, "name": "Test Dashboard"}

        handler = DashboardHandler(import_context)
        dash = Dashboard(
            id=1,
            name="Test Dashboard",
            file_path="test_dashboard.json",
            collection_id=10,
            archived=False,
        )

        handler._import_single_dashboard(dash)

        mock_client.create_dashboard.assert_called_once()
        mock_client.update_dashboard.assert_called_once()

    def test_import_dashboard_existing_skip(self, import_context, mock_client, tmp_path):
        """Test import when dashboard exists and strategy is skip."""
        dash_file = tmp_path / "test_dashboard.json"
        dash_file.write_text(
            json.dumps(
                {
                    "name": "Test Dashboard",
                    "collection_id": 10,
                    "parameters": [],
                    "dashcards": [],
                }
            )
        )

        mock_client.get_collection_items.return_value = {
            "data": [{"id": 999, "model": "dashboard", "name": "Test Dashboard"}]
        }

        handler = DashboardHandler(import_context)
        dash = Dashboard(
            id=1,
            name="Test Dashboard",
            file_path="test_dashboard.json",
            collection_id=10,
            archived=False,
        )

        handler._import_single_dashboard(dash)

        # Should not create or update
        mock_client.create_dashboard.assert_not_called()
        mock_client.update_dashboard.assert_not_called()

    def test_import_dashboard_error(self, import_context, mock_client, tmp_path):
        """Test import when error occurs."""
        dash_file = tmp_path / "test_dashboard.json"
        dash_file.write_text(
            json.dumps(
                {
                    "name": "Test Dashboard",
                    "collection_id": 10,
                    "parameters": [],
                    "dashcards": [],
                }
            )
        )

        mock_client.get_collection_items.return_value = {"data": []}
        mock_client.create_dashboard.side_effect = Exception("API Error")

        handler = DashboardHandler(import_context)
        dash = Dashboard(
            id=1,
            name="Test Dashboard",
            file_path="test_dashboard.json",
            collection_id=10,
            archived=False,
        )

        handler._import_single_dashboard(dash)

        # Should report failure
        import_context.report.add.assert_called()


class TestImportDashboards:
    """Tests for importing multiple dashboards."""

    def test_import_dashboards_filters_archived(self, import_context, mock_config, tmp_path):
        """Test that archived dashboards are filtered out."""
        mock_config.include_archived = False

        # Create dashboard file for non-archived dashboard
        dash_file = tmp_path / "dash1.json"
        dash_file.write_text(json.dumps({"parameters": [], "dashcards": []}))

        handler = DashboardHandler(import_context)

        dashboards = [
            Dashboard(
                id=1,
                name="Active Dashboard",
                file_path="dash1.json",
                collection_id=10,
                archived=False,
            ),
            Dashboard(
                id=2,
                name="Archived Dashboard",
                file_path="dash2.json",
                collection_id=10,
                archived=True,
            ),
        ]

        with patch.object(handler, "_import_single_dashboard") as mock_import:
            handler.import_dashboards(dashboards)

            # Should only import active dashboard
            assert mock_import.call_count == 1

    def test_import_dashboards_includes_archived_when_enabled(
        self, import_context, mock_config, tmp_path
    ):
        """Test that archived dashboards are included when flag is set."""
        mock_config.include_archived = True

        # Create dashboard files
        dash1_file = tmp_path / "dash1.json"
        dash1_file.write_text(json.dumps({"parameters": [], "dashcards": []}))
        dash2_file = tmp_path / "dash2.json"
        dash2_file.write_text(json.dumps({"parameters": [], "dashcards": []}))

        handler = DashboardHandler(import_context)

        dashboards = [
            Dashboard(
                id=1,
                name="Active Dashboard",
                file_path="dash1.json",
                collection_id=10,
                archived=False,
            ),
            Dashboard(
                id=2,
                name="Archived Dashboard",
                file_path="dash2.json",
                collection_id=10,
                archived=True,
            ),
        ]

        with patch.object(handler, "_import_single_dashboard") as mock_import:
            handler.import_dashboards(dashboards)

            # Should import both dashboards
            assert mock_import.call_count == 2

    def test_import_dashboards_sorted_by_file_path(self, import_context, tmp_path):
        """Test that dashboards are imported in file path order."""
        # Create dashboard files
        dash_a_file = tmp_path / "a_dash.json"
        dash_a_file.write_text(json.dumps({"parameters": [], "dashcards": []}))
        dash_z_file = tmp_path / "z_dash.json"
        dash_z_file.write_text(json.dumps({"parameters": [], "dashcards": []}))

        handler = DashboardHandler(import_context)

        dashboards = [
            Dashboard(
                id=2,
                name="Z Dashboard",
                file_path="z_dash.json",
                collection_id=10,
                archived=False,
            ),
            Dashboard(
                id=1,
                name="A Dashboard",
                file_path="a_dash.json",
                collection_id=10,
                archived=False,
            ),
        ]

        import_order = []

        def track_import(dash):
            import_order.append(dash.file_path)

        with patch.object(handler, "_import_single_dashboard", side_effect=track_import):
            handler.import_dashboards(dashboards)

        # Should be sorted by file_path
        assert import_order == ["a_dash.json", "z_dash.json"]
