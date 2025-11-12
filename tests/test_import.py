"""
Unit tests for import_metabase.py

Tests the MetabaseImporter class and import logic.
"""

import json
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from import_metabase import MetabaseImporter
from lib.config import ImportConfig
from lib.models import DatabaseMap, ImportReport


class TestMetabaseImporterInit:
    """Test suite for MetabaseImporter initialization."""

    def test_init_with_config(self, sample_import_config):
        """Test MetabaseImporter initialization with config."""
        with patch("import_metabase.MetabaseClient"):
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
        with patch("import_metabase.MetabaseClient") as mock_client_class:
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
        )

        with patch("import_metabase.MetabaseClient"):
            importer = MetabaseImporter(config)

            with pytest.raises(FileNotFoundError, match="manifest.json not found"):
                importer._load_export_package()

    def test_load_package_missing_db_map(self, manifest_file, tmp_path):
        """Test loading package when db_map.json is missing."""
        config = ImportConfig(
            target_url="https://example.com",
            export_dir=str(manifest_file.parent),
            db_map_path=str(tmp_path / "nonexistent_db_map.json"),
        )

        with patch("import_metabase.MetabaseClient"):
            importer = MetabaseImporter(config)

            with pytest.raises(FileNotFoundError, match="Database mapping file not found"):
                importer._load_export_package()

    def test_load_package_success(self, manifest_file, db_map_file):
        """Test successful package loading."""
        config = ImportConfig(
            target_url="https://example.com",
            export_dir=str(manifest_file.parent),
            db_map_path=str(db_map_file),
        )

        with patch("import_metabase.MetabaseClient"):
            importer = MetabaseImporter(config)
            importer._load_export_package()

            assert importer.manifest is not None
            assert importer.db_map is not None
            assert isinstance(importer.db_map, DatabaseMap)


class TestResolveDatabaseId:
    """Test suite for _resolve_db_id method."""

    def test_resolve_by_id(self, sample_import_config, manifest_file, db_map_file):
        """Test resolving database ID using by_id mapping."""
        config = ImportConfig(
            target_url="https://example.com",
            export_dir=str(manifest_file.parent),
            db_map_path=str(db_map_file),
        )

        with patch("import_metabase.MetabaseClient"):
            importer = MetabaseImporter(config)
            importer._load_export_package()

            # Source DB ID 1 should map to target DB ID 10
            target_id = importer._resolve_db_id(1)
            assert target_id == 10

    def test_resolve_by_name(self, sample_import_config, manifest_file, db_map_file):
        """Test resolving database ID using by_name mapping."""
        config = ImportConfig(
            target_url="https://example.com",
            export_dir=str(manifest_file.parent),
            db_map_path=str(db_map_file),
        )

        with patch("import_metabase.MetabaseClient"):
            importer = MetabaseImporter(config)
            importer._load_export_package()

            # Should resolve by name if not in by_id
            target_id = importer._resolve_db_id(2)
            assert target_id == 20

    def test_resolve_unmapped_database(self, sample_import_config, manifest_file, db_map_file):
        """Test resolving unmapped database ID returns None."""
        config = ImportConfig(
            target_url="https://example.com",
            export_dir=str(manifest_file.parent),
            db_map_path=str(db_map_file),
        )

        with patch("import_metabase.MetabaseClient"):
            importer = MetabaseImporter(config)
            importer._load_export_package()

            # Database ID 999 is not mapped
            target_id = importer._resolve_db_id(999)
            assert target_id is None


