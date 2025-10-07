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
