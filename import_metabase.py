"""
Metabase Import Tool

This script reads an export package created by `export_metabase.py`, connects
to a target Metabase instance, and recreates the collections, cards, and
dashboards. It handles remapping database IDs and resolving conflicts.
"""

import copy
import datetime
import re
import sys
from pathlib import Path
from typing import Any

from tqdm import tqdm

from lib.client import MetabaseAPIError, MetabaseClient
from lib.config import ImportConfig, get_import_args
from lib.models import (
    DatabaseMap,
    ImportReport,
    ImportReportItem,
    Manifest,
    UnmappedDatabase,
)
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

    def __init__(self, config: ImportConfig):
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

        # Caches of existing items on the target instance
        self._target_collections: list[dict[str, Any]] = []

    def run_import(self):
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

    def _load_export_package(self):
        """Loads and validates the manifest and database mapping files."""
        manifest_path = self.export_dir / "manifest.json"
        if not manifest_path.exists():
            raise FileNotFoundError("manifest.json not found in the export directory.")

        manifest_data = read_json_file(manifest_path)
        # Reconstruct the manifest from dicts to dataclasses
        # Import the actual dataclasses from lib.models
        from lib.models import Card, Collection, Dashboard, ManifestMeta

        self.manifest = Manifest(
            meta=ManifestMeta(**manifest_data["meta"]),
            databases=manifest_data.get("databases", {}),
            collections=[Collection(**c) for c in manifest_data.get("collections", [])],
            cards=[Card(**c) for c in manifest_data.get("cards", [])],
            dashboards=[Dashboard(**d) for d in manifest_data.get("dashboards", [])],
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
        # by_id takes precedence
        if str(source_db_id) in self.db_map.by_id:
            return self.db_map.by_id[str(source_db_id)]

        source_db_name = self.manifest.databases.get(str(source_db_id))
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
                                str(card.database_id), "Unknown Name"
                            ),
                        )
                    unmapped[card.database_id].card_ids.add(card.id)
        return list(unmapped.values())

    def _validate_target_databases(self):
        """Validates that all mapped database IDs actually exist in the target instance."""
        try:
            target_databases = self.client.get_databases()
            target_db_ids = {db["id"] for db in target_databases}

            # Collect all unique target database IDs from the mapping
            mapped_target_ids = set()
            for source_db_id in self.manifest.databases.keys():
                target_id = self._resolve_db_id(int(source_db_id))
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
            logger.error(f"Failed to fetch databases from target instance: {e}")
            sys.exit(1)

    def _perform_dry_run(self):
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

    def _perform_import(self):
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

        logger.info("Fetching existing collections from target...")
        self._target_collections = self.client.get_collections_tree(params={"archived": True})

        self._import_collections()
        self._import_cards()
        if self.manifest.dashboards:
            self._import_dashboards()

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
            / f"import_report_{datetime.datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.json"
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
                    def find_in_tree(nodes, node_id):
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

    def _import_collections(self):
        """Imports all collections from the manifest."""
        sorted_collections = sorted(self.manifest.collections, key=lambda c: c.path)

        for collection in tqdm(sorted_collections, desc="Importing Collections"):
            try:
                target_parent_id = (
                    self._collection_map.get(collection.parent_id) if collection.parent_id else None
                )

                # Check for existing collection on target
                existing_coll = None
                # Naive check by name and parent_id
                for tc in self.client.get_collections_tree(params={"archived": True}):
                    if tc["name"] == collection.name and tc.get("parent_id") == target_parent_id:
                        existing_coll = tc
                        break

                if existing_coll:
                    self._collection_map[collection.id] = existing_coll["id"]
                    self.report.add(
                        ImportReportItem(
                            "collection",
                            "skipped",
                            collection.id,
                            existing_coll["id"],
                            collection.name,
                            "Exists on target",
                        )
                    )
                    continue

                payload = {
                    "name": collection.name,
                    "description": collection.description,
                    "parent_id": target_parent_id,
                }

                new_coll = self.client.create_collection(clean_for_create(payload))
                self._collection_map[collection.id] = new_coll["id"]
                self.report.add(
                    ImportReportItem(
                        "collection", "created", collection.id, new_coll["id"], collection.name
                    )
                )

            except Exception as e:
                logger.error(f"Failed to import collection '{collection.name}': {e}")
                self.report.add(
                    ImportReportItem(
                        "collection", "failed", collection.id, None, collection.name, str(e)
                    )
                )

    def _extract_card_dependencies(self, card_data: dict) -> set[int]:
        """
        Extracts card IDs that this card depends on (references in source-table).
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
        """
        Sorts cards in topological order so that dependencies are imported first.
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

    def _remap_card_query(self, card_data: dict) -> tuple[dict, bool]:
        """Remaps the database ID in a card's dataset_query and card references."""
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

        if "database" in query:
            query["database"] = target_db_id
        if "database_id" in data:
            data["database_id"] = target_db_id

        # Remap card references in source-table
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

        return data, True

    def _import_cards(self):
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

                # 3. Handle Conflicts (simplified for this example)
                # A real implementation would query the target instance
                if self.config.conflict_strategy == "skip":
                    # Assume it doesn't exist for now
                    pass

                payload = clean_for_create(card_data)
                new_card = self.client.create_card(payload)
                self._card_map[card.id] = new_card["id"]
                self.report.add(
                    ImportReportItem("card", "created", card.id, new_card["id"], card.name)
                )
                logger.debug(f"Successfully imported card {card.id} -> {new_card['id']}")

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
                        f"Source database name: {self.manifest.databases.get(str(card.database_id), 'Unknown')}"
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

    def _import_dashboards(self):
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
                            for param_mapping in dashcard["parameter_mappings"]:
                                clean_param = param_mapping.copy()
                                # Remap card_id in parameter_mappings
                                if "card_id" in clean_param:
                                    source_param_card_id = clean_param["card_id"]
                                    if source_param_card_id in self._card_map:
                                        clean_param["card_id"] = self._card_map[
                                            source_param_card_id
                                        ]
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

                # 3. Clean dashboard data and remap card IDs in parameters
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
                            else:
                                # Card not found, skip this parameter
                                logger.warning(
                                    f"Skipping dashboard parameter '{param.get('name')}' - references missing card {source_card_id}"
                                )
                                continue
                    remapped_parameters.append(param_copy)

                # 4. Create dashboard with basic info first
                create_payload = {
                    "name": payload["name"],
                    "collection_id": target_collection_id,
                    "description": payload.get("description"),
                    "parameters": remapped_parameters,
                }
                new_dash = self.client.create_dashboard(create_payload)

                # 5. Update dashboard with dashcards and other settings
                # Note: Removed enable_embedding and embedding_params as they require
                # embedding to be enabled in Metabase settings
                update_payload = {
                    "parameters": remapped_parameters,
                    "cache_ttl": payload.get("cache_ttl"),
                }

                # Only add dashcards if there are any to import
                if dashcards_to_import:
                    update_payload["dashcards"] = dashcards_to_import
                    logger.debug(
                        f"Updating dashboard {new_dash['id']} with {len(dashcards_to_import)} dashcards"
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

                updated_dash = self.client.update_dashboard(new_dash["id"], update_payload)

                self.report.add(
                    ImportReportItem("dashboard", "created", dash.id, updated_dash["id"], dash.name)
                )

            except Exception as e:
                logger.error(
                    f"Failed to import dashboard '{dash.name}' (ID: {dash.id}): {e}", exc_info=True
                )
                self.report.add(
                    ImportReportItem("dashboard", "failed", dash.id, None, dash.name, str(e))
                )


def main() -> None:
    """Main entry point for the import tool."""
    config = get_import_args()
    setup_logging(config.log_level)
    importer = MetabaseImporter(config)
    importer.run_import()


if __name__ == "__main__":
    main()
