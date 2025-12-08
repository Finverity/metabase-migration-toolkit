"""
Unit tests for sync functionality.

Tests for SyncConfig, get_sync_args, and sync_metabase.py.
"""

import os
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from lib.config import SyncConfig


class TestSyncConfig:
    """Test suite for SyncConfig Pydantic model."""

    def test_sync_config_creation(self):
        """Test creating a SyncConfig instance with all fields."""
        config = SyncConfig(
            source_url="https://source.example.com",
            source_username="source_user@example.com",
            source_password="source_password",  # pragma: allowlist secret
            target_url="https://target.example.com",
            target_username="target_user@example.com",
            target_password="target_password",  # pragma: allowlist secret
            export_dir="./export",
            db_map_path="./db_map.json",
            include_dashboards=True,
            include_permissions=True,
            conflict_strategy="overwrite",
            apply_permissions=True,
            log_level="INFO",
        )

        assert config.source_url == "https://source.example.com"
        assert config.source_username == "source_user@example.com"
        assert config.target_url == "https://target.example.com"
        assert config.target_username == "target_user@example.com"
        assert config.export_dir == "./export"
        assert config.db_map_path == "./db_map.json"
        assert config.include_dashboards is True
        assert config.include_permissions is True
        assert config.conflict_strategy == "overwrite"
        assert config.apply_permissions is True

    def test_sync_config_defaults(self):
        """Test SyncConfig with default values."""
        config = SyncConfig(
            source_url="https://source.example.com",
            source_session_token="source_token",
            target_url="https://target.example.com",
            target_session_token="target_token",
            export_dir="./export",
            db_map_path="./db_map.json",
        )

        assert config.include_dashboards is False
        assert config.include_archived is False
        assert config.include_permissions is False
        assert config.root_collection_ids is None
        assert config.conflict_strategy == "skip"
        assert config.dry_run is False
        assert config.apply_permissions is False
        assert config.log_level == "INFO"

    def test_sync_config_with_session_tokens(self):
        """Test SyncConfig with session tokens."""
        config = SyncConfig(
            source_url="https://source.example.com",
            source_session_token="source-session-token",
            target_url="https://target.example.com",
            target_session_token="target-session-token",
            export_dir="./export",
            db_map_path="./db_map.json",
        )

        assert config.source_session_token == "source-session-token"
        assert config.target_session_token == "target-session-token"

    def test_sync_config_with_personal_tokens(self):
        """Test SyncConfig with personal tokens."""
        config = SyncConfig(
            source_url="https://source.example.com",
            source_personal_token="source-personal-token",
            target_url="https://target.example.com",
            target_personal_token="target-personal-token",
            export_dir="./export",
            db_map_path="./db_map.json",
        )

        assert config.source_personal_token == "source-personal-token"
        assert config.target_personal_token == "target-personal-token"

    def test_sync_config_url_trailing_slash_stripped(self):
        """Test that trailing slashes are stripped from URLs."""
        config = SyncConfig(
            source_url="https://source.example.com/",
            source_session_token="token",
            target_url="https://target.example.com/",
            target_session_token="token",
            export_dir="./export",
            db_map_path="./db_map.json",
        )

        assert config.source_url == "https://source.example.com"
        assert config.target_url == "https://target.example.com"

    def test_sync_config_log_level_uppercase(self):
        """Test that log level is uppercased."""
        config = SyncConfig(
            source_url="https://source.example.com",
            source_session_token="token",
            target_url="https://target.example.com",
            target_session_token="token",
            export_dir="./export",
            db_map_path="./db_map.json",
            log_level="debug",
        )

        assert config.log_level == "DEBUG"

    def test_sync_config_immutable(self):
        """Test that SyncConfig is immutable (frozen)."""
        config = SyncConfig(
            source_url="https://source.example.com",
            source_session_token="token",
            target_url="https://target.example.com",
            target_session_token="token",
            export_dir="./export",
            db_map_path="./db_map.json",
        )

        with pytest.raises(ValidationError):
            config.source_url = "https://other.com"