class TestValidateDatabaseMappings:
    """Test suite for _validate_database_mappings method."""

    def test_validate_all_mapped(self, manifest_file, db_map_file):
        """Test validation when all databases are mapped."""
        config = ImportConfig(
            target_url="https://example.com",
            export_dir=str(manifest_file.parent),
            db_map_path=str(db_map_file),
        )

        with patch("import_metabase.MetabaseClient"):
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
            target_url="https://example.com", export_dir=str(tmp_path), db_map_path=str(db_map_path)
        )

        with patch("import_metabase.MetabaseClient"):
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
        )

        with patch("import_metabase.MetabaseClient") as mock_client_class:
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
        )

        with patch("import_metabase.MetabaseClient") as mock_client_class:
            mock_client = Mock()
            # Target only has DB 10, but mapping references 10, 20, 30
            mock_client.get_databases.return_value = [{"id": 10, "name": "Target DB 1"}]
            mock_client_class.return_value = mock_client

            importer = MetabaseImporter(config)
            importer._load_export_package()

            # Should exit with error
            with pytest.raises(SystemExit):
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
        )

        assert config.conflict_strategy == "skip"

    def test_overwrite_strategy(self):
        """Test overwrite conflict strategy."""
        config = ImportConfig(
            target_url="https://example.com",
            export_dir="./export",
            db_map_path="./db_map.json",
            conflict_strategy="overwrite",
        )

        assert config.conflict_strategy == "overwrite"

    def test_rename_strategy(self):
        """Test rename conflict strategy."""
        config = ImportConfig(
            target_url="https://example.com",
            export_dir="./export",
            db_map_path="./db_map.json",
            conflict_strategy="rename",
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
        )

        assert config.dry_run is True

    def test_dry_run_disabled(self):
        """Test that dry_run defaults to False."""
        config = ImportConfig(
            target_url="https://example.com", export_dir="./export", db_map_path="./db_map.json"
        )

        assert config.dry_run is False


class TestImportReport:
    """Test suite for import report generation."""

    def test_report_initialization(self, sample_import_config):
        """Test that import report is initialized."""
        with patch("import_metabase.MetabaseClient"):
            importer = MetabaseImporter(sample_import_config)

            assert isinstance(importer.report, ImportReport)
            assert importer.report.items == []


class TestCollectionMapping:
    """Test suite for collection ID mapping."""

    def test_collection_map_empty_initially(self, sample_import_config):
        """Test that collection map is empty initially."""
        with patch("import_metabase.MetabaseClient"):
            importer = MetabaseImporter(sample_import_config)

            assert importer._collection_map == {}

    def test_card_map_empty_initially(self, sample_import_config):
        """Test that card map is empty initially."""
        with patch("import_metabase.MetabaseClient"):
            importer = MetabaseImporter(sample_import_config)

            assert importer._card_map == {}


class TestImportConfiguration:
    """Test suite for import configuration validation."""

    def test_config_requires_target_url(self):
        """Test that target_url is required."""
        with pytest.raises(TypeError):
            ImportConfig(export_dir="./export", db_map_path="./db_map.json")

    def test_config_requires_export_dir(self):
        """Test that export_dir is required."""
        with pytest.raises(TypeError):
            ImportConfig(target_url="https://example.com", db_map_path="./db_map.json")

    def test_config_requires_db_map_path(self):
        """Test that db_map_path is required."""
        with pytest.raises(TypeError):
            ImportConfig(target_url="https://example.com", export_dir="./export")


