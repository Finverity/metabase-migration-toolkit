"""
Unit tests for import_metabase.py

Tests the MetabaseImporter (ImportService) class and import logic.
"""

import json
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from import_metabase import MetabaseImporter
from lib.config import ImportConfig
from lib.models import DatabaseMap, ImportReport, Manifest, ManifestMeta
from lib.remapping import IDMapper, QueryRemapper


class TestMetabaseImporterInit:
    """Test suite for MetabaseImporter initialization."""

    def test_init_with_config(self, sample_import_config):
        """Test MetabaseImporter initialization with config."""
        with patch("lib.services.import_service.MetabaseClient"):
            importer = MetabaseImporter(sample_import_config)

            assert importer.config == sample_import_config
            assert importer.export_dir == Path(sample_import_config.export_dir)
            assert importer.manifest is None
            assert importer.db_map is None
            assert isinstance(importer.report, ImportReport)
            assert importer._collection_map == {}
            assert importer._card_map == {}
            assert importer._target_collections == []

    def test_init_creates_client(self, sample_import_config):
        """Test that initialization creates a MetabaseClient."""
        with patch("lib.services.import_service.MetabaseClient") as mock_client_class:
            MetabaseImporter(sample_import_config)

            mock_client_class.assert_called_once_with(
                base_url=sample_import_config.target_url,
                username=sample_import_config.target_username,
                password=sample_import_config.target_password,
                session_token=sample_import_config.target_session_token,
                personal_token=sample_import_config.target_personal_token,
            )


class TestLoadExportPackage:
    """Test suite for _load_export_package method."""

    def test_load_package_missing_manifest(self, sample_import_config, tmp_path):
        """Test loading package when manifest.json is missing."""
        config = ImportConfig(
            target_url="https://example.com",
            export_dir=str(tmp_path / "nonexistent"),
            db_map_path=str(tmp_path / "db_map.json"),
            target_session_token="token",
        )

        with patch("lib.services.import_service.MetabaseClient"):
            importer = MetabaseImporter(config)

            with pytest.raises(FileNotFoundError, match="manifest.json not found"):
                importer._load_export_package()

    def test_load_package_missing_db_map(self, manifest_file, tmp_path):
        """Test loading package when db_map.json is missing."""
        config = ImportConfig(
            target_url="https://example.com",
            export_dir=str(manifest_file.parent),
            db_map_path=str(tmp_path / "nonexistent_db_map.json"),
            target_session_token="token",
        )

        with patch("lib.services.import_service.MetabaseClient"):
            importer = MetabaseImporter(config)

            with pytest.raises(FileNotFoundError, match="Database mapping file not found"):
                importer._load_export_package()

    def test_load_package_success(self, manifest_file, db_map_file):
        """Test successful package loading."""
        config = ImportConfig(
            target_url="https://example.com",
            export_dir=str(manifest_file.parent),
            db_map_path=str(db_map_file),
            target_session_token="token",
        )

        with patch("lib.services.import_service.MetabaseClient"):
            importer = MetabaseImporter(config)
            importer._load_export_package()

            assert importer.manifest is not None
            assert importer.db_map is not None
            assert isinstance(importer.db_map, DatabaseMap)


class TestResolveDatabaseId:
    """Test suite for IDMapper.resolve_db_id method."""

    def test_resolve_by_id(self, sample_import_config, manifest_file, db_map_file):
        """Test resolving database ID using by_id mapping."""
        config = ImportConfig(
            target_url="https://example.com",
            export_dir=str(manifest_file.parent),
            db_map_path=str(db_map_file),
            target_session_token="token",
        )

        with patch("lib.services.import_service.MetabaseClient"):
            importer = MetabaseImporter(config)
            importer._load_export_package()

            # Source DB ID 1 should map to target DB ID 10
            target_id = importer._id_mapper.resolve_db_id(1)
            assert target_id == 10

    def test_resolve_by_name(self, sample_import_config, manifest_file, db_map_file):
        """Test resolving database ID using by_name mapping."""
        config = ImportConfig(
            target_url="https://example.com",
            export_dir=str(manifest_file.parent),
            db_map_path=str(db_map_file),
            target_session_token="token",
        )

        with patch("lib.services.import_service.MetabaseClient"):
            importer = MetabaseImporter(config)
            importer._load_export_package()

            # Should resolve by name if not in by_id
            target_id = importer._id_mapper.resolve_db_id(2)
            assert target_id == 20

    def test_resolve_unmapped_database(self, sample_import_config, manifest_file, db_map_file):
        """Test resolving unmapped database ID returns None."""
        config = ImportConfig(
            target_url="https://example.com",
            export_dir=str(manifest_file.parent),
            db_map_path=str(db_map_file),
            target_session_token="token",
        )

        with patch("lib.services.import_service.MetabaseClient"):
            importer = MetabaseImporter(config)
            importer._load_export_package()

            # Database ID 999 is not mapped
            target_id = importer._id_mapper.resolve_db_id(999)
            assert target_id is None


class TestValidateDatabaseMappings:
    """Test suite for _validate_database_mappings method."""

    def test_validate_all_mapped(self, manifest_file, db_map_file):
        """Test validation when all databases are mapped."""
        config = ImportConfig(
            target_url="https://example.com",
            export_dir=str(manifest_file.parent),
            db_map_path=str(db_map_file),
            target_session_token="token",
        )

        with patch("lib.services.import_service.MetabaseClient"):
            importer = MetabaseImporter(config)
            importer._load_export_package()

            unmapped = importer._validate_database_mappings()

            # All databases in sample data should be mapped
            assert len(unmapped) == 0

    def test_validate_with_unmapped(self, tmp_path):
        """Test validation when some databases are unmapped."""
        # Create manifest with unmapped database
        manifest_data = {
            "meta": {
                "source_url": "https://example.com",
                "export_timestamp": "2025-10-07T12:00:00",
                "tool_version": "1.0.0",
                "cli_args": {},
            },
            "databases": {"1": "DB1", "999": "Unmapped DB"},
            "collections": [],
            "cards": [
                {
                    "id": 100,
                    "name": "Test Card",
                    "collection_id": 1,
                    "database_id": 999,
                    "archived": False,
                    "file_path": "test.json",
                }
            ],
            "dashboards": [],
        }

        manifest_path = tmp_path / "manifest.json"
        with open(manifest_path, "w") as f:
            json.dump(manifest_data, f)

        # Create db_map with only DB1 mapped
        db_map_data = {"by_id": {"1": 10}, "by_name": {"DB1": 10}}

        db_map_path = tmp_path / "db_map.json"
        with open(db_map_path, "w") as f:
            json.dump(db_map_data, f)

        config = ImportConfig(
            target_url="https://example.com",
            export_dir=str(tmp_path),
            db_map_path=str(db_map_path),
            target_session_token="token",
        )

        with patch("lib.services.import_service.MetabaseClient"):
            importer = MetabaseImporter(config)
            importer._load_export_package()

            unmapped = importer._validate_database_mappings()

            assert len(unmapped) == 1
            assert unmapped[0].source_db_id == 999
            assert unmapped[0].source_db_name == "Unmapped DB"
            assert 100 in unmapped[0].card_ids


