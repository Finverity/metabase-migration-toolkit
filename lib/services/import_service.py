"""Import service for orchestrating Metabase content import."""

import datetime
import logging
from pathlib import Path
from typing import Any

from lib.client import MetabaseAPIError, MetabaseClient
from lib.config import ImportConfig
from lib.constants import MetabaseVersion
from lib.handlers import (
    CardHandler,
    CollectionHandler,
    DashboardHandler,
    ImportContext,
    PermissionsHandler,
)
from lib.models import (
    Card,
    Collection,
    Dashboard,
    DatabaseMap,
    ImportReport,
    Manifest,
    ManifestMeta,
    PermissionGroup,
    UnmappedDatabase,
)
from lib.remapping import IDMapper, QueryRemapper
from lib.utils import read_json_file, write_json_file
from lib.version import validate_version_compatibility

logger = logging.getLogger("metabase_migration")


class ImportService:
    """Orchestrates the import of Metabase content from an export package."""

    def __init__(self, config: ImportConfig) -> None:
        """Initialize the ImportService.

        Args:
            config: The import configuration.
        """
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

        # These will be initialized after loading the manifest
        self._id_mapper: IDMapper | None = None
        self._query_remapper: QueryRemapper | None = None
        self._context: ImportContext | None = None

        # Backward compatibility: expose internal maps directly
        # These are populated after _load_export_package() is called
        self._collection_map: dict[int, int] = {}
        self._card_map: dict[int, int] = {}
        self._target_collections: list[dict[str, Any]] = []

    def _get_manifest(self) -> Manifest:
        """Returns manifest, ensuring it has been loaded."""
        if self.manifest is None:
            raise RuntimeError("Manifest not loaded")
        return self.manifest

    def _get_id_mapper(self) -> IDMapper:
        """Returns ID mapper, ensuring it has been initialized."""
        if self._id_mapper is None:
            raise RuntimeError("ID mapper not initialized")
        return self._id_mapper

    def _get_context(self) -> ImportContext:
        """Returns import context, ensuring it has been initialized."""
        if self._context is None:
            raise RuntimeError("Import context not initialized")
        return self._context

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
            raise
        except (FileNotFoundError, ValueError) as e:
            logger.error(f"Failed to load export package: {e}", exc_info=True)
            raise
        except Exception as e:
            logger.error(f"An unexpected error occurred: {e}", exc_info=True)
            raise

    def _load_export_package(self) -> None:
        """Loads and validates the manifest and database mapping files."""
        manifest_path = self.export_dir / "manifest.json"
        if not manifest_path.exists():
            raise FileNotFoundError("manifest.json not found in the export directory.")

        manifest_data = read_json_file(manifest_path)
        self.manifest = self._parse_manifest(manifest_data)

        # Validate Metabase version compatibility (strict validation)
        self._validate_metabase_version()

        db_map_path = Path(self.config.db_map_path)
        if not db_map_path.exists():
            raise FileNotFoundError(f"Database mapping file not found at {db_map_path}")

        db_map_data = read_json_file(db_map_path)
        self.db_map = DatabaseMap(
            by_id=db_map_data.get("by_id", {}),
            by_name=db_map_data.get("by_name", {}),
        )

        # Initialize mapping and context
        self._id_mapper = IDMapper(self.manifest, self.db_map, self.client)
        self._query_remapper = QueryRemapper(self._id_mapper)

        logger.info("Export package loaded successfully.")

    def _parse_manifest(self, manifest_data: dict[str, Any]) -> Manifest:
        """Parses raw manifest data into a Manifest object.

        Args:
            manifest_data: The raw manifest dictionary.

        Returns:
            The parsed Manifest object.
        """
        # Convert database keys from strings back to integers
        databases_dict = manifest_data.get("databases", {})
        databases_with_int_keys = {int(k): v for k, v in databases_dict.items()}

        database_metadata_dict = manifest_data.get("database_metadata", {})
        database_metadata_with_int_keys = {int(k): v for k, v in database_metadata_dict.items()}

        return Manifest(
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

    def _validate_metabase_version(self) -> None:
        """Validates Metabase version compatibility between export and target.

        Uses strict validation: source and target must be the same version.

        Raises:
            ValueError: If versions are incompatible or source version is missing.
        """
        manifest = self._get_manifest()
        source_version_str = manifest.meta.metabase_version
        target_version = self.config.metabase_version

        if source_version_str is None:
            logger.warning(
                "Export manifest does not contain Metabase version. "
                "This export was created with an older version of the toolkit. "
                f"Assuming target version '{target_version}' for compatibility check."
            )
            # For backward compatibility, assume the version matches if not specified
            return

        try:
            source_version = MetabaseVersion(source_version_str)
        except ValueError:
            raise ValueError(
                f"Export was created with unsupported Metabase version '{source_version_str}'. "
                f"Target version is '{target_version}'."
            ) from None

        logger.info(f"Export Metabase version: {source_version}")
        logger.info(f"Target Metabase version: {target_version}")

        validate_version_compatibility(source_version, target_version)

    def _validate_database_mappings(self) -> list[UnmappedDatabase]:
        """Validates that all databases referenced by cards have a mapping.

        Returns:
            List of unmapped databases.
        """
        manifest = self._get_manifest()
        id_mapper = self._get_id_mapper()
        unmapped: dict[int, UnmappedDatabase] = {}
        for card in manifest.cards:
            if card.archived and not self.config.include_archived:
                continue
            if card.database_id is None:
                continue
            target_db_id = id_mapper.resolve_db_id(card.database_id)
            if target_db_id is None:
                if card.database_id not in unmapped:
                    unmapped[card.database_id] = UnmappedDatabase(
                        source_db_id=card.database_id,
                        source_db_name=manifest.databases.get(card.database_id, "Unknown Name"),
                    )
                unmapped[card.database_id].card_ids.add(card.id)
        return list(unmapped.values())

    def _validate_target_databases(self) -> None:
        """Validates that all mapped database IDs exist in the target instance."""
        manifest = self._get_manifest()
        id_mapper = self._get_id_mapper()
        try:
            target_databases = self.client.get_databases()
            target_db_ids = {db["id"] for db in target_databases}

            mapped_target_ids = set()
            for source_db_id in manifest.databases.keys():
                target_id = id_mapper.resolve_db_id(source_db_id)
                if target_id:
                    mapped_target_ids.add(target_id)

            missing_ids = mapped_target_ids - target_db_ids

            if missing_ids:
                self._log_invalid_database_mapping(missing_ids, target_databases)
                raise ValueError(
                    f"Invalid database mapping: IDs {missing_ids} don't exist in target"
                )

            logger.info("All mapped database IDs are valid in the target instance.")

        except MetabaseAPIError as e:
            logger.error(f"Failed to validate database mappings: {e}")
            raise

    def _log_invalid_database_mapping(
        self, missing_ids: set[int], target_databases: list[dict[str, Any]]
    ) -> None:
        """Logs an error about invalid database mappings."""
        logger.error("=" * 80)
        logger.error("INVALID DATABASE MAPPING!")
        logger.error("=" * 80)
        logger.error("Your db_map.json references database IDs that don't exist in the target.")
        logger.error(f"Missing database IDs in target: {sorted(missing_ids)}")
        logger.error("")
        logger.error("Available databases in target instance:")
        for db in sorted(target_databases, key=lambda x: x["id"]):
            logger.error(f"  ID: {db['id']}, Name: '{db['name']}'")
        logger.error("")
        logger.error("SOLUTION: Update your db_map.json file with valid target IDs")
        logger.error("=" * 80)

    def _perform_dry_run(self) -> None:
        """Simulates the import process and reports on planned actions."""
        manifest = self._get_manifest()
        logger.info("--- Starting Dry Run ---")

        unmapped_dbs = self._validate_database_mappings()
        if unmapped_dbs:
            self._log_unmapped_databases_error(unmapped_dbs)
            raise ValueError("Unmapped databases found. Import cannot proceed.")

        logger.info("Database mappings are valid.")
        logger.info("\n--- Import Plan ---")
        logger.info(f"Conflict Strategy: {self.config.conflict_strategy.upper()}")

        logger.info("\nCollections:")
        for collection in sorted(manifest.collections, key=lambda c: c.path):
            logger.info(f"  [CREATE] Collection '{collection.name}' at path '{collection.path}'")

        logger.info("\nCards:")
        for card in sorted(manifest.cards, key=lambda c: c.file_path):
            if card.archived and not self.config.include_archived:
                continue
            logger.info(f"  [CREATE] Card '{card.name}' from '{card.file_path}'")

        if manifest.dashboards:
            logger.info("\nDashboards:")
            for dash in sorted(manifest.dashboards, key=lambda d: d.file_path):
                if dash.archived and not self.config.include_archived:
                    continue
                logger.info(f"  [CREATE] Dashboard '{dash.name}' from '{dash.file_path}'")

        logger.info("\n--- Dry Run Complete ---")

    def _perform_import(self) -> None:
        """Executes the full import process."""
        manifest = self._get_manifest()
        id_mapper = self._get_id_mapper()
        if self._query_remapper is None:
            raise RuntimeError("Query remapper not initialized")
        logger.info("--- Starting Import ---")

        unmapped_dbs = self._validate_database_mappings()
        if unmapped_dbs:
            self._log_unmapped_databases_error(unmapped_dbs)
            raise ValueError("Unmapped databases found. Import cannot proceed.")

        # Validate and build mappings
        logger.info("Validating database mappings against target instance...")
        self._validate_target_databases()

        logger.info("Building table and field ID mappings...")
        id_mapper.build_table_and_field_mappings()

        logger.info("Fetching existing collections from target...")
        target_collections = self.client.get_collections_tree(params={"archived": True})

        # Create the import context
        self._context = ImportContext(
            config=self.config,
            client=self.client,
            manifest=manifest,
            export_dir=self.export_dir,
            id_mapper=id_mapper,
            query_remapper=self._query_remapper,
            report=self.report,
            target_collections=target_collections,
        )

        # Run imports using handlers
        self._import_collections()

        # Pre-fetch collection items for O(1) conflict lookup
        # This must be done AFTER collections are imported so we have the collection mappings
        context = self._get_context()
        logger.info("Pre-fetching target collection items for conflict detection...")
        context.prefetch_collection_items()
        self._import_cards()
        if manifest.dashboards:
            self._import_dashboards()
        if self.config.apply_permissions and manifest.permission_groups:
            self._import_permissions()

        # Log summary and save report
        self._log_import_summary()
        self._save_report()

        if any(s["failed"] > 0 for s in self.report.summary.values()):
            logger.error("Import finished with one or more failures.")
            raise RuntimeError("Import finished with one or more failures.")
        else:
            logger.info("Import completed successfully.")

    def _import_collections(self) -> None:
        """Imports collections using the CollectionHandler."""
        context = self._get_context()
        manifest = self._get_manifest()
        handler = CollectionHandler(context)
        handler.import_collections(manifest.collections)

    def _import_cards(self) -> None:
        """Imports cards using the CardHandler."""
        context = self._get_context()
        manifest = self._get_manifest()
        handler = CardHandler(context)
        handler.import_cards(manifest.cards)

    def _import_dashboards(self) -> None:
        """Imports dashboards using the DashboardHandler."""
        context = self._get_context()
        manifest = self._get_manifest()
        handler = DashboardHandler(context)
        handler.import_dashboards(manifest.dashboards)

    def _import_permissions(self) -> None:
        """Imports permissions using the PermissionsHandler."""
        context = self._get_context()
        logger.info("\nApplying permissions...")
        handler = PermissionsHandler(context)
        handler.import_permissions()

    def _log_unmapped_databases_error(self, unmapped_dbs: list[UnmappedDatabase]) -> None:
        """Logs an error about unmapped databases."""
        logger.error("=" * 80)
        logger.error("DATABASE MAPPING ERROR!")
        logger.error("=" * 80)
        logger.error("Found unmapped databases. Import cannot proceed.")
        logger.error("")
        for db in unmapped_dbs:
            logger.error(f"  Source Database ID: {db.source_db_id}")
            logger.error(f"  Source Database Name: '{db.source_db_name}'")
            logger.error(f"  Used by {len(db.card_ids)} card(s)")
            logger.error("")
        logger.error("SOLUTION: Add mappings to your db_map.json file")
        logger.error("=" * 80)

    def _log_import_summary(self) -> None:
        """Logs the import summary."""
        manifest = self._get_manifest()
        logger.info("\n--- Import Summary ---")
        summary = self.report.summary
        logger.info(
            f"Collections: {summary['collections']['created']} created, "
            f"{summary['collections']['updated']} updated, "
            f"{summary['collections']['skipped']} skipped, "
            f"{summary['collections']['failed']} failed."
        )
        logger.info(
            f"Cards: {summary['cards']['created']} created, "
            f"{summary['cards']['updated']} updated, "
            f"{summary['cards']['skipped']} skipped, "
            f"{summary['cards']['failed']} failed."
        )
        if manifest.dashboards:
            logger.info(
                f"Dashboards: {summary['dashboards']['created']} created, "
                f"{summary['dashboards']['updated']} updated, "
                f"{summary['dashboards']['skipped']} skipped, "
                f"{summary['dashboards']['failed']} failed."
            )

    def _save_report(self) -> None:
        """Saves the import report to a file."""
        report_path = (
            self.export_dir
            / f"import_report_{datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d_%H%M%S')}.json"
        )
        write_json_file(self.report, report_path)
        logger.info(f"Full import report saved to {report_path}")
