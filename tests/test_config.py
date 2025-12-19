"""
Unit tests for lib/config.py

Tests configuration loading from CLI arguments and environment variables,
including Pydantic validation.
"""

import os
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from lib.config import (
    ConfigValidationError,
    ExportConfig,
    ImportConfig,
    _validate_path_no_traversal,
    _validate_url,
)


class TestExportConfig:
    """Test suite for ExportConfig Pydantic model."""

    def test_export_config_creation(self):
        """Test creating an ExportConfig instance."""
        config = ExportConfig(
            source_url="https://example.com",
            export_dir="./export",
            source_username="user@example.com",
            source_password="password123",  # pragma: allowlist secret
            include_dashboards=True,
            include_archived=False,
            root_collection_ids=[1, 2, 3],
            log_level="INFO",
        )

        assert config.source_url == "https://example.com"
        assert config.export_dir == "./export"
        assert config.source_username == "user@example.com"
        assert config.source_password == "password123"  # pragma: allowlist secret
        assert config.include_dashboards is True
        assert config.include_archived is False
        assert config.root_collection_ids == [1, 2, 3]
        assert config.log_level == "INFO"

    def test_export_config_defaults(self):
        """Test ExportConfig with default values."""
        config = ExportConfig(
            source_url="https://example.com",
            export_dir="./export",
            source_session_token="token123",  # Authentication required
        )

        assert config.source_username is None
        assert config.source_password is None
        assert config.source_session_token == "token123"
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

    def test_export_config_url_trailing_slash_stripped(self):
        """Test that trailing slashes are stripped from URLs."""
        config = ExportConfig(
            source_url="https://example.com/",
            export_dir="./export",
            source_session_token="token123",
        )

        assert config.source_url == "https://example.com"

    def test_export_config_log_level_uppercase(self):
        """Test that log level is uppercased."""
        config = ExportConfig(
            source_url="https://example.com",
            export_dir="./export",
            source_session_token="token123",
            log_level="debug",
        )

        assert config.log_level == "DEBUG"

    def test_export_config_immutable(self):
        """Test that ExportConfig is immutable (frozen)."""
        config = ExportConfig(
            source_url="https://example.com",
            export_dir="./export",
            source_session_token="token123",
        )

        with pytest.raises(ValidationError):
            config.source_url = "https://other.com"


class TestExportConfigValidation:
    """Test validation errors for ExportConfig."""

    def test_invalid_url_scheme(self):
        """Test that non-http/https schemes are rejected."""
        with pytest.raises(ValidationError) as exc_info:
            ExportConfig(
                source_url="ftp://example.com",
                export_dir="./export",
                source_session_token="token123",
            )

        assert "http or https" in str(exc_info.value)

    def test_missing_url_scheme(self):
        """Test that URLs without scheme are rejected."""
        with pytest.raises(ValidationError) as exc_info:
            ExportConfig(
                source_url="example.com",
                export_dir="./export",
                source_session_token="token123",
            )

        assert "scheme" in str(exc_info.value)

    def test_empty_url(self):
        """Test that empty URLs are rejected."""
        with pytest.raises(ValidationError) as exc_info:
            ExportConfig(
                source_url="",
                export_dir="./export",
                source_session_token="token123",
            )

        assert "empty" in str(exc_info.value).lower()

    def test_path_traversal_rejected(self):
        """Test that path traversal patterns are rejected."""
        with pytest.raises(ValidationError) as exc_info:
            ExportConfig(
                source_url="https://example.com",
                export_dir="../../../etc",
                source_session_token="token123",
            )

        assert "traversal" in str(exc_info.value)

    def test_invalid_log_level(self):
        """Test that invalid log levels are rejected."""
        with pytest.raises(ValidationError) as exc_info:
            ExportConfig(
                source_url="https://example.com",
                export_dir="./export",
                source_session_token="token123",
                log_level="VERBOSE",
            )

        assert "log_level" in str(exc_info.value)

    def test_negative_collection_ids(self):
        """Test that negative collection IDs are rejected."""
        with pytest.raises(ValidationError) as exc_info:
            ExportConfig(
                source_url="https://example.com",
                export_dir="./export",
                source_session_token="token123",
                root_collection_ids=[1, -2, 3],
            )

        assert "positive" in str(exc_info.value).lower()

    def test_zero_collection_id(self):
        """Test that zero collection IDs are rejected."""
        with pytest.raises(ValidationError) as exc_info:
            ExportConfig(
                source_url="https://example.com",
                export_dir="./export",
                source_session_token="token123",
                root_collection_ids=[0],
            )

        assert "positive" in str(exc_info.value).lower()

    def test_missing_authentication(self):
        """Test that missing authentication is rejected."""
        with pytest.raises(ValidationError) as exc_info:
            ExportConfig(
                source_url="https://example.com",
                export_dir="./export",
            )

        assert "authentication" in str(exc_info.value).lower()

    def test_username_without_password(self):
        """Test that username without password is rejected."""
        with pytest.raises(ValidationError) as exc_info:
            ExportConfig(
                source_url="https://example.com",
                export_dir="./export",
                source_username="user@example.com",
            )

        assert "authentication" in str(exc_info.value).lower()

    def test_password_without_username(self):
        """Test that password without username is rejected."""
        with pytest.raises(ValidationError) as exc_info:
            ExportConfig(
                source_url="https://example.com",
                export_dir="./export",
                source_password="password123",  # pragma: allowlist secret
            )

        assert "authentication" in str(exc_info.value).lower()

    def test_empty_collection_ids_becomes_none(self):
        """Test that empty collection IDs list becomes None."""
        config = ExportConfig(
            source_url="https://example.com",
            export_dir="./export",
            source_session_token="token123",
            root_collection_ids=[],
        )

        assert config.root_collection_ids is None

    def test_extra_fields_rejected(self):
        """Test that extra fields are rejected."""
        with pytest.raises(ValidationError) as exc_info:
            ExportConfig(
                source_url="https://example.com",
                export_dir="./export",
                source_session_token="token123",
                unknown_field="value",
            )

        assert "extra" in str(exc_info.value).lower()


