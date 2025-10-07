"""
Helper utilities for integration tests.

Provides functions to set up Metabase instances, create test data,
and verify export/import operations.
"""

import logging
import time
from typing import Any

import requests

logger = logging.getLogger(__name__)


class MetabaseTestHelper:
    """Helper class for setting up and managing Metabase test instances."""

    def __init__(
        self, base_url: str, email: str = "admin@example.com", password: str = "Admin123!"
    ):
        self.base_url = base_url.rstrip("/")
        self.api_url = f"{self.base_url}/api"
        self.email = email
        self.password = password
        self.session_token: str | None = None

    def wait_for_metabase(self, timeout: int = 300, interval: int = 10) -> bool:
        """
        Wait for Metabase to be ready.

        Args:
            timeout: Maximum time to wait in seconds
            interval: Time between checks in seconds

        Returns:
            True if Metabase is ready, False otherwise
        """
        start_time = time.time()
        logger.info(f"Waiting for Metabase at {self.base_url} to be ready...")

        while time.time() - start_time < timeout:
            try:
                response = requests.get(f"{self.api_url}/health", timeout=5)
                if response.status_code == 200:
                    logger.info(f"Metabase at {self.base_url} is ready!")
                    return True
            except requests.exceptions.RequestException:
                pass

            time.sleep(interval)
            logger.debug(
                f"Still waiting for Metabase... ({int(time.time() - start_time)}s elapsed)"
            )

        logger.error(f"Metabase at {self.base_url} did not become ready within {timeout}s")
        return False

    def is_setup_complete(self) -> bool:
        """Check if Metabase setup is complete."""
        try:
            response = requests.get(f"{self.api_url}/session/properties", timeout=10)
            if response.status_code == 200:
                data = response.json()
                return data.get("setup-token") is None
            return False
        except Exception as e:
            logger.debug(f"Error checking setup status: {e}")
            return False

    def setup_metabase(self) -> bool:
        """
        Complete initial Metabase setup.

        Returns:
            True if setup was successful, False otherwise
        """
        if self.is_setup_complete():
            logger.info(f"Metabase at {self.base_url} is already set up")
            return True

        logger.info(f"Setting up Metabase at {self.base_url}...")

        try:
            # Get setup token
            response = requests.get(f"{self.api_url}/session/properties", timeout=10)
            setup_token = response.json().get("setup-token")

            if not setup_token:
                logger.error("No setup token found")
                return False

            # Complete setup
            setup_data = {
                "token": setup_token,
                "user": {
                    "first_name": "Admin",
                    "last_name": "User",
                    "email": self.email,
                    "password": self.password,
                    "site_name": "Test Metabase",
                },
                "prefs": {"site_name": "Test Metabase", "allow_tracking": False},
            }

            response = requests.post(f"{self.api_url}/setup", json=setup_data, timeout=30)

            if response.status_code in [200, 201]:
                logger.info(f"Metabase at {self.base_url} setup complete!")
                return True
            else:
                logger.error(f"Setup failed: {response.status_code} - {response.text}")
                return False

        except Exception as e:
            logger.error(f"Error during setup: {e}")
            return False

    def login(self) -> bool:
        """
        Login to Metabase and get session token.

        Returns:
            True if login was successful, False otherwise
        """
        try:
            response = requests.post(
                f"{self.api_url}/session",
                json={"username": self.email, "password": self.password},
                timeout=10,
            )

            if response.status_code == 200:
                self.session_token = response.json().get("id")
                logger.info(f"Successfully logged in to {self.base_url}")
                return True
            else:
                logger.error(f"Login failed: {response.status_code} - {response.text}")
                return False

        except Exception as e:
            logger.error(f"Error during login: {e}")
            return False

    def _get_headers(self) -> dict[str, str]:
        """Get headers for authenticated requests."""
        if not self.session_token:
            raise ValueError("Not logged in. Call login() first.")
        return {"X-Metabase-Session": self.session_token, "Content-Type": "application/json"}

    def add_database(
        self, name: str, host: str, port: int, dbname: str, user: str, password: str
    ) -> int | None:
        """
        Add a PostgreSQL database to Metabase.

        Returns:
            Database ID if successful, None otherwise
        """
        try:
            database_data = {
                "name": name,
                "engine": "postgres",
                "details": {
                    "host": host,
                    "port": port,
                    "dbname": dbname,
                    "user": user,
                    "password": password,
                    "ssl": False,
                    "tunnel-enabled": False,
                },
                "auto_run_queries": True,
                "is_full_sync": True,
                "schedules": {},
            }

            response = requests.post(
                f"{self.api_url}/database",
                json=database_data,
                headers=self._get_headers(),
                timeout=30,
            )

            if response.status_code in [200, 201]:
                db_id = response.json().get("id")
                logger.info(f"Added database '{name}' with ID {db_id}")

                # Wait for sync to complete
                self._wait_for_database_sync(db_id)
                return db_id
            else:
                logger.error(f"Failed to add database: {response.status_code} - {response.text}")
                return None

        except Exception as e:
            logger.error(f"Error adding database: {e}")
            return None

    def _wait_for_database_sync(self, db_id: int, timeout: int = 60) -> bool:
        """Wait for database sync to complete."""
        start_time = time.time()

        while time.time() - start_time < timeout:
            try:
                response = requests.get(
                    f"{self.api_url}/database/{db_id}", headers=self._get_headers(), timeout=10
                )

                if response.status_code == 200:
                    data = response.json()
                    if data.get("initial_sync_status") == "complete":
                        logger.info(f"Database {db_id} sync complete")
                        return True

            except Exception as e:
                logger.debug(f"Error checking sync status: {e}")

            time.sleep(5)

        logger.warning(f"Database {db_id} sync did not complete within {timeout}s")
        return False

    def create_collection(
        self, name: str, description: str = "", parent_id: int | None = None
    ) -> int | None:
        """
        Create a collection.

        Returns:
            Collection ID if successful, None otherwise
        """
        try:
            collection_data = {"name": name, "description": description, "color": "#509EE3"}

            if parent_id is not None:
                collection_data["parent_id"] = parent_id

            response = requests.post(
                f"{self.api_url}/collection",
                json=collection_data,
                headers=self._get_headers(),
                timeout=10,
            )

            if response.status_code in [200, 201]:
                collection_id = response.json().get("id")
                logger.info(f"Created collection '{name}' with ID {collection_id}")
                return collection_id
            else:
                logger.error(
                    f"Failed to create collection: {response.status_code} - {response.text}"
                )
                return None

        except Exception as e:
            logger.error(f"Error creating collection: {e}")
            return None

    def create_card(
        self,
        name: str,
        database_id: int,
        collection_id: int | None = None,
        query: dict[str, Any] | None = None,
    ) -> int | None:
        """
        Create a card (question).

        Returns:
            Card ID if successful, None otherwise
        """
        try:
            if query is None:
                # Default simple query
                query = {
                    "database": database_id,
                    "type": "query",
                    "query": {"source-table": 1},  # Assuming first table
                }

            card_data = {
                "name": name,
                "dataset_query": query,
                "display": "table",
                "visualization_settings": {},
                "collection_id": collection_id,
            }

            response = requests.post(
                f"{self.api_url}/card", json=card_data, headers=self._get_headers(), timeout=10
            )

            if response.status_code in [200, 201]:
                card_id = response.json().get("id")
                logger.info(f"Created card '{name}' with ID {card_id}")
                return card_id
            else:
                logger.error(f"Failed to create card: {response.status_code} - {response.text}")
                return None

        except Exception as e:
            logger.error(f"Error creating card: {e}")
            return None

    def create_dashboard(
        self, name: str, collection_id: int | None = None, card_ids: list[int] | None = None
    ) -> int | None:
        """
        Create a dashboard.

        Returns:
            Dashboard ID if successful, None otherwise
        """
        try:
            dashboard_data = {
                "name": name,
                "description": f"Test dashboard: {name}",
                "collection_id": collection_id,
                "parameters": [],
            }

            response = requests.post(
                f"{self.api_url}/dashboard",
                json=dashboard_data,
                headers=self._get_headers(),
                timeout=10,
            )

            if response.status_code not in [200, 201]:
                logger.error(
                    f"Failed to create dashboard: {response.status_code} - {response.text}"
                )
                return None

            dashboard_id = response.json().get("id")
            logger.info(f"Created dashboard '{name}' with ID {dashboard_id}")

            # Add cards to dashboard if provided
            if card_ids:
                for idx, card_id in enumerate(card_ids):
                    self._add_card_to_dashboard(dashboard_id, card_id, row=idx * 4)

            return dashboard_id

        except Exception as e:
            logger.error(f"Error creating dashboard: {e}")
            return None

    def _add_card_to_dashboard(
        self, dashboard_id: int, card_id: int, row: int = 0, col: int = 0
    ) -> bool:
        """Add a card to a dashboard."""
        try:
            dashcard_data = {"cardId": card_id, "row": row, "col": col, "size_x": 4, "size_y": 4}

            response = requests.post(
                f"{self.api_url}/dashboard/{dashboard_id}/cards",
                json=dashcard_data,
                headers=self._get_headers(),
                timeout=10,
            )

            return response.status_code in [200, 201]

        except Exception as e:
            logger.error(f"Error adding card to dashboard: {e}")
            return False

    def get_collections(self) -> list[dict[str, Any]]:
        """Get all collections."""
        try:
            response = requests.get(
                f"{self.api_url}/collection", headers=self._get_headers(), timeout=10
            )

            if response.status_code == 200:
                return response.json()
            return []

        except Exception as e:
            logger.error(f"Error getting collections: {e}")
            return []

    def get_cards_in_collection(self, collection_id: int) -> list[dict[str, Any]]:
        """Get all cards in a collection."""
        try:
            response = requests.get(
                f"{self.api_url}/collection/{collection_id}/items",
                params={"models": "card"},
                headers=self._get_headers(),
                timeout=10,
            )

            if response.status_code == 200:
                return response.json().get("data", [])
            return []

        except Exception as e:
            logger.error(f"Error getting cards: {e}")
            return []

    def get_databases(self) -> list[dict[str, Any]]:
        """Get all databases."""
        try:
            response = requests.get(
                f"{self.api_url}/database", headers=self._get_headers(), timeout=10
            )

            if response.status_code == 200:
                data = response.json()
                # Handle both list and dict responses
                if isinstance(data, list):
                    return data
                elif isinstance(data, dict) and "data" in data:
                    return data["data"]
            return []

        except Exception as e:
            logger.error(f"Error getting databases: {e}")
            return []

    def cleanup_test_data(self):
        """Clean up test collections and cards."""
        try:
            # Get all collections
            collections = self.get_collections()

            # Delete test collections (those starting with "Test")
            for collection in collections:
                if collection.get("name", "").startswith("Test"):
                    collection_id = collection.get("id")
                    try:
                        requests.delete(
                            f"{self.api_url}/collection/{collection_id}",
                            headers=self._get_headers(),
                            timeout=10,
                        )
                        logger.info(f"Deleted test collection {collection_id}")
                    except Exception as e:
                        logger.warning(f"Failed to delete collection {collection_id}: {e}")

        except Exception as e:
            logger.error(f"Error during cleanup: {e}")
