"""Utility functions for the Metabase Migration Toolkit.

This module re-exports utilities from submodules for backward compatibility.
"""

from lib.utils.file_io import (
    CustomJsonEncoder,
    calculate_checksum,
    read_json_file,
    write_json_file,
)
from lib.utils.logging import setup_logging
from lib.utils.payload import clean_dashboard_for_update, clean_for_create
from lib.utils.sanitization import sanitize_filename

# Re-export TOOL_VERSION for backward compatibility
try:
    from lib import __version__ as TOOL_VERSION
except ImportError:
    TOOL_VERSION = "1.0.0"

__all__ = [
    # File I/O
    "CustomJsonEncoder",
    "read_json_file",
    "write_json_file",
    "calculate_checksum",
    # Logging
    "setup_logging",
    # Sanitization
    "sanitize_filename",
    # Payload cleaning
    "clean_for_create",
    "clean_dashboard_for_update",
    # Version
    "TOOL_VERSION",
]
