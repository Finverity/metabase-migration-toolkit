"""Database export logic.

This module handles exporting database information and metadata from the
source Metabase instance.
"""

import logging
from typing import Any

from lib.client import MetabaseClient
from lib.models import Manifest

logger = logging.getLogger("metabase_migration")


class DatabaseExporter:
    """Handles exporting database information and metadata."""

    def __init__(self, client: MetabaseClient, manifest: Manifest):
        """Initialize the DatabaseExporter.

        Args:
            client: Metabase API client
            manifest: Manifest object to populate with database data
        """
        self.client = client
        self.manifest = manifest

    def export_databases(self) -> None:
        """Fetch all databases from the source and add them to the manifest."""
        logger.info("Fetching source databases...")
        databases_response = self.client.get_databases()

        # Handle different response formats
        if isinstance(databases_response, dict) and "data" in databases_response:
            databases = databases_response["data"]
        elif isinstance(databases_response, list):
            databases = databases_response
        else:
            logger.error(f"Unexpected databases response format: {type(databases_response)}")
            logger.debug(f"Response: {databases_response}")
            databases = []

        self.manifest.databases = {db["id"]: db["name"] for db in databases}
        logger.info(f"Found {len(self.manifest.databases)} databases.")

        # Fetch and store metadata for each database (tables and fields)
        self._export_database_metadata(databases)

    def _export_database_metadata(self, databases: list[dict[str, Any]]) -> None:
        """Fetch and store metadata for each database.

        Args:
            databases: List of database dictionaries
        """
        logger.info("Fetching database metadata (tables and fields)...")
        for db in databases:
            db_id = db["id"]
            try:
                logger.debug(f"Fetching metadata for database {db_id} ({db['name']})...")
                metadata = self.client.get_database_metadata(db_id)

                # Store simplified metadata: only id and name for tables and fields
                simplified_metadata = {
                    "tables": [
                        {
                            "id": table["id"],
                            "name": table["name"],
                            "fields": [
                                {"id": field["id"], "name": field["name"]}
                                for field in table.get("fields", [])
                            ],
                        }
                        for table in metadata.get("tables", [])
                    ]
                }
                self.manifest.database_metadata[db_id] = simplified_metadata
                logger.debug(
                    f"  -> Stored metadata for {len(simplified_metadata['tables'])} tables"
                )
            except Exception as e:
                logger.warning(f"Failed to fetch metadata for database {db_id}: {e}")
                # Continue with other databases