class TestValidateTargetDatabases:
    """Test suite for _validate_target_databases method."""

    def test_validate_all_exist(self, manifest_file, db_map_file):
        """Test validation when all mapped databases exist in target."""
        config = ImportConfig(
            target_url="https://example.com",
            export_dir=str(manifest_file.parent),
            db_map_path=str(db_map_file),
            target_session_token="token",
        )

        with patch("lib.services.import_service.MetabaseClient") as mock_client_class:
            mock_client = Mock()
            mock_client.get_databases.return_value = [
                {"id": 10, "name": "Target DB 1"},
                {"id": 20, "name": "Target DB 2"},
                {"id": 30, "name": "Target DB 3"},
            ]
            mock_client_class.return_value = mock_client

            importer = MetabaseImporter(config)
            importer._load_export_package()

            # Should not raise an error
            importer._validate_target_databases()

    def test_validate_missing_databases(self, manifest_file, db_map_file):
        """Test validation when mapped databases don't exist in target."""
        config = ImportConfig(
            target_url="https://example.com",
            export_dir=str(manifest_file.parent),
            db_map_path=str(db_map_file),
            target_session_token="token",
        )

        with patch("lib.services.import_service.MetabaseClient") as mock_client_class:
            mock_client = Mock()
            # Target only has DB 10, but mapping references 10, 20, 30
            mock_client.get_databases.return_value = [{"id": 10, "name": "Target DB 1"}]
            mock_client_class.return_value = mock_client

            importer = MetabaseImporter(config)
            importer._load_export_package()

            # Should raise ValueError for missing database mappings
            with pytest.raises(ValueError, match="Invalid database mapping"):
                importer._validate_target_databases()


class TestConflictStrategies:
    """Test suite for different conflict resolution strategies."""

    def test_skip_strategy(self):
        """Test skip conflict strategy."""
        config = ImportConfig(
            target_url="https://example.com",
            export_dir="./export",
            db_map_path="./db_map.json",
            conflict_strategy="skip",
            target_session_token="token",
        )

        assert config.conflict_strategy == "skip"

    def test_overwrite_strategy(self):
        """Test overwrite conflict strategy."""
        config = ImportConfig(
            target_url="https://example.com",
            export_dir="./export",
            db_map_path="./db_map.json",
            conflict_strategy="overwrite",
            target_session_token="token",
        )

        assert config.conflict_strategy == "overwrite"

    def test_rename_strategy(self):
        """Test rename conflict strategy."""
        config = ImportConfig(
            target_url="https://example.com",
            export_dir="./export",
            db_map_path="./db_map.json",
            conflict_strategy="rename",
            target_session_token="token",
        )

        assert config.conflict_strategy == "rename"


class TestDryRun:
    """Test suite for dry-run mode."""

    def test_dry_run_enabled(self):
        """Test that dry_run flag is respected."""
        config = ImportConfig(
            target_url="https://example.com",
            export_dir="./export",
            db_map_path="./db_map.json",
            dry_run=True,
            target_session_token="token",
        )

        assert config.dry_run is True

    def test_dry_run_disabled(self):
        """Test that dry_run defaults to False."""
        config = ImportConfig(
            target_url="https://example.com",
            export_dir="./export",
            db_map_path="./db_map.json",
            target_session_token="token",
        )

        assert config.dry_run is False


class TestImportReport:
    """Test suite for import report generation."""

    def test_report_initialization(self, sample_import_config):
        """Test that import report is initialized."""
        with patch("lib.services.import_service.MetabaseClient"):
            importer = MetabaseImporter(sample_import_config)

            assert isinstance(importer.report, ImportReport)
            assert importer.report.items == []


class TestCollectionMapping:
    """Test suite for collection ID mapping."""

    def test_collection_map_empty_initially(self, sample_import_config):
        """Test that collection map is empty initially."""
        with patch("lib.services.import_service.MetabaseClient"):
            importer = MetabaseImporter(sample_import_config)

            assert importer._collection_map == {}

    def test_card_map_empty_initially(self, sample_import_config):
        """Test that card map is empty initially."""
        with patch("lib.services.import_service.MetabaseClient"):
            importer = MetabaseImporter(sample_import_config)

            assert importer._card_map == {}