class TestRemapCardQuery:
    """Test suite for _remap_card_query method."""

    def test_remap_card_query_always_sets_database_field(self, sample_import_config):
        """Test that database field is always set in dataset_query, even if not present originally.

        This is a regression test for the pMBQL normalization error where cards that reference
        other cards (source-table: card__XXX) were missing the database field in dataset_query.
        """
        with patch("import_metabase.MetabaseClient"):
            importer = MetabaseImporter(sample_import_config)

            # Set up database mapping
            importer.db_map = DatabaseMap(by_id={"1": 10})

            # Card data with database_id but NO database field in dataset_query
            # This simulates a card that queries from another card
            card_data = {
                "id": 100,
                "name": "Test Card",
                "database_id": 1,
                "dataset_query": {
                    "type": "query",
                    # Note: NO "database" field here
                    "query": {"source-table": "card__50"},
                },
            }

            remapped_data, success = importer._remap_card_query(card_data)

            assert success is True
            assert remapped_data["database_id"] == 10
            # The key assertion: database field should be set in dataset_query
            assert remapped_data["dataset_query"]["database"] == 10

    def test_remap_card_query_with_existing_database_field(self, sample_import_config):
        """Test that existing database field in dataset_query is properly remapped."""
        with patch("import_metabase.MetabaseClient"):
            importer = MetabaseImporter(sample_import_config)

            # Set up database mapping
            importer.db_map = DatabaseMap(by_id={"1": 10})

            # Card data with database field already present
            card_data = {
                "id": 100,
                "name": "Test Card",
                "database_id": 1,
                "dataset_query": {
                    "type": "query",
                    "database": 1,  # Already present
                    "query": {"source-table": "card__50"},
                },
            }

            remapped_data, success = importer._remap_card_query(card_data)

            assert success is True
            assert remapped_data["database_id"] == 10
            assert remapped_data["dataset_query"]["database"] == 10

    def test_remap_card_query_without_database_id(self, sample_import_config):
        """Test that cards without database_id return False."""
        with patch("import_metabase.MetabaseClient"):
            importer = MetabaseImporter(sample_import_config)

            card_data = {
                "id": 100,
                "name": "Test Card",
                "dataset_query": {"type": "query", "query": {}},
            }

            remapped_data, success = importer._remap_card_query(card_data)

            assert success is False

    def test_remap_card_query_with_table_id(self, sample_import_config):
        """Test that table_id is remapped correctly."""
        with patch("import_metabase.MetabaseClient"):
            importer = MetabaseImporter(sample_import_config)

            # Set up database and table mappings
            importer.db_map = DatabaseMap(by_id={"1": 10})
            importer._table_map = {(1, 27): 42}  # source table 27 -> target table 42

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

            remapped_data, success = importer._remap_card_query(card_data)

            assert success is True
            assert remapped_data["table_id"] == 42
            assert remapped_data["dataset_query"]["query"]["source-table"] == 42

    def test_remap_field_ids_in_filter(self, sample_import_config):
        """Test that field IDs in filters are remapped correctly."""
        with patch("import_metabase.MetabaseClient"):
            importer = MetabaseImporter(sample_import_config)

            # Set up field mappings
            importer._field_map = {(1, 201): 301, (1, 204): 304}

            # Filter expression with field IDs
            filter_expr = [
                "and",
                ["=", ["field", 201, {"base-type": "type/PostgresEnum"}], "CUSTOMER"],
                ["=", ["field", 204, {"base-type": "type/PostgresEnum"}], "ACTIVE"],
            ]

            remapped_filter = importer._remap_field_ids_recursively(filter_expr, 1)

            # Check that field IDs were remapped
            assert remapped_filter[1][1][1] == 301  # First field ID
            assert remapped_filter[2][1][1] == 304  # Second field ID

    def test_remap_field_ids_in_aggregation(self, sample_import_config):
        """Test that field IDs in aggregations are remapped correctly."""
        with patch("import_metabase.MetabaseClient"):
            importer = MetabaseImporter(sample_import_config)

            # Set up field mappings
            importer._field_map = {(1, 5): 105}

            # Aggregation with field ID
            aggregation = [["sum", ["field", 5, None]]]

            remapped_agg = importer._remap_field_ids_recursively(aggregation, 1)

            # Check that field ID was remapped
            assert remapped_agg[0][1][1] == 105

    def test_remap_field_ids_in_breakout(self, sample_import_config):
        """Test that field IDs in breakouts are remapped correctly."""
        with patch("import_metabase.MetabaseClient"):
            importer = MetabaseImporter(sample_import_config)

            # Set up field mappings
            importer._field_map = {(1, 3): 103}

            # Breakout with field ID
            breakout = [["field", 3, {"temporal-unit": "month"}]]

            remapped_breakout = importer._remap_field_ids_recursively(breakout, 1)

            # Check that field ID was remapped
            assert remapped_breakout[0][1] == 103

    def test_remap_field_ids_in_dashboard_parameter_target(self, sample_import_config):
        """Test that field IDs in dashboard parameter targets are remapped correctly."""
        with patch("import_metabase.MetabaseClient"):
            importer = MetabaseImporter(sample_import_config)

            # Set up field mappings
            importer._field_map = {(1, 10): 110}

            # Parameter mapping target with field ID
            target = ["dimension", ["field", 10, None]]

            remapped_target = importer._remap_field_ids_recursively(target, 1)

            # Check that field ID was remapped
            assert remapped_target[1][1] == 110

    def test_remap_field_ids_in_dashboard_parameter_value_field(self, sample_import_config):
        """Test that field IDs in dashboard parameter value_field use the correct database ID."""
        with patch("import_metabase.MetabaseClient"):
            importer = MetabaseImporter(sample_import_config)

            # Set up field mappings for database 3
            importer._field_map = {(3, 218): 318}

            # value_field with field ID from database 3
            value_field = ["field", 218, {"base-type": "type/Text"}]

            # Remap using database 3 (not database 7)
            remapped_value_field = importer._remap_field_ids_recursively(value_field, 3)

            # Check that field ID was remapped
            assert remapped_value_field[1] == 318

    def test_remap_result_metadata(self, sample_import_config):
        """Test that field IDs and table IDs in result_metadata are remapped correctly."""
        with patch("import_metabase.MetabaseClient"):
            importer = MetabaseImporter(sample_import_config)

            # Set up database, table, and field mappings
            importer.db_map = DatabaseMap(by_id={"3": 4})
            importer._table_map = {(3, 27): 42}
            importer._field_map = {(3, 218): 318, (3, 210): 310}

            # Card data with result_metadata
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

            remapped_data, success = importer._remap_card_query(card_data)

            assert success is True
            # Check database ID was remapped
            assert remapped_data["database_id"] == 4
            # Check table ID was remapped
            assert remapped_data["table_id"] == 42
            # Check result_metadata field IDs were remapped
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
            target_url="https://example.com", export_dir=str(tmp_path), db_map_path=str(db_map_path)
        )

        with patch("import_metabase.MetabaseClient") as mock_client_class:
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
            importer._build_table_and_field_mappings()

            # Check table mapping
            assert (3, 27) in importer._table_map
            assert importer._table_map[(3, 27)] == 42

            # Check field mappings
            assert (3, 201) in importer._field_map
            assert importer._field_map[(3, 201)] == 301
            assert (3, 204) in importer._field_map
            assert importer._field_map[(3, 204)] == 304


