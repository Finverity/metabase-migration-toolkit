"""Handles loading configuration from CLI arguments and environment variables."""

import argparse
import os
from typing import Literal
from urllib.parse import urlparse

from dotenv import find_dotenv, load_dotenv
from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from lib.constants import (
    DEFAULT_METABASE_VERSION,
    SUPPORTED_METABASE_VERSIONS,
    MetabaseVersion,
)


class ConfigValidationError(ValueError):
    """Raised when configuration validation fails."""

    def __init__(self, message: str, field: str | None = None) -> None:
        """Initialize configuration validation error with message and optional field."""
        self.field = field
        super().__init__(message)


def _parse_metabase_version(version_str: str | None) -> MetabaseVersion:
    """Parse and validate a Metabase version string.

    Args:
        version_str: Version string (e.g., "v56") or None for default.

    Returns:
        The corresponding MetabaseVersion enum value.

    Raises:
        ValueError: If the version string is not supported.
    """
    if version_str is None:
        return DEFAULT_METABASE_VERSION

    version_lower = version_str.lower().strip()
    try:
        return MetabaseVersion(version_lower)
    except ValueError:
        supported = ", ".join(SUPPORTED_METABASE_VERSIONS)
        raise ValueError(
            f"Unsupported Metabase version '{version_str}'. " f"Supported versions: {supported}"
        ) from None


# Valid log levels
VALID_LOG_LEVELS = frozenset({"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"})

# Valid conflict strategies
VALID_CONFLICT_STRATEGIES = frozenset({"skip", "overwrite", "rename"})


def _validate_url(url: str, field_name: str) -> str:
    """Validate that a URL uses http or https scheme.

    Args:
        url: The URL to validate.
        field_name: Name of the field for error messages.

    Returns:
        The validated URL (stripped of trailing slashes).

    Raises:
        ConfigValidationError: If the URL is invalid.
    """
    url = url.strip().rstrip("/")

    if not url:
        raise ConfigValidationError(f"{field_name} cannot be empty", field=field_name)

    parsed = urlparse(url)

    if not parsed.scheme:
        raise ConfigValidationError(
            f"{field_name} must include a scheme (http:// or https://)",
            field=field_name,
        )

    if parsed.scheme.lower() not in ("http", "https"):
        raise ConfigValidationError(
            f"{field_name} must use http or https scheme, got '{parsed.scheme}'",
            field=field_name,
        )

    if not parsed.netloc:
        raise ConfigValidationError(
            f"{field_name} must include a host",
            field=field_name,
        )

    return url


def _validate_path_no_traversal(path: str, field_name: str) -> str:
    """Validate that a path doesn't contain path traversal attempts.

    Args:
        path: The path to validate.
        field_name: Name of the field for error messages.

    Returns:
        The validated path.

    Raises:
        ConfigValidationError: If the path contains traversal patterns.
    """
    if not path or not path.strip():
        raise ConfigValidationError(f"{field_name} cannot be empty", field=field_name)

    # Check for path traversal patterns
    # Normalize path separators for cross-platform check
    normalized = path.replace("\\", "/")

    # Check for obvious traversal patterns
    traversal_patterns = ["../", "..\\", "/.."]
    for pattern in traversal_patterns:
        if pattern in normalized or normalized.endswith(".."):
            raise ConfigValidationError(
                f"{field_name} contains path traversal pattern",
                field=field_name,
            )

    return path