class TestImportConfig:
    """Test suite for ImportConfig Pydantic model."""

    def test_import_config_creation(self):
        """Test creating an ImportConfig instance."""
        config = ImportConfig(
            target_url="https://example.com",
            export_dir="./export",
            db_map_path="./db_map.json",
            target_username="user@example.com",
            target_password="password123",  # pragma: allowlist secret
            conflict_strategy="skip",
            dry_run=False,
            log_level="INFO",
        )

        assert config.target_url == "https://example.com"
        assert config.export_dir == "./export"
        assert config.db_map_path == "./db_map.json"
        assert config.target_username == "user@example.com"
        assert config.target_password == "password123"  # pragma: allowlist secret
        assert config.conflict_strategy == "skip"
        assert config.dry_run is False
        assert config.log_level == "INFO"

    def test_import_config_defaults(self):
        """Test ImportConfig with default values."""
        config = ImportConfig(
            target_url="https://example.com",
            export_dir="./export",
            db_map_path="./db_map.json",
            target_session_token="token123",  # Authentication required
        )

        assert config.target_username is None
        assert config.target_password is None
        assert config.target_session_token == "token123"
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
                target_session_token="token123",
                conflict_strategy=strategy,
            )
            assert config.conflict_strategy == strategy

    def test_import_config_dry_run(self):
        """Test ImportConfig with dry_run enabled."""
        config = ImportConfig(
            target_url="https://example.com",
            export_dir="./export",
            db_map_path="./db_map.json",
            target_session_token="token123",
            dry_run=True,
        )

        assert config.dry_run is True


class TestImportConfigValidation:
    """Test validation errors for ImportConfig."""

    def test_invalid_conflict_strategy(self):
        """Test that invalid conflict strategy is rejected."""
        with pytest.raises(ValidationError) as exc_info:
            ImportConfig(
                target_url="https://example.com",
                export_dir="./export",
                db_map_path="./db_map.json",
                target_session_token="token123",
                conflict_strategy="invalid",
            )

        assert "conflict" in str(exc_info.value).lower() or "literal" in str(exc_info.value).lower()

    def test_invalid_url_scheme(self):
        """Test that non-http/https schemes are rejected."""
        with pytest.raises(ValidationError) as exc_info:
            ImportConfig(
                target_url="file:///etc/passwd",
                export_dir="./export",
                db_map_path="./db_map.json",
                target_session_token="token123",
            )

        assert "http or https" in str(exc_info.value)

    def test_path_traversal_in_export_dir(self):
        """Test that path traversal in export_dir is rejected."""
        with pytest.raises(ValidationError) as exc_info:
            ImportConfig(
                target_url="https://example.com",
                export_dir="../../secrets",
                db_map_path="./db_map.json",
                target_session_token="token123",
            )

        assert "traversal" in str(exc_info.value)

    def test_path_traversal_in_db_map_path(self):
        """Test that path traversal in db_map_path is rejected."""
        with pytest.raises(ValidationError) as exc_info:
            ImportConfig(
                target_url="https://example.com",
                export_dir="./export",
                db_map_path="../../../etc/passwd",
                target_session_token="token123",
            )

        assert "traversal" in str(exc_info.value)

    def test_missing_authentication(self):
        """Test that missing authentication is rejected."""
        with pytest.raises(ValidationError) as exc_info:
            ImportConfig(
                target_url="https://example.com",
                export_dir="./export",
                db_map_path="./db_map.json",
            )

        assert "authentication" in str(exc_info.value).lower()


