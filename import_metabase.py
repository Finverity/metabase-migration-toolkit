"""Metabase Import Tool.

This script reads an export package created by `export_metabase.py`, connects
to a target Metabase instance, and recreates the collections, cards, and
dashboards. It handles remapping database IDs and resolving conflicts.
"""

import copy
import datetime
import re
import sys
from pathlib import Path
from typing import Any, Literal, cast

from tqdm import tqdm

from lib.client import MetabaseAPIError, MetabaseClient
from lib.config import ImportConfig, get_import_args
from lib.models import DatabaseMap, ImportReport, ImportReportItem, Manifest, UnmappedDatabase
from lib.utils import (
    clean_for_create,
    read_json_file,
    sanitize_filename,
    setup_logging,
    write_json_file,
)

# Initialize logger
logger = setup_logging(__name__)


class MetabaseImporter:
    """Handles the logic for importing content into a Metabase instance."""

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

        # Mappings from source ID to target ID, populated during import
        self._collection_map: dict[int, int] = {}
        self._card_map: dict[int, int] = {}
        self._group_map: dict[int, int] = {}  # Maps source group IDs to target group IDs

        # Table and field mappings: (source_db_id, source_table_id) -> target_table_id
        self._table_map: dict[tuple[int, int], int] = {}
        # Field mappings: (source_db_id, source_field_id) -> target_field_id
        self._field_map: dict[tuple[int, int], int] = {}

        # Caches of existing items on the target instance
        self._target_collections: list[dict[str, Any]] = []
        # Cache of target database metadata: db_id -> {tables: [...], fields: [...]}
        self._target_db_metadata: dict[int, dict[str, Any]] = {}

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

    def _resolve_db_id(self, source_db_id: int) -> int | None:
        """Resolves a source database ID to a target database ID using the map."""
        # by_id takes precedence (db_map.json uses string keys for JSON compatibility)
        if str(source_db_id) in self.db_map.by_id:
            return self.db_map.by_id[str(source_db_id)]

        # Look up database name using integer key (manifest.databases now has int keys)
        source_db_name = self.manifest.databases.get(source_db_id)
        if source_db_name and source_db_name in self.db_map.by_name:
            return self.db_map.by_name[source_db_name]

        return None

    def _validate_database_mappings(self) -> list[UnmappedDatabase]:
        """Validates that all databases referenced by cards have a mapping."""
        unmapped: dict[int, UnmappedDatabase] = {}
        for card in self.manifest.cards:
            if not card.archived or self.config.include_archived:
                target_db_id = self._resolve_db_id(card.database_id)
                if target_db_id is None:
                    if card.database_id not in unmapped:
                        unmapped[card.database_id] = UnmappedDatabase(
                            source_db_id=card.database_id,
                            source_db_name=self.manifest.databases.get(
                                card.database_id, "Unknown Name"
                            ),
                        )
                    unmapped[card.database_id].card_ids.add(card.id)
        return list(unmapped.values())

    def _validate_target_databases(self) -> None:
        """Validates that all mapped database IDs actually exist in the target instance."""
        try:
            target_databases = self.client.get_databases()
            target_db_ids = {db["id"] for db in target_databases}

            # Collect all unique target database IDs from the mapping
            # manifest.databases now has integer keys after our fix
            mapped_target_ids = set()
            for source_db_id in self.manifest.databases.keys():
                target_id = self._resolve_db_id(source_db_id)
                if target_id:
                    mapped_target_ids.add(target_id)

            # Check if any mapped IDs don't exist in target
            missing_ids = mapped_target_ids - target_db_ids

            if missing_ids:
                logger.error("=" * 80)
                logger.error("❌ INVALID DATABASE MAPPING!")
                logger.error("=" * 80)
                logger.error(
                    "Your db_map.json references database IDs that don't exist in the target instance."
                )
                logger.error("")
                logger.error(f"Missing database IDs in target: {sorted(missing_ids)}")
                logger.error("")
                logger.error("Available databases in target instance:")
                for db in sorted(target_databases, key=lambda x: x["id"]):
                    logger.error(f"  ID: {db['id']}, Name: '{db['name']}'")
                logger.error("")
                logger.error("SOLUTION:")
                logger.error("1. Update your db_map.json file to use valid target database IDs")
                logger.error(
                    "2. Make sure you're mapping to databases that exist in the target instance"
                )
                logger.error("=" * 80)
                sys.exit(1)

            logger.info("✅ All mapped database IDs are valid in the target instance.")

        except MetabaseAPIError as e:
            logger.error(f"Failed to validate database mappings: {e}")
            sys.exit(1)

    def _build_table_and_field_mappings(self) -> None:
        """Builds mappings between source and target table/field IDs.

        This is necessary because table and field IDs are instance-specific.
        We match tables by name within the same database.
        """
        logger.info("Building table and field ID mappings...")

        try:
            # For each source database, get its target equivalent
            for source_db_id, source_db_name in self.manifest.databases.items():
                target_db_id = self._resolve_db_id(source_db_id)
                if not target_db_id:
                    logger.debug(f"Skipping table mapping for unmapped database {source_db_id}")
                    continue

                # Get source database metadata from manifest
                source_metadata = self.manifest.database_metadata.get(source_db_id, {})
                source_tables = source_metadata.get("tables", [])

                if not source_tables:
                    logger.debug(
                        f"No table metadata available for source database {source_db_id}. "
                        f"Table ID remapping will not work."
                    )
                    continue

                # Fetch target database metadata
                if target_db_id not in self._target_db_metadata:
                    logger.debug(f"Fetching metadata for target database {target_db_id}...")
                    try:
                        target_metadata_response = self.client.get_database_metadata(target_db_id)
                        self._target_db_metadata[target_db_id] = target_metadata_response
                    except MetabaseAPIError as e:
                        logger.warning(
                            f"Failed to fetch metadata for target database {target_db_id}: {e}. "
                            f"Table ID remapping will not work for this database."
                        )
                        continue

                target_metadata = self._target_db_metadata[target_db_id]
                # Build a map of table names to table objects in target
                target_tables_by_name = {t["name"]: t for t in target_metadata.get("tables", [])}
                target_fields_by_table_id = {}
                for table in target_metadata.get("tables", []):
                    target_fields_by_table_id[table["id"]] = {
                        f["name"]: f for f in table.get("fields", [])
                    }

                logger.debug(
                    f"Mapping tables from source DB {source_db_id} ({source_db_name}) "
                    f"to target DB {target_db_id}"
                )
                logger.debug(
                    f"  Source has {len(source_tables)} tables, "
                    f"target has {len(target_tables_by_name)} tables"
                )

                # Map each source table to target table by name
                for source_table in source_tables:
                    source_table_id = source_table["id"]
                    source_table_name = source_table["name"]

                    if source_table_name in target_tables_by_name:
                        target_table = target_tables_by_name[source_table_name]
                        target_table_id = target_table["id"]

                        # Store the mapping
                        mapping_key = (source_db_id, source_table_id)
                        self._table_map[mapping_key] = target_table_id

                        logger.debug(
                            f"  Mapped table '{source_table_name}': "
                            f"{source_table_id} (source) -> {target_table_id} (target)"
                        )

                        # Map fields within this table
                        source_fields = source_table.get("fields", [])
                        target_fields = target_fields_by_table_id.get(target_table_id, {})

                        for source_field in source_fields:
                            source_field_id = source_field["id"]
                            source_field_name = source_field["name"]

                            if source_field_name in target_fields:
                                target_field = target_fields[source_field_name]
                                target_field_id = target_field["id"]

                                # Store the field mapping
                                field_mapping_key = (source_db_id, source_field_id)
                                self._field_map[field_mapping_key] = target_field_id

                                logger.debug(
                                    f"    Mapped field '{source_field_name}': "
                                    f"{source_field_id} (source) -> {target_field_id} (target)"
                                )
                    else:
                        logger.warning(
                            f"  Table '{source_table_name}' (ID: {source_table_id}) "
                            f"not found in target database {target_db_id}. "
                            f"Cards using this table may fail to import."
                        )

        except Exception as e:
            logger.warning(f"Failed to build table and field mappings: {e}", exc_info=True)
            # This is not fatal - we'll try to import without mappings

    def _perform_dry_run(self) -> None:
        """Simulates the import process and reports on planned actions."""
        logger.info("--- Starting Dry Run ---")

        unmapped_dbs = self._validate_database_mappings()
        if unmapped_dbs:
            logger.error("!!! Found unmapped databases. Import cannot proceed. !!!")
            for db in unmapped_dbs:
                logger.error(
                    f"  - Source DB ID: {db.source_db_id} (Name: '{db.source_db_name}') is not mapped."
                )
                logger.error(
                    f"    Used by cards (IDs): {', '.join(map(str, sorted(db.card_ids)[:10]))}{'...' if len(db.card_ids) > 10 else ''}"
                )
            logger.error("Please update your database mapping file and try again.")
            sys.exit(1)
        else:
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
        """Executes the full import process."""
        logger.info("--- Starting Import ---")

        unmapped_dbs = self._validate_database_mappings()
        if unmapped_dbs:
            logger.error("=" * 80)
            logger.error("❌ DATABASE MAPPING ERROR!")
            logger.error("=" * 80)
            logger.error("Found unmapped databases. Import cannot proceed.")
            logger.error("")
            for db in unmapped_dbs:
                logger.error(f"  Source Database ID: {db.source_db_id}")
                logger.error(f"  Source Database Name: '{db.source_db_name}'")
                logger.error(f"  Used by {len(db.card_ids)} card(s)")
                logger.error("")
            logger.error("SOLUTION:")
            logger.error("1. Edit your db_map.json file")
            logger.error("2. Add mappings for the databases listed above")
            logger.error("3. Run the import again")
            logger.error("")
            logger.error("Example db_map.json structure:")
            logger.error("{")
            logger.error('  "by_id": {')
            logger.error('    "7": 2,  // Maps source DB ID 7 to target DB ID 2')
            logger.error('    "8": 3   // Maps source DB ID 8 to target DB ID 3')
            logger.error("  },")
            logger.error('  "by_name": {')
            logger.error('    "Production DB": 2,  // Maps by database name')
            logger.error('    "Analytics DB": 3')
            logger.error("  }")
            logger.error("}")
            logger.error("=" * 80)
            sys.exit(1)

        # Validate that mapped database IDs actually exist in target
        logger.info("Validating database mappings against target instance...")
        self._validate_target_databases()

        # Build table and field ID mappings
        logger.info("Building table and field ID mappings...")
        self._build_table_and_field_mappings()

        logger.info("Fetching existing collections from target...")
        self._target_collections = self.client.get_collections_tree(params={"archived": True})

        self._import_collections()
        self._import_cards()
        if self.manifest.dashboards:
            self._import_dashboards()

        # Apply permissions after all content is imported
        if self.config.apply_permissions and self.manifest.permission_groups:
            logger.info("\nApplying permissions...")
            self._import_permissions()

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

    def _find_target_collection_by_path(self, source_path: str) -> dict | None:
        """Finds an existing target collection by its sanitized path."""
        # This is an approximation. A perfect match requires traversing the target tree.
        # For now, we match on name and parent, which is reasonably robust.
        path_parts = source_path.replace("collections/", "").split("/")

        current_parent_id = None
        found_collection = None

        for part in path_parts:
            found_match_at_level = False
            for target_coll in self._target_collections:
                if (
                    sanitize_filename(target_coll["name"]) == part
                    and target_coll.get("parent_id") == current_parent_id
                ):

                    found_collection = target_coll
                    current_parent_id = target_coll["id"]
                    found_match_at_level = True

                    # We need to find the full object in the nested tree
                    def find_in_tree(nodes: list, node_id: int) -> Any:
                        for node in nodes:
                            if node["id"] == node_id:
                                return node
                            if "children" in node:
                                found = find_in_tree(node["children"], node_id)
                                if found:
                                    return found
                        return None

                    self._target_collections = found_collection.get("children", [])
                    break
            if not found_match_at_level:
                return None
        return found_collection

    def _find_existing_card_in_collection(
        self, name: str, collection_id: int | None
    ) -> dict[Any, Any] | None:
        """Finds an existing card by name in a specific collection.

        Args:
            name: The name of the card to find
            collection_id: The collection ID to search in (None for root collection)

        Returns:
            The card dict if found, None otherwise
        """
        try:
            # Use 'root' for the root collection, otherwise use the collection ID
            coll_id: int | str = "root" if collection_id is None else collection_id
            items = self.client.get_collection_items(coll_id)

            # Filter for cards (model='card') with matching name
            for item in items.get("data", []):
                if item.get("model") == "card" and item.get("name") == name:
                    return item  # type: ignore[no-any-return]
            return None
        except Exception as e:
            logger.warning(f"Failed to check for existing card '{name}': {e}")
            return None

    def _find_existing_dashboard_in_collection(
        self, name: str, collection_id: int | None
    ) -> dict[Any, Any] | None:
        """Finds an existing dashboard by name in a specific collection.

        Args:
            name: The name of the dashboard to find
            collection_id: The collection ID to search in (None for root collection)

        Returns:
            The dashboard dict if found, None otherwise
        """
        try:
            # Use 'root' for the root collection, otherwise use the collection ID
            coll_id: int | str = "root" if collection_id is None else collection_id
            items = self.client.get_collection_items(coll_id)

            # Filter for dashboards (model='dashboard') with matching name
            for item in items.get("data", []):
                if item.get("model") == "dashboard" and item.get("name") == name:
                    return item  # type: ignore[no-any-return]
            return None
        except Exception as e:
            logger.warning(f"Failed to check for existing dashboard '{name}': {e}")
            return None

    def _generate_unique_name(
        self, base_name: str, collection_id: int | None, item_type: str
    ) -> str:
        """Generates a unique name by appending a number if needed.

        Args:
            base_name: The original name
            collection_id: The collection to check for conflicts
            item_type: Either 'card' or 'dashboard'

        Returns:
            A unique name that doesn't conflict with existing items
        """
        # Try the base name first
        if item_type == "card":
            existing = self._find_existing_card_in_collection(base_name, collection_id)
        else:
            existing = self._find_existing_dashboard_in_collection(base_name, collection_id)

        if not existing:
            return base_name

        # Try appending numbers until we find a unique name
        counter = 1
        while True:
            new_name = f"{base_name} ({counter})"
            if item_type == "card":
                existing = self._find_existing_card_in_collection(new_name, collection_id)
            else:
                existing = self._find_existing_dashboard_in_collection(new_name, collection_id)

            if not existing:
                return new_name
            counter += 1

    def _flatten_collection_tree(
        self, collections: list[dict], parent_id: int | None = None
    ) -> list[dict]:
        """Recursively flattens a collection tree into a list of collections."""
        flat_list = []
        for coll in collections:
            # Skip root collection (it's a special case)
            if coll.get("id") == "root":
                # Process root's children
                if "children" in coll:
                    flat_list.extend(self._flatten_collection_tree(coll["children"], None))
                continue

            # Add current collection with its parent_id
            flat_coll = {
                "id": coll["id"],
                "name": coll["name"],
                "parent_id": parent_id,
            }
            flat_list.append(flat_coll)

            # Recursively process children
            if "children" in coll and coll["children"]:
                flat_list.extend(self._flatten_collection_tree(coll["children"], coll["id"]))

        return flat_list

    def _import_collections(self) -> None:
        """Imports all collections from the manifest."""
        sorted_collections = sorted(self.manifest.collections, key=lambda c: c.path)

        # Flatten the collection tree into a list for easier lookup
        flat_target_collections = self._flatten_collection_tree(self._target_collections)

        print(f"\n[DEBUG] Total target collections (flattened): {len(flat_target_collections)}")
        print("[DEBUG] Target collections:")
        for tc in flat_target_collections:
            print(f"[DEBUG]   - '{tc['name']}' (ID: {tc['id']}, parent_id: {tc.get('parent_id')})")

        for collection in tqdm(sorted_collections, desc="Importing Collections"):
            try:
                target_parent_id = (
                    self._collection_map.get(collection.parent_id) if collection.parent_id else None
                )

                # Check for existing collection on target
                existing_coll = None
                # Check by name and parent_id using flattened collections
                print(
                    f"\n[DEBUG] Looking for: name='{collection.name}', target_parent_id={target_parent_id}, source_parent_id={collection.parent_id}"
                )
                for tc in flat_target_collections:
                    if tc["name"] == collection.name:
                        print(
                            f"[DEBUG]   Found name match: '{tc['name']}', tc_parent_id={tc.get('parent_id')}, match={tc.get('parent_id') == target_parent_id}"
                        )
                    if tc["name"] == collection.name and tc.get("parent_id") == target_parent_id:
                        existing_coll = tc
                        print(f"[DEBUG]   ✓ MATCH! Using existing ID: {tc['id']}")
                        break
                if not existing_coll:
                    print("[DEBUG]   ✗ No match found, will create new collection")

                if existing_coll:
                    # Handle conflict based on strategy
                    if self.config.conflict_strategy == "skip":
                        # Skip and reuse existing collection
                        self._collection_map[collection.id] = existing_coll["id"]
                        self.report.add(
                            ImportReportItem(
                                "collection",
                                "skipped",
                                collection.id,
                                existing_coll["id"],
                                collection.name,
                                "Already exists (skipped)",
                            )
                        )
                        logger.debug(
                            f"Skipped collection '{collection.name}' - already exists with ID {existing_coll['id']}"
                        )
                        continue

                    elif self.config.conflict_strategy == "overwrite":
                        # Update existing collection
                        update_payload = {
                            "name": collection.name,
                            "description": collection.description,
                            "parent_id": target_parent_id,
                        }
                        updated_coll = self.client.update_collection(
                            existing_coll["id"], clean_for_create(update_payload)
                        )
                        self._collection_map[collection.id] = updated_coll["id"]
                        self.report.add(
                            ImportReportItem(
                                "collection",
                                "updated",
                                collection.id,
                                updated_coll["id"],
                                collection.name,
                            )
                        )
                        logger.debug(
                            f"Updated collection '{collection.name}' (ID: {updated_coll['id']})"
                        )
                        continue

                    elif self.config.conflict_strategy == "rename":
                        # Create with a new name - fall through to creation logic below
                        # We'll modify the name before creating
                        pass

                # Prepare payload for creation
                collection_name = collection.name
                if existing_coll and self.config.conflict_strategy == "rename":
                    # Generate a unique name
                    counter = 1
                    while True:
                        new_name = f"{collection.name} ({counter})"
                        # Check if this name exists
                        name_exists = False
                        for tc in self.client.get_collections_tree(params={"archived": True}):
                            if tc["name"] == new_name and tc.get("parent_id") == target_parent_id:
                                name_exists = True
                                break
                        if not name_exists:
                            collection_name = new_name
                            logger.info(
                                f"Renamed collection '{collection.name}' to '{collection_name}' to avoid conflict"
                            )
                            break
                        counter += 1

                payload = {
                    "name": collection_name,
                    "description": collection.description,
                    "parent_id": target_parent_id,
                }

                new_coll = self.client.create_collection(clean_for_create(payload))
                self._collection_map[collection.id] = new_coll["id"]
                self.report.add(
                    ImportReportItem(
                        "collection", "created", collection.id, new_coll["id"], collection_name
                    )
                )
                logger.debug(f"Created collection '{collection_name}' (ID: {new_coll['id']})")

            except Exception as e:
                logger.error(f"Failed to import collection '{collection.name}': {e}")
                self.report.add(
                    ImportReportItem(
                        "collection", "failed", collection.id, None, collection.name, str(e)
                    )
                )

    def _extract_card_dependencies(self, card_data: dict) -> set[int]:
        """Extracts card IDs that this card depends on (references in source-table).

        Returns a set of card IDs that must be imported before this card.
        """
        dependencies = set()

        # Check for card references in dataset_query
        dataset_query = card_data.get("dataset_query", {})
        query = dataset_query.get("query", {})

        # Check source-table for card references (format: "card__123")
        source_table = query.get("source-table")
        if isinstance(source_table, str) and source_table.startswith("card__"):
            try:
                card_id = int(source_table.replace("card__", ""))
                dependencies.add(card_id)
            except ValueError:
                logger.warning(f"Invalid card reference format: {source_table}")

        # Recursively check joins for card references
        joins = query.get("joins", [])
        for join in joins:
            join_source_table = join.get("source-table")
            if isinstance(join_source_table, str) and join_source_table.startswith("card__"):
                try:
                    card_id = int(join_source_table.replace("card__", ""))
                    dependencies.add(card_id)
                except ValueError:
                    logger.warning(f"Invalid card reference in join: {join_source_table}")

        return dependencies

    def _topological_sort_cards(self, cards: list) -> list:
        """Sorts cards in topological order so that dependencies are imported first.

        Cards with missing dependencies are placed at the end with a warning.
        """
        # Build a map of card ID to card object
        card_map = {card.id: card for card in cards}

        # Build dependency graph
        dependencies = {}
        for card in cards:
            try:
                card_data = read_json_file(self.export_dir / card.file_path)
                deps = self._extract_card_dependencies(card_data)
                # Only keep dependencies that are in our export
                dependencies[card.id] = deps & set(card_map.keys())
            except Exception as e:
                logger.warning(f"Failed to extract dependencies for card {card.id}: {e}")
                dependencies[card.id] = set()

        # Perform topological sort using Kahn's algorithm
        sorted_cards = []
        in_degree = {card.id: 0 for card in cards}

        # Calculate in-degrees
        for card_id, deps in dependencies.items():
            for dep_id in deps:
                if dep_id in in_degree:
                    in_degree[card_id] += 1

        # Queue of cards with no dependencies
        queue = [card_id for card_id, degree in in_degree.items() if degree == 0]

        while queue:
            # Sort queue to ensure deterministic order
            queue.sort()
            card_id = queue.pop(0)
            sorted_cards.append(card_map[card_id])

            # Reduce in-degree for dependent cards
            for other_id, deps in dependencies.items():
                if card_id in deps and other_id in in_degree:
                    in_degree[other_id] -= 1
                    if in_degree[other_id] == 0:
                        queue.append(other_id)

        # Check for circular dependencies or missing dependencies
        if len(sorted_cards) < len(cards):
            remaining = [
                card_map[card_id]
                for card_id in card_map.keys()
                if card_id not in [c.id for c in sorted_cards]
            ]
            logger.warning(f"Found {len(remaining)} cards with circular or missing dependencies")

            # Log details about missing dependencies
            for card in remaining:
                card_data = read_json_file(self.export_dir / card.file_path)
                deps = self._extract_card_dependencies(card_data)
                missing_deps = deps - set(card_map.keys())
                if missing_deps:
                    logger.warning(
                        f"Card {card.id} ('{card.name}') depends on missing cards: {missing_deps}"
                    )

            # Add remaining cards at the end
            sorted_cards.extend(remaining)

        return sorted_cards

    def _remap_field_ids_recursively(self, data: Any, source_db_id: int) -> Any:
        """Recursively remaps field IDs in any data structure (lists, dicts, or primitives).

        This handles field references in all MBQL clauses including:
        - Filters: ["and", ["=", ["field", 201, {...}], "CUSTOMER"]]
        - Aggregations: ["sum", ["field", 5, None]]
        - Breakouts: [["field", 3, {"temporal-unit": "month"}]]
        - Order-by: [["asc", ["field", 10]]]
        - Fields: [["field", 100], ["field", 200]]
        - Expressions: {"+": [["field", 10], 5]}
        - Dashboard parameter targets: ["dimension", ["field", 3, {...}]]
        - Dashboard parameter value_field: ["field", 10, None]
        """
        if data is None:
            return data

        # Handle lists (most MBQL clauses are lists)
        if isinstance(data, list):
            if len(data) == 0:
                return data

            # Check if this is a field reference: ["field", field_id, {...}]
            # or ["field-id", field_id] (older format)
            if len(data) >= 2 and data[0] in ("field", "field-id"):
                source_field_id = data[1]
                if isinstance(source_field_id, int):
                    mapping_key = (source_db_id, source_field_id)
                    if mapping_key in self._field_map:
                        target_field_id = self._field_map[mapping_key]
                        result = list(data)  # Make a copy
                        result[1] = target_field_id
                        logger.debug(
                            f"Remapped field ID from {source_field_id} to {target_field_id}"
                        )
                        return result
                    else:
                        logger.warning(
                            f"No field ID mapping found for source field {source_field_id} in database {source_db_id}. "
                            f"Keeping original field ID - this may cause issues."
                        )
                return data

            # Recursively process all items in the list
            return [self._remap_field_ids_recursively(item, source_db_id) for item in data]

        # Handle dictionaries
        if isinstance(data, dict):
            return {
                key: self._remap_field_ids_recursively(value, source_db_id)
                for key, value in data.items()
            }

        # Primitive values (strings, numbers, booleans, None) - return as-is
        return data

    def _remap_card_query(self, card_data: dict) -> tuple[dict, bool]:
        """Remaps the database ID, table IDs, and field IDs in a card's dataset_query and card references."""
        data = copy.deepcopy(card_data)
        query = data.get("dataset_query", {})

        source_db_id = data.get("database_id") or query.get("database")
        if not source_db_id:
            return data, False

        target_db_id = self._resolve_db_id(source_db_id)
        if not target_db_id:
            raise ValueError(
                f"FATAL: Unmapped database ID {source_db_id} found during card import. This should have been caught by validation."
            )

        # Always set the database field in dataset_query, even if it wasn't present originally
        # This is required for Metabase to properly normalize queries to pMBQL format
        query["database"] = target_db_id
        if "database_id" in data:
            data["database_id"] = target_db_id

        # Remap table_id at the card level (if present)
        if "table_id" in data and isinstance(data["table_id"], int):
            source_table_id = data["table_id"]
            # Try to find target table ID using the mapping
            mapping_key = (source_db_id, source_table_id)
            if mapping_key in self._table_map:
                target_table_id = self._table_map[mapping_key]
                data["table_id"] = target_table_id
                logger.debug(f"Remapped table_id from {source_table_id} to {target_table_id}")
            else:
                logger.warning(
                    f"No table ID mapping found for source table {source_table_id} in database {source_db_id}. "
                    f"Keeping original table_id - this may cause issues if the table ID doesn't exist in target."
                )

        # Remap card references and table IDs in source-table
        inner_query = query.get("query", {})
        if inner_query:
            source_table = inner_query.get("source-table")
            if isinstance(source_table, str) and source_table.startswith("card__"):
                try:
                    source_card_id = int(source_table.replace("card__", ""))
                    if source_card_id in self._card_map:
                        inner_query["source-table"] = f"card__{self._card_map[source_card_id]}"
                        logger.debug(
                            f"Remapped source-table from card__{source_card_id} to card__{self._card_map[source_card_id]}"
                        )
                except ValueError:
                    logger.warning(f"Invalid card reference format: {source_table}")
            elif isinstance(source_table, int):
                # This is a table ID, try to remap it
                mapping_key = (source_db_id, source_table)
                if mapping_key in self._table_map:
                    target_table_id = self._table_map[mapping_key]
                    inner_query["source-table"] = target_table_id
                    logger.debug(f"Remapped source-table from {source_table} to {target_table_id}")
                else:
                    logger.warning(
                        f"No table ID mapping found for source table {source_table} in database {source_db_id}. "
                        f"Keeping original table ID - this may cause issues."
                    )

            # Remap card references in joins
            joins = inner_query.get("joins", [])
            for join in joins:
                join_source_table = join.get("source-table")
                if isinstance(join_source_table, str) and join_source_table.startswith("card__"):
                    try:
                        source_card_id = int(join_source_table.replace("card__", ""))
                        if source_card_id in self._card_map:
                            join["source-table"] = f"card__{self._card_map[source_card_id]}"
                            logger.debug(
                                f"Remapped join source-table from card__{source_card_id} to card__{self._card_map[source_card_id]}"
                            )
                    except ValueError:
                        logger.warning(f"Invalid card reference in join: {join_source_table}")
                elif isinstance(join_source_table, int):
                    # This is a table ID in a join, try to remap it
                    mapping_key = (source_db_id, join_source_table)
                    if mapping_key in self._table_map:
                        target_table_id = self._table_map[mapping_key]
                        join["source-table"] = target_table_id
                        logger.debug(
                            f"Remapped join source-table from {join_source_table} to {target_table_id}"
                        )

            # Remap field IDs in ALL query clauses (filter, aggregation, breakout, order-by, fields, expressions, etc.)
            # This handles field references throughout the entire query structure
            for key in ["filter", "aggregation", "breakout", "order-by", "fields", "expressions"]:
                if key in inner_query:
                    inner_query[key] = self._remap_field_ids_recursively(
                        inner_query[key], source_db_id
                    )

        # Remap field IDs and table IDs in result_metadata
        # result_metadata contains field references that Metabase uses to display results
        if "result_metadata" in data and isinstance(data["result_metadata"], list):
            remapped_metadata = []
            for metadata_item in data["result_metadata"]:
                if isinstance(metadata_item, dict):
                    metadata_copy = metadata_item.copy()

                    # Remap field_ref if present: ["field", field_id, {...}]
                    if "field_ref" in metadata_copy:
                        metadata_copy["field_ref"] = self._remap_field_ids_recursively(
                            metadata_copy["field_ref"], source_db_id
                        )

                    # Remap the direct field ID if present
                    if "id" in metadata_copy and isinstance(metadata_copy["id"], int):
                        field_id = metadata_copy["id"]
                        mapping_key = (source_db_id, field_id)
                        if mapping_key in self._field_map:
                            metadata_copy["id"] = self._field_map[mapping_key]
                            logger.debug(
                                f"Remapped result_metadata field ID from {field_id} to {self._field_map[mapping_key]}"
                            )

                    # Remap table_id if present
                    if "table_id" in metadata_copy and isinstance(metadata_copy["table_id"], int):
                        table_id = metadata_copy["table_id"]
                        mapping_key = (source_db_id, table_id)
                        if mapping_key in self._table_map:
                            metadata_copy["table_id"] = self._table_map[mapping_key]
                            logger.debug(
                                f"Remapped result_metadata table ID from {table_id} to {self._table_map[mapping_key]}"
                            )

                    remapped_metadata.append(metadata_copy)
                else:
                    remapped_metadata.append(metadata_item)

            data["result_metadata"] = remapped_metadata

        # Remap field IDs in visualization_settings
        # visualization_settings can contain field references in various formats
        if "visualization_settings" in data:
            data["visualization_settings"] = self._remap_field_ids_recursively(
                data["visualization_settings"], source_db_id
            )

        return data, True

    def _import_cards(self) -> None:
        """Imports all cards from the manifest in dependency order."""
        # Filter cards based on archived status
        cards_to_import = [
            card
            for card in self.manifest.cards
            if not card.archived or self.config.include_archived
        ]

        # Sort cards in topological order (dependencies first)
        logger.info("Analyzing card dependencies...")
        sorted_cards = self._topological_sort_cards(cards_to_import)
        logger.info(f"Importing {len(sorted_cards)} cards in dependency order...")

        for card in tqdm(sorted_cards, desc="Importing Cards"):
            try:
                card_data = read_json_file(self.export_dir / card.file_path)

                # Check for missing dependencies
                deps = self._extract_card_dependencies(card_data)
                missing_deps = []
                for dep_id in deps:
                    if dep_id not in self._card_map:
                        # Check if the dependency is in our export but not yet imported
                        dep_in_export = any(c.id == dep_id for c in self.manifest.cards)
                        if not dep_in_export:
                            missing_deps.append(dep_id)

                if missing_deps:
                    error_msg = f"Card depends on missing cards: {missing_deps}. These cards are not in the export."
                    logger.error(f"Skipping card '{card.name}' (ID: {card.id}): {error_msg}")
                    self.report.add(
                        ImportReportItem("card", "failed", card.id, None, card.name, error_msg)
                    )
                    continue

                # 1. Remap database and card references
                card_data, remapped = self._remap_card_query(card_data)
                if not remapped:
                    raise ValueError("Card does not have a database reference.")

                # 2. Remap collection
                target_collection_id = (
                    self._collection_map.get(card.collection_id) if card.collection_id else None
                )
                card_data["collection_id"] = target_collection_id

                # 3. Handle Conflicts - check if card already exists
                existing_card = self._find_existing_card_in_collection(
                    card.name, target_collection_id
                )

                if existing_card:
                    # Handle conflict based on strategy
                    if self.config.conflict_strategy == "skip":
                        # Skip this card and map to existing
                        self._card_map[card.id] = existing_card["id"]
                        self.report.add(
                            ImportReportItem(
                                "card",
                                "skipped",
                                card.id,
                                existing_card["id"],
                                card.name,
                                "Already exists (skipped)",
                            )
                        )
                        logger.debug(
                            f"Skipped card '{card.name}' - already exists with ID {existing_card['id']}"
                        )
                        continue

                    elif self.config.conflict_strategy == "overwrite":
                        # Update existing card
                        payload = clean_for_create(card_data)

                        updated_card = self.client.update_card(existing_card["id"], payload)
                        self._card_map[card.id] = updated_card["id"]
                        self.report.add(
                            ImportReportItem(
                                "card", "updated", card.id, updated_card["id"], card.name
                            )
                        )
                        logger.debug(f"Updated card '{card.name}' (ID: {updated_card['id']})")
                        continue

                    elif self.config.conflict_strategy == "rename":
                        # Generate a unique name and create new card
                        card_data["name"] = self._generate_unique_name(
                            card.name, target_collection_id, "card"
                        )
                        logger.info(
                            f"Renamed card '{card.name}' to '{card_data['name']}' to avoid conflict"
                        )

                # Create new card (either no conflict or rename strategy)
                payload = clean_for_create(card_data)

                new_card = self.client.create_card(payload)
                self._card_map[card.id] = new_card["id"]
                self.report.add(
                    ImportReportItem(
                        "card", "created", card.id, new_card["id"], card_data.get("name", card.name)
                    )
                )
                logger.debug(
                    f"Successfully imported card '{card_data.get('name', card.name)}' {card.id} -> {new_card['id']}"
                )

            except MetabaseAPIError as e:
                error_msg = str(e)

                # Check for missing card reference errors
                if "does not exist" in error_msg and "Card" in error_msg:
                    # Extract card ID from error message
                    match = re.search(r"Card (\d+) does not exist", error_msg)
                    if match:
                        missing_card_id = int(match.group(1))
                        logger.error("=" * 80)
                        logger.error("❌ MISSING CARD DEPENDENCY ERROR!")
                        logger.error("=" * 80)
                        logger.error(f"Failed to import card '{card.name}' (ID: {card.id})")
                        logger.error(
                            f"The card references another card (ID: {missing_card_id}) that doesn't exist in the target instance."
                        )
                        logger.error("")
                        logger.error("This usually means:")
                        logger.error(f"1. Card {missing_card_id} was not included in the export")
                        logger.error(f"2. Card {missing_card_id} failed to import earlier")
                        logger.error(
                            f"3. Card {missing_card_id} is archived and --include-archived was not used during export"
                        )
                        logger.error("")
                        logger.error("SOLUTIONS:")
                        logger.error(f"1. Re-export with card {missing_card_id} included")
                        logger.error(
                            "2. If the card is archived, use --include-archived flag during export"
                        )
                        logger.error("3. Manually create or import the missing card first")
                        logger.error("=" * 80)
                        self.report.add(
                            ImportReportItem(
                                "card",
                                "failed",
                                card.id,
                                None,
                                card.name,
                                f"Missing dependency: card {missing_card_id}",
                            )
                        )
                        continue

                # Check for table ID constraint violation
                elif "fk_report_card_ref_table_id" in error_msg.lower() or (
                    "table_id" in error_msg.lower() and "not present in table" in error_msg.lower()
                ):
                    # Extract table ID from error message
                    match = re.search(r"table_id\)=\((\d+)\)", error_msg)
                    table_id = match.group(1) if match else "unknown"

                    logger.error("=" * 80)
                    logger.error("❌ TABLE ID MAPPING ERROR DETECTED!")
                    logger.error("=" * 80)
                    logger.error(f"Failed to import card '{card.name}' (ID: {card.id})")
                    logger.error(
                        f"The card references table ID {table_id} that doesn't exist in the target Metabase instance."
                    )
                    logger.error("")
                    logger.error(
                        "This is a known limitation: Table IDs are instance-specific and cannot be directly migrated."
                    )
                    logger.error("")
                    logger.error("CAUSE:")
                    logger.error(
                        "The source and target Metabase instances have different table metadata."
                    )
                    logger.error("This happens when:")
                    logger.error("1. The databases haven't been synced in the target instance")
                    logger.error("2. The database schemas are different between source and target")
                    logger.error("3. The table was removed or renamed in the target database")
                    logger.error("")
                    logger.error("SOLUTIONS:")
                    logger.error("1. Ensure the target database is properly synced in Metabase")
                    logger.error(
                        "2. Go to Admin > Databases > [Your Database] > 'Sync database schema now'"
                    )
                    logger.error("3. Verify the table exists in the target database")
                    logger.error(
                        "4. If using GUI queries, consider converting to native SQL queries"
                    )
                    logger.error("")
                    logger.error(f"Error details: {error_msg}")
                    logger.error("=" * 80)
                    self.report.add(
                        ImportReportItem(
                            "card",
                            "failed",
                            card.id,
                            None,
                            card.name,
                            f"Table ID {table_id} not found in target",
                        )
                    )
                    continue

                # Check for database foreign key constraint violation
                elif (
                    "FK_REPORT_CARD_REF_DATABASE_ID" in error_msg
                    or "FOREIGN KEY(DATABASE_ID)" in error_msg
                ):
                    logger.error("=" * 80)
                    logger.error("❌ DATABASE MAPPING ERROR DETECTED!")
                    logger.error("=" * 80)
                    logger.error(f"Failed to import card '{card.name}' (ID: {card.id})")
                    logger.error(
                        f"The card references database ID {card.database_id}, but this database ID does not exist in the target Metabase instance."
                    )
                    logger.error("")
                    logger.error("This means your db_map.json file is incorrectly configured.")
                    logger.error("")
                    logger.error("SOLUTION:")
                    logger.error("1. Check your db_map.json file")
                    logger.error(
                        "2. Ensure the source database ID is mapped to a valid target database ID"
                    )
                    logger.error("3. You can list target databases using: GET /api/database")
                    logger.error("")
                    logger.error(f"Source database ID: {card.database_id}")
                    logger.error(
                        f"Source database name: {self.manifest.databases.get(card.database_id, 'Unknown')}"
                    )
                    logger.error(f"Mapped to target ID: {self._resolve_db_id(card.database_id)}")
                    logger.error("")
                    logger.error("Please fix db_map.json and run the import again.")
                    logger.error("=" * 80)
                    sys.exit(1)

                # Check for field ID constraint violation
                elif (
                    "fk_query_field_field_id" in error_msg.lower()
                    or "field_id" in error_msg.lower()
                ):
                    logger.error("=" * 80)
                    logger.error("❌ FIELD ID MAPPING ERROR DETECTED!")
                    logger.error("=" * 80)
                    logger.error(f"Failed to import card '{card.name}' (ID: {card.id})")
                    logger.error(
                        "The card references field IDs that don't exist in the target Metabase instance."
                    )
                    logger.error("")
                    logger.error(
                        "This is a known limitation: Field IDs are instance-specific and cannot be directly migrated."
                    )
                    logger.error("")
                    logger.error("SOLUTIONS:")
                    logger.error("1. Recreate the card manually in the target instance")
                    logger.error(
                        "2. Use native SQL queries instead of GUI queries (they use field names, not IDs)"
                    )
                    logger.error("3. Ensure both instances have synced the same database schema")
                    logger.error("")
                    logger.error(f"Error details: {error_msg}")
                    logger.error("=" * 80)
                    sys.exit(1)

                else:
                    logger.error(
                        f"Failed to import card '{card.name}' (ID: {card.id}): {e}", exc_info=True
                    )
                    self.report.add(
                        ImportReportItem("card", "failed", card.id, None, card.name, str(e))
                    )

            except Exception as e:
                logger.error(
                    f"Failed to import card '{card.name}' (ID: {card.id}): {e}", exc_info=True
                )
                self.report.add(
                    ImportReportItem("card", "failed", card.id, None, card.name, str(e))
                )

    def _import_dashboards(self) -> None:
        """Imports all dashboards from the manifest."""
        for dash in tqdm(
            sorted(self.manifest.dashboards, key=lambda d: d.file_path), desc="Importing Dashboards"
        ):
            if dash.archived and not self.config.include_archived:
                continue

            try:
                dash_data = read_json_file(self.export_dir / dash.file_path)

                # 1. Remap collection
                target_collection_id = (
                    self._collection_map.get(dash.collection_id) if dash.collection_id else None
                )
                dash_data["collection_id"] = target_collection_id

                # 2. Prepare dashcards for import
                dashcards_to_import = []
                if "dashcards" in dash_data:
                    # Use negative sequential IDs for new dashcards (Metabase requires unique IDs)
                    # Start from -1 and decrement for each dashcard
                    next_temp_id = -1

                    for dashcard in dash_data["dashcards"]:
                        # Create a clean copy with only allowed fields
                        clean_dashcard = {}

                        # Fields to explicitly exclude (these are auto-generated or not needed for import)
                        excluded_fields = {
                            "dashboard_id",  # Will be set by the dashboard
                            "created_at",  # Auto-generated
                            "updated_at",  # Auto-generated
                            "entity_id",  # Auto-generated
                            "card",  # Full card object not needed, only card_id
                            "action_id",  # Not needed for import
                            "collection_authority_level",  # Not needed for import
                            "dashboard_tab_id",  # Will be handled separately if needed
                        }

                        # Copy only essential positioning and display fields
                        for field in ["col", "row", "size_x", "size_y"]:
                            if field in dashcard and dashcard[field] is not None:
                                clean_dashcard[field] = dashcard[field]

                        # Set unique negative ID for this dashcard
                        # Metabase requires IDs to be unique, so we use sequential negative numbers
                        clean_dashcard["id"] = next_temp_id
                        next_temp_id -= 1

                        # Copy visualization_settings if present
                        if "visualization_settings" in dashcard:
                            clean_dashcard["visualization_settings"] = dashcard[
                                "visualization_settings"
                            ]

                        # Copy parameter_mappings if present
                        if "parameter_mappings" in dashcard and dashcard["parameter_mappings"]:
                            clean_dashcard["parameter_mappings"] = []

                            # Get the database ID for this dashcard's card (for field remapping)
                            dashcard_db_id = None
                            source_card_id = dashcard.get("card_id")
                            if source_card_id:
                                # Find the card in the manifest to get its database_id
                                for manifest_card in self.manifest.cards:
                                    if manifest_card.id == source_card_id:
                                        dashcard_db_id = manifest_card.database_id
                                        break

                            for param_mapping in dashcard["parameter_mappings"]:
                                clean_param = param_mapping.copy()
                                # Remap card_id in parameter_mappings
                                if "card_id" in clean_param:
                                    source_param_card_id = clean_param["card_id"]
                                    if source_param_card_id in self._card_map:
                                        clean_param["card_id"] = self._card_map[
                                            source_param_card_id
                                        ]

                                # Remap field IDs in parameter mapping target
                                # Target can contain field references like ["dimension", ["field", 3, {...}]]
                                if "target" in clean_param and dashcard_db_id:
                                    clean_param["target"] = self._remap_field_ids_recursively(
                                        clean_param["target"], dashcard_db_id
                                    )

                                clean_dashcard["parameter_mappings"].append(clean_param)

                        # Copy series if present (for combo charts)
                        # Series contains references to other cards that need to be remapped
                        if "series" in dashcard and dashcard["series"]:
                            clean_dashcard["series"] = []
                            for series_card in dashcard["series"]:
                                if isinstance(series_card, dict) and "id" in series_card:
                                    series_card_id = series_card["id"]
                                    if series_card_id in self._card_map:
                                        # Only include the remapped card ID, not the full card object
                                        clean_dashcard["series"].append(
                                            {"id": self._card_map[series_card_id]}
                                        )
                                    else:
                                        logger.warning(
                                            f"Skipping series card with unmapped id: {series_card_id}"
                                        )

                        # Remap card_id to target (if it's a regular card, not a text/heading)
                        source_card_id = dashcard.get("card_id")
                        if source_card_id:
                            if source_card_id in self._card_map:
                                clean_dashcard["card_id"] = self._card_map[source_card_id]
                            else:
                                # Card not found in mapping, skip this dashcard
                                logger.warning(
                                    f"Skipping dashcard with unmapped card_id: {source_card_id}"
                                )
                                continue
                        # else: it's a virtual card (text/heading), no card_id needed

                        # Final safety check: ensure no excluded fields made it through
                        for excluded_field in excluded_fields:
                            if excluded_field in clean_dashcard:
                                del clean_dashcard[excluded_field]
                                logger.debug(
                                    f"Removed excluded field '{excluded_field}' from dashcard"
                                )

                        dashcards_to_import.append(clean_dashcard)

                # 3. Clean dashboard data and remap card IDs and field IDs in parameters
                payload = clean_for_create(dash_data)
                parameters = payload.get("parameters", [])
                remapped_parameters = []

                for param in parameters:
                    param_copy = param.copy()
                    # Check if parameter has values_source_config with card_id
                    if "values_source_config" in param_copy and isinstance(
                        param_copy["values_source_config"], dict
                    ):
                        source_card_id = param_copy["values_source_config"].get("card_id")
                        if source_card_id:
                            if source_card_id in self._card_map:
                                # Remap to target card ID
                                param_copy["values_source_config"]["card_id"] = self._card_map[
                                    source_card_id
                                ]
                                logger.debug(
                                    f"Remapped parameter card_id {source_card_id} -> {self._card_map[source_card_id]}"
                                )

                                # Remap field IDs in value_field if present
                                # We need to get the database ID from the card referenced in values_source_config
                                if "value_field" in param_copy["values_source_config"]:
                                    # Find the database ID for this specific card
                                    param_source_db_id = None
                                    for card in self.manifest.cards:
                                        if card.id == source_card_id:
                                            param_source_db_id = card.database_id
                                            break

                                    if param_source_db_id:
                                        param_copy["values_source_config"]["value_field"] = (
                                            self._remap_field_ids_recursively(
                                                param_copy["values_source_config"]["value_field"],
                                                param_source_db_id,
                                            )
                                        )
                                    else:
                                        logger.warning(
                                            f"Could not determine database ID for card {source_card_id} "
                                            f"referenced in parameter '{param.get('name')}'. "
                                            f"Field IDs in value_field will not be remapped."
                                        )
                            else:
                                # Card not found, remove values_source_config but keep the parameter
                                logger.warning(
                                    f"Dashboard parameter '{param.get('name')}' references missing card {source_card_id}. "
                                    f"Importing parameter without values_source_config (filter values won't be populated from card)."
                                )
                                # Remove the values_source_config to avoid API errors
                                del param_copy["values_source_config"]
                                if "values_source_type" in param_copy:
                                    del param_copy["values_source_type"]

                    remapped_parameters.append(param_copy)

                # 4. Check for existing dashboard and handle conflicts
                existing_dashboard = self._find_existing_dashboard_in_collection(
                    dash.name, target_collection_id
                )

                dashboard_name = dash.name
                dashboard_id = None
                action_taken: str = "created"

                if existing_dashboard:
                    # Handle conflict based on strategy
                    if self.config.conflict_strategy == "skip":
                        # Skip this dashboard
                        self.report.add(
                            ImportReportItem(
                                "dashboard",
                                "skipped",
                                dash.id,
                                existing_dashboard["id"],
                                dash.name,
                                "Already exists (skipped)",
                            )
                        )
                        logger.debug(
                            f"Skipped dashboard '{dash.name}' - already exists with ID {existing_dashboard['id']}"
                        )
                        continue

                    elif self.config.conflict_strategy == "overwrite":
                        # Use existing dashboard ID for update
                        dashboard_id = existing_dashboard["id"]
                        action_taken = "updated"
                        logger.debug(
                            f"Will overwrite existing dashboard '{dash.name}' (ID: {dashboard_id})"
                        )

                    elif self.config.conflict_strategy == "rename":
                        # Generate a unique name and create new dashboard
                        dashboard_name = self._generate_unique_name(
                            dash.name, target_collection_id, "dashboard"
                        )
                        logger.info(
                            f"Renamed dashboard '{dash.name}' to '{dashboard_name}' to avoid conflict"
                        )

                # 5. Create or update dashboard
                if dashboard_id is None:
                    # Create new dashboard
                    create_payload = {
                        "name": dashboard_name,
                        "collection_id": target_collection_id,
                        "description": payload.get("description"),
                        "parameters": remapped_parameters,
                    }
                    new_dash = self.client.create_dashboard(create_payload)
                    dashboard_id = new_dash["id"]
                    logger.debug(f"Created dashboard '{dashboard_name}' (ID: {dashboard_id})")

                # 6. Update dashboard with dashcards and other settings
                update_payload = {
                    "name": dashboard_name,
                    "description": payload.get("description"),
                    "parameters": remapped_parameters,
                    "cache_ttl": payload.get("cache_ttl"),
                }

                # Include dashboard display settings
                # width: Controls dashboard width mode (e.g., "fixed", "full")
                if "width" in payload:
                    update_payload["width"] = payload["width"]

                # auto_apply_filters: Controls whether filters are automatically applied
                if "auto_apply_filters" in payload:
                    update_payload["auto_apply_filters"] = payload["auto_apply_filters"]

                # Only add dashcards if there are any to import
                if dashcards_to_import:
                    update_payload["dashcards"] = dashcards_to_import
                    logger.debug(
                        f"Updating dashboard {dashboard_id} with {len(dashcards_to_import)} dashcards"
                    )

                    # Verify no dashcard has problematic fields
                    # Note: 'id' is intentionally included with negative values for new dashcards (Metabase requirement)
                    problematic_fields = ["dashboard_id", "created_at", "updated_at", "entity_id"]
                    for idx, dc in enumerate(dashcards_to_import):
                        for field in problematic_fields:
                            if field in dc:
                                logger.error(
                                    f"Dashcard {idx} still has '{field}' field: {dc.get(field)} - this will cause import to fail!"
                                )
                                logger.error(f"Dashcard keys: {list(dc.keys())}")

                # Remove None values
                update_payload = {k: v for k, v in update_payload.items() if v is not None}

                updated_dash = self.client.update_dashboard(dashboard_id, update_payload)

                self.report.add(
                    ImportReportItem(
                        "dashboard",
                        cast(
                            Literal["created", "updated", "skipped", "failed", "success", "error"],
                            action_taken,
                        ),
                        dash.id,
                        updated_dash["id"],
                        dashboard_name,
                    )
                )
                logger.debug(
                    f"Successfully {action_taken} dashboard '{dashboard_name}' (ID: {updated_dash['id']})"
                )

            except Exception as e:
                logger.error(
                    f"Failed to import dashboard '{dash.name}' (ID: {dash.id}): {e}", exc_info=True
                )
                self.report.add(
                    ImportReportItem("dashboard", "failed", dash.id, None, dash.name, str(e))
                )

    def _import_permissions(self) -> None:
        """Imports permission groups and applies permissions graphs."""
        try:
            # Step 1: Map permission groups from source to target
            logger.info("Mapping permission groups...")
            target_groups = self.client.get_permission_groups()
            target_groups_by_name = {g["name"]: g for g in target_groups}

            # Built-in groups that should always exist
            builtin_groups = {"All Users", "Administrators"}

            for source_group in self.manifest.permission_groups:
                if source_group.name in target_groups_by_name:
                    # Group exists on target, map it
                    target_group = target_groups_by_name[source_group.name]
                    self._group_map[source_group.id] = target_group["id"]
                    logger.info(
                        f"  -> Mapped group '{source_group.name}': source ID {source_group.id} -> target ID {target_group['id']}"
                    )
                elif source_group.name not in builtin_groups:
                    # Custom group doesn't exist, we should create it
                    # Note: Metabase API doesn't provide a direct endpoint to create groups
                    # Groups are typically created through the UI or admin API
                    logger.warning(
                        f"  -> Group '{source_group.name}' (ID: {source_group.id}) not found on target. "
                        f"Permissions for this group will be skipped."
                    )
                else:
                    logger.warning(
                        f"  -> Built-in group '{source_group.name}' not found on target. This is unexpected."
                    )

            if not self._group_map:
                logger.warning("No permission groups could be mapped. Skipping permissions import.")
                return

            # Step 2: Remap and apply data permissions graph
            data_perms_applied = False
            if self.manifest.permissions_graph:
                logger.info("Applying data permissions...")
                remapped_permissions = self._remap_permissions_graph(
                    self.manifest.permissions_graph
                )
                if remapped_permissions:
                    try:
                        self.client.update_permissions_graph(remapped_permissions)
                        logger.info("✓ Data permissions applied successfully")
                        data_perms_applied = True
                    except MetabaseAPIError as e:
                        logger.error(f"Failed to apply data permissions: {e}")
                        logger.warning("Continuing without data permissions...")
                else:
                    logger.info("No data permissions to apply (all databases unmapped)")

            # Step 3: Remap and apply collection permissions graph
            collection_perms_applied = False
            if self.manifest.collection_permissions_graph:
                logger.info("Applying collection permissions...")
                remapped_collection_permissions = self._remap_collection_permissions_graph(
                    self.manifest.collection_permissions_graph
                )
                if remapped_collection_permissions:
                    try:
                        self.client.update_collection_permissions_graph(
                            remapped_collection_permissions
                        )
                        logger.info("✓ Collection permissions applied successfully")
                        collection_perms_applied = True
                    except MetabaseAPIError as e:
                        logger.error(f"Failed to apply collection permissions: {e}")
                        logger.warning("Continuing without collection permissions...")
                else:
                    logger.info("No collection permissions to apply (all collections unmapped)")

            # Summary
            logger.info("=" * 60)
            logger.info("Permissions Import Summary:")
            logger.info(f"  Groups mapped: {len(self._group_map)}")
            logger.info(
                f"  Data permissions: {'✓ Applied' if data_perms_applied else '✗ Not applied'}"
            )
            logger.info(
                f"  Collection permissions: {'✓ Applied' if collection_perms_applied else '✗ Not applied'}"
            )
            logger.info("=" * 60)

        except Exception as e:
            logger.error(f"Failed to import permissions: {e}", exc_info=True)
            logger.warning("Permissions import failed. Continuing without permissions...")

    def _remap_permissions_graph(self, source_graph: dict[str, Any]) -> dict[str, Any]:
        """Remaps database and group IDs in the permissions graph."""
        if not source_graph or "groups" not in source_graph:
            return {}

        # Get current revision from target instance to avoid 409 conflicts
        try:
            current_graph = self.client.get_permissions_graph()
            current_revision = current_graph.get("revision", 0)
            logger.debug(f"Using current permissions revision: {current_revision}")
        except Exception as e:
            logger.warning(f"Could not fetch current permissions revision: {e}. Using 0.")
            current_revision = 0

        remapped_graph = {"revision": current_revision, "groups": {}}

        # Track unmapped databases to report once at the end
        unmapped_databases: set[int] = set()

        for source_group_id_str, group_perms in source_graph.get("groups", {}).items():
            source_group_id = int(source_group_id_str)

            # Skip if group not mapped
            if source_group_id not in self._group_map:
                logger.debug(f"Skipping permissions for unmapped group ID {source_group_id}")
                continue

            target_group_id = self._group_map[source_group_id]
            remapped_group_perms = {}

            # Remap database IDs in permissions
            for source_db_id_str, db_perms in group_perms.items():
                source_db_id = int(source_db_id_str)

                # Map source database ID to target database ID
                target_db_id = None
                if str(source_db_id) in self.db_map.by_id:
                    target_db_id = self.db_map.by_id[str(source_db_id)]
                else:
                    # Try to find by database name
                    source_db_name = self.manifest.databases.get(source_db_id)
                    if source_db_name and source_db_name in self.db_map.by_name:
                        target_db_id = self.db_map.by_name[source_db_name]

                if target_db_id:
                    remapped_group_perms[str(target_db_id)] = db_perms
                    logger.debug(
                        f"Remapped database permissions: group {target_group_id}, DB {source_db_id} -> {target_db_id}"
                    )
                else:
                    # Track unmapped databases
                    unmapped_databases.add(source_db_id)
                    logger.debug(f"Skipping database ID {source_db_id} (not in db_map.json)")

            if remapped_group_perms:
                remapped_graph["groups"][str(target_group_id)] = remapped_group_perms

        # Report unmapped databases once at WARNING level (these should be in db_map.json)
        if unmapped_databases:
            db_names = [
                f"{db_id} ({self.manifest.databases.get(db_id, 'unknown')})"
                for db_id in sorted(unmapped_databases)
            ]
            logger.warning(
                f"Skipped permissions for {len(unmapped_databases)} database(s) "
                f"not found in db_map.json: {', '.join(db_names)}"
            )

        return remapped_graph if remapped_graph["groups"] else {}

    def _remap_collection_permissions_graph(self, source_graph: dict[str, Any]) -> dict[str, Any]:
        """Remaps collection and group IDs in the collection permissions graph."""
        if not source_graph or "groups" not in source_graph:
            return {}

        # Get current revision from target instance to avoid 409 conflicts
        try:
            current_graph = self.client.get_collection_permissions_graph()
            current_revision = current_graph.get("revision", 0)
            logger.debug(f"Using current collection permissions revision: {current_revision}")
        except Exception as e:
            logger.warning(
                f"Could not fetch current collection permissions revision: {e}. Using 0."
            )
            current_revision = 0

        remapped_graph = {"revision": current_revision, "groups": {}}

        # Track unmapped collections to report once at the end
        unmapped_collections: set[int] = set()

        for source_group_id_str, group_perms in source_graph.get("groups", {}).items():
            source_group_id = int(source_group_id_str)

            # Skip if group not mapped
            if source_group_id not in self._group_map:
                logger.debug(
                    f"Skipping collection permissions for unmapped group ID {source_group_id}"
                )
                continue

            target_group_id = self._group_map[source_group_id]
            remapped_group_perms = {}

            # Remap collection IDs in permissions
            for source_collection_id_str, collection_perms in group_perms.items():
                # Handle special "root" collection
                if source_collection_id_str == "root":
                    remapped_group_perms["root"] = collection_perms
                    continue

                source_collection_id = int(source_collection_id_str)

                # Map source collection ID to target collection ID
                if source_collection_id in self._collection_map:
                    target_collection_id = self._collection_map[source_collection_id]
                    remapped_group_perms[str(target_collection_id)] = collection_perms
                    logger.debug(
                        f"Remapped collection permissions: group {target_group_id}, "
                        f"collection {source_collection_id} -> {target_collection_id}"
                    )
                else:
                    # Track unmapped collections (likely not exported)
                    unmapped_collections.add(source_collection_id)
                    logger.debug(f"Skipping collection ID {source_collection_id} (not in export)")

            if remapped_group_perms:
                remapped_graph["groups"][str(target_group_id)] = remapped_group_perms

        # Report unmapped collections once at INFO level
        if unmapped_collections:
            logger.info(
                f"Skipped permissions for {len(unmapped_collections)} collection(s) "
                f"that were not included in the export: {sorted(unmapped_collections)}"
            )

        return remapped_graph if remapped_graph["groups"] else {}


def main() -> None:
    """Main entry point for the import tool."""
    config = get_import_args()
    setup_logging(config.log_level)
    importer = MetabaseImporter(config)
    importer.run_import()


if __name__ == "__main__":
    main()
