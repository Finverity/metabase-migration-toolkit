"""
Unit tests for lib/config.py

Tests configuration loading from CLI arguments and environment variables.
"""

import os
from unittest.mock import patch

from lib.config import ExportConfig, ImportConfig


class TestExportConfig:
    """Test suite for ExportConfig dataclass."""

    def test_export_config_creation(self):
        """Test creating an ExportConfig instance."""
        config = ExportConfig(
            source_url="https://example.com",
            export_dir="./export",
            source_username="user@example.com",
            source_password="password123",
            include_dashboards=True,
            include_archived=False,
            root_collection_ids=[1, 2, 3],
            log_level="INFO",
        )

        assert config.source_url == "https://example.com"
        assert config.export_dir == "./export"
        assert config.source_username == "user@example.com"
        assert config.source_password == "password123"
        assert config.include_dashboards is True
        assert config.include_archived is False
        assert config.root_collection_ids == [1, 2, 3]
        assert config.log_level == "INFO"

    def test_export_config_defaults(self):
        """Test ExportConfig with default values."""
        config = ExportConfig(source_url="https://example.com", export_dir="./export")

        assert config.source_username is None
        assert config.source_password is None
        assert config.source_session_token is None
        assert config.source_personal_token is None
        assert config.include_dashboards is False
        assert config.include_archived is False
        assert config.root_collection_ids is None
        assert config.log_level == "INFO"

    def test_export_config_with_session_token(self):
        """Test ExportConfig with session token."""
        config = ExportConfig(
            source_url="https://example.com",
            export_dir="./export",
            source_session_token="session-token-123",
        )

        assert config.source_session_token == "session-token-123"
        assert config.source_username is None
        assert config.source_password is None

    def test_export_config_with_personal_token(self):
        """Test ExportConfig with personal token."""
        config = ExportConfig(
            source_url="https://example.com",
            export_dir="./export",
            source_personal_token="personal-token-123",
        )

        assert config.source_personal_token == "personal-token-123"


class TestImportConfig:
    """Test suite for ImportConfig dataclass."""

    def test_import_config_creation(self):
        """Test creating an ImportConfig instance."""
        config = ImportConfig(
            target_url="https://example.com",
            export_dir="./export",
            db_map_path="./db_map.json",
            target_username="user@example.com",
            target_password="password123",
            conflict_strategy="skip",
            dry_run=False,
            log_level="INFO",
        )

        assert config.target_url == "https://example.com"
        assert config.export_dir == "./export"
        assert config.db_map_path == "./db_map.json"
        assert config.target_username == "user@example.com"
        assert config.target_password == "password123"
        assert config.conflict_strategy == "skip"
        assert config.dry_run is False
        assert config.log_level == "INFO"

    def test_import_config_defaults(self):
        """Test ImportConfig with default values."""
        config = ImportConfig(
            target_url="https://example.com", export_dir="./export", db_map_path="./db_map.json"
        )

        assert config.target_username is None
        assert config.target_password is None
        assert config.target_session_token is None
        assert config.target_personal_token is None
        assert config.conflict_strategy == "skip"
        assert config.dry_run is False
        assert config.log_level == "INFO"

    def test_import_config_conflict_strategies(self):
        """Test ImportConfig with different conflict strategies."""
        for strategy in ["skip", "overwrite", "rename"]:
            config = ImportConfig(
                target_url="https://example.com",
                export_dir="./export",
                db_map_path="./db_map.json",
                conflict_strategy=strategy,
            )
            assert config.conflict_strategy == strategy

    def test_import_config_dry_run(self):
        """Test ImportConfig with dry_run enabled."""
        config = ImportConfig(
            target_url="https://example.com",
            export_dir="./export",
            db_map_path="./db_map.json",
            dry_run=True,
        )

        assert config.dry_run is True


