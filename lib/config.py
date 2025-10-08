"""
Handles loading configuration from CLI arguments and environment variables.
"""

import argparse
import os
from dataclasses import dataclass
from typing import Literal

from dotenv import find_dotenv, load_dotenv


@dataclass
class ExportConfig:
    """Configuration for the export script."""

    source_url: str
    export_dir: str
    source_username: str | None = None
    source_password: str | None = None
    source_session_token: str | None = None
    source_personal_token: str | None = None
    include_dashboards: bool = False
    include_archived: bool = False
    root_collection_ids: list[int] | None = None
    log_level: str = "INFO"


@dataclass
class ImportConfig:
    """Configuration for the import script."""

    target_url: str
    export_dir: str
    db_map_path: str
    target_username: str | None = None
    target_password: str | None = None
    target_session_token: str | None = None
    target_personal_token: str | None = None
    conflict_strategy: Literal["skip", "overwrite", "rename"] = "skip"
    dry_run: bool = False
    log_level: str = "INFO"


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

    # Optional arguments
    parser.add_argument(
        "--include-dashboards", action="store_true", help="Include dashboards in the export"
    )
    parser.add_argument(
        "--include-archived", action="store_true", help="Include archived items in the export"
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

    # Create config object, prioritizing CLI args, then env vars
    return ExportConfig(
        source_url=source_url,
        export_dir=args.export_dir,
        source_username=args.source_username or os.getenv("MB_SOURCE_USERNAME"),
        source_password=args.source_password or os.getenv("MB_SOURCE_PASSWORD"),
        source_session_token=args.source_session or os.getenv("MB_SOURCE_SESSION_TOKEN"),
        source_personal_token=args.source_token or os.getenv("MB_SOURCE_PERSONAL_TOKEN"),
        include_dashboards=args.include_dashboards,
        include_archived=args.include_archived,
        root_collection_ids=(
            [int(c_id) for c_id in args.root_collections.split(",")]
            if args.root_collections
            else None
        ),
        log_level=args.log_level,
    )


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

    return ImportConfig(
        target_url=target_url,
        export_dir=args.export_dir,
        db_map_path=args.db_map,
        target_username=args.target_username or os.getenv("MB_TARGET_USERNAME"),
        target_password=args.target_password or os.getenv("MB_TARGET_PASSWORD"),
        target_session_token=args.target_session or os.getenv("MB_TARGET_SESSION_TOKEN"),
        target_personal_token=args.target_token or os.getenv("MB_TARGET_PERSONAL_TOKEN"),
        conflict_strategy=args.conflict,
        dry_run=args.dry_run,
        log_level=args.log_level,
    )