class TestImportConfiguration:
    """Test suite for import configuration validation."""

    def test_config_requires_target_url(self):
        """Test that target_url is required."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            ImportConfig(
                export_dir="./export", db_map_path="./db_map.json", target_session_token="token"
            )

    def test_config_requires_export_dir(self):
        """Test that export_dir is required."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            ImportConfig(
                target_url="https://example.com",
                db_map_path="./db_map.json",
                target_session_token="token",
            )

    def test_config_requires_db_map_path(self):
        """Test that db_map_path is required."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            ImportConfig(
                target_url="https://example.com",
                export_dir="./export",
                target_session_token="token",
            )


class TestRemapCardQuery:
    """Test suite for QueryRemapper methods."""

    @pytest.fixture
    def id_mapper(self) -> IDMapper:
        """Create an IDMapper with test data."""
        manifest = Manifest(
            meta=ManifestMeta(
                source_url="https://source.example.com",
                export_timestamp="2025-01-01T00:00:00",
                tool_version="1.0.0",
                cli_args={},
            ),
            databases={1: "DB1", 3: "DB3"},
        )
        db_map = DatabaseMap(by_id={"1": 10, "3": 4})
        return IDMapper(manifest, db_map)

    def test_remap_card_query_always_sets_database_field(self, id_mapper):
        """Test that database field is always set in dataset_query."""
        query_remapper = QueryRemapper(id_mapper)

        card_data = {
            "id": 100,
            "name": "Test Card",
            "database_id": 1,
            "dataset_query": {
                "type": "query",
                "query": {"source-table": "card__50"},
            },
        }

        remapped_data, success = query_remapper.remap_card_data(card_data)

        assert success is True
        assert remapped_data["database_id"] == 10
        assert remapped_data["dataset_query"]["database"] == 10

    def test_remap_card_query_with_existing_database_field(self, id_mapper):
        """Test that existing database field in dataset_query is properly remapped."""
        query_remapper = QueryRemapper(id_mapper)

        card_data = {
            "id": 100,
            "name": "Test Card",
            "database_id": 1,
            "dataset_query": {
                "type": "query",
                "database": 1,
                "query": {"source-table": "card__50"},
            },
        }

        remapped_data, success = query_remapper.remap_card_data(card_data)

        assert success is True
        assert remapped_data["database_id"] == 10
        assert remapped_data["dataset_query"]["database"] == 10

    def test_remap_card_query_without_database_id(self, id_mapper):
        """Test that cards without database_id return False."""
        query_remapper = QueryRemapper(id_mapper)

        card_data = {
            "id": 100,
            "name": "Test Card",
            "dataset_query": {"type": "query", "query": {}},
        }

        remapped_data, success = query_remapper.remap_card_data(card_data)
        assert success is False

    def test_remap_card_query_with_table_id(self, id_mapper):
        """Test that table_id is remapped correctly."""
        # Set up table mapping
        id_mapper._table_map[(1, 27)] = 42

        query_remapper = QueryRemapper(id_mapper)

        card_data = {
            "id": 100,
            "name": "Test Card",
            "database_id": 1,
            "table_id": 27,
            "dataset_query": {
                "type": "query",
                "database": 1,
                "query": {"source-table": 27},
            },
        }

        remapped_data, success = query_remapper.remap_card_data(card_data)

        assert success is True
        assert remapped_data["table_id"] == 42
        assert remapped_data["dataset_query"]["query"]["source-table"] == 42

    def test_remap_field_ids_in_filter(self, id_mapper):
        """Test that field IDs in filters are remapped correctly."""
        id_mapper._field_map[(1, 201)] = 301
        id_mapper._field_map[(1, 204)] = 304

        query_remapper = QueryRemapper(id_mapper)

        filter_expr = [
            "and",
            ["=", ["field", 201, {"base-type": "type/PostgresEnum"}], "CUSTOMER"],
            ["=", ["field", 204, {"base-type": "type/PostgresEnum"}], "ACTIVE"],
        ]

        remapped_filter = query_remapper.remap_field_ids_recursively(filter_expr, 1)

        assert remapped_filter[1][1][1] == 301
        assert remapped_filter[2][1][1] == 304

    def test_remap_field_ids_in_aggregation(self, id_mapper):
        """Test that field IDs in aggregations are remapped correctly."""
        id_mapper._field_map[(1, 5)] = 105

        query_remapper = QueryRemapper(id_mapper)

        aggregation = [["sum", ["field", 5, None]]]
        remapped_agg = query_remapper.remap_field_ids_recursively(aggregation, 1)

        assert remapped_agg[0][1][1] == 105

    def test_remap_field_ids_in_breakout(self, id_mapper):
        """Test that field IDs in breakouts are remapped correctly."""
        id_mapper._field_map[(1, 3)] = 103

        query_remapper = QueryRemapper(id_mapper)

        breakout = [["field", 3, {"temporal-unit": "month"}]]
        remapped_breakout = query_remapper.remap_field_ids_recursively(breakout, 1)

        assert remapped_breakout[0][1] == 103

    def test_remap_field_ids_in_dashboard_parameter_target(self, id_mapper):
        """Test that field IDs in dashboard parameter targets are remapped correctly."""
        id_mapper._field_map[(1, 10)] = 110

        query_remapper = QueryRemapper(id_mapper)

        target = ["dimension", ["field", 10, None]]
        remapped_target = query_remapper.remap_field_ids_recursively(target, 1)

        assert remapped_target[1][1] == 110

    def test_remap_field_ids_in_dashboard_parameter_value_field(self, id_mapper):
        """Test that field IDs in dashboard parameter value_field use the correct database ID."""
        id_mapper._field_map[(3, 218)] = 318

        query_remapper = QueryRemapper(id_mapper)

        value_field = ["field", 218, {"base-type": "type/Text"}]
        remapped_value_field = query_remapper.remap_field_ids_recursively(value_field, 3)

        assert remapped_value_field[1] == 318

    def test_remap_result_metadata(self, id_mapper):
        """Test that field IDs and table IDs in result_metadata are remapped correctly."""
        id_mapper._table_map[(3, 27)] = 42
        id_mapper._field_map[(3, 218)] = 318
        id_mapper._field_map[(3, 210)] = 310

        query_remapper = QueryRemapper(id_mapper)

        card_data = {
            "id": 332,
            "name": "List of Customers",
            "database_id": 3,
            "table_id": 27,
            "dataset_query": {
                "type": "query",
                "database": 3,
                "query": {"source-table": 27},
            },
            "result_metadata": [
                {
                    "id": 210,
                    "name": "id",
                    "table_id": 27,
                    "field_ref": ["field", 210, {"base-type": "type/UUID"}],
                },
                {
                    "id": 218,
                    "name": "name",
                    "table_id": 27,
                    "field_ref": ["field", 218, {"base-type": "type/Text"}],
                },
            ],
        }

        remapped_data, success = query_remapper.remap_card_data(card_data)

        assert success is True
        assert remapped_data["database_id"] == 4
        assert remapped_data["table_id"] == 42
        assert remapped_data["result_metadata"][0]["id"] == 310
        assert remapped_data["result_metadata"][0]["table_id"] == 42
        assert remapped_data["result_metadata"][0]["field_ref"][1] == 310
        assert remapped_data["result_metadata"][1]["id"] == 318
        assert remapped_data["result_metadata"][1]["table_id"] == 42
        assert remapped_data["result_metadata"][1]["field_ref"][1] == 318


class TestBuildTableAndFieldMappings:
    """Test suite for _build_table_and_field_mappings method."""

    def test_build_mappings_with_metadata(self, tmp_path):
        """Test building table and field mappings from manifest metadata."""
        # Create manifest with database metadata
        manifest_data = {
            "meta": {
                "source_url": "http://source.com",
                "export_timestamp": "2025-10-22T00:00:00Z",
                "tool_version": "1.0.0",
                "cli_args": {},
            },
            "databases": {"3": "company_service"},
            "database_metadata": {
                "3": {
                    "tables": [
                        {
                            "id": 27,
                            "name": "companies",
                            "fields": [
                                {"id": 201, "name": "company_type"},
                                {"id": 204, "name": "kyc_status"},
                            ],
                        }
                    ]
                }
            },
            "collections": [],
            "cards": [],
            "dashboards": [],
        }

        manifest_path = tmp_path / "manifest.json"
        with open(manifest_path, "w") as f:
            json.dump(manifest_data, f)

        db_map_data = {"by_id": {"3": 4}, "by_name": {"company_service": 4}}
        db_map_path = tmp_path / "db_map.json"
        with open(db_map_path, "w") as f:
            json.dump(db_map_data, f)

        config = ImportConfig(
            target_url="https://example.com",
            export_dir=str(tmp_path),
            db_map_path=str(db_map_path),
            target_session_token="token",
        )

        with patch("lib.services.import_service.MetabaseClient") as mock_client_class:
            mock_client = Mock()
            # Mock target database metadata
            mock_client.get_database_metadata.return_value = {
                "tables": [
                    {
                        "id": 42,
                        "name": "companies",
                        "fields": [
                            {"id": 301, "name": "company_type"},
                            {"id": 304, "name": "kyc_status"},
                        ],
                    }
                ]
            }
            mock_client_class.return_value = mock_client

            importer = MetabaseImporter(config)
            importer._load_export_package()
            importer._id_mapper.build_table_and_field_mappings()

            # Check table mapping
            assert (3, 27) in importer._id_mapper._table_map
            assert importer._id_mapper._table_map[(3, 27)] == 42

            # Check field mappings
            assert (3, 201) in importer._id_mapper._field_map
            assert importer._id_mapper._field_map[(3, 201)] == 301
            assert (3, 204) in importer._id_mapper._field_map
            assert importer._id_mapper._field_map[(3, 204)] == 304


class TestConflictResolution:
    """Test suite for conflict resolution strategies."""

    @pytest.fixture
    def mock_context(self, sample_import_config, manifest_file, db_map_file):
        """Create a mock ImportContext for handler testing."""
        from pathlib import Path

        from lib.handlers.base import ImportContext
        from lib.models import DatabaseMap, ImportReport, Manifest, ManifestMeta
        from lib.remapping import IDMapper, QueryRemapper

        manifest = Manifest(
            meta=ManifestMeta(
                source_url="https://source.example.com",
                export_timestamp="2025-01-01T00:00:00Z",
                tool_version="1.0.0",
                cli_args={},
            ),
            databases={1: "Test DB"},
        )
        db_map = DatabaseMap(by_id={"1": 2}, by_name={})
        mock_client = Mock()
        id_mapper = IDMapper(manifest, db_map)
        query_remapper = QueryRemapper(id_mapper)

        return ImportContext(
            config=sample_import_config,
            client=mock_client,
            manifest=manifest,
            export_dir=Path(sample_import_config.export_dir),
            id_mapper=id_mapper,
            query_remapper=query_remapper,
            report=ImportReport(),
            target_collections=[],
        )

    def test_find_existing_card_in_collection(self, mock_context):
        """Test finding an existing card by name in a collection."""
        # Mock the get_collection_items response
        mock_context.client.get_collection_items.return_value = {
            "data": [
                {"id": 1, "name": "Existing Card", "model": "card"},
                {"id": 2, "name": "Another Card", "model": "card"},
                {"id": 3, "name": "Some Dashboard", "model": "dashboard"},
            ]
        }

        # Test finding existing card (method is on context, not handler)
        result = mock_context.find_existing_card("Existing Card", 10)
        assert result is not None
        assert result["id"] == 1
        assert result["name"] == "Existing Card"

        # Test card not found
        result = mock_context.find_existing_card("Non-existent Card", 10)
        assert result is None

        # Verify correct API call
        mock_context.client.get_collection_items.assert_called_with(10)

    def test_find_existing_dashboard_in_collection(self, mock_context):
        """Test finding an existing dashboard by name in a collection."""
        # Mock the get_collection_items response
        mock_context.client.get_collection_items.return_value = {
            "data": [
                {"id": 1, "name": "Existing Dashboard", "model": "dashboard"},
                {"id": 2, "name": "Another Dashboard", "model": "dashboard"},
                {"id": 3, "name": "Some Card", "model": "card"},
            ]
        }

        # Test finding existing dashboard (method is on context, not handler)
        result = mock_context.find_existing_dashboard("Existing Dashboard", 10)
        assert result is not None
        assert result["id"] == 1
        assert result["name"] == "Existing Dashboard"

        # Test dashboard not found
        result = mock_context.find_existing_dashboard("Non-existent Dashboard", 10)
        assert result is None

    def test_generate_unique_name_for_card(self, mock_context):
        """Test generating unique names for cards."""
        from lib.handlers.card import CardHandler

        # Mock responses: first call finds "Test Card (1)", second finds nothing
        mock_context.client.get_collection_items.side_effect = [
            {"data": [{"id": 2, "name": "Test Card (1)", "model": "card"}]},
            {"data": []},
        ]

        handler = CardHandler(mock_context)

        # Should return "Test Card (2)" since "Test Card (1)" exists
        unique_name = handler._generate_unique_card_name("Test Card", 10)
        assert unique_name == "Test Card (2)"

    def test_generate_unique_name_no_conflict(self, mock_context):
        """Test generating unique name when there's no conflict."""
        from lib.handlers.card import CardHandler

        # Mock response: no existing items with "(1)" suffix
        mock_context.client.get_collection_items.return_value = {"data": []}

        handler = CardHandler(mock_context)

        # Should return "New Card (1)" since _generate_unique_card_name always adds suffix
        unique_name = handler._generate_unique_card_name("New Card", 10)
        assert unique_name == "New Card (1)"

    def test_collection_conflict_skip_strategy(
        self, sample_import_config, manifest_file, db_map_file
    ):
        """Test collection import with skip conflict strategy."""
        from lib.handlers.base import ImportContext

        config = ImportConfig(
            target_url="https://example.com",
            export_dir=str(manifest_file.parent),
            db_map_path=str(db_map_file),
            conflict_strategy="skip",
            target_session_token="token",
        )

        with patch("lib.services.import_service.MetabaseClient") as mock_client_class:
            mock_client = Mock()
            mock_client_class.return_value = mock_client

            # Mock existing collection
            existing_collections = [{"id": 100, "name": "Test Collection", "parent_id": None}]
            mock_client.get_collections_tree.return_value = existing_collections

            importer = MetabaseImporter(config)
            importer._load_export_package()

            # Initialize the context (normally done in _perform_import)
            importer._context = ImportContext(
                config=importer.config,
                client=importer.client,
                manifest=importer.manifest,
                export_dir=importer.export_dir,
                id_mapper=importer._id_mapper,
                query_remapper=importer._query_remapper,
                report=importer.report,
                target_collections=existing_collections,
            )
            importer._import_collections()

            # Should skip and map to existing collection
            assert importer._id_mapper.resolve_collection_id(1) == 100
            assert importer.report.summary["collections"]["skipped"] == 1
            assert importer.report.summary["collections"]["created"] == 0

            # Should not call create_collection
            mock_client.create_collection.assert_not_called()

    def test_collection_conflict_overwrite_strategy(
        self, sample_import_config, manifest_file, db_map_file
    ):
        """Test collection import with overwrite conflict strategy."""
        from lib.handlers.base import ImportContext

        config = ImportConfig(
            target_url="https://example.com",
            export_dir=str(manifest_file.parent),
            db_map_path=str(db_map_file),
            conflict_strategy="overwrite",
            target_session_token="token",
        )

        with patch("lib.services.import_service.MetabaseClient") as mock_client_class:
            mock_client = Mock()
            mock_client_class.return_value = mock_client

            # Mock existing collection
            existing_collections = [{"id": 100, "name": "Test Collection", "parent_id": None}]
            mock_client.get_collections_tree.return_value = existing_collections
            mock_client.update_collection.return_value = {"id": 100, "name": "Test Collection"}

            importer = MetabaseImporter(config)
            importer._load_export_package()

            # Initialize the context (normally done in _perform_import)
            importer._context = ImportContext(
                config=importer.config,
                client=importer.client,
                manifest=importer.manifest,
                export_dir=importer.export_dir,
                id_mapper=importer._id_mapper,
                query_remapper=importer._query_remapper,
                report=importer.report,
                target_collections=existing_collections,
            )
            importer._import_collections()

            # Should update existing collection
            assert importer._id_mapper.resolve_collection_id(1) == 100
            assert importer.report.summary["collections"]["updated"] == 1
            assert importer.report.summary["collections"]["created"] == 0

            # Should call update_collection
            mock_client.update_collection.assert_called_once()
            mock_client.create_collection.assert_not_called()

    def test_collection_conflict_rename_strategy(
        self, sample_import_config, manifest_file, db_map_file
    ):
        """Test collection import with rename conflict strategy."""
        from lib.handlers.base import ImportContext

        config = ImportConfig(
            target_url="https://example.com",
            export_dir=str(manifest_file.parent),
            db_map_path=str(db_map_file),
            conflict_strategy="rename",
            target_session_token="token",
        )

        with patch("lib.services.import_service.MetabaseClient") as mock_client_class:
            mock_client = Mock()
            mock_client_class.return_value = mock_client

            # Mock existing collection with same name
            existing_collections = [{"id": 100, "name": "Test Collection", "parent_id": None}]

            # First call: initial fetch for _target_collections
            # Second call: check for "Test Collection (1)" (doesn't exist)
            mock_client.get_collections_tree.side_effect = [
                existing_collections,
                existing_collections,  # Still only has original collection
            ]
            mock_client.create_collection.return_value = {"id": 101, "name": "Test Collection (1)"}

            importer = MetabaseImporter(config)
            importer._load_export_package()

            # Initialize the context (normally done in _perform_import)
            importer._context = ImportContext(
                config=importer.config,
                client=importer.client,
                manifest=importer.manifest,
                export_dir=importer.export_dir,
                id_mapper=importer._id_mapper,
                query_remapper=importer._query_remapper,
                report=importer.report,
                target_collections=existing_collections,
            )
            importer._import_collections()

            # Should create with renamed collection
            assert importer.report.summary["collections"]["created"] == 1
            assert importer.report.summary["collections"]["skipped"] == 0

            # Should call create_collection with renamed name
            mock_client.create_collection.assert_called_once()
            call_args = mock_client.create_collection.call_args[0][0]
            assert call_args["name"] == "Test Collection (1)"