class TestSyncConfigValidation:
    """Test validation errors for SyncConfig."""

    def test_invalid_source_url_scheme(self):
        """Test that non-http/https source URL schemes are rejected."""
        with pytest.raises(ValidationError) as exc_info:
            SyncConfig(
                source_url="ftp://source.example.com",
                source_session_token="token",
                target_url="https://target.example.com",
                target_session_token="token",
                export_dir="./export",
                db_map_path="./db_map.json",
            )

        assert "http or https" in str(exc_info.value)

    def test_invalid_target_url_scheme(self):
        """Test that non-http/https target URL schemes are rejected."""
        with pytest.raises(ValidationError) as exc_info:
            SyncConfig(
                source_url="https://source.example.com",
                source_session_token="token",
                target_url="file:///etc/passwd",
                target_session_token="token",
                export_dir="./export",
                db_map_path="./db_map.json",
            )

        assert "http or https" in str(exc_info.value)

    def test_missing_source_authentication(self):
        """Test that missing source authentication is rejected."""
        with pytest.raises(ValidationError) as exc_info:
            SyncConfig(
                source_url="https://source.example.com",
                target_url="https://target.example.com",
                target_session_token="token",
                export_dir="./export",
                db_map_path="./db_map.json",
            )

        assert (
            "source" in str(exc_info.value).lower()
            and "authentication" in str(exc_info.value).lower()
        )

    def test_missing_target_authentication(self):
        """Test that missing target authentication is rejected."""
        with pytest.raises(ValidationError) as exc_info:
            SyncConfig(
                source_url="https://source.example.com",
                source_session_token="token",
                target_url="https://target.example.com",
                export_dir="./export",
                db_map_path="./db_map.json",
            )

        assert (
            "target" in str(exc_info.value).lower()
            and "authentication" in str(exc_info.value).lower()
        )

    def test_path_traversal_in_export_dir(self):
        """Test that path traversal in export_dir is rejected."""
        with pytest.raises(ValidationError) as exc_info:
            SyncConfig(
                source_url="https://source.example.com",
                source_session_token="token",
                target_url="https://target.example.com",
                target_session_token="token",
                export_dir="../../../etc",
                db_map_path="./db_map.json",
            )

        assert "traversal" in str(exc_info.value)

    def test_path_traversal_in_db_map_path(self):
        """Test that path traversal in db_map_path is rejected."""
        with pytest.raises(ValidationError) as exc_info:
            SyncConfig(
                source_url="https://source.example.com",
                source_session_token="token",
                target_url="https://target.example.com",
                target_session_token="token",
                export_dir="./export",
                db_map_path="../../etc/passwd",
            )

        assert "traversal" in str(exc_info.value)

    def test_invalid_conflict_strategy(self):
        """Test that invalid conflict strategy is rejected."""
        with pytest.raises(ValidationError) as exc_info:
            SyncConfig(
                source_url="https://source.example.com",
                source_session_token="token",
                target_url="https://target.example.com",
                target_session_token="token",
                export_dir="./export",
                db_map_path="./db_map.json",
                conflict_strategy="invalid",
            )

        assert "conflict" in str(exc_info.value).lower() or "literal" in str(exc_info.value).lower()

    def test_invalid_log_level(self):
        """Test that invalid log levels are rejected."""
        with pytest.raises(ValidationError) as exc_info:
            SyncConfig(
                source_url="https://source.example.com",
                source_session_token="token",
                target_url="https://target.example.com",
                target_session_token="token",
                export_dir="./export",
                db_map_path="./db_map.json",
                log_level="VERBOSE",
            )

        assert "log_level" in str(exc_info.value)

    def test_negative_collection_ids(self):
        """Test that negative collection IDs are rejected."""
        with pytest.raises(ValidationError) as exc_info:
            SyncConfig(
                source_url="https://source.example.com",
                source_session_token="token",
                target_url="https://target.example.com",
                target_session_token="token",
                export_dir="./export",
                db_map_path="./db_map.json",
                root_collection_ids=[1, -2, 3],
            )

        assert "positive" in str(exc_info.value).lower()


