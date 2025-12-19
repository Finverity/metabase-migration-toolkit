"""
Unit tests for export_metabase.py

Tests the MetabaseExporter class and export logic.
"""

from pathlib import Path
from unittest.mock import Mock, patch

from export_metabase import MetabaseExporter
from lib.config import ExportConfig


class TestMetabaseExporterInit:
    """Test suite for MetabaseExporter initialization."""

    def test_init_with_config(self, sample_export_config):
        """Test MetabaseExporter initialization with config."""
        with patch("lib.services.export_service.MetabaseClient"):
            exporter = MetabaseExporter(sample_export_config)

            assert exporter.config == sample_export_config
            assert exporter.export_dir == Path(sample_export_config.export_dir)
            assert exporter.manifest is not None
            assert exporter._collection_path_map == {}
            assert exporter._processed_collections == set()
            assert exporter._exported_cards == set()
            assert exporter._dependency_chain == []

    def test_init_creates_client(self, sample_export_config):
        """Test that initialization creates a MetabaseClient."""
        with patch("lib.services.export_service.MetabaseClient") as mock_client_class:
            MetabaseExporter(sample_export_config)

            mock_client_class.assert_called_once_with(
                base_url=sample_export_config.source_url,
                username=sample_export_config.source_username,
                password=sample_export_config.source_password,
                session_token=sample_export_config.source_session_token,
                personal_token=sample_export_config.source_personal_token,
            )

    def test_init_creates_manifest(self, sample_export_config):
        """Test that initialization creates a manifest."""
        with patch("lib.services.export_service.MetabaseClient"):
            exporter = MetabaseExporter(sample_export_config)

            assert exporter.manifest is not None
            assert exporter.manifest.meta is not None
            assert exporter.manifest.meta.source_url == sample_export_config.source_url
            assert exporter.manifest.meta.tool_version is not None


class TestManifestInitialization:
    """Test suite for manifest initialization."""

    def test_initialize_manifest_redacts_secrets(self, sample_export_config):
        """Test that secrets are redacted in manifest."""
        with patch("lib.services.export_service.MetabaseClient"):
            exporter = MetabaseExporter(sample_export_config)

            cli_args = exporter.manifest.meta.cli_args
            assert cli_args["source_password"] == "********"

    def test_initialize_manifest_includes_metadata(self, sample_export_config):
        """Test that manifest includes proper metadata."""
        with patch("lib.services.export_service.MetabaseClient"):
            exporter = MetabaseExporter(sample_export_config)

            meta = exporter.manifest.meta
            assert meta.source_url == sample_export_config.source_url
            assert meta.export_timestamp is not None
            assert meta.tool_version is not None
            assert isinstance(meta.cli_args, dict)

    def test_initialize_manifest_with_session_token(self):
        """Test manifest initialization with session token."""
        config = ExportConfig(
            source_url="https://example.com",
            export_dir="./export",
            source_session_token="session-token-123",
        )

        with patch("lib.services.export_service.MetabaseClient"):
            exporter = MetabaseExporter(config)

            cli_args = exporter.manifest.meta.cli_args
            assert cli_args["source_session_token"] == "********"


class TestFetchAndStoreDatabases:
    """Test suite for _fetch_and_store_databases method."""

    def test_fetch_databases_list_format(self, sample_export_config):
        """Test fetching databases when API returns a list."""
        with patch("lib.services.export_service.MetabaseClient") as mock_client_class:
            mock_client = Mock()
            mock_client.get_databases.return_value = [
                {"id": 1, "name": "DB1"},
                {"id": 2, "name": "DB2"},
            ]
            mock_client_class.return_value = mock_client

            exporter = MetabaseExporter(sample_export_config)
            exporter._fetch_and_store_databases()

            assert exporter.manifest.databases == {1: "DB1", 2: "DB2"}

    def test_fetch_databases_dict_format(self, sample_export_config):
        """Test fetching databases when API returns a dict with 'data' key."""
        with patch("lib.services.export_service.MetabaseClient") as mock_client_class:
            mock_client = Mock()
            mock_client.get_databases.return_value = {
                "data": [{"id": 1, "name": "DB1"}, {"id": 2, "name": "DB2"}]
            }
            mock_client_class.return_value = mock_client

            exporter = MetabaseExporter(sample_export_config)
            exporter._fetch_and_store_databases()

            assert exporter.manifest.databases == {1: "DB1", 2: "DB2"}

    def test_fetch_databases_empty_response(self, sample_export_config):
        """Test fetching databases with empty response."""
        with patch("lib.services.export_service.MetabaseClient") as mock_client_class:
            mock_client = Mock()
            mock_client.get_databases.return_value = []
            mock_client_class.return_value = mock_client

            exporter = MetabaseExporter(sample_export_config)
            exporter._fetch_and_store_databases()

            assert exporter.manifest.databases == {}


