"""Metabase Import Tool.

This script reads an export package created by `export_metabase.py`, connects
to a target Metabase instance, and recreates the collections, cards, and
dashboards. It handles remapping database IDs and resolving conflicts.
"""

import datetime
import sys
from pathlib import Path

from lib.client import MetabaseAPIError, MetabaseClient
from lib.config import ImportConfig, get_import_args
from lib.conflict_resolution import ConflictResolver
from lib.id_remapping import IDRemapper
from lib.importers import CardImporter, CollectionImporter, DashboardImporter, PermissionsImporter
from lib.models import DatabaseMap, ImportReport, Manifest
from lib.utils import read_json_file, setup_logging, write_json_file
from lib.validation import ImportValidator

# Initialize logger
logger = setup_logging(__name__)


class MetabaseImporter:
    """Orchestrates the import of Metabase content using specialized modules."""

    def __init__(self, config: ImportConfig) -> None:
        """Initialize the MetabaseImporter with the given configuration."""
        self.config = config
        self.client = MetabaseClient(
            base_url=config.target_url,
            username=config.target_username,
            password=config.target_password,
            session_token=config.target_session_token,
            personal_token=config.target_personal_token,
        )
        self.export_dir = Path(config.export_dir)
        self.manifest: Manifest | None = None
        self.db_map: DatabaseMap | None = None
        self.report = ImportReport()

        # Specialized modules (initialized after manifest is loaded)
        self.id_remapper: IDRemapper | None = None
        self.validator: ImportValidator | None = None
        self.conflict_resolver: ConflictResolver | None = None

    def run_import(self) -> None:
        """Main entry point to start the import process."""
        logger.info(f"Starting Metabase import to {self.config.target_url}")
        logger.info(f"Loading export package from: {self.export_dir.resolve()}")

        try:
            self._load_export_package()

            if self.config.dry_run:
                self._perform_dry_run()
            else:
                self._perform_import()

        except MetabaseAPIError as e:
            logger.error(f"A Metabase API error occurred: {e}", exc_info=True)
            sys.exit(1)
        except (FileNotFoundError, ValueError) as e:
            logger.error(f"Failed to load export package: {e}", exc_info=True)
            sys.exit(2)
        except Exception as e:
            logger.error(f"An unexpected error occurred: {e}", exc_info=True)
            sys.exit(3)

    def _load_export_package(self) -> None:
        """Loads and validates the manifest and database mapping files."""
        manifest_path = self.export_dir / "manifest.json"
        if not manifest_path.exists():
            raise FileNotFoundError("manifest.json not found in the export directory.")

        manifest_data = read_json_file(manifest_path)
        # Reconstruct the manifest from dicts to dataclasses
        # Import the actual dataclasses from lib.models
        from lib.models import Card, Collection, Dashboard, ManifestMeta, PermissionGroup

        # Convert database keys from strings (JSON) back to integers
        # JSON serialization converts integer keys to strings, so we need to convert them back
        databases_dict = manifest_data.get("databases", {})
        databases_with_int_keys = {int(k): v for k, v in databases_dict.items()}

        # Convert database_metadata keys from strings to integers as well
        database_metadata_dict = manifest_data.get("database_metadata", {})
        database_metadata_with_int_keys = {int(k): v for k, v in database_metadata_dict.items()}

        self.manifest = Manifest(
            meta=ManifestMeta(**manifest_data["meta"]),
            databases=databases_with_int_keys,
            collections=[Collection(**c) for c in manifest_data.get("collections", [])],
            cards=[Card(**c) for c in manifest_data.get("cards", [])],
            dashboards=[Dashboard(**d) for d in manifest_data.get("dashboards", [])],
            permission_groups=[
                PermissionGroup(**g) for g in manifest_data.get("permission_groups", [])
            ],
            permissions_graph=manifest_data.get("permissions_graph", {}),
            collection_permissions_graph=manifest_data.get("collection_permissions_graph", {}),
            database_metadata=database_metadata_with_int_keys,
        )

        db_map_path = Path(self.config.db_map_path)
        if not db_map_path.exists():
            raise FileNotFoundError(f"Database mapping file not found at {db_map_path}")

        db_map_data = read_json_file(db_map_path)
        self.db_map = DatabaseMap(
            by_id=db_map_data.get("by_id", {}), by_name=db_map_data.get("by_name", {})
        )
        logger.info("Export package loaded successfully.")

        # Initialize specialized modules
        self.id_remapper = IDRemapper(self.client, self.manifest, self.db_map)
        self.validator = ImportValidator(
            self.client, self.manifest, self.id_remapper, self.config.include_archived
        )
        self.conflict_resolver = ConflictResolver(self.client, self.config.conflict_strategy)

    def _perform_dry_run(self) -> None:
        """Simulates the import process and reports on planned actions."""
        logger.info("--- Starting Dry Run ---")

        unmapped_dbs = self.validator.validate_database_mappings()
        if unmapped_dbs:
            self.validator.report_unmapped_databases(unmapped_dbs)

        logger.info("✅ Database mappings are valid.")

        # In a real dry run, we would fetch target state to predict actions
        # For this version, we will assume creation if not found
        logger.info("\n--- Import Plan ---")
        logger.info(f"Conflict Strategy: {self.config.conflict_strategy.upper()}")

        logger.info("\nCollections:")
        for collection in sorted(self.manifest.collections, key=lambda c: c.path):
            logger.info(f"  [CREATE] Collection '{collection.name}' at path '{collection.path}'")

        logger.info("\nCards:")
        for card in sorted(self.manifest.cards, key=lambda c: c.file_path):
            if card.archived and not self.config.include_archived:
                continue
            logger.info(f"  [CREATE] Card '{card.name}' from '{card.file_path}'")

        if self.manifest.dashboards:
            logger.info("\nDashboards:")
            for dash in sorted(self.manifest.dashboards, key=lambda d: d.file_path):
                if dash.archived and not self.config.include_archived:
                    continue
                logger.info(f"  [CREATE] Dashboard '{dash.name}' from '{dash.file_path}'")

        logger.info("\n--- Dry Run Complete ---")
        sys.exit(0)

    def _perform_import(self) -> None:
        """Executes the full import process using specialized modules."""
        logger.info("--- Starting Import ---")

        # Validate all database mappings
        self.validator.validate_all()

        # Build table and field ID mappings
        logger.info("Building table and field ID mappings...")
        self.id_remapper.build_table_and_field_mappings()

        # Import collections
        collection_importer = CollectionImporter(
            self.client, self.manifest, self.conflict_resolver, self.report
        )
        collection_map = collection_importer.import_collections()

        # Import cards
        card_importer = CardImporter(
            self.client,
            self.manifest,
            self.id_remapper,
            self.conflict_resolver,
            self.report,
            self.export_dir,
            collection_map,
            self.config.include_archived,
        )
        card_map = card_importer.import_cards()

        # Import dashboards
        if self.manifest.dashboards:
            dashboard_importer = DashboardImporter(
                self.client,
                self.manifest,
                self.id_remapper,
                self.conflict_resolver,
                self.report,
                self.export_dir,
                collection_map,
                card_map,
                self.config.include_archived,
            )
            dashboard_importer.import_dashboards()

        # Apply permissions after all content is imported
        if self.config.apply_permissions and self.manifest.permission_groups:
            logger.info("\nApplying permissions...")
            permissions_importer = PermissionsImporter(
                self.client,
                self.manifest,
                self.id_remapper,
                self.report,
                self.export_dir,
                collection_map,
            )
            permissions_importer.import_permissions()

        logger.info("\n--- Import Summary ---")
        summary = self.report.summary
        logger.info(
            f"Collections: {summary['collections']['created']} created, {summary['collections']['updated']} updated, {summary['collections']['skipped']} skipped, {summary['collections']['failed']} failed."
        )
        logger.info(
            f"Cards: {summary['cards']['created']} created, {summary['cards']['updated']} updated, {summary['cards']['skipped']} skipped, {summary['cards']['failed']} failed."
        )
        if self.manifest.dashboards:
            logger.info(
                f"Dashboards: {summary['dashboards']['created']} created, {summary['dashboards']['updated']} updated, {summary['dashboards']['skipped']} skipped, {summary['dashboards']['failed']} failed."
            )

        report_path = (
            self.export_dir
            / f"import_report_{datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d_%H%M%S')}.json"
        )
        write_json_file(self.report, report_path)
        logger.info(f"Full import report saved to {report_path}")

        if any(s["failed"] > 0 for s in summary.values()):
            logger.error("Import finished with one or more failures.")
            sys.exit(4)
        else:
            logger.info("Import completed successfully.")
            sys.exit(0)


def main() -> None:
    """Main entry point for the import tool."""
    config = get_import_args()
    setup_logging(config.log_level)
    importer = MetabaseImporter(config)
    importer.run_import()


if __name__ == "__main__":
    main()