class TestModelImport:
    """Test suite for importing Metabase models (cards with dataset=True)."""

    def test_import_model_preserves_dataset_field(self, sample_import_config, tmp_path):
        """Test that importing a model preserves the dataset=True field."""
        import dataclasses

        from lib.models import Card, Manifest, ManifestMeta
        from tests.fixtures.sample_responses import SAMPLE_MODEL

        # Setup export directory with model data
        export_dir = tmp_path / "export"
        export_dir.mkdir()
        cards_dir = export_dir / "cards"
        cards_dir.mkdir()

        # Write model JSON file
        model_file = cards_dir / "card_102_customer-base-model.json"
        with open(model_file, "w") as f:
            json.dump(SAMPLE_MODEL, f)

        # Create manifest with model
        manifest = Manifest(
            meta=ManifestMeta(
                source_url="https://source.example.com",
                export_timestamp="2025-01-01T00:00:00Z",
                tool_version="1.0.0",
                cli_args={},
            ),
            cards=[
                Card(
                    id=102,
                    name="Customer Base Model",
                    collection_id=None,
                    database_id=2,
                    file_path="cards/card_102_customer-base-model.json",
                    checksum="abc123",
                    dataset=True,  # Model flag
                )
            ],
        )

        # Write manifest
        manifest_file = export_dir / "manifest.json"
        with open(manifest_file, "w") as f:
            json.dump(dataclasses.asdict(manifest), f)

        # Create db_map file
        db_map_data = {"by_id": {"2": 3}, "by_name": {}}
        db_map_file = export_dir / "db_map.json"
        with open(db_map_file, "w") as f:
            json.dump(db_map_data, f)

        # Setup import config
        config = ImportConfig(
            target_url="https://target.example.com",
            export_dir=str(export_dir),
            db_map_path=str(db_map_file),
            target_session_token="token",
        )

        with patch("lib.services.import_service.MetabaseClient") as mock_client_class:
            from lib.handlers.base import ImportContext

            mock_client = Mock()
            mock_client.get_databases.return_value = [{"id": 3, "name": "Target DB"}]
            mock_client.get_collections_tree.return_value = []
            mock_client.get_collection_items.return_value = {"data": []}
            mock_client.create_card.return_value = {"id": 202, "name": "Customer Base Model"}
            mock_client_class.return_value = mock_client

            importer = MetabaseImporter(config)
            importer._load_export_package()

            # Initialize the context (normally done in _perform_import)
            importer._context = ImportContext(
                config=importer.config,
                client=importer.client,
                manifest=importer.manifest,
                export_dir=importer.export_dir,
                id_mapper=importer._id_mapper,
                query_remapper=importer._query_remapper,
                report=importer.report,
                target_collections=[],
            )
            importer._import_cards()

            # Verify create_card was called with dataset=True
            mock_client.create_card.assert_called_once()
            call_args = mock_client.create_card.call_args[0][0]
            assert call_args["dataset"] is True
            assert call_args["name"] == "Customer Base Model"

    def test_import_question_without_dataset_field(self, sample_import_config, tmp_path):
        """Test that importing a regular question works correctly."""
        import dataclasses

        from lib.models import Card, Manifest, ManifestMeta
        from tests.fixtures.sample_responses import SAMPLE_CARD

        # Setup export directory with card data
        export_dir = tmp_path / "export"
        export_dir.mkdir()
        cards_dir = export_dir / "cards"
        cards_dir.mkdir()

        # Write card JSON file
        card_file = cards_dir / "card_100_monthly-revenue.json"
        with open(card_file, "w") as f:
            json.dump(SAMPLE_CARD, f)

        # Create manifest with card (no dataset field)
        manifest = Manifest(
            meta=ManifestMeta(
                source_url="https://source.example.com",
                export_timestamp="2025-01-01T00:00:00Z",
                tool_version="1.0.0",
                cli_args={},
            ),
            cards=[
                Card(
                    id=100,
                    name="Monthly Revenue",
                    collection_id=None,
                    database_id=2,
                    file_path="cards/card_100_monthly-revenue.json",
                    checksum="def456",
                    dataset=False,  # Regular question
                )
            ],
        )

        # Write manifest
        manifest_file = export_dir / "manifest.json"
        with open(manifest_file, "w") as f:
            json.dump(dataclasses.asdict(manifest), f)

        # Create db_map file
        db_map_data = {"by_id": {"2": 3}, "by_name": {}}
        db_map_file = export_dir / "db_map.json"
        with open(db_map_file, "w") as f:
            json.dump(db_map_data, f)

        # Setup import config
        config = ImportConfig(
            target_url="https://target.example.com",
            export_dir=str(export_dir),
            db_map_path=str(db_map_file),
            target_session_token="token",
        )

        with patch("lib.services.import_service.MetabaseClient") as mock_client_class:
            from lib.handlers.base import ImportContext

            mock_client = Mock()
            mock_client.get_databases.return_value = [{"id": 3, "name": "Target DB"}]
            mock_client.get_collections_tree.return_value = []
            mock_client.get_collection_items.return_value = {"data": []}
            mock_client.create_card.return_value = {"id": 200, "name": "Monthly Revenue"}
            mock_client_class.return_value = mock_client

            importer = MetabaseImporter(config)
            importer._load_export_package()

            # Initialize the context (normally done in _perform_import)
            importer._context = ImportContext(
                config=importer.config,
                client=importer.client,
                manifest=importer.manifest,
                export_dir=importer.export_dir,
                id_mapper=importer._id_mapper,
                query_remapper=importer._query_remapper,
                report=importer.report,
                target_collections=[],
            )
            importer._import_cards()

            # Verify create_card was called without dataset field (or dataset=False)
            mock_client.create_card.assert_called_once()
            call_args = mock_client.create_card.call_args[0][0]
            # dataset field should either not be present or be False
            assert call_args.get("dataset", False) is False
            assert call_args["name"] == "Monthly Revenue"