class TestExtractCardDependencies:
    """Test suite for _extract_card_dependencies method."""

    def test_extract_no_dependencies(self, sample_export_config):
        """Test extracting dependencies from card with no dependencies."""
        with patch("lib.services.export_service.MetabaseClient"):
            exporter = MetabaseExporter(sample_export_config)

            card_data = {
                "id": 100,
                "dataset_query": {"type": "query", "database": 1, "query": {"source-table": 10}},
            }

            deps = exporter._extract_card_dependencies(card_data)
            assert deps == set()

    def test_extract_single_dependency(self, sample_export_config):
        """Test extracting single card dependency."""
        with patch("lib.services.export_service.MetabaseClient"):
            exporter = MetabaseExporter(sample_export_config)

            card_data = {
                "id": 100,
                "dataset_query": {
                    "type": "query",
                    "database": 1,
                    "query": {"source-table": "card__50"},
                },
            }

            deps = exporter._extract_card_dependencies(card_data)
            assert deps == {50}

    def test_extract_multiple_dependencies(self, sample_export_config):
        """Test extracting multiple card dependencies from joins."""
        with patch("lib.services.export_service.MetabaseClient"):
            exporter = MetabaseExporter(sample_export_config)

            card_data = {
                "id": 100,
                "dataset_query": {
                    "type": "query",
                    "database": 1,
                    "query": {
                        "source-table": "card__50",
                        "joins": [{"source-table": "card__51"}, {"source-table": "card__52"}],
                    },
                },
            }

            deps = exporter._extract_card_dependencies(card_data)
            assert deps == {50, 51, 52}

    def test_extract_dependencies_invalid_format(self, sample_export_config):
        """Test extracting dependencies with invalid card reference format."""
        with patch("lib.services.export_service.MetabaseClient"):
            exporter = MetabaseExporter(sample_export_config)

            card_data = {
                "id": 100,
                "dataset_query": {
                    "type": "query",
                    "database": 1,
                    "query": {"source-table": "card__invalid"},
                },
            }

            deps = exporter._extract_card_dependencies(card_data)
            assert deps == set()

    def test_extract_dependencies_no_dataset_query(self, sample_export_config):
        """Test extracting dependencies from card without dataset_query."""
        with patch("lib.services.export_service.MetabaseClient"):
            exporter = MetabaseExporter(sample_export_config)

            card_data = {"id": 100}

            deps = exporter._extract_card_dependencies(card_data)
            assert deps == set()


