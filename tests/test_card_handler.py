"""
Unit tests for lib/handlers/card.py

Tests for the CardHandler class covering card import, dependency resolution,
conflict handling, and error scenarios.
"""

import json
from unittest.mock import Mock, patch

import pytest

from lib.client import MetabaseAPIError
from lib.config import ImportConfig
from lib.handlers.base import ImportContext
from lib.handlers.card import CardHandler
from lib.models_core import Card, ImportReport, Manifest
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
    mapper.resolve_card_id.return_value = None
    mapper.resolve_collection_id.return_value = 100
    return mapper


@pytest.fixture
def mock_query_remapper():
    """Create a mock QueryRemapper."""
    remapper = Mock(spec=QueryRemapper)
    remapper.remap_card_data.return_value = ({"name": "Test Card", "database": 1}, True)
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
        Card(
            id=2,
            name="Dependent Card",
            file_path="cards/dependent_card.json",
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
def sample_card_data():
    """Create sample card data."""
    return {
        "id": 1,
        "name": "Test Card",
        "database_id": 1,
        "dataset_query": {
            "type": "query",
            "database": 1,
            "query": {"source-table": 10},
        },
        "display": "table",
        "collection_id": 10,
    }


class TestCardHandlerInit:
    """Tests for CardHandler initialization."""

    def test_init(self, import_context):
        """Test handler initialization."""
        handler = CardHandler(import_context)
        assert handler.context == import_context
        assert handler.client == import_context.client
        assert handler.id_mapper == import_context.id_mapper


class TestExtractCardDependencies:
    """Tests for card dependency extraction."""

    def test_extract_no_dependencies(self):
        """Test extraction with no dependencies."""
        card_data = {
            "dataset_query": {
                "type": "query",
                "database": 1,
                "query": {"source-table": 10},
            }
        }
        deps = CardHandler._extract_card_dependencies(card_data)
        assert deps == set()

    def test_extract_single_card_dependency(self):
        """Test extraction with single card__X dependency."""
        card_data = {
            "dataset_query": {
                "type": "query",
                "database": 1,
                "query": {"source-table": "card__123"},
            }
        }
        deps = CardHandler._extract_card_dependencies(card_data)
        assert deps == {123}

    def test_extract_dependencies_from_joins(self):
        """Test extraction from joins."""
        card_data = {
            "dataset_query": {
                "type": "query",
                "database": 1,
                "query": {
                    "source-table": 10,
                    "joins": [
                        {"source-table": "card__100"},
                        {"source-table": "card__200"},
                    ],
                },
            }
        }
        deps = CardHandler._extract_card_dependencies(card_data)
        assert deps == {100, 200}

    def test_extract_mixed_dependencies(self):
        """Test extraction with both source-table and joins dependencies."""
        card_data = {
            "dataset_query": {
                "type": "query",
                "database": 1,
                "query": {
                    "source-table": "card__50",
                    "joins": [{"source-table": "card__100"}],
                },
            }
        }
        deps = CardHandler._extract_card_dependencies(card_data)
        assert deps == {50, 100}

    def test_extract_native_sql_dependencies(self):
        """Test extraction from native SQL with {{#123-model}} syntax."""
        card_data = {
            "dataset_query": {
                "type": "native",
                "database": 1,
                "native": {
                    "query": "SELECT * FROM {{#456-orders-model}} WHERE id > 0",
                },
            }
        }
        deps = CardHandler._extract_card_dependencies(card_data)
        assert deps == {456}

    def test_extract_template_tag_dependencies(self):
        """Test extraction from template-tags with type='card'."""
        card_data = {
            "dataset_query": {
                "type": "native",
                "database": 1,
                "native": {
                    "query": "SELECT * FROM {{model}} WHERE id > 0",
                    "template-tags": {
                        "model": {
                            "type": "card",
                            "card-id": 789,
                        }
                    },
                },
            }
        }
        deps = CardHandler._extract_card_dependencies(card_data)
        assert deps == {789}

    def test_extract_v57_stages_dependencies(self):
        """Test extraction from v57 MBQL 5 format with stages."""
        card_data = {
            "dataset_query": {
                "type": "query",
                "database": 1,
                "stages": [
                    {"source-table": "card__300"},
                    {"source-table": 10, "joins": [{"source-table": "card__400"}]},
                ],
            }
        }
        deps = CardHandler._extract_card_dependencies(card_data)
        assert deps == {300, 400}

    def test_extract_invalid_card_reference(self):
        """Test handling of invalid card reference format."""
        card_data = {
            "dataset_query": {
                "type": "query",
                "database": 1,
                "query": {"source-table": "card__invalid"},
            }
        }
        # Should not raise, just log warning
        deps = CardHandler._extract_card_dependencies(card_data)
        assert deps == set()

    def test_extract_non_string_source_table(self):
        """Test handling when source-table is not a string."""
        card_data = {
            "dataset_query": {
                "type": "query",
                "database": 1,
                "query": {"source-table": 123},  # Integer, not string
            }
        }
        deps = CardHandler._extract_card_dependencies(card_data)
        assert deps == set()

    def test_extract_empty_dataset_query(self):
        """Test handling of empty dataset_query."""
        card_data = {"dataset_query": {}}
        deps = CardHandler._extract_card_dependencies(card_data)
        assert deps == set()

    def test_extract_missing_dataset_query(self):
        """Test handling of missing dataset_query."""
        card_data = {"name": "Test Card"}
        deps = CardHandler._extract_card_dependencies(card_data)
        assert deps == set()

    def test_extract_invalid_template_tags(self):
        """Test handling of invalid template-tags structure."""
        card_data = {
            "dataset_query": {
                "type": "native",
                "database": 1,
                "native": {
                    "query": "SELECT 1",
                    "template-tags": "invalid",  # Should be dict
                },
            }
        }
        deps = CardHandler._extract_card_dependencies(card_data)
        assert deps == set()


class TestFindExistingCard:
    """Tests for finding existing cards via ImportContext."""

    def test_find_existing_card_found(self, import_context, mock_client):
        """Test finding an existing card via context."""
        mock_client.get_collection_items.return_value = {
            "data": [
                {"id": 999, "model": "card", "name": "Test Card"},
                {"id": 1000, "model": "card", "name": "Other Card"},
            ]
        }

        # Use context.find_existing_card (not prefetched, falls back to API)
        result = import_context.find_existing_card("Test Card", 100)

        assert result is not None
        assert result["id"] == 999

    def test_find_existing_card_not_found(self, import_context, mock_client):
        """Test when card is not found."""
        mock_client.get_collection_items.return_value = {
            "data": [{"id": 999, "model": "card", "name": "Other Card"}]
        }

        result = import_context.find_existing_card("Test Card", 100)

        assert result is None

    def test_find_existing_card_in_root(self, import_context, mock_client):
        """Test finding card in root collection."""
        mock_client.get_collection_items.return_value = {"data": []}

        import_context.find_existing_card("Test Card", None)

        mock_client.get_collection_items.assert_called_once_with("root")

    def test_find_existing_card_handles_exception(self, import_context, mock_client):
        """Test handling of exception when finding card."""
        mock_client.get_collection_items.side_effect = Exception("API Error")

        result = import_context.find_existing_card("Test Card", 100)

        assert result is None

    def test_find_existing_model(self, import_context, mock_client):
        """Test finding an existing model (dataset)."""
        mock_client.get_collection_items.return_value = {
            "data": [{"id": 999, "model": "dataset", "name": "Test Model"}]
        }

        result = import_context.find_existing_card("Test Model", 100)

        assert result is not None
        assert result["id"] == 999

    def test_find_existing_card_uses_cache(self, import_context, mock_client):
        """Test that find_existing_card uses cache when prefetched."""
        # Pre-populate the cache
        import_context._collection_items_cache[100] = [
            {"id": 999, "model": "card", "name": "Cached Card"}
        ]
        import_context._collection_items_prefetched = True

        result = import_context.find_existing_card("Cached Card", 100)

        # Should NOT call the API - data is cached
        mock_client.get_collection_items.assert_not_called()
        assert result is not None
        assert result["id"] == 999


class TestHandleExistingCard:
    """Tests for conflict handling when card exists."""

    def test_skip_strategy(self, import_context, mock_config, mock_id_mapper):
        """Test skip conflict strategy."""
        mock_config.conflict_strategy = "skip"

        handler = CardHandler(import_context)
        card = Card(
            id=1,
            name="Test",
            file_path="test.json",
            collection_id=10,
            database_id=1,
            archived=False,
            dataset=False,
        )
        existing = {"id": 999, "name": "Test"}

        handler._handle_existing_card(card, {"name": "Test"}, existing, 100)

        mock_id_mapper.set_card_mapping.assert_called_once_with(1, 999)

    def test_overwrite_strategy(self, import_context, mock_config, mock_client, mock_id_mapper):
        """Test overwrite conflict strategy."""
        mock_config.conflict_strategy = "overwrite"
        mock_client.update_card.return_value = {"id": 999, "name": "Test"}

        handler = CardHandler(import_context)
        card = Card(
            id=1,
            name="Test",
            file_path="test.json",
            collection_id=10,
            database_id=1,
            archived=False,
            dataset=False,
        )
        existing = {"id": 999, "name": "Test"}

        handler._handle_existing_card(card, {"name": "Test"}, existing, 100)

        mock_client.update_card.assert_called_once()
        mock_id_mapper.set_card_mapping.assert_called_once_with(1, 999)

    def test_rename_strategy(self, import_context, mock_config, mock_client, mock_id_mapper):
        """Test rename conflict strategy."""
        mock_config.conflict_strategy = "rename"
        mock_client.get_collection_items.return_value = {"data": []}
        mock_client.create_card.return_value = {"id": 1000, "name": "Test (1)"}

        handler = CardHandler(import_context)
        card = Card(
            id=1,
            name="Test",
            file_path="test.json",
            collection_id=10,
            database_id=1,
            archived=False,
            dataset=False,
        )
        existing = {"id": 999, "name": "Test"}

        handler._handle_existing_card(card, {"name": "Test"}, existing, 100)

        mock_client.create_card.assert_called_once()


class TestCreateCard:
    """Tests for card creation."""

    def test_create_card_success(self, import_context, mock_client, mock_id_mapper):
        """Test successful card creation."""
        mock_client.create_card.return_value = {"id": 1000, "name": "Test Card"}

        handler = CardHandler(import_context)
        card = Card(
            id=1,
            name="Test Card",
            file_path="test.json",
            collection_id=10,
            database_id=1,
            archived=False,
            dataset=False,
        )

        handler._create_card(card, {"name": "Test Card", "dataset": False})

        mock_client.create_card.assert_called_once()
        mock_id_mapper.set_card_mapping.assert_called_once_with(1, 1000)

    def test_create_model(self, import_context, mock_client, mock_id_mapper):
        """Test creating a model (dataset=True)."""
        mock_client.create_card.return_value = {"id": 1000, "name": "Test Model"}

        handler = CardHandler(import_context)
        card = Card(
            id=1,
            name="Test Model",
            file_path="test.json",
            collection_id=10,
            database_id=1,
            archived=False,
            dataset=True,
        )

        handler._create_card(card, {"name": "Test Model", "dataset": True})

        mock_client.create_card.assert_called_once()


class TestGenerateUniqueCardName:
    """Tests for unique name generation."""

    def test_generate_unique_name(self, import_context, mock_client):
        """Test generating unique name when conflict exists."""
        # First call returns existing card, second call returns empty
        mock_client.get_collection_items.side_effect = [
            {"data": [{"model": "card", "name": "Test (1)"}]},
            {"data": []},
        ]

        handler = CardHandler(import_context)
        result = handler._generate_unique_card_name("Test", 100)

        assert result == "Test (2)"


class TestCheckMissingDependencies:
    """Tests for missing dependency detection."""

    def test_no_missing_dependencies(self, import_context, mock_id_mapper):
        """Test when all dependencies are present."""
        mock_id_mapper.resolve_card_id.return_value = 999  # Mapped

        handler = CardHandler(import_context)
        card = Card(
            id=1,
            name="Test",
            file_path="test.json",
            collection_id=10,
            database_id=1,
            archived=False,
            dataset=False,
        )

        missing = handler._check_missing_dependencies({100, 200}, card)

        assert missing == []

    def test_missing_dependencies_not_in_export(self, import_context, mock_id_mapper):
        """Test when dependency is missing and not in export."""
        mock_id_mapper.resolve_card_id.return_value = None
        import_context.manifest.cards = []  # Empty export

        handler = CardHandler(import_context)
        card = Card(
            id=1,
            name="Test",
            file_path="test.json",
            collection_id=10,
            database_id=1,
            archived=False,
            dataset=False,
        )

        missing = handler._check_missing_dependencies({999}, card)

        assert missing == [999]

    def test_dependency_in_export_but_not_imported_yet(self, import_context, mock_id_mapper):
        """Test when dependency is in export but not yet imported."""
        mock_id_mapper.resolve_card_id.return_value = None
        import_context.manifest.cards = [
            Card(
                id=999,
                name="Dep Card",
                file_path="dep.json",
                collection_id=10,
                database_id=1,
                archived=False,
                dataset=False,
            )
        ]

        handler = CardHandler(import_context)
        card = Card(
            id=1,
            name="Test",
            file_path="test.json",
            collection_id=10,
            database_id=1,
            archived=False,
            dataset=False,
        )

        missing = handler._check_missing_dependencies({999}, card)

        assert missing == []  # Not missing because it's in the export


class TestHandleApiError:
    """Tests for API error handling."""

    def test_handle_missing_card_error(self, import_context):
        """Test handling of missing card reference error."""
        handler = CardHandler(import_context)
        card = Card(
            id=1,
            name="Test",
            file_path="test.json",
            collection_id=10,
            database_id=1,
            archived=False,
            dataset=False,
        )
        error = MetabaseAPIError("Card 456 does not exist")

        handler._handle_api_error(card, error)

        import_context.report.add.assert_called()

    def test_handle_table_id_error(self, import_context):
        """Test handling of table ID constraint error."""
        handler = CardHandler(import_context)
        card = Card(
            id=1,
            name="Test",
            file_path="test.json",
            collection_id=10,
            database_id=1,
            archived=False,
            dataset=False,
        )
        error = MetabaseAPIError(
            "fk_report_card_ref_table_id: Key (table_id)=(999) not present in table"
        )

        handler._handle_api_error(card, error)

        import_context.report.add.assert_called()

    def test_handle_generic_api_error(self, import_context):
        """Test handling of generic API error."""
        handler = CardHandler(import_context)
        card = Card(
            id=1,
            name="Test",
            file_path="test.json",
            collection_id=10,
            database_id=1,
            archived=False,
            dataset=False,
        )
        error = MetabaseAPIError("Some other error")

        handler._handle_api_error(card, error)

        import_context.report.add.assert_called()


class TestLogErrors:
    """Tests for error logging methods."""

    def test_log_missing_card_error(self, import_context):
        """Test logging missing card dependency error."""
        handler = CardHandler(import_context)
        card = Card(
            id=1,
            name="Test",
            file_path="test.json",
            collection_id=10,
            database_id=1,
            archived=False,
            dataset=False,
        )

        # Should not raise
        handler._log_missing_card_error(card, 456)

    def test_log_table_id_error(self, import_context):
        """Test logging table ID mapping error."""
        handler = CardHandler(import_context)
        card = Card(
            id=1,
            name="Test",
            file_path="test.json",
            collection_id=10,
            database_id=1,
            archived=False,
            dataset=False,
        )

        # Should not raise
        handler._log_table_id_error(card, "999", "Error details")


class TestTopologicalSortCards:
    """Tests for topological sorting of cards."""

    def test_sort_no_dependencies(self, import_context, tmp_path):
        """Test sorting cards with no dependencies."""
        # Create card files
        card1_file = tmp_path / "card1.json"
        card1_file.write_text(json.dumps({"dataset_query": {"query": {"source-table": 10}}}))
        card2_file = tmp_path / "card2.json"
        card2_file.write_text(json.dumps({"dataset_query": {"query": {"source-table": 20}}}))

        cards = [
            Card(
                id=1,
                name="Card 1",
                file_path="card1.json",
                collection_id=10,
                database_id=1,
                archived=False,
                dataset=False,
            ),
            Card(
                id=2,
                name="Card 2",
                file_path="card2.json",
                collection_id=10,
                database_id=1,
                archived=False,
                dataset=False,
            ),
        ]

        handler = CardHandler(import_context)
        sorted_cards = handler._topological_sort_cards(cards)

        assert len(sorted_cards) == 2

    def test_sort_with_dependencies(self, import_context, tmp_path):
        """Test sorting cards with dependencies."""
        # Card 2 depends on Card 1
        card1_file = tmp_path / "card1.json"
        card1_file.write_text(json.dumps({"dataset_query": {"query": {"source-table": 10}}}))
        card2_file = tmp_path / "card2.json"
        card2_file.write_text(json.dumps({"dataset_query": {"query": {"source-table": "card__1"}}}))

        cards = [
            Card(
                id=2,
                name="Card 2",
                file_path="card2.json",
                collection_id=10,
                database_id=1,
                archived=False,
                dataset=False,
            ),
            Card(
                id=1,
                name="Card 1",
                file_path="card1.json",
                collection_id=10,
                database_id=1,
                archived=False,
                dataset=False,
            ),
        ]

        handler = CardHandler(import_context)
        sorted_cards = handler._topological_sort_cards(cards)

        # Card 1 should come before Card 2
        card_ids = [c.id for c in sorted_cards]
        assert card_ids.index(1) < card_ids.index(2)

    def test_sort_handles_circular_dependencies(self, import_context, tmp_path):
        """Test handling of circular dependencies."""
        # Card 1 depends on Card 2, Card 2 depends on Card 1
        card1_file = tmp_path / "card1.json"
        card1_file.write_text(json.dumps({"dataset_query": {"query": {"source-table": "card__2"}}}))
        card2_file = tmp_path / "card2.json"
        card2_file.write_text(json.dumps({"dataset_query": {"query": {"source-table": "card__1"}}}))

        cards = [
            Card(
                id=1,
                name="Card 1",
                file_path="card1.json",
                collection_id=10,
                database_id=1,
                archived=False,
                dataset=False,
            ),
            Card(
                id=2,
                name="Card 2",
                file_path="card2.json",
                collection_id=10,
                database_id=1,
                archived=False,
                dataset=False,
            ),
        ]

        handler = CardHandler(import_context)
        sorted_cards = handler._topological_sort_cards(cards)

        # Should still return all cards even with circular dependency
        assert len(sorted_cards) == 2

    def test_sort_handles_read_error(self, import_context, tmp_path):
        """Test handling of file read error during sorting."""
        # Card file doesn't exist
        cards = [
            Card(
                id=1,
                name="Card 1",
                file_path="nonexistent.json",
                collection_id=10,
                database_id=1,
                archived=False,
                dataset=False,
            ),
        ]

        handler = CardHandler(import_context)
        sorted_cards = handler._topological_sort_cards(cards)

        # Should still return the card
        assert len(sorted_cards) == 1


class TestImportSingleCard:
    """Tests for importing a single card."""

    def test_import_card_success(self, import_context, mock_client, tmp_path):
        """Test successful card import."""
        card_file = tmp_path / "test_card.json"
        card_file.write_text(
            json.dumps(
                {
                    "name": "Test Card",
                    "dataset_query": {"query": {"source-table": 10}, "database": 1},
                }
            )
        )

        mock_client.get_collection_items.return_value = {"data": []}
        mock_client.create_card.return_value = {"id": 1000, "name": "Test Card"}

        handler = CardHandler(import_context)
        card = Card(
            id=1,
            name="Test Card",
            file_path="test_card.json",
            collection_id=10,
            database_id=1,
            archived=False,
            dataset=False,
        )

        handler._import_single_card(card)

        mock_client.create_card.assert_called_once()

    def test_import_card_with_missing_deps(self, import_context, mock_client, tmp_path):
        """Test import when card has missing dependencies."""
        card_file = tmp_path / "test_card.json"
        card_file.write_text(
            json.dumps(
                {
                    "name": "Test Card",
                    "dataset_query": {"query": {"source-table": "card__999"}, "database": 1},
                }
            )
        )

        import_context.manifest.cards = []  # No cards in export

        handler = CardHandler(import_context)
        card = Card(
            id=1,
            name="Test Card",
            file_path="test_card.json",
            collection_id=10,
            database_id=1,
            archived=False,
            dataset=False,
        )

        handler._import_single_card(card)

        # Should report failure
        import_context.report.add.assert_called()
        # Should NOT create card
        mock_client.create_card.assert_not_called()

    def test_import_card_remap_fails(self, import_context, mock_client, tmp_path):
        """Test import when remapping fails."""
        card_file = tmp_path / "test_card.json"
        card_file.write_text(
            json.dumps(
                {
                    "name": "Test Card",
                    "dataset_query": {"query": {"source-table": 10}, "database": 1},
                }
            )
        )

        import_context.query_remapper.remap_card_data.return_value = ({}, False)

        handler = CardHandler(import_context)
        card = Card(
            id=1,
            name="Test Card",
            file_path="test_card.json",
            collection_id=10,
            database_id=1,
            archived=False,
            dataset=False,
        )

        handler._import_single_card(card)

        # Should report failure
        import_context.report.add.assert_called()

    def test_import_card_api_error(self, import_context, mock_client, tmp_path):
        """Test import when API returns error."""
        card_file = tmp_path / "test_card.json"
        card_file.write_text(
            json.dumps(
                {
                    "name": "Test Card",
                    "dataset_query": {"query": {"source-table": 10}, "database": 1},
                }
            )
        )

        mock_client.get_collection_items.return_value = {"data": []}
        mock_client.create_card.side_effect = MetabaseAPIError("API Error")

        handler = CardHandler(import_context)
        card = Card(
            id=1,
            name="Test Card",
            file_path="test_card.json",
            collection_id=10,
            database_id=1,
            archived=False,
            dataset=False,
        )

        handler._import_single_card(card)

        # Should report failure
        import_context.report.add.assert_called()

    def test_import_card_generic_error(self, import_context, mock_client, tmp_path):
        """Test import when generic error occurs."""
        card_file = tmp_path / "test_card.json"
        card_file.write_text(
            json.dumps(
                {
                    "name": "Test Card",
                    "dataset_query": {"query": {"source-table": 10}, "database": 1},
                }
            )
        )

        mock_client.get_collection_items.return_value = {"data": []}
        mock_client.create_card.side_effect = Exception("Unexpected error")

        handler = CardHandler(import_context)
        card = Card(
            id=1,
            name="Test Card",
            file_path="test_card.json",
            collection_id=10,
            database_id=1,
            archived=False,
            dataset=False,
        )

        handler._import_single_card(card)

        # Should report failure
        import_context.report.add.assert_called()


class TestImportCards:
    """Tests for importing multiple cards."""

    def test_import_cards_filters_archived(self, import_context, mock_config, tmp_path):
        """Test that archived cards are filtered out."""
        mock_config.include_archived = False

        # Create card file for non-archived card
        card_file = tmp_path / "card1.json"
        card_file.write_text(json.dumps({"dataset_query": {"query": {}}}))

        handler = CardHandler(import_context)

        cards = [
            Card(
                id=1,
                name="Active Card",
                file_path="card1.json",
                collection_id=10,
                database_id=1,
                archived=False,
                dataset=False,
            ),
            Card(
                id=2,
                name="Archived Card",
                file_path="card2.json",
                collection_id=10,
                database_id=1,
                archived=True,
                dataset=False,
            ),
        ]

        with patch.object(handler, "_import_single_card") as mock_import:
            handler.import_cards(cards)

            # Should only import active card
            assert mock_import.call_count == 1

    def test_import_cards_includes_archived_when_enabled(
        self, import_context, mock_config, tmp_path
    ):
        """Test that archived cards are included when flag is set."""
        mock_config.include_archived = True

        # Create card files
        card1_file = tmp_path / "card1.json"
        card1_file.write_text(json.dumps({"dataset_query": {"query": {}}}))
        card2_file = tmp_path / "card2.json"
        card2_file.write_text(json.dumps({"dataset_query": {"query": {}}}))

        handler = CardHandler(import_context)

        cards = [
            Card(
                id=1,
                name="Active Card",
                file_path="card1.json",
                collection_id=10,
                database_id=1,
                archived=False,
                dataset=False,
            ),
            Card(
                id=2,
                name="Archived Card",
                file_path="card2.json",
                collection_id=10,
                database_id=1,
                archived=True,
                dataset=False,
            ),
        ]

        with patch.object(handler, "_import_single_card") as mock_import:
            handler.import_cards(cards)

            # Should import both cards
            assert mock_import.call_count == 2