class ExportConfig(BaseModel):
    """Configuration for the export script with validation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_url: str
    export_dir: str
    metabase_version: MetabaseVersion = DEFAULT_METABASE_VERSION
    source_username: str | None = None
    source_password: str | None = None
    source_session_token: str | None = None
    source_personal_token: str | None = None
    include_dashboards: bool = False
    include_archived: bool = False
    include_permissions: bool = False
    root_collection_ids: list[int] | None = None
    log_level: str = "INFO"

    @field_validator("source_url")
    @classmethod
    def validate_source_url(cls, v: str) -> str:
        """Validate source URL uses http/https."""
        return _validate_url(v, "source_url")

    @field_validator("export_dir")
    @classmethod
    def validate_export_dir(cls, v: str) -> str:
        """Validate export directory path."""
        return _validate_path_no_traversal(v, "export_dir")

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        """Validate log level is a valid Python logging level."""
        v_upper = v.upper()
        if v_upper not in VALID_LOG_LEVELS:
            raise ConfigValidationError(
                f"log_level must be one of {sorted(VALID_LOG_LEVELS)}, got '{v}'",
                field="log_level",
            )
        return v_upper

    @field_validator("root_collection_ids")
    @classmethod
    def validate_collection_ids(cls, v: list[int] | None) -> list[int] | None:
        """Validate that collection IDs are positive integers."""
        if v is None:
            return v

        if not v:
            return None  # Empty list treated as None (export all)

        for i, collection_id in enumerate(v):
            if collection_id <= 0:
                raise ConfigValidationError(
                    f"Collection IDs must be positive integers, got {collection_id} at index {i}",
                    field="root_collection_ids",
                )

        return v

    @model_validator(mode="after")
    def validate_authentication(self) -> "ExportConfig":
        """Validate that at least one authentication method is provided."""
        has_credentials = self.source_username and self.source_password
        has_session = self.source_session_token is not None
        has_token = self.source_personal_token is not None

        if not (has_credentials or has_session or has_token):
            raise ConfigValidationError(
                "At least one authentication method required: "
                "username/password, session token, or personal API token",
                field="authentication",
            )

        return self


class ImportConfig(BaseModel):
    """Configuration for the import script with validation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    target_url: str
    export_dir: str
    db_map_path: str
    metabase_version: MetabaseVersion = DEFAULT_METABASE_VERSION
    target_username: str | None = None
    target_password: str | None = None
    target_session_token: str | None = None
    target_personal_token: str | None = None
    conflict_strategy: Literal["skip", "overwrite", "rename"] = "skip"
    dry_run: bool = False
    include_archived: bool = False
    apply_permissions: bool = False
    log_level: str = "INFO"

    @field_validator("target_url")
    @classmethod
    def validate_target_url(cls, v: str) -> str:
        """Validate target URL uses http/https."""
        return _validate_url(v, "target_url")

    @field_validator("export_dir")
    @classmethod
    def validate_export_dir(cls, v: str) -> str:
        """Validate export directory path."""
        return _validate_path_no_traversal(v, "export_dir")

    @field_validator("db_map_path")
    @classmethod
    def validate_db_map_path(cls, v: str) -> str:
        """Validate database map path."""
        return _validate_path_no_traversal(v, "db_map_path")

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        """Validate log level is a valid Python logging level."""
        v_upper = v.upper()
        if v_upper not in VALID_LOG_LEVELS:
            raise ConfigValidationError(
                f"log_level must be one of {sorted(VALID_LOG_LEVELS)}, got '{v}'",
                field="log_level",
            )
        return v_upper

    @field_validator("conflict_strategy")
    @classmethod
    def validate_conflict_strategy(cls, v: str) -> str:
        """Validate conflict strategy is valid."""
        v_lower = v.lower()
        if v_lower not in VALID_CONFLICT_STRATEGIES:
            raise ConfigValidationError(
                f"conflict_strategy must be one of {sorted(VALID_CONFLICT_STRATEGIES)}, got '{v}'",
                field="conflict_strategy",
            )
        return v_lower

    @model_validator(mode="after")
    def validate_authentication(self) -> "ImportConfig":
        """Validate that at least one authentication method is provided."""
        has_credentials = self.target_username and self.target_password
        has_session = self.target_session_token is not None
        has_token = self.target_personal_token is not None

        if not (has_credentials or has_session or has_token):
            raise ConfigValidationError(
                "At least one authentication method required: "
                "username/password, session token, or personal API token",
                field="authentication",
            )

        return self


