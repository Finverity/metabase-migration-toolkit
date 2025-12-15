"""Metabase Export Tool.

This script connects to a source Metabase instance, traverses its collections,
and exports cards (questions) and dashboards into a structured directory layout.
It produces a `manifest.json` file that indexes the exported content, which is
used by the import script.

This is a thin CLI wrapper around the ExportService.
"""

import sys

from lib.client import (
    MetabaseAPIError,  # noqa: F401 - backward compat
    MetabaseClient,  # noqa: F401 - backward compat
)
from lib.config import get_export_args
from lib.services import ExportService
from lib.utils import setup_logging

# Backward compatibility alias - the old MetabaseExporter is now ExportService
MetabaseExporter = ExportService


def main() -> None:
    """Main entry point for the export tool."""
    config = get_export_args()
    setup_logging(config.log_level)
    exporter = ExportService(config)
    try:
        exporter.run_export()
    except MetabaseAPIError:
        sys.exit(1)
    except Exception:
        sys.exit(2)


if __name__ == "__main__":
    main()