class TestConflictResolution:
    """Test suite for conflict resolution strategies."""

    def test_find_existing_card_in_collection(self, sample_import_config):
        """Test finding an existing card by name in a collection."""
        with patch("import_metabase.MetabaseClient") as mock_client_class:
            mock_client = Mock()
            mock_client_class.return_value = mock_client

            # Mock the get_collection_items response
            mock_client.get_collection_items.return_value = {
                "data": [
                    {"id": 1, "name": "Existing Card", "model": "card"},
                    {"id": 2, "name": "Another Card", "model": "card"},
                    {"id": 3, "name": "Some Dashboard", "model": "dashboard"},
                ]
            }

            importer = MetabaseImporter(sample_import_config)

            # Test finding existing card
            result = importer._find_existing_card_in_collection("Existing Card", 10)
            assert result is not None
            assert result["id"] == 1
            assert result["name"] == "Existing Card"

            # Test card not found
            result = importer._find_existing_card_in_collection("Non-existent Card", 10)
            assert result is None

            # Verify correct API call
            mock_client.get_collection_items.assert_called_with(10)

    def test_find_existing_dashboard_in_collection(self, sample_import_config):
        """Test finding an existing dashboard by name in a collection."""
        with patch("import_metabase.MetabaseClient") as mock_client_class:
            mock_client = Mock()
            mock_client_class.return_value = mock_client

            # Mock the get_collection_items response
            mock_client.get_collection_items.return_value = {
                "data": [
                    {"id": 1, "name": "Existing Dashboard", "model": "dashboard"},
                    {"id": 2, "name": "Another Dashboard", "model": "dashboard"},
                    {"id": 3, "name": "Some Card", "model": "card"},
                ]
            }

            importer = MetabaseImporter(sample_import_config)

            # Test finding existing dashboard
            result = importer._find_existing_dashboard_in_collection("Existing Dashboard", 10)
            assert result is not None
            assert result["id"] == 1
            assert result["name"] == "Existing Dashboard"

            # Test dashboard not found
            result = importer._find_existing_dashboard_in_collection("Non-existent Dashboard", 10)
            assert result is None

    def test_generate_unique_name_for_card(self, sample_import_config):
        """Test generating unique names for cards."""
        with patch("import_metabase.MetabaseClient") as mock_client_class:
            mock_client = Mock()
            mock_client_class.return_value = mock_client

            # Mock responses: first call finds "Test Card", second finds "Test Card (1)"
            # third call finds nothing (unique name found)
            mock_client.get_collection_items.side_effect = [
                {"data": [{"id": 1, "name": "Test Card", "model": "card"}]},
                {"data": [{"id": 2, "name": "Test Card (1)", "model": "card"}]},
                {"data": []},
            ]

            importer = MetabaseImporter(sample_import_config)

            # Should return "Test Card (2)" since "Test Card" and "Test Card (1)" exist
            unique_name = importer._generate_unique_name("Test Card", 10, "card")
            assert unique_name == "Test Card (2)"

    def test_generate_unique_name_no_conflict(self, sample_import_config):
        """Test generating unique name when there's no conflict."""
        with patch("import_metabase.MetabaseClient") as mock_client_class:
            mock_client = Mock()
            mock_client_class.return_value = mock_client

            # Mock response: no existing items
            mock_client.get_collection_items.return_value = {"data": []}

            importer = MetabaseImporter(sample_import_config)

            # Should return original name since no conflict
            unique_name = importer._generate_unique_name("New Card", 10, "card")
            assert unique_name == "New Card"

    def test_collection_conflict_skip_strategy(
        self, sample_import_config, manifest_file, db_map_file
    ):
        """Test collection import with skip conflict strategy."""
        config = ImportConfig(
            target_url="https://example.com",
            export_dir=str(manifest_file.parent),
            db_map_path=str(db_map_file),
            conflict_strategy="skip",
        )

        with patch("import_metabase.MetabaseClient") as mock_client_class:
            mock_client = Mock()
            mock_client_class.return_value = mock_client

            # Mock existing collection
            existing_collections = [{"id": 100, "name": "Test Collection", "parent_id": None}]
            mock_client.get_collections_tree.return_value = existing_collections

            importer = MetabaseImporter(config)
            importer._load_export_package()
            # Set _target_collections before calling _import_collections
            importer._target_collections = existing_collections
            importer._import_collections()

            # Should skip and map to existing collection
            assert importer._collection_map[1] == 100
            assert importer.report.summary["collections"]["skipped"] == 1
            assert importer.report.summary["collections"]["created"] == 0

            # Should not call create_collection
            mock_client.create_collection.assert_not_called()

    def test_collection_conflict_overwrite_strategy(
        self, sample_import_config, manifest_file, db_map_file
    ):
        """Test collection import with overwrite conflict strategy."""
        config = ImportConfig(
            target_url="https://example.com",
            export_dir=str(manifest_file.parent),
            db_map_path=str(db_map_file),
            conflict_strategy="overwrite",
        )

        with patch("import_metabase.MetabaseClient") as mock_client_class:
            mock_client = Mock()
            mock_client_class.return_value = mock_client

            # Mock existing collection
            existing_collections = [{"id": 100, "name": "Test Collection", "parent_id": None}]
            mock_client.get_collections_tree.return_value = existing_collections
            mock_client.update_collection.return_value = {"id": 100, "name": "Test Collection"}

            importer = MetabaseImporter(config)
            importer._load_export_package()
            # Set _target_collections before calling _import_collections
            importer._target_collections = existing_collections
            importer._import_collections()

            # Should update existing collection
            assert importer._collection_map[1] == 100
            assert importer.report.summary["collections"]["updated"] == 1
            assert importer.report.summary["collections"]["created"] == 0

            # Should call update_collection
            mock_client.update_collection.assert_called_once()
            mock_client.create_collection.assert_not_called()

    def test_collection_conflict_rename_strategy(
        self, sample_import_config, manifest_file, db_map_file
    ):
        """Test collection import with rename conflict strategy."""
        config = ImportConfig(
            target_url="https://example.com",
            export_dir=str(manifest_file.parent),
            db_map_path=str(db_map_file),
            conflict_strategy="rename",
        )

        with patch("import_metabase.MetabaseClient") as mock_client_class:
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
            # Set _target_collections before calling _import_collections
            importer._target_collections = existing_collections
            importer._import_collections()

            # Should create with renamed collection
            assert importer.report.summary["collections"]["created"] == 1
            assert importer.report.summary["collections"]["skipped"] == 0

            # Should call create_collection with renamed name
            mock_client.create_collection.assert_called_once()
            call_args = mock_client.create_collection.call_args[0][0]
            assert call_args["name"] == "Test Collection (1)"