class TestRunImport:
    """Test suite for run_import method."""

    def test_run_import_dry_run(self, tmp_path):
        """Test run_import with dry_run mode."""
        # Create manifest
        manifest_data = {
            "meta": {
                "source_url": "https://example.com",
                "export_timestamp": "2025-10-07T12:00:00",
                "tool_version": "1.0.0",
                "cli_args": {},
            },
            "databases": {"1": "DB1"},
            "collections": [
                {
                    "id": 1,
                    "name": "Test Collection",
                    "path": "collections/test",
                    "slug": "test-collection",
                }
            ],
            "cards": [],
            "dashboards": [],
        }
        manifest_path = tmp_path / "manifest.json"
        with open(manifest_path, "w") as f:
            json.dump(manifest_data, f)

        db_map_data = {"by_id": {"1": 10}, "by_name": {"DB1": 10}}
        db_map_path = tmp_path / "db_map.json"
        with open(db_map_path, "w") as f:
            json.dump(db_map_data, f)

        config = ImportConfig(
            target_url="https://example.com",
            export_dir=str(tmp_path),
            db_map_path=str(db_map_path),
            target_session_token="token",
            dry_run=True,
        )

        with patch("lib.services.import_service.MetabaseClient"):
            importer = MetabaseImporter(config)
            importer.run_import()

            # Dry run should complete without making API calls
            assert importer.manifest is not None

    def test_run_import_file_not_found(self, tmp_path):
        """Test run_import raises FileNotFoundError for missing manifest."""
        config = ImportConfig(
            target_url="https://example.com",
            export_dir=str(tmp_path / "nonexistent"),
            db_map_path=str(tmp_path / "db_map.json"),
            target_session_token="token",
        )

        with patch("lib.services.import_service.MetabaseClient"):
            importer = MetabaseImporter(config)
            with pytest.raises(FileNotFoundError):
                importer.run_import()

    def test_run_import_api_error(self, tmp_path):
        """Test run_import handles MetabaseAPIError."""
        from lib.client import MetabaseAPIError

        # Create manifest
        manifest_data = {
            "meta": {
                "source_url": "https://example.com",
                "export_timestamp": "2025-10-07T12:00:00",
                "tool_version": "1.0.0",
                "cli_args": {},
            },
            "databases": {"1": "DB1"},
            "collections": [],
            "cards": [],
            "dashboards": [],
        }
        manifest_path = tmp_path / "manifest.json"
        with open(manifest_path, "w") as f:
            json.dump(manifest_data, f)

        db_map_data = {"by_id": {"1": 10}, "by_name": {"DB1": 10}}
        db_map_path = tmp_path / "db_map.json"
        with open(db_map_path, "w") as f:
            json.dump(db_map_data, f)

        config = ImportConfig(
            target_url="https://example.com",
            export_dir=str(tmp_path),
            db_map_path=str(db_map_path),
            target_session_token="token",
        )

        with patch("lib.services.import_service.MetabaseClient") as mock_client_class:
            mock_client = Mock()
            mock_client.get_databases.side_effect = MetabaseAPIError("API Error", status_code=500)
            mock_client_class.return_value = mock_client

            importer = MetabaseImporter(config)
            with pytest.raises(MetabaseAPIError):
                importer.run_import()


