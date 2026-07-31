"""Unit tests for the CLI argument error paths in lib/config.py.

tests/test_config.py covers successful parsing and model validation. This module
targets the parser.error() branches — missing required URLs, unparsable version
strings, malformed comma-separated ID lists and both failure branches around
config construction — plus the validators that reject bad enum values.

Every CLI test neutralises python-dotenv so the repository's own .env file cannot
leak values into the parsed configuration.
"""

import os
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from lib.config import (
    ConfigValidationError,
    ExportConfig,
    ImportConfig,
    SyncConfig,
    _validate_url,
    get_export_args,
    get_import_args,
    get_sync_args,
)


def run_cli(func, argv: list[str], env: dict[str, str] | None = None):
    """Invoke a get_*_args function with a controlled environment and argv."""
    with (
        patch.dict(os.environ, env or {}, clear=True),
        patch("lib.config.load_dotenv"),
        patch("lib.config.find_dotenv", return_value=""),
        patch("sys.argv", argv),
    ):
        return func()


def assert_cli_error(func, argv, capsys, expected: str, env: dict[str, str] | None = None) -> None:
    """Assert that the CLI exits and writes the expected message to stderr."""
    with pytest.raises(SystemExit):
        run_cli(func, argv, env)

    assert expected in capsys.readouterr().err


# ============================================================================
# Field validators
# ============================================================================


class TestUrlValidator:
    """Tests for the shared _validate_url helper."""

    def test_rejects_url_without_host(self):
        with pytest.raises(ConfigValidationError, match="must include a host"):
            _validate_url("https://", "source_url")

    def test_rejects_non_http_scheme(self):
        with pytest.raises(ConfigValidationError, match="must use http or https scheme"):
            _validate_url("ftp://example.com", "source_url")

    def test_accepts_http_and_https(self):
        assert _validate_url("http://example.com", "source_url") == "http://example.com"
        assert _validate_url("https://example.com/", "source_url") == "https://example.com"


class TestEnumValidators:
    """Tests for log_level and conflict_strategy validation on every config model."""

    def test_export_config_rejects_bad_log_level(self):
        with pytest.raises(ValidationError, match="log_level must be one of"):
            ExportConfig(
                source_url="https://example.com",
                export_dir="./export",
                source_session_token="tok",
                log_level="LOUD",
            )

    def test_import_config_rejects_bad_log_level(self, tmp_path):
        with pytest.raises(ValidationError, match="log_level must be one of"):
            ImportConfig(
                target_url="https://example.com",
                export_dir=str(tmp_path),
                db_map_path=str(tmp_path / "db_map.json"),
                target_session_token="tok",
                log_level="LOUD",
            )

    @pytest.mark.parametrize("model", [ImportConfig, SyncConfig])
    def test_conflict_strategy_validator_rejects_unknown_value(self, model):
        """The field type is a Literal, so the validator is exercised directly."""
        with pytest.raises(ConfigValidationError, match="conflict_strategy must be one of"):
            model.validate_conflict_strategy("explode")

    @pytest.mark.parametrize("model", [ImportConfig, SyncConfig])
    def test_conflict_strategy_validator_normalises_case(self, model):
        assert model.validate_conflict_strategy("SKIP") == "skip"

    def test_sync_config_empty_id_lists_become_none(self, tmp_path):
        """Empty lists mean 'no restriction' and are normalised to None."""
        config = SyncConfig(
            source_url="https://source.example.com",
            source_session_token="tok",
            target_url="https://target.example.com",
            target_session_token="tok",
            export_dir=str(tmp_path),
            db_map_path=str(tmp_path / "db_map.json"),
            root_collection_ids=[],
            exclude_database_ids=[],
        )

        assert config.root_collection_ids is None
        assert config.exclude_database_ids is None

    def test_sync_config_rejects_non_positive_database_id(self, tmp_path):
        with pytest.raises(ValidationError, match="Database IDs must be positive integers"):
            SyncConfig(
                source_url="https://source.example.com",
                source_session_token="tok",
                target_url="https://target.example.com",
                target_session_token="tok",
                export_dir=str(tmp_path),
                db_map_path=str(tmp_path / "db_map.json"),
                exclude_database_ids=[1, 0],
            )

    def test_sync_config_rejects_non_positive_collection_id(self, tmp_path):
        with pytest.raises(ValidationError, match="Collection IDs must be positive integers"):
            SyncConfig(
                source_url="https://source.example.com",
                source_session_token="tok",
                target_url="https://target.example.com",
                target_session_token="tok",
                export_dir=str(tmp_path),
                db_map_path=str(tmp_path / "db_map.json"),
                root_collection_ids=[-1],
            )


# ============================================================================
# get_export_args
# ============================================================================