class TestGetExportArgs:
    """Test suite for get_export_args function."""

    @patch.dict(
        os.environ,
        {
            "MB_SOURCE_URL": "https://env.example.com",
            "MB_SOURCE_USERNAME": "env_user@example.com",
            "MB_SOURCE_PASSWORD": "env_password",
        },
    )
    @patch("sys.argv", ["export_metabase.py", "--export-dir", "./test_export"])
    def test_get_export_args_from_env(self):
        """Test loading export config from environment variables."""
        from lib.config import get_export_args

        config = get_export_args()

        assert config.source_url == "https://env.example.com"
        assert config.source_username == "env_user@example.com"
        assert config.source_password == "env_password"
        assert config.export_dir == "./test_export"

    @patch.dict(os.environ, {}, clear=True)
    @patch(
        "sys.argv",
        [
            "export_metabase.py",
            "--source-url",
            "https://cli.example.com",
            "--source-username",
            "cli_user@example.com",
            "--source-password",
            "cli_password",
            "--export-dir",
            "./cli_export",
            "--include-dashboards",
            "--include-archived",
            "--root-collections",
            "1,2,3",
            "--log-level",
            "DEBUG",
        ],
    )
    def test_get_export_args_from_cli(self):
        """Test loading export config from CLI arguments."""
        from lib.config import get_export_args

        config = get_export_args()

        assert config.source_url == "https://cli.example.com"
        assert config.source_username == "cli_user@example.com"
        assert config.source_password == "cli_password"
        assert config.export_dir == "./cli_export"
        assert config.include_dashboards is True
        assert config.include_archived is True
        assert config.root_collection_ids == [1, 2, 3]
        assert config.log_level == "DEBUG"

    @patch.dict(
        os.environ,
        {"MB_SOURCE_URL": "https://env.example.com", "MB_SOURCE_USERNAME": "env_user@example.com"},
    )
    @patch(
        "sys.argv",
        [
            "export_metabase.py",
            "--source-url",
            "https://cli.example.com",
            "--export-dir",
            "./test_export",
        ],
    )
    def test_get_export_args_cli_overrides_env(self):
        """Test that CLI arguments override environment variables."""
        from lib.config import get_export_args

        config = get_export_args()

        # CLI should override env
        assert config.source_url == "https://cli.example.com"
        # Env should be used when CLI not provided
        assert config.source_username == "env_user@example.com"


class TestGetImportArgs:
    """Test suite for get_import_args function."""

    @patch.dict(
        os.environ,
        {
            "MB_TARGET_URL": "https://env.example.com",
            "MB_TARGET_USERNAME": "env_user@example.com",
            "MB_TARGET_PASSWORD": "env_password",
        },
    )
    @patch(
        "sys.argv",
        ["import_metabase.py", "--export-dir", "./test_export", "--db-map", "./db_map.json"],
    )
    def test_get_import_args_from_env(self):
        """Test loading import config from environment variables."""
        from lib.config import get_import_args

        config = get_import_args()

        assert config.target_url == "https://env.example.com"
        assert config.target_username == "env_user@example.com"
        assert config.target_password == "env_password"
        assert config.export_dir == "./test_export"
        assert config.db_map_path == "./db_map.json"

    @patch.dict(os.environ, {}, clear=True)
    @patch(
        "sys.argv",
        [
            "import_metabase.py",
            "--target-url",
            "https://cli.example.com",
            "--target-username",
            "cli_user@example.com",
            "--target-password",
            "cli_password",
            "--export-dir",
            "./cli_export",
            "--db-map",
            "./cli_db_map.json",
            "--conflict",
            "overwrite",
            "--dry-run",
            "--log-level",
            "DEBUG",
        ],
    )
    def test_get_import_args_from_cli(self):
        """Test loading import config from CLI arguments."""
        from lib.config import get_import_args

        config = get_import_args()

        assert config.target_url == "https://cli.example.com"
        assert config.target_username == "cli_user@example.com"
        assert config.target_password == "cli_password"
        assert config.export_dir == "./cli_export"
        assert config.db_map_path == "./cli_db_map.json"
        assert config.conflict_strategy == "overwrite"
        assert config.dry_run is True
        assert config.log_level == "DEBUG"

    @patch.dict(os.environ, {"MB_TARGET_URL": "https://env.example.com"})
    @patch(
        "sys.argv",
        [
            "import_metabase.py",
            "--target-url",
            "https://cli.example.com",
            "--export-dir",
            "./test_export",
            "--db-map",
            "./db_map.json",
        ],
    )
    def test_get_import_args_cli_overrides_env(self):
        """Test that CLI arguments override environment variables."""
        from lib.config import get_import_args

        config = get_import_args()

        # CLI should override env
        assert config.target_url == "https://cli.example.com"
