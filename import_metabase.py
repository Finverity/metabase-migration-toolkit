"""Metabase Import Tool.

This script reads an export package created by `export_metabase.py`, connects
to a target Metabase instance, and recreates the collections, cards, and
dashboards. It handles remapping database IDs and resolving conflicts.

This is a thin CLI wrapper around the ImportService.
"""

import sys

from lib.client import (
    MetabaseAPIError,  # noqa: F401 - backward compat
    MetabaseClient,  # noqa: F401 - backward compat
)
from lib.config import get_import_args
from lib.services import ImportService
from lib.utils import setup_logging

# Backward compatibility alias - the old MetabaseImporter is now ImportService
MetabaseImporter = ImportService


def main() -> None:
    """Main entry point for the import tool."""
    config = get_import_args()
    setup_logging(config.log_level)
    importer = ImportService(config)
    try:
        importer.run_import()
    except MetabaseAPIError:
        sys.exit(1)
    except (FileNotFoundError, ValueError):
        sys.exit(2)
    except RuntimeError:
        sys.exit(4)
    except Exception:
        sys.exit(3)


if __name__ == "__main__":
    main()