class TestTraverseCollections:
    """Test suite for _traverse_collections method."""

    def test_traverse_empty_collections(self, sample_export_config, tmp_path):
        """Test traversing empty collection list."""
        config = ExportConfig(
            source_url="https://example.com",
            export_dir=str(tmp_path / "export"),
            source_session_token="token",
        )

        with patch("lib.services.export_service.MetabaseClient"):
            exporter = MetabaseExporter(config)
            exporter._traverse_collections([])

            assert len(exporter.manifest.collections) == 0

    def test_traverse_skips_personal_collections(self, sample_export_config, tmp_path):
        """Test that personal collections are skipped."""
        config = ExportConfig(
            source_url="https://example.com",
            export_dir=str(tmp_path / "export"),
            source_session_token="token",
        )

        with patch("lib.services.export_service.MetabaseClient"):
            exporter = MetabaseExporter(config)

            collections = [
                {"id": 1, "name": "Personal Collection", "personal_owner_id": 123, "children": []}
            ]

            with patch.object(exporter, "_process_collection_items"):
                exporter._traverse_collections(collections)

            assert len(exporter.manifest.collections) == 0

    def test_traverse_processes_root_collection(self, sample_export_config, tmp_path):
        """Test processing root collection."""
        config = ExportConfig(
            source_url="https://example.com",
            export_dir=str(tmp_path / "export"),
            source_session_token="token",
        )

        with patch("lib.services.export_service.MetabaseClient"):
            exporter = MetabaseExporter(config)

            collections = [{"id": "root", "name": "Our analytics", "children": []}]

            with patch.object(exporter, "_process_collection_items") as mock_process:
                exporter._traverse_collections(collections)
                mock_process.assert_called_once_with("root", "collections")


class TestProcessCollectionItems:
    """Test suite for _process_collection_items method."""

    def test_process_empty_collection(self, sample_export_config):
        """Test processing collection with no items."""
        with patch("lib.services.export_service.MetabaseClient") as mock_client_class:
            mock_client = Mock()
            mock_client.get_collection_items.return_value = {"data": []}
            mock_client_class.return_value = mock_client

            exporter = MetabaseExporter(sample_export_config)
            exporter._process_collection_items(1, "test-path")

            # Should not raise any errors
            assert True

    def test_process_collection_with_cards(self, sample_export_config):
        """Test processing collection with cards."""
        with patch("lib.services.export_service.MetabaseClient") as mock_client_class:
            mock_client = Mock()
            mock_client.get_collection_items.return_value = {
                "data": [{"id": 100, "model": "card"}, {"id": 101, "model": "card"}]
            }
            mock_client_class.return_value = mock_client

            exporter = MetabaseExporter(sample_export_config)

            with patch.object(exporter, "_export_card_with_dependencies") as mock_export:
                exporter._process_collection_items(1, "test-path")

                assert mock_export.call_count == 2


class TestExportDirectory:
    """Test suite for export directory creation."""

    def test_export_dir_created(self, sample_export_config, tmp_path):
        """Test that export directory is created."""
        config = ExportConfig(
            source_url="https://example.com",
            export_dir=str(tmp_path / "new_export"),
            source_session_token="token",
        )

        with patch("lib.services.export_service.MetabaseClient"):
            exporter = MetabaseExporter(config)

            # Directory should not exist yet
            assert not exporter.export_dir.exists()


class TestModelExport:
    """Test suite for exporting Metabase models (cards with dataset=True)."""

    def test_export_model_preserves_dataset_field(self, sample_export_config, tmp_path):
        """Test that exporting a model preserves the dataset=True field."""
        from tests.fixtures.sample_responses import SAMPLE_MODEL

        config = ExportConfig(
            source_url="https://example.com",
            export_dir=str(tmp_path / "export"),
            source_session_token="token",
        )

        with patch("lib.services.export_service.MetabaseClient") as mock_client_class:
            mock_client = Mock()
            mock_client.get_card.return_value = SAMPLE_MODEL
            mock_client_class.return_value = mock_client

            exporter = MetabaseExporter(config)
            exporter._export_card(102, "test-collection")

            # Check that the card was added to manifest with dataset=True
            assert len(exporter.manifest.cards) == 1
            exported_card = exporter.manifest.cards[0]
            assert exported_card.id == 102
            assert exported_card.name == "Customer Base Model"
            assert exported_card.dataset is True

    def test_export_question_has_dataset_false(self, sample_export_config, tmp_path):
        """Test that exporting a regular question has dataset=False."""
        from tests.fixtures.sample_responses import SAMPLE_CARD

        config = ExportConfig(
            source_url="https://example.com",
            export_dir=str(tmp_path / "export"),
            source_session_token="token",
        )

        with patch("lib.services.export_service.MetabaseClient") as mock_client_class:
            mock_client = Mock()
            mock_client.get_card.return_value = SAMPLE_CARD
            mock_client_class.return_value = mock_client

            exporter = MetabaseExporter(config)
            exporter._export_card(100, "test-collection")

            # Check that the card was added to manifest with dataset=False (default)
            assert len(exporter.manifest.cards) == 1
            exported_card = exporter.manifest.cards[0]
            assert exported_card.id == 100
            assert exported_card.name == "Monthly Revenue"
            assert exported_card.dataset is False


