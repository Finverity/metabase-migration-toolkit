"""Metabase Sync Tool.

This script combines export and import into a single operation. It connects to a
source Metabase instance, exports its content, and then imports it to a target
Metabase instance.

This is a thin CLI wrapper that orchestrates ExportService and ImportService.
"""

import logging
import sys

from lib.client import MetabaseAPIError
from lib.config import get_sync_args
from lib.services import ExportService, ImportService
from lib.utils import setup_logging

logger = logging.getLogger("metabase_migration")


def main() -> None:
    """Main entry point for the sync tool."""
    config = get_sync_args()
    setup_logging(config.log_level)

    logger.info("=" * 60)
    logger.info("METABASE SYNC - Export and Import in One Operation")
    logger.info("=" * 60)
    logger.info(f"Source: {config.source_url}")
    logger.info(f"Target: {config.target_url}")
    logger.info(f"Export directory: {config.export_dir}")
    logger.info("=" * 60)

    # Phase 1: Export
    logger.info("")
    logger.info("PHASE 1: EXPORT")
    logger.info("-" * 40)

    export_config = config.to_export_config()
    exporter = ExportService(export_config)

    try:
        exporter.run_export()
        logger.info("Export completed successfully")
    except MetabaseAPIError as e:
        logger.error(f"Export failed with API error: {e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Export failed with unexpected error: {e}")
        sys.exit(2)

    # Phase 2: Import
    logger.info("")
    logger.info("PHASE 2: IMPORT")
    logger.info("-" * 40)

    import_config = config.to_import_config()
    importer = ImportService(import_config)

    try:
        importer.run_import()
        logger.info("Import completed successfully")
    except MetabaseAPIError as e:
        logger.error(f"Import failed with API error: {e}")
        sys.exit(3)
    except (FileNotFoundError, ValueError) as e:
        logger.error(f"Import failed to load export package: {e}")
        sys.exit(4)
    except RuntimeError as e:
        logger.error(f"Import failed with runtime error: {e}")
        sys.exit(5)
    except Exception as e:
        logger.error(f"Import failed with unexpected error: {e}")
        sys.exit(6)

    # Success
    logger.info("")
    logger.info("=" * 60)
    logger.info("SYNC COMPLETED SUCCESSFULLY")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