class TestGettersWithErrors:
    """Test suite for getter methods when not initialized."""

    def test_get_manifest_not_loaded(self, tmp_path):
        """Test _get_manifest raises RuntimeError when not loaded."""
        config = ImportConfig(
            target_url="https://example.com",
            export_dir=str(tmp_path),
            db_map_path=str(tmp_path / "db_map.json"),
            target_session_token="token",
        )

        with patch("lib.services.import_service.MetabaseClient"):
            importer = MetabaseImporter(config)
            with pytest.raises(RuntimeError, match="Manifest not loaded"):
                importer._get_manifest()

    def test_get_id_mapper_not_initialized(self, tmp_path):
        """Test _get_id_mapper raises RuntimeError when not initialized."""
        config = ImportConfig(
            target_url="https://example.com",
            export_dir=str(tmp_path),
            db_map_path=str(tmp_path / "db_map.json"),
            target_session_token="token",
        )

        with patch("lib.services.import_service.MetabaseClient"):
            importer = MetabaseImporter(config)
            with pytest.raises(RuntimeError, match="ID mapper not initialized"):
                importer._get_id_mapper()

    def test_get_context_not_initialized(self, tmp_path):
        """Test _get_context raises RuntimeError when not initialized."""
        config = ImportConfig(
            target_url="https://example.com",
            export_dir=str(tmp_path),
            db_map_path=str(tmp_path / "db_map.json"),
            target_session_token="token",
        )

        with patch("lib.services.import_service.MetabaseClient"):
            importer = MetabaseImporter(config)
            with pytest.raises(RuntimeError, match="Import context not initialized"):
                importer._get_context()