def get_export_args() -> ExportConfig:
    """Parses CLI arguments for the export script."""
    load_dotenv(find_dotenv(usecwd=True))
    parser = argparse.ArgumentParser(description="Metabase Export Tool")

    # Required arguments (can also be set via .env)
    parser.add_argument("--source-url", help="Source Metabase instance URL (or use MB_SOURCE_URL)")
    parser.add_argument("--export-dir", required=True, help="Directory to save the exported files")

    # Authentication group
    auth_group = parser.add_mutually_exclusive_group(required=False)
    auth_group.add_argument(
        "--source-username", help="Source Metabase username (or use MB_SOURCE_USERNAME)"
    )
    auth_group.add_argument(
        "--source-session", help="Source Metabase session token (or use MB_SOURCE_SESSION_TOKEN)"
    )
    auth_group.add_argument(
        "--source-token",
        help="Source Metabase personal API token (or use MB_SOURCE_PERSONAL_TOKEN)",
    )
    parser.add_argument(
        "--source-password", help="Source Metabase password (or use MB_SOURCE_PASSWORD)"
    )

    # Metabase version configuration
    parser.add_argument(
        "--metabase-version",
        choices=list(SUPPORTED_METABASE_VERSIONS),
        help=f"Metabase version to use for export (or use MB_METABASE_VERSION). "
        f"Supported: {', '.join(SUPPORTED_METABASE_VERSIONS)}",
    )

    # Optional arguments
    parser.add_argument(
        "--include-dashboards", action="store_true", help="Include dashboards in the export"
    )
    parser.add_argument(
        "--include-archived", action="store_true", help="Include archived items in the export"
    )
    parser.add_argument(
        "--include-permissions",
        action="store_true",
        help="Include permissions (groups and access control) in the export",
    )
    parser.add_argument(
        "--root-collections",
        help="Comma-separated list of root collection IDs to export (empty=all)",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level",
    )

    args = parser.parse_args()

    # Get source_url from args or env
    source_url = args.source_url or os.getenv("MB_SOURCE_URL")
    if not source_url:
        parser.error("--source-url is required (or set MB_SOURCE_URL in .env)")

    # Get metabase_version from args or env
    version_str = args.metabase_version or os.getenv("MB_METABASE_VERSION")
    metabase_version: MetabaseVersion = DEFAULT_METABASE_VERSION
    try:
        metabase_version = _parse_metabase_version(version_str)
    except ValueError as e:
        parser.error(str(e))  # parser.error() raises SystemExit, never returns

    # Parse root collection IDs
    root_collection_ids: list[int] | None = None
    if args.root_collections:
        try:
            root_collection_ids = [int(c_id.strip()) for c_id in args.root_collections.split(",")]
        except ValueError:
            parser.error(
                f"--root-collections must be comma-separated integers, got '{args.root_collections}'"
            )

    # Create config object with validation
    try:
        return ExportConfig(
            source_url=source_url,
            export_dir=args.export_dir,
            metabase_version=metabase_version,
            source_username=args.source_username or os.getenv("MB_SOURCE_USERNAME"),
            source_password=args.source_password or os.getenv("MB_SOURCE_PASSWORD"),
            source_session_token=args.source_session or os.getenv("MB_SOURCE_SESSION_TOKEN"),
            source_personal_token=args.source_token or os.getenv("MB_SOURCE_PERSONAL_TOKEN"),
            include_dashboards=args.include_dashboards,
            include_archived=args.include_archived,
            include_permissions=args.include_permissions,
            root_collection_ids=root_collection_ids,
            log_level=args.log_level,
        )
    except ConfigValidationError as e:
        parser.error(str(e))
        raise  # Unreachable: parser.error() raises SystemExit
    except Exception as e:
        # Handle Pydantic validation errors
        parser.error(f"Configuration error: {e}")
        raise  # Unreachable: parser.error() raises SystemExit