class TestValidationHelpers:
    """Test validation helper functions."""

    def test_validate_url_valid_https(self):
        """Test valid HTTPS URL."""
        result = _validate_url("https://example.com/path", "test_url")
        assert result == "https://example.com/path"

    def test_validate_url_valid_http(self):
        """Test valid HTTP URL."""
        result = _validate_url("http://localhost:3000", "test_url")
        assert result == "http://localhost:3000"

    def test_validate_url_strips_trailing_slash(self):
        """Test that trailing slashes are stripped."""
        result = _validate_url("https://example.com/", "test_url")
        assert result == "https://example.com"

    def test_validate_url_invalid_scheme(self):
        """Test invalid URL scheme."""
        with pytest.raises(ConfigValidationError) as exc_info:
            _validate_url("ftp://example.com", "test_url")

        assert exc_info.value.field == "test_url"
        assert "http or https" in str(exc_info.value)

    def test_validate_url_missing_scheme(self):
        """Test URL missing scheme."""
        with pytest.raises(ConfigValidationError) as exc_info:
            _validate_url("example.com", "test_url")

        assert exc_info.value.field == "test_url"
        assert "scheme" in str(exc_info.value)

    def test_validate_url_empty(self):
        """Test empty URL."""
        with pytest.raises(ConfigValidationError) as exc_info:
            _validate_url("", "test_url")

        assert exc_info.value.field == "test_url"
        assert "empty" in str(exc_info.value).lower()

    def test_validate_path_valid(self):
        """Test valid path."""
        result = _validate_path_no_traversal("./export/data", "test_path")
        assert result == "./export/data"

    def test_validate_path_traversal_dotdot(self):
        """Test path with .. traversal."""
        with pytest.raises(ConfigValidationError) as exc_info:
            _validate_path_no_traversal("../secret", "test_path")

        assert exc_info.value.field == "test_path"
        assert "traversal" in str(exc_info.value)

    def test_validate_path_traversal_middle(self):
        """Test path with .. in middle."""
        with pytest.raises(ConfigValidationError) as exc_info:
            _validate_path_no_traversal("/home/user/../../../etc", "test_path")

        assert "traversal" in str(exc_info.value)

    def test_validate_path_empty(self):
        """Test empty path."""
        with pytest.raises(ConfigValidationError) as exc_info:
            _validate_path_no_traversal("", "test_path")

        assert "empty" in str(exc_info.value).lower()


class TestGetExportArgs:
    """Test suite for get_export_args function."""

    @patch.dict(
        os.environ,
        {
            "MB_SOURCE_URL": "https://env.example.com",
            "MB_SOURCE_USERNAME": "env_user@example.com",
            "MB_SOURCE_PASSWORD": "env_password",  # pragma: allowlist secret
        },
    )
    @patch("sys.argv", ["export_metabase.py", "--export-dir", "./test_export"])
    def test_get_export_args_from_env(self):
        """Test loading export config from environment variables."""
        from lib.config import get_export_args

        config = get_export_args()

        assert config.source_url == "https://env.example.com"
        assert config.source_username == "env_user@example.com"
        assert config.source_password == "env_password"  # pragma: allowlist secret
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
        assert config.source_password == "cli_password"  # pragma: allowlist secret
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
            "--source-session",
            "session-token",
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
        # CLI session token should be used
        assert config.source_session_token == "session-token"


class TestGetImportArgs:
    """Test suite for get_import_args function."""

    @patch.dict(
        os.environ,
        {
            "MB_TARGET_URL": "https://env.example.com",
            "MB_TARGET_USERNAME": "env_user@example.com",
            "MB_TARGET_PASSWORD": "env_password",  # pragma: allowlist secret
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
        assert config.target_password == "env_password"  # pragma: allowlist secret
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
        assert config.target_password == "cli_password"  # pragma: allowlist secret
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
            "--target-session",
            "session-token",
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
        # CLI session token should be used
        assert config.target_session_token == "session-token"