class TestValidateMetabaseVersion:
    """Test suite for _validate_metabase_version method."""

    def test_validate_version_missing_in_manifest(self, tmp_path):
        """Test validation when manifest has no metabase_version."""
        manifest_data = {
            "meta": {
                "source_url": "https://example.com",
                "export_timestamp": "2025-10-07T12:00:00",
                "tool_version": "1.0.0",
                "cli_args": {},
            },
            "databases": {"1": "DB1"},
            "collections": [],
            "cards": [],
            "dashboards": [],
        }
        manifest_path = tmp_path / "manifest.json"
        with open(manifest_path, "w") as f:
            json.dump(manifest_data, f)

        db_map_data = {"by_id": {"1": 10}, "by_name": {"DB1": 10}}
        db_map_path = tmp_path / "db_map.json"
        with open(db_map_path, "w") as f:
            json.dump(db_map_data, f)

        config = ImportConfig(
            target_url="https://example.com",
            export_dir=str(tmp_path),
            db_map_path=str(db_map_path),
            target_session_token="token",
        )

        with patch("lib.services.import_service.MetabaseClient"):
            importer = MetabaseImporter(config)
            importer._load_export_package()
            # Should not raise - backward compatible
            importer._validate_metabase_version()

    def test_validate_version_unsupported(self, tmp_path):
        """Test validation with unsupported version raises ValueError."""
        manifest_data = {
            "meta": {
                "source_url": "https://example.com",
                "export_timestamp": "2025-10-07T12:00:00",
                "tool_version": "1.0.0",
                "cli_args": {},
                "metabase_version": "v99",  # Unsupported version
            },
            "databases": {"1": "DB1"},
            "collections": [],
            "cards": [],
            "dashboards": [],
        }
        manifest_path = tmp_path / "manifest.json"
        with open(manifest_path, "w") as f:
            json.dump(manifest_data, f)

        db_map_data = {"by_id": {"1": 10}, "by_name": {"DB1": 10}}
        db_map_path = tmp_path / "db_map.json"
        with open(db_map_path, "w") as f:
            json.dump(db_map_data, f)

        config = ImportConfig(
            target_url="https://example.com",
            export_dir=str(tmp_path),
            db_map_path=str(db_map_path),
            target_session_token="token",
        )

        with patch("lib.services.import_service.MetabaseClient"):
            importer = MetabaseImporter(config)
            with pytest.raises(ValueError, match="unsupported Metabase version"):
                importer._load_export_package()

    def test_validate_version_compatible(self, tmp_path):
        """Test validation with compatible versions."""
        manifest_data = {
            "meta": {
                "source_url": "https://example.com",
                "export_timestamp": "2025-10-07T12:00:00",
                "tool_version": "1.0.0",
                "cli_args": {},
                "metabase_version": "v56",
            },
            "databases": {"1": "DB1"},
            "collections": [],
            "cards": [],
            "dashboards": [],
        }
        manifest_path = tmp_path / "manifest.json"
        with open(manifest_path, "w") as f:
            json.dump(manifest_data, f)

        db_map_data = {"by_id": {"1": 10}, "by_name": {"DB1": 10}}
        db_map_path = tmp_path / "db_map.json"
        with open(db_map_path, "w") as f:
            json.dump(db_map_data, f)

        config = ImportConfig(
            target_url="https://example.com",
            export_dir=str(tmp_path),
            db_map_path=str(db_map_path),
            target_session_token="token",
            metabase_version="v56",
        )

        with patch("lib.services.import_service.MetabaseClient"):
            importer = MetabaseImporter(config)
            importer._load_export_package()
            # Should not raise
            importer._validate_metabase_version()


class TestPerformDryRun:
    """Test suite for _perform_dry_run method."""

    def test_dry_run_with_unmapped_database(self, tmp_path):
        """Test dry run raises ValueError for unmapped databases."""
        manifest_data = {
            "meta": {
                "source_url": "https://example.com",
                "export_timestamp": "2025-10-07T12:00:00",
                "tool_version": "1.0.0",
                "cli_args": {},
            },
            "databases": {"1": "DB1", "999": "Unmapped DB"},
            "collections": [],
            "cards": [
                {
                    "id": 100,
                    "name": "Test Card",
                    "collection_id": 1,
                    "database_id": 999,
                    "archived": False,
                    "file_path": "test.json",
                }
            ],
            "dashboards": [],
        }
        manifest_path = tmp_path / "manifest.json"
        with open(manifest_path, "w") as f:
            json.dump(manifest_data, f)

        db_map_data = {"by_id": {"1": 10}, "by_name": {"DB1": 10}}
        db_map_path = tmp_path / "db_map.json"
        with open(db_map_path, "w") as f:
            json.dump(db_map_data, f)

        config = ImportConfig(
            target_url="https://example.com",
            export_dir=str(tmp_path),
            db_map_path=str(db_map_path),
            target_session_token="token",
            dry_run=True,
        )

        with patch("lib.services.import_service.MetabaseClient"):
            importer = MetabaseImporter(config)
            with pytest.raises(ValueError, match="Unmapped databases found"):
                importer.run_import()

    def test_dry_run_with_dashboards(self, tmp_path):
        """Test dry run logs dashboards."""
        manifest_data = {
            "meta": {
                "source_url": "https://example.com",
                "export_timestamp": "2025-10-07T12:00:00",
                "tool_version": "1.0.0",
                "cli_args": {},
            },
            "databases": {"1": "DB1"},
            "collections": [],
            "cards": [],
            "dashboards": [
                {
                    "id": 1,
                    "name": "Test Dashboard",
                    "collection_id": 1,
                    "archived": False,
                    "file_path": "dashboards/dash.json",
                }
            ],
        }
        manifest_path = tmp_path / "manifest.json"
        with open(manifest_path, "w") as f:
            json.dump(manifest_data, f)

        db_map_data = {"by_id": {"1": 10}, "by_name": {"DB1": 10}}
        db_map_path = tmp_path / "db_map.json"
        with open(db_map_path, "w") as f:
            json.dump(db_map_data, f)

        config = ImportConfig(
            target_url="https://example.com",
            export_dir=str(tmp_path),
            db_map_path=str(db_map_path),
            target_session_token="token",
            dry_run=True,
        )

        with patch("lib.services.import_service.MetabaseClient"):
            importer = MetabaseImporter(config)
            importer.run_import()
            # Should complete without errors

    def test_dry_run_skips_archived_cards(self, tmp_path):
        """Test dry run skips archived cards when include_archived is False."""
        manifest_data = {
            "meta": {
                "source_url": "https://example.com",
                "export_timestamp": "2025-10-07T12:00:00",
                "tool_version": "1.0.0",
                "cli_args": {},
            },
            "databases": {"1": "DB1"},
            "collections": [],
            "cards": [
                {
                    "id": 100,
                    "name": "Archived Card",
                    "collection_id": 1,
                    "database_id": 1,
                    "archived": True,
                    "file_path": "cards/archived.json",
                }
            ],
            "dashboards": [],
        }
        manifest_path = tmp_path / "manifest.json"
        with open(manifest_path, "w") as f:
            json.dump(manifest_data, f)

        db_map_data = {"by_id": {"1": 10}, "by_name": {"DB1": 10}}
        db_map_path = tmp_path / "db_map.json"
        with open(db_map_path, "w") as f:
            json.dump(db_map_data, f)

        config = ImportConfig(
            target_url="https://example.com",
            export_dir=str(tmp_path),
            db_map_path=str(db_map_path),
            target_session_token="token",
            dry_run=True,
            include_archived=False,
        )

        with patch("lib.services.import_service.MetabaseClient"):
            importer = MetabaseImporter(config)
            importer.run_import()
            # Should complete without errors


