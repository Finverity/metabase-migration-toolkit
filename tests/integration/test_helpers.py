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

    # =========================================================================
    # Database Methods
    # =========================================================================

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

    def _wait_for_database_sync(self, db_id: int, timeout: int = 120) -> bool:
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

    def get_database_metadata(self, db_id: int) -> dict[str, Any] | None:
        """Get database metadata including tables and fields."""
        try:
            response = requests.get(
                f"{self.api_url}/database/{db_id}/metadata",
                headers=self._get_headers(),
                timeout=30,
            )
            if response.status_code == 200:
                return response.json()
            return None
        except Exception as e:
            logger.error(f"Error getting database metadata: {e}")
            return None

    def get_table_id_by_name(self, db_id: int, table_name: str) -> int | None:
        """Get table ID by name from database metadata."""
        metadata = self.get_database_metadata(db_id)
        if metadata:
            for table in metadata.get("tables", []):
                if table.get("name") == table_name:
                    return table.get("id")
        return None

    def get_field_id_by_name(self, db_id: int, table_name: str, field_name: str) -> int | None:
        """Get field ID by name from database metadata."""
        metadata = self.get_database_metadata(db_id)
        if metadata:
            for table in metadata.get("tables", []):
                if table.get("name") == table_name:
                    for field in table.get("fields", []):
                        if field.get("name") == field_name:
                            return field.get("id")
        return None

    # =========================================================================
    # Collection Methods
    # =========================================================================

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

    def get_collection(self, collection_id: int) -> dict[str, Any] | None:
        """Get a single collection by ID."""
        try:
            response = requests.get(
                f"{self.api_url}/collection/{collection_id}",
                headers=self._get_headers(),
                timeout=10,
            )
            if response.status_code == 200:
                return response.json()
            return None
        except Exception as e:
            logger.error(f"Error getting collection: {e}")
            return None

    def get_collection_items(
        self, collection_id: int | str, models: list[str] | None = None
    ) -> list[dict[str, Any]]:
        """Get items in a collection."""
        try:
            params = {}
            if models:
                params["models"] = models

            response = requests.get(
                f"{self.api_url}/collection/{collection_id}/items",
                params=params,
                headers=self._get_headers(),
                timeout=10,
            )

            if response.status_code == 200:
                data = response.json()
                return data.get("data", []) if isinstance(data, dict) else data
            return []

        except Exception as e:
            logger.error(f"Error getting collection items: {e}")
            return []

    # =========================================================================
    # Card Methods
    # =========================================================================

    def create_card(
        self,
        name: str,
        database_id: int,
        collection_id: int | None = None,
        query: dict[str, Any] | None = None,
        display: str = "table",
        visualization_settings: dict[str, Any] | None = None,
        description: str | None = None,
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
                "display": display,
                "visualization_settings": visualization_settings or {},
                "collection_id": collection_id,
            }

            if description:
                card_data["description"] = description

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

    def create_model(
        self,
        name: str,
        database_id: int,
        collection_id: int | None = None,
        query: dict[str, Any] | None = None,
        description: str | None = None,
    ) -> int | None:
        """
        Create a model (dataset).

        Returns:
            Model ID if successful, None otherwise
        """
        try:
            if query is None:
                query = {
                    "database": database_id,
                    "type": "query",
                    "query": {"source-table": 1},
                }

            card_data = {
                "name": name,
                "dataset_query": query,
                "display": "table",
                "visualization_settings": {},
                "collection_id": collection_id,
                "type": "model",  # This makes it a model instead of a question
            }

            if description:
                card_data["description"] = description

            response = requests.post(
                f"{self.api_url}/card", json=card_data, headers=self._get_headers(), timeout=10
            )

            if response.status_code in [200, 201]:
                model_id = response.json().get("id")
                logger.info(f"Created model '{name}' with ID {model_id}")
                return model_id
            else:
                logger.error(f"Failed to create model: {response.status_code} - {response.text}")
                return None

        except Exception as e:
            logger.error(f"Error creating model: {e}")
            return None

    def create_native_query_card(
        self,
        name: str,
        database_id: int,
        sql: str,
        collection_id: int | None = None,
        template_tags: dict[str, Any] | None = None,
    ) -> int | None:
        """Create a card with a native SQL query."""
        try:
            native_query: dict[str, Any] = {"query": sql}
            if template_tags:
                native_query["template-tags"] = template_tags

            query = {
                "database": database_id,
                "type": "native",
                "native": native_query,
            }

            return self.create_card(name, database_id, collection_id, query)
        except Exception as e:
            logger.error(f"Error creating native query card: {e}")
            return None

    def get_card(self, card_id: int) -> dict[str, Any] | None:
        """Get a single card by ID."""
        try:
            response = requests.get(
                f"{self.api_url}/card/{card_id}",
                headers=self._get_headers(),
                timeout=10,
            )
            if response.status_code == 200:
                return response.json()
            return None
        except Exception as e:
            logger.error(f"Error getting card: {e}")
            return None

    def get_cards_in_collection(self, collection_id: int) -> list[dict[str, Any]]:
        """Get all cards and models in a collection."""
        return self.get_collection_items(collection_id, models=["card", "dataset"])

    def create_card_with_join(
        self,
        name: str,
        database_id: int,
        source_table_id: int,
        join_table_id: int,
        source_field_id: int,
        join_field_id: int,
        collection_id: int | None = None,
    ) -> int | None:
        """Create a card with a join between two tables."""
        try:
            query = {
                "database": database_id,
                "type": "query",
                "query": {
                    "source-table": source_table_id,
                    "joins": [
                        {
                            "fields": "all",
                            "source-table": join_table_id,
                            "condition": [
                                "=",
                                ["field", source_field_id, None],
                                ["field", join_field_id, {"join-alias": "JoinedTable"}],
                            ],
                            "alias": "JoinedTable",
                        }
                    ],
                },
            }
            return self.create_card(name, database_id, collection_id, query)
        except Exception as e:
            logger.error(f"Error creating card with join: {e}")
            return None

    def create_card_with_aggregation(
        self,
        name: str,
        database_id: int,
        table_id: int,
        aggregation_type: str,  # "count", "sum", "avg", "min", "max"
        aggregation_field_id: int | None,
        breakout_field_id: int | None = None,
        collection_id: int | None = None,
        display: str = "bar",
    ) -> int | None:
        """Create a card with aggregation and optional breakout."""
        try:
            # Build aggregation
            if aggregation_type == "count":
                aggregation = [["count"]]
            elif aggregation_field_id:
                aggregation = [[aggregation_type, ["field", aggregation_field_id, None]]]
            else:
                aggregation = [["count"]]

            query_dict: dict[str, Any] = {
                "source-table": table_id,
                "aggregation": aggregation,
            }

            if breakout_field_id:
                query_dict["breakout"] = [["field", breakout_field_id, None]]

            query = {
                "database": database_id,
                "type": "query",
                "query": query_dict,
            }

            return self.create_card(name, database_id, collection_id, query, display=display)
        except Exception as e:
            logger.error(f"Error creating card with aggregation: {e}")
            return None

    def create_card_with_filter(
        self,
        name: str,
        database_id: int,
        table_id: int,
        filter_field_id: int,
        filter_value: Any,
        filter_operator: str = "=",  # "=", "!=", ">", "<", ">=", "<=", "contains"
        collection_id: int | None = None,
    ) -> int | None:
        """Create a card with a filter."""
        try:
            query = {
                "database": database_id,
                "type": "query",
                "query": {
                    "source-table": table_id,
                    "filter": [filter_operator, ["field", filter_field_id, None], filter_value],
                },
            }
            return self.create_card(name, database_id, collection_id, query)
        except Exception as e:
            logger.error(f"Error creating card with filter: {e}")
            return None

    def create_card_with_expression(
        self,
        name: str,
        database_id: int,
        table_id: int,
        expression_name: str,
        expression: list[Any],  # MBQL expression like ["+", ["field", 1, None], 100]
        collection_id: int | None = None,
    ) -> int | None:
        """Create a card with a custom expression/calculated field."""
        try:
            query = {
                "database": database_id,
                "type": "query",
                "query": {
                    "source-table": table_id,
                    "expressions": {expression_name: expression},
                },
            }
            return self.create_card(name, database_id, collection_id, query)
        except Exception as e:
            logger.error(f"Error creating card with expression: {e}")
            return None

    def create_card_with_sorting(
        self,
        name: str,
        database_id: int,
        table_id: int,
        order_by_field_id: int,
        direction: str = "descending",  # "ascending" or "descending"
        limit: int | None = None,
        collection_id: int | None = None,
    ) -> int | None:
        """Create a card with sorting and optional limit."""
        try:
            query_dict: dict[str, Any] = {
                "source-table": table_id,
                "order-by": [[direction, ["field", order_by_field_id, None]]],
            }

            if limit:
                query_dict["limit"] = limit

            query = {
                "database": database_id,
                "type": "query",
                "query": query_dict,
            }

            return self.create_card(name, database_id, collection_id, query)
        except Exception as e:
            logger.error(f"Error creating card with sorting: {e}")
            return None

    def archive_card(self, card_id: int) -> bool:
        """Archive a card."""
        try:
            response = requests.put(
                f"{self.api_url}/card/{card_id}",
                json={"archived": True},
                headers=self._get_headers(),
                timeout=10,
            )
            return response.status_code == 200
        except Exception as e:
            logger.error(f"Error archiving card: {e}")
            return False

    def delete_card(self, card_id: int) -> bool:
        """Delete a card."""
        try:
            response = requests.delete(
                f"{self.api_url}/card/{card_id}",
                headers=self._get_headers(),
                timeout=10,
            )
            return response.status_code in [200, 204]
        except Exception as e:
            logger.error(f"Error deleting card: {e}")
            return False

    # =========================================================================
    # Dashboard Methods
    # =========================================================================

    def create_dashboard(
        self,
        name: str,
        collection_id: int | None = None,
        card_ids: list[int] | None = None,
        description: str | None = None,
        parameters: list[dict[str, Any]] | None = None,
    ) -> int | None:
        """
        Create a dashboard.

        Returns:
            Dashboard ID if successful, None otherwise
        """
        try:
            dashboard_data: dict[str, Any] = {
                "name": name,
                "collection_id": collection_id,
                "parameters": parameters or [],
            }

            if description:
                dashboard_data["description"] = description

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

    def create_dashboard_with_filter(
        self,
        name: str,
        collection_id: int | None,
        card_id: int,
        filter_field_id: int,
        filter_table_id: int,
    ) -> int | None:
        """Create a dashboard with a filter parameter linked to a card."""
        try:
            # Define a filter parameter
            parameters = [
                {
                    "id": "category_filter",
                    "name": "Category",
                    "slug": "category",
                    "type": "string/=",
                    "sectionId": "string",
                }
            ]

            dashboard_id = self.create_dashboard(
                name=name,
                collection_id=collection_id,
                parameters=parameters,
            )

            if not dashboard_id:
                return None

            # Add card with parameter mapping
            dashcard_data = {
                "cardId": card_id,
                "row": 0,
                "col": 0,
                "size_x": 8,
                "size_y": 6,
                "parameter_mappings": [
                    {
                        "parameter_id": "category_filter",
                        "card_id": card_id,
                        "target": ["dimension", ["field", filter_field_id, None]],
                    }
                ],
            }

            response = requests.post(
                f"{self.api_url}/dashboard/{dashboard_id}/cards",
                json=dashcard_data,
                headers=self._get_headers(),
                timeout=10,
            )

            if response.status_code not in [200, 201]:
                logger.error(f"Failed to add card with filter: {response.text}")

            return dashboard_id

        except Exception as e:
            logger.error(f"Error creating dashboard with filter: {e}")
            return None

    def _add_card_to_dashboard(
        self,
        dashboard_id: int,
        card_id: int,
        row: int = 0,
        col: int = 0,
        size_x: int = 4,
        size_y: int = 4,
        parameter_mappings: list[dict[str, Any]] | None = None,
    ) -> int | None:
        """Add a card to a dashboard and return the dashcard ID."""
        try:
            dashcard_data: dict[str, Any] = {
                "cardId": card_id,
                "row": row,
                "col": col,
                "size_x": size_x,
                "size_y": size_y,
            }

            if parameter_mappings:
                dashcard_data["parameter_mappings"] = parameter_mappings

            response = requests.post(
                f"{self.api_url}/dashboard/{dashboard_id}/cards",
                json=dashcard_data,
                headers=self._get_headers(),
                timeout=10,
            )

            if response.status_code in [200, 201]:
                return response.json().get("id")
            return None

        except Exception as e:
            logger.error(f"Error adding card to dashboard: {e}")
            return None

    def get_dashboard(self, dashboard_id: int) -> dict[str, Any] | None:
        """Get a single dashboard by ID."""
        try:
            response = requests.get(
                f"{self.api_url}/dashboard/{dashboard_id}",
                headers=self._get_headers(),
                timeout=10,
            )
            if response.status_code == 200:
                return response.json()
            return None
        except Exception as e:
            logger.error(f"Error getting dashboard: {e}")
            return None

    def get_dashboards_in_collection(self, collection_id: int) -> list[dict[str, Any]]:
        """Get all dashboards in a collection."""
        return self.get_collection_items(collection_id, models=["dashboard"])

    def add_text_card_to_dashboard(
        self,
        dashboard_id: int,
        text: str,
        row: int = 0,
        col: int = 0,
        size_x: int = 4,
        size_y: int = 2,
    ) -> int | None:
        """Add a text/markdown card to a dashboard."""
        try:
            dashcard_data = {
                "row": row,
                "col": col,
                "size_x": size_x,
                "size_y": size_y,
                "visualization_settings": {
                    "text": text,
                    "virtual_card": {
                        "name": None,
                        "display": "text",
                        "visualization_settings": {},
                        "dataset_query": {},
                        "archived": False,
                    },
                },
            }

            response = requests.post(
                f"{self.api_url}/dashboard/{dashboard_id}/cards",
                json=dashcard_data,
                headers=self._get_headers(),
                timeout=10,
            )

            if response.status_code in [200, 201]:
                return response.json().get("id")
            logger.error(f"Failed to add text card: {response.status_code} - {response.text}")
            return None

        except Exception as e:
            logger.error(f"Error adding text card to dashboard: {e}")
            return None

    def create_dashboard_with_multiple_filters(
        self,
        name: str,
        collection_id: int | None,
        card_ids: list[int],
        filter_configs: list[dict[str, Any]],
    ) -> int | None:
        """
        Create a dashboard with multiple filter parameters.

        filter_configs should be a list of dicts with keys:
            - id: str (parameter ID)
            - name: str (display name)
            - slug: str (URL slug)
            - type: str (e.g., "string/=", "number/=", "date/single")
            - field_id: int (field to filter on)
        """
        try:
            parameters = []
            for fc in filter_configs:
                parameters.append(
                    {
                        "id": fc["id"],
                        "name": fc["name"],
                        "slug": fc["slug"],
                        "type": fc["type"],
                        "sectionId": fc.get("sectionId", "string"),
                    }
                )

            dashboard_id = self.create_dashboard(
                name=name,
                collection_id=collection_id,
                parameters=parameters,
            )

            if not dashboard_id:
                return None

            # Add cards with parameter mappings
            for idx, card_id in enumerate(card_ids):
                parameter_mappings = []
                for fc in filter_configs:
                    parameter_mappings.append(
                        {
                            "parameter_id": fc["id"],
                            "card_id": card_id,
                            "target": ["dimension", ["field", fc["field_id"], None]],
                        }
                    )

                self._add_card_to_dashboard(
                    dashboard_id=dashboard_id,
                    card_id=card_id,
                    row=idx * 4,
                    col=0,
                    size_x=8,
                    size_y=4,
                    parameter_mappings=parameter_mappings,
                )

            return dashboard_id

        except Exception as e:
            logger.error(f"Error creating dashboard with multiple filters: {e}")
            return None

    def archive_dashboard(self, dashboard_id: int) -> bool:
        """Archive a dashboard."""
        try:
            response = requests.put(
                f"{self.api_url}/dashboard/{dashboard_id}",
                json={"archived": True},
                headers=self._get_headers(),
                timeout=10,
            )
            return response.status_code == 200
        except Exception as e:
            logger.error(f"Error archiving dashboard: {e}")
            return False

    # =========================================================================
    # Permissions Methods
    # =========================================================================

    def create_permission_group(self, name: str) -> int | None:
        """Create a permission group."""
        try:
            response = requests.post(
                f"{self.api_url}/permissions/group",
                json={"name": name},
                headers=self._get_headers(),
                timeout=10,
            )

            if response.status_code in [200, 201]:
                group_id = response.json().get("id")
                logger.info(f"Created permission group '{name}' with ID {group_id}")
                return group_id
            else:
                logger.error(
                    f"Failed to create permission group: {response.status_code} - {response.text}"
                )
                return None

        except Exception as e:
            logger.error(f"Error creating permission group: {e}")
            return None

    def get_permission_groups(self) -> list[dict[str, Any]]:
        """Get all permission groups."""
        try:
            response = requests.get(
                f"{self.api_url}/permissions/group",
                headers=self._get_headers(),
                timeout=10,
            )

            if response.status_code == 200:
                return response.json()
            return []

        except Exception as e:
            logger.error(f"Error getting permission groups: {e}")
            return []

    def get_permissions_graph(self) -> dict[str, Any] | None:
        """Get the data permissions graph."""
        try:
            response = requests.get(
                f"{self.api_url}/permissions/graph",
                headers=self._get_headers(),
                timeout=10,
            )

            if response.status_code == 200:
                return response.json()
            return None

        except Exception as e:
            logger.error(f"Error getting permissions graph: {e}")
            return None

    def update_permissions_graph(self, graph: dict[str, Any]) -> bool:
        """Update the data permissions graph."""
        try:
            response = requests.put(
                f"{self.api_url}/permissions/graph",
                json=graph,
                headers=self._get_headers(),
                timeout=30,
            )

            return response.status_code in [200, 201]

        except Exception as e:
            logger.error(f"Error updating permissions graph: {e}")
            return False

    def set_database_permission(
        self,
        group_id: int,
        database_id: int,
        permission: str = "all",
    ) -> bool:
        """
        Set database permissions for a group.

        Args:
            group_id: The permission group ID
            database_id: The database ID
            permission: Permission level ('all', 'none', 'block')
        """
        try:
            graph = self.get_permissions_graph()
            if not graph:
                return False

            # Update the graph
            if "groups" not in graph:
                graph["groups"] = {}

            group_key = str(group_id)
            db_key = str(database_id)

            if group_key not in graph["groups"]:
                graph["groups"][group_key] = {}

            # Set view-data permission
            graph["groups"][group_key][db_key] = {
                "view-data": permission,
                "create-queries": "query-builder-and-native" if permission == "all" else "no",
            }

            return self.update_permissions_graph(graph)

        except Exception as e:
            logger.error(f"Error setting database permission: {e}")
            return False

    def get_collection_permissions_graph(self) -> dict[str, Any] | None:
        """Get the collection permissions graph."""
        try:
            response = requests.get(
                f"{self.api_url}/collection/graph",
                headers=self._get_headers(),
                timeout=10,
            )

            if response.status_code == 200:
                return response.json()
            return None

        except Exception as e:
            logger.error(f"Error getting collection permissions graph: {e}")
            return None

    def set_collection_permission(
        self,
        group_id: int,
        collection_id: int,
        permission: str = "write",
    ) -> bool:
        """
        Set collection permissions for a group.

        Args:
            group_id: The permission group ID
            collection_id: The collection ID
            permission: Permission level ('write', 'read', 'none')
        """
        try:
            graph = self.get_collection_permissions_graph()
            if not graph:
                return False

            group_key = str(group_id)
            collection_key = str(collection_id)

            if "groups" not in graph:
                graph["groups"] = {}

            if group_key not in graph["groups"]:
                graph["groups"][group_key] = {}

            graph["groups"][group_key][collection_key] = permission

            response = requests.put(
                f"{self.api_url}/collection/graph",
                json=graph,
                headers=self._get_headers(),
                timeout=30,
            )

            return response.status_code in [200, 201]

        except Exception as e:
            logger.error(f"Error setting collection permission: {e}")
            return False

    # =========================================================================
    # Cleanup Methods
    # =========================================================================

    def cleanup_test_data(self):
        """Clean up test collections and cards."""
        try:
            # Get all collections
            collections = self.get_collections()

            # Delete test collections (those starting with "Test" or "E2E")
            for collection in collections:
                name = collection.get("name", "")
                if name.startswith("Test") or name.startswith("E2E"):
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

            # Clean up permission groups
            groups = self.get_permission_groups()
            for group in groups:
                name = group.get("name", "")
                if name.startswith("Test") or name.startswith("E2E"):
                    group_id = group.get("id")
                    try:
                        requests.delete(
                            f"{self.api_url}/permissions/group/{group_id}",
                            headers=self._get_headers(),
                            timeout=10,
                        )
                        logger.info(f"Deleted test permission group {group_id}")
                    except Exception as e:
                        logger.warning(f"Failed to delete permission group {group_id}: {e}")

        except Exception as e:
            logger.error(f"Error during cleanup: {e}")

    # =========================================================================
    # Verification Methods
    # =========================================================================

    def verify_card_query_remapping(self, card_id: int, expected_database_id: int) -> bool:
        """Verify that a card's query has been remapped to the expected database."""
        card = self.get_card(card_id)
        if not card:
            return False

        query = card.get("dataset_query", {})
        actual_db_id = query.get("database")

        if actual_db_id != expected_database_id:
            logger.error(
                f"Card {card_id} has database_id {actual_db_id}, expected {expected_database_id}"
            )
            return False

        return True

    def verify_dashboard_cards(self, dashboard_id: int, expected_card_count: int) -> bool:
        """Verify that a dashboard has the expected number of cards."""
        dashboard = self.get_dashboard(dashboard_id)
        if not dashboard:
            return False

        dashcards = dashboard.get("dashcards", [])
        actual_count = len([dc for dc in dashcards if dc.get("card_id")])

        if actual_count != expected_card_count:
            logger.error(
                f"Dashboard {dashboard_id} has {actual_count} cards, expected {expected_card_count}"
            )
            return False

        return True

    # =========================================================================
    # Advanced Card Methods for Dependency Testing
    # =========================================================================

    def create_native_query_with_model_reference(
        self,
        name: str,
        database_id: int,
        model_id: int,
        model_name: str,
        collection_id: int | None = None,
    ) -> int | None:
        """Create a native SQL query that references a model via {{#id-name}} syntax.

        This pattern is used by Metabase for referencing models/questions from native SQL.

        Args:
            name: Card name
            database_id: Target database ID
            model_id: The ID of the model being referenced
            model_name: The slug/name portion for the reference (e.g., "users-model")
            collection_id: Optional collection ID

        Returns:
            Card ID if successful, None otherwise
        """
        # Create SQL with model reference: {{#123-model-name}}
        sql = f"""
            SELECT *
            FROM {{{{#{model_id}-{model_name}}}}}
            LIMIT 100
        """
        return self.create_native_query_card(
            name=name,
            database_id=database_id,
            sql=sql,
            collection_id=collection_id,
        )

    def create_native_query_with_template_tag_card(
        self,
        name: str,
        database_id: int,
        referenced_card_id: int,
        collection_id: int | None = None,
    ) -> int | None:
        """Create a native SQL query with a template-tag that references another card.

        Template tags with type "card" are used for card references in native queries.

        Args:
            name: Card name
            database_id: Target database ID
            referenced_card_id: The ID of the card being referenced
            collection_id: Optional collection ID

        Returns:
            Card ID if successful, None otherwise
        """
        try:
            # SQL with template tag reference
            sql = """
                SELECT *
                FROM {{card_reference}}
                LIMIT 100
            """

            # Template tag of type "card" that references another card
            template_tags = {
                "card_reference": {
                    "id": "card_reference_tag",
                    "name": "card_reference",
                    "display-name": "Card Reference",
                    "type": "card",
                    "card-id": referenced_card_id,
                }
            }

            native_query: dict[str, Any] = {
                "query": sql,
                "template-tags": template_tags,
            }

            query = {
                "database": database_id,
                "type": "native",
                "native": native_query,
            }

            return self.create_card(name, database_id, collection_id, query)
        except Exception as e:
            logger.error(f"Error creating native query with template tag: {e}")
            return None

    def create_card_with_join_to_card(
        self,
        name: str,
        database_id: int,
        source_table_id: int,
        join_card_id: int,
        source_field_id: int,
        join_field_name: str = "id",
        collection_id: int | None = None,
    ) -> int | None:
        """Create a card with a join to another card (not a table).

        This tests MBQL card references in join clauses.

        Args:
            name: Card name
            database_id: Target database ID
            source_table_id: The source table for the main query
            join_card_id: The card ID to join with (will be card__123)
            source_field_id: Field ID from source table for the join condition
            join_field_name: Field name from the joined card
            collection_id: Optional collection ID

        Returns:
            Card ID if successful, None otherwise
        """
        try:
            query = {
                "database": database_id,
                "type": "query",
                "query": {
                    "source-table": source_table_id,
                    "joins": [
                        {
                            "fields": "all",
                            "source-table": f"card__{join_card_id}",
                            "condition": [
                                "=",
                                ["field", source_field_id, None],
                                [
                                    "field",
                                    join_field_name,
                                    {"join-alias": "JoinedCard", "base-type": "type/Integer"},
                                ],
                            ],
                            "alias": "JoinedCard",
                        }
                    ],
                },
            }
            return self.create_card(name, database_id, collection_id, query)
        except Exception as e:
            logger.error(f"Error creating card with join to card: {e}")
            return None