class TestExportDashboard:
    """Test suite for _export_dashboard method."""

    def test_export_dashboard_success(self, tmp_path):
        """Test successful dashboard export."""
        config = ExportConfig(
            source_url="https://example.com",
            export_dir=str(tmp_path / "export"),
            source_session_token="token",
        )

        with patch("lib.services.export_service.MetabaseClient") as mock_client_class:
            mock_client = Mock()
            mock_client.get_dashboard.return_value = {
                "id": 1,
                "name": "Test Dashboard",
                "collection_id": 10,
                "dashcards": [],
                "parameters": [],
            }
            mock_client_class.return_value = mock_client

            exporter = MetabaseExporter(config)
            exporter._export_dashboard(1, "test-collection")

            assert len(exporter.manifest.dashboards) == 1
            assert exporter.manifest.dashboards[0].id == 1
            assert exporter.manifest.dashboards[0].name == "Test Dashboard"

    def test_export_dashboard_with_cards(self, tmp_path):
        """Test dashboard export with dashcards."""
        config = ExportConfig(
            source_url="https://example.com",
            export_dir=str(tmp_path / "export"),
            source_session_token="token",
        )

        with patch("lib.services.export_service.MetabaseClient") as mock_client_class:
            mock_client = Mock()
            mock_client.get_dashboard.return_value = {
                "id": 1,
                "name": "Test Dashboard",
                "collection_id": 10,
                "dashcards": [{"id": 1, "card_id": 100}, {"id": 2, "card_id": 101}],
                "parameters": [],
            }
            mock_client.get_card.return_value = {
                "id": 100,
                "name": "Card 1",
                "database_id": 1,
                "dataset_query": {"database": 1, "type": "query", "query": {}},
            }
            mock_client_class.return_value = mock_client

            exporter = MetabaseExporter(config)
            exporter._export_dashboard(1, "test-collection")

            assert len(exporter.manifest.dashboards) == 1
            assert exporter.manifest.dashboards[0].ordered_cards == [100, 101]

    def test_export_dashboard_with_parameter_card_reference(self, tmp_path):
        """Test dashboard export with parameter referencing a card."""
        config = ExportConfig(
            source_url="https://example.com",
            export_dir=str(tmp_path / "export"),
            source_session_token="token",
        )

        with patch("lib.services.export_service.MetabaseClient") as mock_client_class:
            mock_client = Mock()
            mock_client.get_dashboard.return_value = {
                "id": 1,
                "name": "Test Dashboard",
                "collection_id": 10,
                "dashcards": [],
                "parameters": [
                    {
                        "name": "Filter",
                        "values_source_config": {"card_id": 200},
                    }
                ],
            }
            mock_client.get_card.return_value = {
                "id": 200,
                "name": "Values Card",
                "database_id": 1,
                "dataset_query": {"database": 1, "type": "query", "query": {}},
            }
            mock_client_class.return_value = mock_client

            exporter = MetabaseExporter(config)
            exporter._export_dashboard(1, "test-collection")

            # Card ID from parameter should be included
            assert 200 in exporter.manifest.dashboards[0].ordered_cards

    def test_export_dashboard_archived_404(self, tmp_path):
        """Test handling of archived dashboard 404."""
        from lib.client import MetabaseAPIError

        config = ExportConfig(
            source_url="https://example.com",
            export_dir=str(tmp_path / "export"),
            source_session_token="token",
        )

        with patch("lib.services.export_service.MetabaseClient") as mock_client_class:
            mock_client = Mock()
            mock_client.get_dashboard.side_effect = MetabaseAPIError(
                "archived dashboard", status_code=404
            )
            mock_client_class.return_value = mock_client

            exporter = MetabaseExporter(config)
            # Should not raise, should log warning
            exporter._export_dashboard(1, "test-collection")

            assert len(exporter.manifest.dashboards) == 0


