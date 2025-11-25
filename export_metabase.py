"""Metabase Export Tool.

This script connects to a source Metabase instance, traverses its collections,
and exports cards (questions) and dashboards into a structured directory layout.
It produces a `manifest.json` file that indexes the exported content, which is
used by the import script.
"""

import dataclasses
import datetime
import sys
from pathlib import Path

from lib.client import MetabaseAPIError, MetabaseClient
from lib.config import ExportConfig, get_export_args
from lib.exporters import (
    CardExporter,
    CollectionExporter,
    DashboardExporter,
    DatabaseExporter,
    PermissionsExporter,
)
from lib.models import Manifest, ManifestMeta
from lib.utils import TOOL_VERSION, setup_logging, write_json_file

# Initialize logger
logger = setup_logging(__name__)


class MetabaseExporter:
    """Handles the logic for exporting content from a Metabase instance."""

    def __init__(self, config: ExportConfig) -> None:
        """Initialize the MetabaseExporter with the given configuration."""
        self.config = config
        self.client = MetabaseClient(
            base_url=config.source_url,
            username=config.source_username,
            password=config.source_password,
            session_token=config.source_session_token,
            personal_token=config.source_personal_token,
        )
        self.export_dir = Path(config.export_dir)
        self.manifest = self._initialize_manifest()

    def _initialize_manifest(self) -> Manifest:
        """Initializes the manifest with metadata."""
        cli_args = dataclasses.asdict(self.config)
        # Redact secrets from the manifest
        for secret in ["source_password", "source_session_token", "source_personal_token"]:
            if cli_args.get(secret):
                cli_args[secret] = "********"

        meta = ManifestMeta(
            source_url=self.config.source_url,
            export_timestamp=datetime.datetime.utcnow().isoformat(),
            tool_version=TOOL_VERSION,
            cli_args=cli_args,
        )
        return Manifest(meta=meta)

    def run_export(self) -> None:
        """Main entry point to start the export process."""
        logger.info(f"Starting Metabase export from {self.config.source_url}")
        logger.info(f"Export directory: {self.export_dir.resolve()}")

        self.export_dir.mkdir(parents=True, exist_ok=True)

        try:
            # Initialize specialized exporters
            database_exporter = DatabaseExporter(self.client, self.manifest)
            database_exporter.export_databases()

            # Fetch collection tree
            logger.info("Fetching collection tree...")
            collection_tree = self.client.get_collections_tree(
                params={"archived": self.config.include_archived}
            )

            # Filter tree if root_collection_ids are specified
            if self.config.root_collection_ids:
                collection_tree = [
                    c for c in collection_tree if c.get("id") in self.config.root_collection_ids
                ]
                logger.info(
                    f"Export restricted to root collections: {self.config.root_collection_ids}"
                )

            if not collection_tree:
                logger.warning("No collections found to export.")
                return

            # Initialize card and dashboard exporters
            card_exporter = CardExporter(
                self.client,
                self.manifest,
                self.export_dir,
                {},  # collection_path_map will be updated
            )
            dashboard_exporter = DashboardExporter(
                self.client, self.manifest, self.export_dir, card_exporter, {}
            )

            # Initialize collection exporter with card and dashboard exporters
            collection_exporter = CollectionExporter(
                self.client,
                self.manifest,
                self.export_dir,
                self.config,
                card_exporter,
                dashboard_exporter,
            )

            # Update the collection_path_map references
            card_exporter.collection_path_map = collection_exporter.collection_path_map
            dashboard_exporter.collection_path_map = collection_exporter.collection_path_map

            # Export collections and their contents
            collection_exporter.export_collections(collection_tree)

            # Export permissions if requested
            if self.config.include_permissions:
                permissions_exporter = PermissionsExporter(self.client, self.manifest)
                permissions_exporter.export_permissions()

            # Write the final manifest file
            manifest_path = self.export_dir / "manifest.json"
            logger.info(f"Writing manifest to {manifest_path}")
            write_json_file(self.manifest, manifest_path)

            # Print summary
            logger.info("=" * 80)
            logger.info("Export Summary:")
            logger.info(f"  Collections: {len(self.manifest.collections)}")
            logger.info(f"  Cards: {len(self.manifest.cards)}")
            logger.info(f"  Dashboards: {len(self.manifest.dashboards)}")
            logger.info(f"  Databases: {len(self.manifest.databases)}")
            if self.config.include_permissions:
                logger.info(f"  Permission Groups: {len(self.manifest.permission_groups)}")
            logger.info("=" * 80)
            logger.info("Export completed successfully.")
            sys.exit(0)

        except MetabaseAPIError as e:
            logger.error(f"A Metabase API error occurred: {e}", exc_info=True)
            sys.exit(1)
        except Exception as e:
            logger.error(f"An unexpected error occurred: {e}", exc_info=True)
            sys.exit(2)


def main() -> None:
    """Main entry point for the export tool."""
    config = get_export_args()
    setup_logging(config.log_level)
    exporter = MetabaseExporter(config)
    exporter.run_export()


if __name__ == "__main__":
    main()