class TestSyncConfigConversion:
    """Test SyncConfig conversion to ExportConfig and ImportConfig."""

    def test_to_export_config(self):
        """Test converting SyncConfig to ExportConfig."""
        sync_config = SyncConfig(
            source_url="https://source.example.com",
            source_username="source_user@example.com",
            source_password="source_password",  # pragma: allowlist secret
            target_url="https://target.example.com",
            target_session_token="target_token",
            export_dir="./export",
            db_map_path="./db_map.json",
            include_dashboards=True,
            include_archived=True,
            include_permissions=True,
            root_collection_ids=[1, 2, 3],
            log_level="DEBUG",
        )

        export_config = sync_config.to_export_config()

        assert export_config.source_url == "https://source.example.com"
        assert export_config.source_username == "source_user@example.com"
        assert export_config.source_password == "source_password"  # pragma: allowlist secret
        assert export_config.export_dir == "./export"
        assert export_config.include_dashboards is True
        assert export_config.include_archived is True
        assert export_config.include_permissions is True
        assert export_config.root_collection_ids == [1, 2, 3]
        assert export_config.log_level == "DEBUG"

    def test_to_import_config(self):
        """Test converting SyncConfig to ImportConfig."""
        sync_config = SyncConfig(
            source_url="https://source.example.com",
            source_session_token="source_token",
            target_url="https://target.example.com",
            target_username="target_user@example.com",
            target_password="target_password",  # pragma: allowlist secret
            export_dir="./export",
            db_map_path="./db_map.json",
            include_archived=True,
            conflict_strategy="overwrite",
            dry_run=True,
            apply_permissions=True,
            log_level="DEBUG",
        )

        import_config = sync_config.to_import_config()

        assert import_config.target_url == "https://target.example.com"
        assert import_config.target_username == "target_user@example.com"
        assert import_config.target_password == "target_password"  # pragma: allowlist secret
        assert import_config.export_dir == "./export"
        assert import_config.db_map_path == "./db_map.json"
        assert import_config.include_archived is True
        assert import_config.conflict_strategy == "overwrite"
        assert import_config.dry_run is True
        assert import_config.apply_permissions is True
        assert import_config.log_level == "DEBUG"

    def test_export_and_import_configs_share_export_dir(self):
        """Test that export and import configs share the same export_dir."""
        sync_config = SyncConfig(
            source_url="https://source.example.com",
            source_session_token="token",
            target_url="https://target.example.com",
            target_session_token="token",
            export_dir="./shared_export",
            db_map_path="./db_map.json",
        )

        export_config = sync_config.to_export_config()
        import_config = sync_config.to_import_config()

        assert export_config.export_dir == import_config.export_dir == "./shared_export"


class TestGetSyncArgs:
    """Test suite for get_sync_args function."""

    @patch.dict(
        os.environ,
        {
            "MB_SOURCE_URL": "https://env-source.example.com",
            "MB_SOURCE_USERNAME": "env_source_user@example.com",
            "MB_SOURCE_PASSWORD": "env_source_password",  # pragma: allowlist secret
            "MB_TARGET_URL": "https://env-target.example.com",
            "MB_TARGET_USERNAME": "env_target_user@example.com",
            "MB_TARGET_PASSWORD": "env_target_password",  # pragma: allowlist secret
        },
    )
    @patch(
        "sys.argv",
        [
            "sync_metabase.py",
            "--export-dir",
            "./test_export",
            "--db-map",
            "./db_map.json",
        ],
    )
    def test_get_sync_args_from_env(self):
        """Test loading sync config from environment variables."""
        from lib.config import get_sync_args

        config = get_sync_args()

        assert config.source_url == "https://env-source.example.com"
        assert config.source_username == "env_source_user@example.com"
        assert config.source_password == "env_source_password"  # pragma: allowlist secret
        assert config.target_url == "https://env-target.example.com"
        assert config.target_username == "env_target_user@example.com"
        assert config.target_password == "env_target_password"  # pragma: allowlist secret
        assert config.export_dir == "./test_export"
        assert config.db_map_path == "./db_map.json"

    @patch.dict(os.environ, {}, clear=True)
    @patch(
        "sys.argv",
        [
            "sync_metabase.py",
            "--source-url",
            "https://cli-source.example.com",
            "--source-username",
            "cli_source_user@example.com",
            "--source-password",
            "cli_source_password",
            "--target-url",
            "https://cli-target.example.com",
            "--target-username",
            "cli_target_user@example.com",
            "--target-password",
            "cli_target_password",
            "--export-dir",
            "./cli_export",
            "--db-map",
            "./cli_db_map.json",
            "--include-dashboards",
            "--include-permissions",
            "--apply-permissions",
            "--conflict",
            "overwrite",
            "--root-collections",
            "24,25",
            "--log-level",
            "DEBUG",
        ],
    )
    def test_get_sync_args_from_cli(self):
        """Test loading sync config from CLI arguments."""
        from lib.config import get_sync_args

        config = get_sync_args()

        assert config.source_url == "https://cli-source.example.com"
        assert config.source_username == "cli_source_user@example.com"
        assert config.source_password == "cli_source_password"  # pragma: allowlist secret
        assert config.target_url == "https://cli-target.example.com"
        assert config.target_username == "cli_target_user@example.com"
        assert config.target_password == "cli_target_password"  # pragma: allowlist secret
        assert config.export_dir == "./cli_export"
        assert config.db_map_path == "./cli_db_map.json"
        assert config.include_dashboards is True
        assert config.include_permissions is True
        assert config.apply_permissions is True
        assert config.conflict_strategy == "overwrite"
        assert config.root_collection_ids == [24, 25]
        assert config.log_level == "DEBUG"

    @patch.dict(
        os.environ,
        {
            "MB_SOURCE_URL": "https://env-source.example.com",
            "MB_TARGET_URL": "https://env-target.example.com",
        },
    )
    @patch(
        "sys.argv",
        [
            "sync_metabase.py",
            "--source-url",
            "https://cli-source.example.com",
            "--source-session",
            "source-session-token",
            "--target-url",
            "https://cli-target.example.com",
            "--target-session",
            "target-session-token",
            "--export-dir",
            "./test_export",
            "--db-map",
            "./db_map.json",
        ],
    )
    def test_get_sync_args_cli_overrides_env(self):
        """Test that CLI arguments override environment variables."""
        from lib.config import get_sync_args

        config = get_sync_args()

        # CLI should override env
        assert config.source_url == "https://cli-source.example.com"
        assert config.target_url == "https://cli-target.example.com"
        # CLI session tokens should be used
        assert config.source_session_token == "source-session-token"
        assert config.target_session_token == "target-session-token"