class TestGetExportArgsErrors:
    """Tests for the parser.error() paths in get_export_args."""

    BASE = [
        "export_metabase.py",
        "--export-dir",
        "./export",
        "--source-session",
        "tok",
        "--source-url",
        "https://s.example.com",
    ]

    def test_missing_source_url(self, capsys):
        assert_cli_error(
            get_export_args,
            ["export_metabase.py", "--export-dir", "./export"],
            capsys,
            "--source-url is required",
        )

    def test_invalid_metabase_version_from_env(self, capsys):
        """--metabase-version is constrained by argparse; the env var is not."""
        assert_cli_error(
            get_export_args,
            self.BASE,
            capsys,
            "Unsupported Metabase version 'v99'",
            env={"MB_METABASE_VERSION": "v99"},
        )

    def test_invalid_root_collections(self, capsys):
        assert_cli_error(
            get_export_args,
            self.BASE + ["--root-collections", "1,x"],
            capsys,
            "--root-collections must be comma-separated integers",
        )

    def test_config_validation_error_is_reported(self, capsys):
        """A bare ConfigValidationError surfaces with its own message."""
        with patch(
            "lib.config.ExportConfig",
            side_effect=ConfigValidationError("export_dir is not writable"),
        ):
            assert_cli_error(get_export_args, self.BASE, capsys, "export_dir is not writable")

    def test_pydantic_error_is_reported(self, capsys):
        """Other failures are wrapped as 'Configuration error'."""
        with patch("lib.config.ExportConfig", side_effect=RuntimeError("model exploded")):
            assert_cli_error(
                get_export_args, self.BASE, capsys, "Configuration error: model exploded"
            )

    def test_model_validation_failure_is_reported(self, capsys):
        """A real Pydantic failure (missing auth) exits with a configuration error."""
        assert_cli_error(
            get_export_args,
            [
                "export_metabase.py",
                "--export-dir",
                "./export",
                "--source-url",
                "https://s.example.com",
            ],
            capsys,
            "Configuration error",
        )

    def test_valid_version_from_env_is_used(self):
        config = run_cli(get_export_args, self.BASE, env={"MB_METABASE_VERSION": "v57"})
        assert str(config.metabase_version) == "v57"


# ============================================================================
# get_import_args
# ============================================================================


class TestGetImportArgsErrors:
    """Tests for the parser.error() paths in get_import_args."""

    def base(self, tmp_path) -> list[str]:
        return [
            "import_metabase.py",
            "--export-dir",
            str(tmp_path),
            "--db-map",
            str(tmp_path / "db_map.json"),
            "--target-session",
            "tok",
            "--target-url",
            "https://t.example.com",
        ]

    def test_missing_target_url(self, tmp_path, capsys):
        assert_cli_error(
            get_import_args,
            [
                "import_metabase.py",
                "--export-dir",
                str(tmp_path),
                "--db-map",
                str(tmp_path / "db_map.json"),
            ],
            capsys,
            "--target-url is required",
        )

    def test_invalid_metabase_version_from_env(self, tmp_path, capsys):
        assert_cli_error(
            get_import_args,
            self.base(tmp_path),
            capsys,
            "Unsupported Metabase version 'v99'",
            env={"MB_METABASE_VERSION": "v99"},
        )

    def test_config_validation_error_is_reported(self, tmp_path, capsys):
        with patch(
            "lib.config.ImportConfig",
            side_effect=ConfigValidationError("db_map_path escapes the export dir"),
        ):
            assert_cli_error(
                get_import_args,
                self.base(tmp_path),
                capsys,
                "db_map_path escapes the export dir",
            )

    def test_pydantic_error_is_reported(self, tmp_path, capsys):
        with patch("lib.config.ImportConfig", side_effect=RuntimeError("model exploded")):
            assert_cli_error(
                get_import_args,
                self.base(tmp_path),
                capsys,
                "Configuration error: model exploded",
            )


# ============================================================================
# get_sync_args
# ============================================================================


class TestGetSyncArgsErrors:
    """Tests for the parser.error() paths in get_sync_args."""

    def base(self, tmp_path, *, source_url=True, target_url=True) -> list[str]:
        argv = [
            "sync_metabase.py",
            "--export-dir",
            str(tmp_path),
            "--db-map",
            str(tmp_path / "db_map.json"),
            "--source-session",
            "tok",
            "--target-session",
            "tok",
        ]
        if source_url:
            argv += ["--source-url", "https://s.example.com"]
        if target_url:
            argv += ["--target-url", "https://t.example.com"]
        return argv

    def test_missing_source_url(self, tmp_path, capsys):
        assert_cli_error(
            get_sync_args,
            self.base(tmp_path, source_url=False),
            capsys,
            "--source-url is required",
        )

    def test_missing_target_url(self, tmp_path, capsys):
        assert_cli_error(
            get_sync_args,
            self.base(tmp_path, target_url=False),
            capsys,
            "--target-url is required",
        )

    def test_invalid_metabase_version_from_env(self, tmp_path, capsys):
        assert_cli_error(
            get_sync_args,
            self.base(tmp_path),
            capsys,
            "Unsupported Metabase version 'v99'",
            env={"MB_METABASE_VERSION": "v99"},
        )

    def test_invalid_root_collections(self, tmp_path, capsys):
        assert_cli_error(
            get_sync_args,
            self.base(tmp_path) + ["--root-collections", "1,x"],
            capsys,
            "--root-collections must be comma-separated integers",
        )

    def test_invalid_exclude_databases(self, tmp_path, capsys):
        assert_cli_error(
            get_sync_args,
            self.base(tmp_path) + ["--exclude-databases", "4,x"],
            capsys,
            "--exclude-databases must be comma-separated integers",
        )

    def test_config_validation_error_is_reported(self, tmp_path, capsys):
        with patch(
            "lib.config.SyncConfig",
            side_effect=ConfigValidationError("source_url must include a host"),
        ):
            assert_cli_error(
                get_sync_args, self.base(tmp_path), capsys, "source_url must include a host"
            )

    def test_pydantic_error_is_reported(self, tmp_path, capsys):
        with patch("lib.config.SyncConfig", side_effect=RuntimeError("model exploded")):
            assert_cli_error(
                get_sync_args,
                self.base(tmp_path),
                capsys,
                "Configuration error: model exploded",
            )

    def test_exclude_databases_parsed_into_config(self, tmp_path):
        config = run_cli(get_sync_args, self.base(tmp_path) + ["--exclude-databases", " 4 , 24 "])

        assert config.exclude_database_ids == [4, 24]

    def test_root_collections_parsed_into_config(self, tmp_path):
        config = run_cli(get_sync_args, self.base(tmp_path) + ["--root-collections", "1, 2"])

        assert config.root_collection_ids == [1, 2]
