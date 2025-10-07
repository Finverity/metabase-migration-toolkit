"""
General utility functions for logging, file operations, and string manipulation.
"""

import dataclasses
import hashlib
import json
import logging
import re
import sys
from pathlib import Path
from typing import Any

# Import version from package
try:
    from lib import __version__ as TOOL_VERSION
except ImportError:
    # Fallback for development
    TOOL_VERSION = "1.0.0"


class CustomJsonEncoder(json.JSONEncoder):
    """Custom JSON encoder to handle dataclasses."""

    def default(self, o: Any) -> Any:
        if dataclasses.is_dataclass(o):
            return dataclasses.asdict(o)
        return super().default(o)


def setup_logging(name_or_level: str = "INFO", level: str = None) -> logging.Logger:
    """
    Configures and returns a structured logger.

    Args:
        name_or_level: Either a logger name (e.g., __name__) or a log level (e.g., "INFO").
                       If it looks like a log level, it's used as the level.
                       If it looks like a module name, it's used as the logger name.
        level: Optional explicit log level. If provided, overrides name_or_level interpretation.

    Returns:
        A configured logger instance.
    """
    # Determine if first argument is a log level or a logger name
    log_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}

    if level is not None:
        # Explicit level provided
        log_level_str = level
        logger_name = (
            name_or_level if name_or_level.upper() not in log_levels else "metabase_migration"
        )
    elif name_or_level.upper() in log_levels:
        # First argument is a log level
        log_level_str = name_or_level
        logger_name = "metabase_migration"
    else:
        # First argument is a logger name
        logger_name = name_or_level
        log_level_str = "INFO"

    log_level = getattr(logging, log_level_str.upper(), logging.INFO)

    # Configure the root logger to ensure all loggers inherit the level and handler
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    # Only add handler if root logger doesn't have handlers
    if not root_logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
        handler.setFormatter(formatter)
        root_logger.addHandler(handler)

    # Get the specific logger (it will inherit from root)
    logger = logging.getLogger(logger_name)
    # Ensure logger uses root handlers to avoid duplicate outputs
    logger.propagate = True
    logger.setLevel(log_level)

    return logger


def sanitize_filename(name: str) -> str:
    """
    Sanitizes a string to be a valid filename.

    Args:
        name: The string to sanitize.

    Returns:
        A URL-safe, filesystem-safe version of the name.
    """
    # Replace slashes and backslashes with a space
    s = re.sub(r"[/\\]+", " ", name)
    # Remove invalid filename characters
    s = re.sub(r'[<>:"|?*]', "", s)
    # Replace multiple spaces/hyphens with a single hyphen
    s = re.sub(r"[\s_]+", "-", s).strip("-")
    # Truncate to a reasonable length
    return s[:100]


def calculate_checksum(file_path: Path) -> str:
    """
    Calculates the SHA256 checksum of a file.

    Args:
        file_path: Path to the file.

    Returns:
        The hex digest of the SHA256 hash.
    """
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256.update(byte_block)
    return sha256.hexdigest()


def write_json_file(data: Any, path: Path):
    """Writes a dictionary or dataclass to a JSON file with pretty printing."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, cls=CustomJsonEncoder, indent=2, ensure_ascii=False)


def read_json_file(path: Path) -> dict[str, Any]:
    """Reads a JSON file into a dictionary."""
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def clean_for_create(payload: dict[str, Any]) -> dict[str, Any]:
    """Removes immutable or server-generated fields before creating a new item."""
    # This list may need to be adjusted based on Metabase API version
    fields_to_remove = [
        "id",
        "creator_id",
        "creator",
        "created_at",
        "updated_at",
        "made_public_by_id",
        "public_uuid",
        "moderation_reviews",
        "can_write",
    ]
    cleaned = {k: v for k, v in payload.items() if k not in fields_to_remove}

    # Set table_id to null - it's instance-specific and will be auto-populated by Metabase
    # based on the query's source-table
    if "table_id" in cleaned:
        cleaned["table_id"] = None

    return cleaned


def clean_dashboard_for_update(payload: dict[str, Any]) -> dict[str, Any]:
    """Removes fields that should not be sent on a dashboard update."""
    cleaned = clean_for_create(payload)
    # Dashcards are updated via their own field, not at the top level
    if "dashcards" in cleaned:
        del cleaned["dashcards"]
    # Dash tabs are also updated via their own field
    if "tabs" in cleaned:
        del cleaned["tabs"]
    return cleaned