class TestExportPermissions:
    """Test suite for _export_permissions method."""

    def test_export_permissions_success(self, tmp_path):
        """Test successful permissions export."""
        config = ExportConfig(
            source_url="https://example.com",
            export_dir=str(tmp_path / "export"),
            source_session_token="token",
            include_permissions=True,
        )

        with patch("lib.services.export_service.MetabaseClient") as mock_client_class:
            mock_client = Mock()
            mock_client.get_permission_groups.return_value = [
                {"id": 1, "name": "All Users", "member_count": 10},
                {"id": 2, "name": "Admins", "member_count": 2},
            ]
            mock_client.get_permissions_graph.return_value = {"groups": {}}
            mock_client.get_collection_permissions_graph.return_value = {"groups": {}}
            mock_client_class.return_value = mock_client

            exporter = MetabaseExporter(config)
            exporter._export_permissions()

            assert len(exporter.manifest.permission_groups) == 2
            assert exporter.manifest.permissions_graph is not None
            assert exporter.manifest.collection_permissions_graph is not None

    def test_export_permissions_api_error(self, tmp_path):
        """Test permissions export with API error continues gracefully."""
        from lib.client import MetabaseAPIError

        config = ExportConfig(
            source_url="https://example.com",
            export_dir=str(tmp_path / "export"),
            source_session_token="token",
            include_permissions=True,
        )

        with patch("lib.services.export_service.MetabaseClient") as mock_client_class:
            mock_client = Mock()
            mock_client.get_permission_groups.side_effect = MetabaseAPIError(
                "Permission denied", status_code=403
            )
            mock_client_class.return_value = mock_client

            exporter = MetabaseExporter(config)
            # Should not raise, should log warning
            exporter._export_permissions()


class TestRunExport:
    """Test suite for run_export method."""

    def test_run_export_no_collections(self, tmp_path):
        """Test export with no collections."""
        config = ExportConfig(
            source_url="https://example.com",
            export_dir=str(tmp_path / "export"),
            source_session_token="token",
        )

        with patch("lib.services.export_service.MetabaseClient") as mock_client_class:
            mock_client = Mock()
            mock_client.get_databases.return_value = []
            mock_client.get_collections_tree.return_value = []
            mock_client_class.return_value = mock_client

            exporter = MetabaseExporter(config)
            exporter.run_export()

            # Should complete without errors
            assert len(exporter.manifest.collections) == 0

    def test_run_export_with_root_collection_filter(self, tmp_path):
        """Test export with root collection filter."""
        config = ExportConfig(
            source_url="https://example.com",
            export_dir=str(tmp_path / "export"),
            source_session_token="token",
            root_collection_ids=[5],
        )

        with patch("lib.services.export_service.MetabaseClient") as mock_client_class:
            mock_client = Mock()
            mock_client.get_databases.return_value = []
            mock_client.get_database_metadata.return_value = {"tables": []}
            mock_client.get_collections_tree.return_value = [
                {"id": 1, "name": "Collection 1", "children": []},
                {"id": 5, "name": "Collection 5", "children": []},
            ]
            mock_client.get_collection_items.return_value = {"data": []}
            mock_client_class.return_value = mock_client

            exporter = MetabaseExporter(config)
            exporter.run_export()

            # Should only include collection 5
            collection_ids = [c.id for c in exporter.manifest.collections]
            assert 5 in collection_ids
            assert 1 not in collection_ids

    def test_run_export_with_permissions(self, tmp_path):
        """Test export with permissions included."""
        config = ExportConfig(
            source_url="https://example.com",
            export_dir=str(tmp_path / "export"),
            source_session_token="token",
            include_permissions=True,
        )

        with patch("lib.services.export_service.MetabaseClient") as mock_client_class:
            mock_client = Mock()
            mock_client.get_databases.return_value = []
            # Need at least one collection for permissions to be exported
            mock_client.get_collections_tree.return_value = [
                {"id": 1, "name": "Test Collection", "children": []}
            ]
            mock_client.get_collection_items.return_value = {"data": []}
            mock_client.get_permission_groups.return_value = [
                {"id": 1, "name": "All Users", "member_count": 5}
            ]
            mock_client.get_permissions_graph.return_value = {"groups": {}}
            mock_client.get_collection_permissions_graph.return_value = {"groups": {}}
            mock_client_class.return_value = mock_client

            exporter = MetabaseExporter(config)
            exporter.run_export()

            assert len(exporter.manifest.permission_groups) == 1


