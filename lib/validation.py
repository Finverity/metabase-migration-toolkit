"""Validation logic for import operations.

This module handles validation of database mappings, target instance state,
and other pre-import checks.
"""

import logging
import sys

from lib.client import MetabaseAPIError, MetabaseClient
from lib.id_remapping import IDRemapper
from lib.models import Manifest, UnmappedDatabase

logger = logging.getLogger("metabase_migration")


class ImportValidator:
    """Validates import configuration and target instance state."""

    def __init__(
        self,
        client: MetabaseClient,
        manifest: Manifest,
        id_remapper: IDRemapper,
        include_archived: bool = False,
    ) -> None:
        """Initialize the import validator.

        Args:
            client: Metabase API client for the target instance
            manifest: Export manifest
            id_remapper: ID remapper instance
            include_archived: Whether to include archived items
        """
        self.client = client
        self.manifest = manifest
        self.id_remapper = id_remapper
        self.include_archived = include_archived

    def validate_database_mappings(self) -> list[UnmappedDatabase]:
        """Validate that all databases referenced by cards have a mapping.

        Returns:
            List of unmapped databases
        """
        unmapped: dict[int, UnmappedDatabase] = {}
        for card in self.manifest.cards:
            if not card.archived or self.include_archived:
                target_db_id = self.id_remapper.resolve_db_id(card.database_id)
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

    def validate_target_databases(self) -> None:
        """Validate that all mapped database IDs exist in the target instance.

        Raises:
            SystemExit: If validation fails
        """
        try:
            target_databases = self.client.get_databases()
            target_db_ids = {db["id"] for db in target_databases}

            # Collect all unique target database IDs from the mapping
            mapped_target_ids = set()
            for source_db_id in self.manifest.databases.keys():
                target_id = self.id_remapper.resolve_db_id(source_db_id)
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

    def report_unmapped_databases(self, unmapped_dbs: list[UnmappedDatabase]) -> None:
        """Report unmapped databases and exit.

        Args:
            unmapped_dbs: List of unmapped databases
        """
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

    def validate_all(self) -> None:
        """Run all validation checks.

        Raises:
            SystemExit: If any validation fails
        """
        logger.info("Validating database mappings...")
        unmapped_dbs = self.validate_database_mappings()
        if unmapped_dbs:
            self.report_unmapped_databases(unmapped_dbs)

        logger.info("Validating database mappings against target instance...")
        self.validate_target_databases()

        logger.info("✅ All validations passed.")