class TestPerformImport:
    """Test suite for _perform_import method."""

    def test_perform_import_with_failures(self, tmp_path):
        """Test that import raises RuntimeError when there are failures."""

        manifest_data = {
            "meta": {
                "source_url": "https://example.com",
                "export_timestamp": "2025-10-07T12:00:00",
                "tool_version": "1.0.0",
                "cli_args": {},
            },
            "databases": {"1": "DB1"},
            "collections": [
                {
                    "id": 1,
                    "name": "Test Collection",
                    "path": "collections/test",
                    "slug": "test-collection",
                }
            ],
            "cards": [],
            "dashboards": [],
        }
        manifest_path = tmp_path / "manifest.json"
        with open(manifest_path, "w") as f:
            json.dump(manifest_data, f)

        db_map_data = {"by_id": {"1": 10}, "by_name": {"DB1": 10}}
        db_map_path = tmp_path / "db_map.json"
        with open(db_map_path, "w") as f:
            json.dump(db_map_data, f)

        config = ImportConfig(
            target_url="https://example.com",
            export_dir=str(tmp_path),
            db_map_path=str(db_map_path),
            target_session_token="token",
        )

        with patch("lib.services.import_service.MetabaseClient") as mock_client_class:
            mock_client = Mock()
            mock_client.get_databases.return_value = [{"id": 10, "name": "DB1"}]
            mock_client.get_database_metadata.return_value = {"tables": []}
            mock_client.get_collections_tree.return_value = []
            mock_client.get_collection_items.return_value = {"data": []}
            mock_client.create_collection.side_effect = Exception("Creation failed")
            mock_client_class.return_value = mock_client

            importer = MetabaseImporter(config)
            with pytest.raises(RuntimeError, match="Import finished with one or more failures"):
                importer.run_import()


class TestImportPermissions:
    """Test suite for permissions import."""

    def test_import_permissions_when_enabled(self, tmp_path):
        """Test permissions are imported when apply_permissions is True."""

        manifest_data = {
            "meta": {
                "source_url": "https://example.com",
                "export_timestamp": "2025-10-07T12:00:00",
                "tool_version": "1.0.0",
                "cli_args": {},
            },
            "databases": {"1": "DB1"},
            "collections": [],
            "cards": [],
            "dashboards": [],
            "permission_groups": [{"id": 1, "name": "All Users", "member_count": 5}],
            "permissions_graph": {"groups": {}},
            "collection_permissions_graph": {"groups": {}},
        }
        manifest_path = tmp_path / "manifest.json"
        with open(manifest_path, "w") as f:
            json.dump(manifest_data, f)

        db_map_data = {"by_id": {"1": 10}, "by_name": {"DB1": 10}}
        db_map_path = tmp_path / "db_map.json"
        with open(db_map_path, "w") as f:
            json.dump(db_map_data, f)

        config = ImportConfig(
            target_url="https://example.com",
            export_dir=str(tmp_path),
            db_map_path=str(db_map_path),
            target_session_token="token",
            apply_permissions=True,
        )

        with patch("lib.services.import_service.MetabaseClient") as mock_client_class:
            mock_client = Mock()
            mock_client.get_databases.return_value = [{"id": 10, "name": "DB1"}]
            mock_client.get_database_metadata.return_value = {"tables": []}
            mock_client.get_collections_tree.return_value = []
            mock_client.get_collection_items.return_value = {"data": []}
            mock_client.get_permission_groups.return_value = [
                {"id": 1, "name": "All Users", "member_count": 5}
            ]
            mock_client.get_permissions_graph.return_value = {"groups": {}}
            mock_client.get_collection_permissions_graph.return_value = {"groups": {}}
            mock_client_class.return_value = mock_client

            importer = MetabaseImporter(config)
            importer.run_import()

            # Should complete without errors


class TestLogUnmappedDatabases:
    """Test suite for _log_unmapped_databases_error method."""

    def test_log_unmapped_databases(self, tmp_path):
        """Test logging of unmapped databases."""
        from lib.models import UnmappedDatabase

        config = ImportConfig(
            target_url="https://example.com",
            export_dir=str(tmp_path),
            db_map_path=str(tmp_path / "db_map.json"),
            target_session_token="token",
        )

        with patch("lib.services.import_service.MetabaseClient"):
            importer = MetabaseImporter(config)
            unmapped = [
                UnmappedDatabase(
                    source_db_id=999, source_db_name="Unmapped DB", card_ids={100, 101}
                )
            ]
            # Should not raise
            importer._log_unmapped_databases_error(unmapped)


class TestLogInvalidDatabaseMapping:
    """Test suite for _log_invalid_database_mapping method."""

    def test_log_invalid_mapping(self, tmp_path):
        """Test logging of invalid database mappings."""
        config = ImportConfig(
            target_url="https://example.com",
            export_dir=str(tmp_path),
            db_map_path=str(tmp_path / "db_map.json"),
            target_session_token="token",
        )

        with patch("lib.services.import_service.MetabaseClient"):
            importer = MetabaseImporter(config)
            missing_ids = {99, 100}
            target_databases = [{"id": 10, "name": "DB1"}, {"id": 20, "name": "DB2"}]
            # Should not raise
            importer._log_invalid_database_mapping(missing_ids, target_databases)