class TestFetchDatabasesMetadata:
    """Test suite for database metadata fetching."""

    def test_fetch_databases_with_metadata(self, sample_export_config, tmp_path):
        """Test fetching databases with metadata."""
        config = ExportConfig(
            source_url="https://example.com",
            export_dir=str(tmp_path / "export"),
            source_session_token="token",
        )

        with patch("lib.services.export_service.MetabaseClient") as mock_client_class:
            mock_client = Mock()
            mock_client.get_databases.return_value = [{"id": 1, "name": "TestDB"}]
            mock_client.get_database_metadata.return_value = {
                "tables": [
                    {
                        "id": 10,
                        "name": "users",
                        "fields": [{"id": 100, "name": "id"}, {"id": 101, "name": "email"}],
                    }
                ]
            }
            mock_client_class.return_value = mock_client

            exporter = MetabaseExporter(config)
            exporter._fetch_and_store_databases()

            assert 1 in exporter.manifest.database_metadata
            assert len(exporter.manifest.database_metadata[1]["tables"]) == 1
            assert exporter.manifest.database_metadata[1]["tables"][0]["name"] == "users"

    def test_fetch_databases_metadata_error(self, sample_export_config, tmp_path):
        """Test handling of metadata fetch error."""
        config = ExportConfig(
            source_url="https://example.com",
            export_dir=str(tmp_path / "export"),
            source_session_token="token",
        )

        with patch("lib.services.export_service.MetabaseClient") as mock_client_class:
            mock_client = Mock()
            mock_client.get_databases.return_value = [{"id": 1, "name": "TestDB"}]
            mock_client.get_database_metadata.side_effect = Exception("Connection error")
            mock_client_class.return_value = mock_client

            exporter = MetabaseExporter(config)
            # Should not raise, should continue
            exporter._fetch_and_store_databases()

            assert exporter.manifest.databases == {1: "TestDB"}
            # Metadata may be missing but database should still be recorded

    def test_fetch_databases_unexpected_format(self, sample_export_config, tmp_path):
        """Test handling of unexpected database response format."""
        config = ExportConfig(
            source_url="https://example.com",
            export_dir=str(tmp_path / "export"),
            source_session_token="token",
        )

        with patch("lib.services.export_service.MetabaseClient") as mock_client_class:
            mock_client = Mock()
            mock_client.get_databases.return_value = "unexpected string"
            mock_client_class.return_value = mock_client

            exporter = MetabaseExporter(config)
            exporter._fetch_and_store_databases()

            # Should handle gracefully
            assert exporter.manifest.databases == {}


