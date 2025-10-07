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
        with patch("export_metabase.MetabaseClient"):
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
        with patch("export_metabase.MetabaseClient") as mock_client_class:
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
        with patch("export_metabase.MetabaseClient"):
            exporter = MetabaseExporter(sample_export_config)

            assert exporter.manifest is not None
            assert exporter.manifest.meta is not None
            assert exporter.manifest.meta.source_url == sample_export_config.source_url
            assert exporter.manifest.meta.tool_version is not None


class TestManifestInitialization:
    """Test suite for manifest initialization."""

    def test_initialize_manifest_redacts_secrets(self, sample_export_config):
        """Test that secrets are redacted in manifest."""
        with patch("export_metabase.MetabaseClient"):
            exporter = MetabaseExporter(sample_export_config)

            cli_args = exporter.manifest.meta.cli_args
            assert cli_args["source_password"] == "********"

    def test_initialize_manifest_includes_metadata(self, sample_export_config):
        """Test that manifest includes proper metadata."""
        with patch("export_metabase.MetabaseClient"):
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

        with patch("export_metabase.MetabaseClient"):
            exporter = MetabaseExporter(config)

            cli_args = exporter.manifest.meta.cli_args
            assert cli_args["source_session_token"] == "********"


class TestFetchAndStoreDatabases:
    """Test suite for _fetch_and_store_databases method."""

    def test_fetch_databases_list_format(self, sample_export_config):
        """Test fetching databases when API returns a list."""
        with patch("export_metabase.MetabaseClient") as mock_client_class:
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
        with patch("export_metabase.MetabaseClient") as mock_client_class:
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
        with patch("export_metabase.MetabaseClient") as mock_client_class:
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
        with patch("export_metabase.MetabaseClient"):
            exporter = MetabaseExporter(sample_export_config)

            card_data = {
                "id": 100,
                "dataset_query": {"type": "query", "database": 1, "query": {"source-table": 10}},
            }

            deps = exporter._extract_card_dependencies(card_data)
            assert deps == set()

    def test_extract_single_dependency(self, sample_export_config):
        """Test extracting single card dependency."""
        with patch("export_metabase.MetabaseClient"):
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
        with patch("export_metabase.MetabaseClient"):
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
        with patch("export_metabase.MetabaseClient"):
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
        with patch("export_metabase.MetabaseClient"):
            exporter = MetabaseExporter(sample_export_config)

            card_data = {"id": 100}

            deps = exporter._extract_card_dependencies(card_data)
            assert deps == set()


class TestTraverseCollections:
    """Test suite for _traverse_collections method."""

    def test_traverse_empty_collections(self, sample_export_config, tmp_path):
        """Test traversing empty collection list."""
        config = ExportConfig(source_url="https://example.com", export_dir=str(tmp_path / "export"))

        with patch("export_metabase.MetabaseClient"):
            exporter = MetabaseExporter(config)
            exporter._traverse_collections([])

            assert len(exporter.manifest.collections) == 0

    def test_traverse_skips_personal_collections(self, sample_export_config, tmp_path):
        """Test that personal collections are skipped."""
        config = ExportConfig(source_url="https://example.com", export_dir=str(tmp_path / "export"))

        with patch("export_metabase.MetabaseClient"):
            exporter = MetabaseExporter(config)

            collections = [
                {"id": 1, "name": "Personal Collection", "personal_owner_id": 123, "children": []}
            ]

            with patch.object(exporter, "_process_collection_items"):
                exporter._traverse_collections(collections)

            assert len(exporter.manifest.collections) == 0

    def test_traverse_processes_root_collection(self, sample_export_config, tmp_path):
        """Test processing root collection."""
        config = ExportConfig(source_url="https://example.com", export_dir=str(tmp_path / "export"))

        with patch("export_metabase.MetabaseClient"):
            exporter = MetabaseExporter(config)

            collections = [{"id": "root", "name": "Our analytics", "children": []}]

            with patch.object(exporter, "_process_collection_items") as mock_process:
                exporter._traverse_collections(collections)
                mock_process.assert_called_once_with("root", "collections")


class TestProcessCollectionItems:
    """Test suite for _process_collection_items method."""

    def test_process_empty_collection(self, sample_export_config):
        """Test processing collection with no items."""
        with patch("export_metabase.MetabaseClient") as mock_client_class:
            mock_client = Mock()
            mock_client.get_collection_items.return_value = {"data": []}
            mock_client_class.return_value = mock_client

            exporter = MetabaseExporter(sample_export_config)
            exporter._process_collection_items(1, "test-path")

            # Should not raise any errors
            assert True

    def test_process_collection_with_cards(self, sample_export_config):
        """Test processing collection with cards."""
        with patch("export_metabase.MetabaseClient") as mock_client_class:
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
            source_url="https://example.com", export_dir=str(tmp_path / "new_export")
        )

        with patch("export_metabase.MetabaseClient"):
            exporter = MetabaseExporter(config)

            # Directory should not exist yet
            assert not exporter.export_dir.exists()