def get_import_args() -> ImportConfig:
    """Parses CLI arguments for the import script."""
    load_dotenv(find_dotenv(usecwd=True))
    parser = argparse.ArgumentParser(description="Metabase Import Tool")

    # Required arguments (can also be set via .env)
    parser.add_argument("--target-url", help="Target Metabase instance URL (or use MB_TARGET_URL)")
    parser.add_argument(
        "--export-dir", required=True, help="Directory containing the exported files"
    )
    parser.add_argument(
        "--db-map",
        required=True,
        help="Path to the JSON file mapping source DB IDs to target DB IDs",
    )

    # Authentication group
    auth_group = parser.add_mutually_exclusive_group(required=False)
    auth_group.add_argument(
        "--target-username", help="Target Metabase username (or use MB_TARGET_USERNAME)"
    )
    auth_group.add_argument(
        "--target-session", help="Target Metabase session token (or use MB_TARGET_SESSION_TOKEN)"
    )
    auth_group.add_argument(
        "--target-token",
        help="Target Metabase personal API token (or use MB_TARGET_PERSONAL_TOKEN)",
    )
    parser.add_argument(
        "--target-password", help="Target Metabase password (or use MB_TARGET_PASSWORD)"
    )

    # Metabase version configuration
    parser.add_argument(
        "--metabase-version",
        choices=list(SUPPORTED_METABASE_VERSIONS),
        help=f"Metabase version of target instance (or use MB_METABASE_VERSION). "
        f"Supported: {', '.join(SUPPORTED_METABASE_VERSIONS)}",
    )

    # Optional arguments
    parser.add_argument(
        "--conflict",
        default="skip",
        choices=["skip", "overwrite", "rename"],
        help="Conflict resolution strategy",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Perform a dry run without making any changes"
    )
    parser.add_argument(
        "--include-archived", action="store_true", help="Include archived items in the import"
    )
    parser.add_argument(
        "--apply-permissions",
        action="store_true",
        help="Apply permissions from the export (requires admin privileges)",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level",
    )

    args = parser.parse_args()

    # Get target_url from args or env
    target_url = args.target_url or os.getenv("MB_TARGET_URL")
    if not target_url:
        parser.error("--target-url is required (or set MB_TARGET_URL in .env)")

    # Get metabase_version from args or env
    version_str = args.metabase_version or os.getenv("MB_METABASE_VERSION")
    metabase_version: MetabaseVersion = DEFAULT_METABASE_VERSION
    try:
        metabase_version = _parse_metabase_version(version_str)
    except ValueError as e:
        parser.error(str(e))  # parser.error() raises SystemExit, never returns

    # Create config object with validation
    try:
        return ImportConfig(
            target_url=target_url,
            export_dir=args.export_dir,
            db_map_path=args.db_map,
            metabase_version=metabase_version,
            target_username=args.target_username or os.getenv("MB_TARGET_USERNAME"),
            target_password=args.target_password or os.getenv("MB_TARGET_PASSWORD"),
            target_session_token=args.target_session or os.getenv("MB_TARGET_SESSION_TOKEN"),
            target_personal_token=args.target_token or os.getenv("MB_TARGET_PERSONAL_TOKEN"),
            conflict_strategy=args.conflict,
            dry_run=args.dry_run,
            include_archived=args.include_archived,
            apply_permissions=args.apply_permissions,
            log_level=args.log_level,
        )
    except ConfigValidationError as e:
        parser.error(str(e))
        raise  # Unreachable: parser.error() raises SystemExit
    except Exception as e:
        # Handle Pydantic validation errors
        parser.error(f"Configuration error: {e}")
        raise  # Unreachable: parser.error() raises SystemExit