class TestTraverseCollectionsParentId:
    """Test suite for parent ID extraction in collection traversal."""

    def test_extract_parent_id_from_location(self, tmp_path):
        """Test extracting parent ID from location field."""
        config = ExportConfig(
            source_url="https://example.com",
            export_dir=str(tmp_path / "export"),
            source_session_token="token",
        )

        with patch("lib.services.export_service.MetabaseClient") as mock_client_class:
            mock_client = Mock()
            mock_client.get_collection_items.return_value = {"data": []}
            mock_client_class.return_value = mock_client

            exporter = MetabaseExporter(config)

            collections = [
                {
                    "id": 10,
                    "name": "Child Collection",
                    "location": "/5/7/",  # Parent is 7, grandparent is 5
                    "children": [],
                }
            ]

            exporter._traverse_collections(collections)

            assert len(exporter.manifest.collections) == 1
            assert exporter.manifest.collections[0].parent_id == 7

    def test_extract_parent_id_empty_location(self, tmp_path):
        """Test with empty location field (root collection)."""
        config = ExportConfig(
            source_url="https://example.com",
            export_dir=str(tmp_path / "export"),
            source_session_token="token",
        )

        with patch("lib.services.export_service.MetabaseClient") as mock_client_class:
            mock_client = Mock()
            mock_client.get_collection_items.return_value = {"data": []}
            mock_client_class.return_value = mock_client

            exporter = MetabaseExporter(config)

            collections = [
                {
                    "id": 10,
                    "name": "Root Collection",
                    "location": "/",
                    "children": [],
                }
            ]

            exporter._traverse_collections(collections)

            assert len(exporter.manifest.collections) == 1
            assert exporter.manifest.collections[0].parent_id is None


class TestExportCardEdgeCases:
    """Test suite for export card edge cases."""

    def test_export_card_no_dataset_query(self, tmp_path):
        """Test exporting card without dataset_query."""
        config = ExportConfig(
            source_url="https://example.com",
            export_dir=str(tmp_path / "export"),
            source_session_token="token",
        )

        with patch("lib.services.export_service.MetabaseClient") as mock_client_class:
            mock_client = Mock()
            mock_client.get_card.return_value = {
                "id": 100,
                "name": "Invalid Card",
            }
            mock_client_class.return_value = mock_client

            exporter = MetabaseExporter(config)
            exporter._export_card(100, "test-collection")

            # Card without dataset_query should be skipped
            assert len(exporter.manifest.cards) == 0

    def test_export_card_no_database_id(self, tmp_path):
        """Test exporting card without database ID."""
        config = ExportConfig(
            source_url="https://example.com",
            export_dir=str(tmp_path / "export"),
            source_session_token="token",
        )

        with patch("lib.services.export_service.MetabaseClient") as mock_client_class:
            mock_client = Mock()
            mock_client.get_card.return_value = {
                "id": 100,
                "name": "No DB Card",
                "dataset_query": {"type": "native", "native": {"query": "SELECT 1"}},
            }
            mock_client_class.return_value = mock_client

            exporter = MetabaseExporter(config)
            exporter._export_card(100, "test-collection")

            # Card without database_id should be skipped
            assert len(exporter.manifest.cards) == 0

    def test_export_card_already_exported(self, tmp_path):
        """Test that already exported cards are skipped."""
        config = ExportConfig(
            source_url="https://example.com",
            export_dir=str(tmp_path / "export"),
            source_session_token="token",
        )

        with patch("lib.services.export_service.MetabaseClient") as mock_client_class:
            mock_client = Mock()
            mock_client.get_card.return_value = {
                "id": 100,
                "name": "Test Card",
                "database_id": 1,
                "dataset_query": {"database": 1, "type": "query", "query": {}},
            }
            mock_client_class.return_value = mock_client

            exporter = MetabaseExporter(config)
            exporter._exported_cards.add(100)  # Pre-mark as exported

            exporter._export_card(100, "test-collection")

            # Should not add again
            assert len(exporter.manifest.cards) == 0
            mock_client.get_card.assert_not_called()

    def test_export_card_with_type_model(self, tmp_path):
        """Test exporting card with type='model' (Metabase 0.49+)."""
        config = ExportConfig(
            source_url="https://example.com",
            export_dir=str(tmp_path / "export"),
            source_session_token="token",
        )

        with patch("lib.services.export_service.MetabaseClient") as mock_client_class:
            mock_client = Mock()
            mock_client.get_card.return_value = {
                "id": 100,
                "name": "Model Card",
                "type": "model",
                "database_id": 1,
                "dataset_query": {"database": 1, "type": "query", "query": {}},
            }
            mock_client_class.return_value = mock_client

            exporter = MetabaseExporter(config)
            exporter._export_card(100, "test-collection")

            assert len(exporter.manifest.cards) == 1
            assert exporter.manifest.cards[0].dataset is True