class TestSyncMetabaseMain:
    """Test suite for sync_metabase main function."""

    @patch("sync_metabase.ExportService")
    @patch("sync_metabase.ImportService")
    @patch("sync_metabase.get_sync_args")
    @patch("sync_metabase.setup_logging")
    def test_sync_main_success(
        self, mock_setup_logging, mock_get_sync_args, mock_import_service, mock_export_service
    ):
        """Test successful sync operation."""
        # Create a mock config
        mock_config = MagicMock()
        mock_config.source_url = "https://source.example.com"
        mock_config.target_url = "https://target.example.com"
        mock_config.export_dir = "./export"
        mock_config.log_level = "INFO"

        # Create mock export and import configs
        mock_export_config = MagicMock()
        mock_import_config = MagicMock()
        mock_config.to_export_config.return_value = mock_export_config
        mock_config.to_import_config.return_value = mock_import_config

        mock_get_sync_args.return_value = mock_config

        # Create mock exporter and importer
        mock_exporter = MagicMock()
        mock_importer = MagicMock()
        mock_export_service.return_value = mock_exporter
        mock_import_service.return_value = mock_importer

        from sync_metabase import main

        # Should not raise
        main()

        # Verify services were called
        mock_export_service.assert_called_once_with(mock_export_config)
        mock_exporter.run_export.assert_called_once()
        mock_import_service.assert_called_once_with(mock_import_config)
        mock_importer.run_import.assert_called_once()

    @patch("sync_metabase.ExportService")
    @patch("sync_metabase.get_sync_args")
    @patch("sync_metabase.setup_logging")
    def test_sync_main_export_failure(
        self, mock_setup_logging, mock_get_sync_args, mock_export_service
    ):
        """Test sync operation fails when export fails."""
        from lib.client import MetabaseAPIError

        # Create a mock config
        mock_config = MagicMock()
        mock_config.source_url = "https://source.example.com"
        mock_config.target_url = "https://target.example.com"
        mock_config.export_dir = "./export"
        mock_config.log_level = "INFO"

        mock_export_config = MagicMock()
        mock_config.to_export_config.return_value = mock_export_config

        mock_get_sync_args.return_value = mock_config

        # Create mock exporter that raises an error
        mock_exporter = MagicMock()
        mock_exporter.run_export.side_effect = MetabaseAPIError("Export failed")
        mock_export_service.return_value = mock_exporter

        from sync_metabase import main

        # Should exit with code 1
        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 1

    @patch("sync_metabase.ExportService")
    @patch("sync_metabase.ImportService")
    @patch("sync_metabase.get_sync_args")
    @patch("sync_metabase.setup_logging")
    def test_sync_main_import_failure(
        self, mock_setup_logging, mock_get_sync_args, mock_import_service, mock_export_service
    ):
        """Test sync operation fails when import fails after successful export."""
        from lib.client import MetabaseAPIError

        # Create a mock config
        mock_config = MagicMock()
        mock_config.source_url = "https://source.example.com"
        mock_config.target_url = "https://target.example.com"
        mock_config.export_dir = "./export"
        mock_config.log_level = "INFO"

        mock_export_config = MagicMock()
        mock_import_config = MagicMock()
        mock_config.to_export_config.return_value = mock_export_config
        mock_config.to_import_config.return_value = mock_import_config

        mock_get_sync_args.return_value = mock_config

        # Export succeeds
        mock_exporter = MagicMock()
        mock_export_service.return_value = mock_exporter

        # Import fails
        mock_importer = MagicMock()
        mock_importer.run_import.side_effect = MetabaseAPIError("Import failed")
        mock_import_service.return_value = mock_importer

        from sync_metabase import main

        # Should exit with code 3
        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 3