class SyncConfig(BaseModel):
    """Configuration for the sync script (export + import) with validation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    # Source instance configuration
    source_url: str
    source_username: str | None = None
    source_password: str | None = None
    source_session_token: str | None = None
    source_personal_token: str | None = None

    # Target instance configuration
    target_url: str
    target_username: str | None = None
    target_password: str | None = None
    target_session_token: str | None = None
    target_personal_token: str | None = None

    # Shared configuration
    export_dir: str
    db_map_path: str
    metabase_version: MetabaseVersion = DEFAULT_METABASE_VERSION
    log_level: str = "INFO"

    # Export options
    include_dashboards: bool = False
    include_archived: bool = False
    include_permissions: bool = False
    root_collection_ids: list[int] | None = None

    # Import options
    conflict_strategy: Literal["skip", "overwrite", "rename"] = "skip"
    dry_run: bool = False
    apply_permissions: bool = False

    @field_validator("source_url")
    @classmethod
    def validate_source_url(cls, v: str) -> str:
        """Validate source URL uses http/https."""
        return _validate_url(v, "source_url")

    @field_validator("target_url")
    @classmethod
    def validate_target_url(cls, v: str) -> str:
        """Validate target URL uses http/https."""
        return _validate_url(v, "target_url")

    @field_validator("export_dir")
    @classmethod
    def validate_export_dir(cls, v: str) -> str:
        """Validate export directory path."""
        return _validate_path_no_traversal(v, "export_dir")

    @field_validator("db_map_path")
    @classmethod
    def validate_db_map_path(cls, v: str) -> str:
        """Validate database map path."""
        return _validate_path_no_traversal(v, "db_map_path")

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        """Validate log level is a valid Python logging level."""
        v_upper = v.upper()
        if v_upper not in VALID_LOG_LEVELS:
            raise ConfigValidationError(
                f"log_level must be one of {sorted(VALID_LOG_LEVELS)}, got '{v}'",
                field="log_level",
            )
        return v_upper

    @field_validator("conflict_strategy")
    @classmethod
    def validate_conflict_strategy(cls, v: str) -> str:
        """Validate conflict strategy is valid."""
        v_lower = v.lower()
        if v_lower not in VALID_CONFLICT_STRATEGIES:
            raise ConfigValidationError(
                f"conflict_strategy must be one of {sorted(VALID_CONFLICT_STRATEGIES)}, got '{v}'",
                field="conflict_strategy",
            )
        return v_lower

    @field_validator("root_collection_ids")
    @classmethod
    def validate_collection_ids(cls, v: list[int] | None) -> list[int] | None:
        """Validate that collection IDs are positive integers."""
        if v is None:
            return v

        if not v:
            return None  # Empty list treated as None (export all)

        for i, collection_id in enumerate(v):
            if collection_id <= 0:
                raise ConfigValidationError(
                    f"Collection IDs must be positive integers, got {collection_id} at index {i}",
                    field="root_collection_ids",
                )

        return v

    @model_validator(mode="after")
    def validate_authentication(self) -> "SyncConfig":
        """Validate that at least one authentication method is provided for both source and target."""
        # Validate source authentication
        has_source_credentials = self.source_username and self.source_password
        has_source_session = self.source_session_token is not None
        has_source_token = self.source_personal_token is not None

        if not (has_source_credentials or has_source_session or has_source_token):
            raise ConfigValidationError(
                "At least one source authentication method required: "
                "username/password, session token, or personal API token",
                field="source_authentication",
            )

        # Validate target authentication
        has_target_credentials = self.target_username and self.target_password
        has_target_session = self.target_session_token is not None
        has_target_token = self.target_personal_token is not None

        if not (has_target_credentials or has_target_session or has_target_token):
            raise ConfigValidationError(
                "At least one target authentication method required: "
                "username/password, session token, or personal API token",
                field="target_authentication",
            )

        return self

    def to_export_config(self) -> ExportConfig:
        """Convert to ExportConfig for the export phase."""
        return ExportConfig(
            source_url=self.source_url,
            export_dir=self.export_dir,
            metabase_version=self.metabase_version,
            source_username=self.source_username,
            source_password=self.source_password,
            source_session_token=self.source_session_token,
            source_personal_token=self.source_personal_token,
            include_dashboards=self.include_dashboards,
            include_archived=self.include_archived,
            include_permissions=self.include_permissions,
            root_collection_ids=self.root_collection_ids,
            log_level=self.log_level,
        )

    def to_import_config(self) -> ImportConfig:
        """Convert to ImportConfig for the import phase."""
        return ImportConfig(
            target_url=self.target_url,
            export_dir=self.export_dir,
            db_map_path=self.db_map_path,
            metabase_version=self.metabase_version,
            target_username=self.target_username,
            target_password=self.target_password,
            target_session_token=self.target_session_token,
            target_personal_token=self.target_personal_token,
            conflict_strategy=self.conflict_strategy,
            dry_run=self.dry_run,
            include_archived=self.include_archived,
            apply_permissions=self.apply_permissions,
            log_level=self.log_level,
        )


def get_sync_args() -> SyncConfig:
    """Parses CLI arguments for the sync script."""
    load_dotenv(find_dotenv(usecwd=True))
    parser = argparse.ArgumentParser(
        description="Metabase Sync Tool - Export from source and import to target in one operation"
    )

    # Source instance configuration
    source_group = parser.add_argument_group("Source Instance")
    source_group.add_argument(
        "--source-url", help="Source Metabase instance URL (or use MB_SOURCE_URL)"
    )
    source_auth = source_group.add_mutually_exclusive_group(required=False)
    source_auth.add_argument(
        "--source-username", help="Source Metabase username (or use MB_SOURCE_USERNAME)"
    )
    source_auth.add_argument(
        "--source-session", help="Source Metabase session token (or use MB_SOURCE_SESSION_TOKEN)"
    )
    source_auth.add_argument(
        "--source-token",
        help="Source Metabase personal API token (or use MB_SOURCE_PERSONAL_TOKEN)",
    )
    source_group.add_argument(
        "--source-password", help="Source Metabase password (or use MB_SOURCE_PASSWORD)"
    )

    # Target instance configuration
    target_group = parser.add_argument_group("Target Instance")
    target_group.add_argument(
        "--target-url", help="Target Metabase instance URL (or use MB_TARGET_URL)"
    )
    target_auth = target_group.add_mutually_exclusive_group(required=False)
    target_auth.add_argument(
        "--target-username", help="Target Metabase username (or use MB_TARGET_USERNAME)"
    )
    target_auth.add_argument(
        "--target-session", help="Target Metabase session token (or use MB_TARGET_SESSION_TOKEN)"
    )
    target_auth.add_argument(
        "--target-token",
        help="Target Metabase personal API token (or use MB_TARGET_PERSONAL_TOKEN)",
    )
    target_group.add_argument(
        "--target-password", help="Target Metabase password (or use MB_TARGET_PASSWORD)"
    )

    # Shared configuration
    parser.add_argument(
        "--export-dir",
        required=True,
        help="Directory to save/load exported files",
    )
    parser.add_argument(
        "--db-map",
        required=True,
        help="Path to the JSON file mapping source DB IDs to target DB IDs",
    )
    parser.add_argument(
        "--metabase-version",
        choices=list(SUPPORTED_METABASE_VERSIONS),
        help=f"Metabase version (or use MB_METABASE_VERSION). "
        f"Supported: {', '.join(SUPPORTED_METABASE_VERSIONS)}",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level",
    )

    # Export options
    export_group = parser.add_argument_group("Export Options")
    export_group.add_argument(
        "--include-dashboards", action="store_true", help="Include dashboards in the export"
    )
    export_group.add_argument(
        "--include-archived", action="store_true", help="Include archived items"
    )
    export_group.add_argument(
        "--include-permissions",
        action="store_true",
        help="Include permissions (groups and access control)",
    )
    export_group.add_argument(
        "--root-collections",
        help="Comma-separated list of root collection IDs to export (empty=all)",
    )

    # Import options
    import_group = parser.add_argument_group("Import Options")
    import_group.add_argument(
        "--conflict",
        default="skip",
        choices=["skip", "overwrite", "rename"],
        help="Conflict resolution strategy",
    )
    import_group.add_argument(
        "--dry-run", action="store_true", help="Perform a dry run without making any changes"
    )
    import_group.add_argument(
        "--apply-permissions",
        action="store_true",
        help="Apply permissions from the export (requires admin privileges)",
    )

    args = parser.parse_args()

    # Get URLs from args or env
    source_url = args.source_url or os.getenv("MB_SOURCE_URL")
    if not source_url:
        parser.error("--source-url is required (or set MB_SOURCE_URL in .env)")

    target_url = args.target_url or os.getenv("MB_TARGET_URL")
    if not target_url:
        parser.error("--target-url is required (or set MB_TARGET_URL in .env)")

    # Get metabase_version from args or env
    version_str = args.metabase_version or os.getenv("MB_METABASE_VERSION")
    metabase_version: MetabaseVersion = DEFAULT_METABASE_VERSION
    try:
        metabase_version = _parse_metabase_version(version_str)
    except ValueError as e:
        parser.error(str(e))  # parser.error() raises SystemExit, never returns

    # Parse root collection IDs
    root_collection_ids: list[int] | None = None
    if args.root_collections:
        try:
            root_collection_ids = [int(c_id.strip()) for c_id in args.root_collections.split(",")]
        except ValueError:
            parser.error(
                f"--root-collections must be comma-separated integers, got '{args.root_collections}'"
            )

    # Create config object with validation
    try:
        return SyncConfig(
            source_url=source_url,
            source_username=args.source_username or os.getenv("MB_SOURCE_USERNAME"),
            source_password=args.source_password or os.getenv("MB_SOURCE_PASSWORD"),
            source_session_token=args.source_session or os.getenv("MB_SOURCE_SESSION_TOKEN"),
            source_personal_token=args.source_token or os.getenv("MB_SOURCE_PERSONAL_TOKEN"),
            target_url=target_url,
            target_username=args.target_username or os.getenv("MB_TARGET_USERNAME"),
            target_password=args.target_password or os.getenv("MB_TARGET_PASSWORD"),
            target_session_token=args.target_session or os.getenv("MB_TARGET_SESSION_TOKEN"),
            target_personal_token=args.target_token or os.getenv("MB_TARGET_PERSONAL_TOKEN"),
            export_dir=args.export_dir,
            db_map_path=args.db_map,
            metabase_version=metabase_version,
            include_dashboards=args.include_dashboards,
            include_archived=args.include_archived,
            include_permissions=args.include_permissions,
            root_collection_ids=root_collection_ids,
            conflict_strategy=args.conflict,
            dry_run=args.dry_run,
            apply_permissions=args.apply_permissions,
            log_level=args.log_level,
        )
    except ConfigValidationError as e:
        parser.error(str(e))
        raise  # Unreachable: parser.error() raises SystemExit
    except Exception as e:
        # Handle Pydantic validation errors
        parser.error(f"Configuration error: {e}")
        raise  # Unreachable: parser.error() raises SystemExit
