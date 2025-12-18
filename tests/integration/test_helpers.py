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
                return db_id  # type: ignore[no-any-return]
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
                    return data["data"]  # type: ignore[no-any-return]
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
                return response.json()  # type: ignore[no-any-return]
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
                    return table.get("id")  # type: ignore[no-any-return]
        return None

    def get_field_id_by_name(self, db_id: int, table_name: str, field_name: str) -> int | None:
        """Get field ID by name from database metadata."""
        metadata = self.get_database_metadata(db_id)
        if metadata:
            for table in metadata.get("tables", []):
                if table.get("name") == table_name:
                    for field in table.get("fields", []):
                        if field.get("name") == field_name:
                            return field.get("id")  # type: ignore[no-any-return]
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
            collection_data: dict[str, str | int] = {
                "name": name,
                "description": description,
                "color": "#509EE3",
            }

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
                return collection_id  # type: ignore[no-any-return]
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
                return response.json()  # type: ignore[no-any-return]
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
                return response.json()  # type: ignore[no-any-return]
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
                return data.get("data", []) if isinstance(data, dict) else data  # type: ignore[no-any-return]
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
                return card_id  # type: ignore[no-any-return]
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
                return model_id  # type: ignore[no-any-return]
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
                return response.json()  # type: ignore[no-any-return]
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
                aggregation: list[list[Any]] = [["count"]]
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

            return dashboard_id  # type: ignore[no-any-return]

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
        """Add a card to a dashboard and return the dashcard ID.

        In v57+, uses PUT /dashboard/:id/cards which requires sending all cards.
        Falls back to POST for older versions.
        """
        try:
            # First, get existing cards on the dashboard
            dashboard = self.get_dashboard(dashboard_id)
            existing_cards = []
            if dashboard:
                for dc in dashboard.get("dashcards", []):
                    existing_cards.append(
                        {
                            "id": dc.get("id"),
                            "card_id": dc.get("card_id"),
                            "row": dc.get("row", 0),
                            "col": dc.get("col", 0),
                            "size_x": dc.get("size_x", 4),
                            "size_y": dc.get("size_y", 4),
                            "parameter_mappings": dc.get("parameter_mappings", []),
                        }
                    )

            # Add new card
            new_card: dict[str, Any] = {
                "id": -1,  # Negative ID for new cards
                "card_id": card_id,
                "row": row,
                "col": col,
                "size_x": size_x,
                "size_y": size_y,
            }
            if parameter_mappings:
                new_card["parameter_mappings"] = parameter_mappings

            all_cards = existing_cards + [new_card]

            # Try v57+ PUT method first
            response = requests.put(
                f"{self.api_url}/dashboard/{dashboard_id}/cards",
                json={"cards": all_cards},
                headers=self._get_headers(),
                timeout=10,
            )

            if response.status_code == 200:
                result = response.json()
                # Find the newly added card (last one or the one with our card_id)
                for card in result.get("cards", []):
                    if card.get("card_id") == card_id:
                        return card.get("id")  # type: ignore[no-any-return]
                return None

            # Fall back to v56 POST method
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
                return response.json().get("id")  # type: ignore[no-any-return]
            return None

        except Exception as e:
            logger.error(f"Error adding card to dashboard: {e}")
            return None

    def create_dashboard_with_visualize_another_way(
        self,
        name: str,
        collection_id: int | None,
        card_id: int,
        database_id: int,
        original_display: str = "table",
        alternate_display: str = "bar",
    ) -> int | None:
        """Create a dashboard with a card displayed twice - normal and 'Visualize another way'.

        This tests the bug fix for embedded card objects in dashcards. When 'Visualize
        another way' is used, the dashcard stores a `card` object with custom visualization
        settings. During migration, the `card.id` reference must be remapped.

        Args:
            name: Dashboard name
            collection_id: Collection to create dashboard in
            card_id: The card to add (will be added twice with different visualizations)
            database_id: Database ID for the card
            original_display: Display type for normal view (default: "table")
            alternate_display: Display type for alternate view (default: "bar")

        Returns:
            Dashboard ID if successful, None otherwise
        """
        try:
            # Create the dashboard
            dashboard_id = self.create_dashboard(
                name=name,
                collection_id=collection_id,
                description="Dashboard testing 'Visualize another way' feature migration",
            )

            if not dashboard_id:
                return None

            # Get the original card to copy its properties
            card_response = requests.get(
                f"{self.api_url}/card/{card_id}",
                headers=self._get_headers(),
                timeout=10,
            )
            if card_response.status_code != 200:
                logger.error(f"Failed to get card {card_id}: {card_response.text}")
                return None

            original_card = card_response.json()

            # Build two dashcards:
            # 1. Normal view (just card_id reference)
            # 2. "Visualize another way" view (card_id + embedded card object with different display)
            dashcards = [
                # Normal dashcard - just references the card
                {
                    "id": -1,
                    "card_id": card_id,
                    "row": 0,
                    "col": 0,
                    "size_x": 8,
                    "size_y": 6,
                    "visualization_settings": {},
                },
                # "Visualize another way" dashcard - includes embedded card object
                {
                    "id": -2,
                    "card_id": card_id,
                    "row": 0,
                    "col": 8,
                    "size_x": 8,
                    "size_y": 6,
                    "visualization_settings": {},
                    # The 'card' object is what makes this "Visualize another way"
                    # It contains the card definition with a different display type
                    "card": {
                        "id": card_id,
                        "name": original_card.get("name", ""),
                        "database_id": database_id,
                        "display": alternate_display,
                        "dataset_query": original_card.get("dataset_query", {}),
                        "visualization_settings": original_card.get("visualization_settings", {}),
                    },
                },
            ]

            # Update dashboard with both dashcards
            response = requests.put(
                f"{self.api_url}/dashboard/{dashboard_id}/cards",
                json={"cards": dashcards},
                headers=self._get_headers(),
                timeout=10,
            )

            if response.status_code == 200:
                logger.info(
                    f"Created dashboard '{name}' with 'Visualize another way' "
                    f"(card {card_id} displayed as {original_display} and {alternate_display})"
                )
                return dashboard_id

            # Fall back to older API if needed
            logger.warning(f"PUT failed: {response.status_code}, trying POST method")

            # Add cards one by one for older versions
            for dashcard in dashcards:
                dashcard_data = {
                    "cardId": dashcard["card_id"],
                    "row": dashcard["row"],
                    "col": dashcard["col"],
                    "size_x": dashcard["size_x"],
                    "size_y": dashcard["size_y"],
                }
                if "card" in dashcard:
                    dashcard_data["card"] = dashcard["card"]

                response = requests.post(
                    f"{self.api_url}/dashboard/{dashboard_id}/cards",
                    json=dashcard_data,
                    headers=self._get_headers(),
                    timeout=10,
                )
                if response.status_code not in [200, 201]:
                    logger.error(f"Failed to add dashcard: {response.text}")

            return dashboard_id

        except Exception as e:
            logger.error(f"Error creating dashboard with visualize another way: {e}")
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
                return response.json()  # type: ignore[no-any-return]
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
                return response.json().get("id")  # type: ignore[no-any-return]
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
                return group_id  # type: ignore[no-any-return]
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
                return response.json()  # type: ignore[no-any-return]
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
                return response.json()  # type: ignore[no-any-return]
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
                return response.json()  # type: ignore[no-any-return]
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

    def cleanup_test_data(self) -> None:
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

    def verify_model_reference_card(self, card_id: int, expected_model_id: int) -> tuple[bool, str]:
        """Verify that a SQL card's model reference has been correctly remapped.

        Checks that:
        1. The SQL contains the correct {{#id-name}} reference
        2. The template-tag key matches the ID in the SQL
        3. The template-tag card-id matches the expected model ID
        4. The template-tag name field matches the key
        5. The card can be executed without errors

        Args:
            card_id: The ID of the card to verify
            expected_model_id: The expected model ID in the remapped card

        Returns:
            Tuple of (success, error_message)
        """
        card = self.get_card(card_id)
        if not card:
            return False, f"Card {card_id} not found"

        dataset_query = card.get("dataset_query", {})

        # Handle v57 stages format
        stages = dataset_query.get("stages", [])
        if stages:
            stage = stages[0]
            sql = stage.get("native", "")
            template_tags = stage.get("template-tags", {})
        else:
            # v56 format
            native = dataset_query.get("native", {})
            sql = native.get("query", "")
            template_tags = native.get("template-tags", {})

        errors = []

        # Check 1: SQL contains the expected model ID reference
        expected_pattern = f"{{{{#{expected_model_id}-"
        if expected_pattern not in sql:
            errors.append(
                f"SQL does not contain expected pattern '{expected_pattern}'. "
                f"SQL: {sql[:200]}..."
            )

        # Check 2 & 3: Template tag key and card-id
        found_correct_tag = False
        for tag_key, tag_data in template_tags.items():
            if tag_data.get("type") == "card":
                tag_card_id = tag_data.get("card-id")
                tag_name = tag_data.get("name", "")

                # Check if this tag references the expected model
                if tag_card_id == expected_model_id:
                    # Check that the key matches the expected format
                    if not tag_key.startswith(f"#{expected_model_id}-"):
                        errors.append(
                            f"Template tag key '{tag_key}' does not match expected "
                            f"format '#{{expected_model_id}}-...'"
                        )

                    # Check that name matches the key
                    if tag_name != tag_key:
                        errors.append(
                            f"Template tag name '{tag_name}' does not match key '{tag_key}'"
                        )

                    found_correct_tag = True
                else:
                    # Found a card tag with wrong ID - this is the bug scenario
                    if f"#{expected_model_id}-" in tag_key or f"#{expected_model_id}-" in tag_name:
                        errors.append(
                            f"Template tag has mismatched IDs: key='{tag_key}', "
                            f"card-id={tag_card_id}, name='{tag_name}'. "
                            f"Expected card-id={expected_model_id}"
                        )

        if not found_correct_tag and not errors:
            errors.append(
                f"No template tag found with card-id={expected_model_id}. "
                f"Tags: {list(template_tags.keys())}"
            )

        # Check 4: Try to execute the card
        try:
            response = requests.post(
                f"{self.api_url}/card/{card_id}/query",
                headers=self._get_headers(),
                timeout=30,
            )
            if response.status_code != 200 and response.status_code != 202:
                error_msg = response.json().get("message", response.text)
                if "missing required parameters" in error_msg.lower():
                    errors.append(f"Card execution failed with missing parameters: {error_msg}")
                else:
                    # Other errors might be OK (e.g., permission issues)
                    logger.warning(f"Card execution returned {response.status_code}: {error_msg}")
        except Exception as e:
            logger.warning(f"Could not execute card: {e}")

        if errors:
            return False, "; ".join(errors)
        return True, "All checks passed"

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
        # Create SQL with model reference: {{#123-model-name}} AS alias
        # The alias is required because the model reference expands to a subquery
        tag_key = f"#{model_id}-{model_name}"
        sql = f"""
            SELECT *
            FROM {{{{{tag_key}}}}} AS model_ref
            LIMIT 100
        """

        # In v57, template-tag key must include # prefix to match SQL reference
        template_tags = {
            tag_key: {
                "type": "card",
                "card-id": model_id,
                "name": tag_key,
                "display-name": tag_key,
            }
        }

        return self.create_native_query_card(
            name=name,
            database_id=database_id,
            sql=sql,
            collection_id=collection_id,
            template_tags=template_tags,
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

    def create_query_builder_card_from_model(
        self,
        name: str,
        database_id: int,
        model_id: int,
        collection_id: int | None = None,
        aggregation: tuple[str, int | None] | None = None,
        breakout_field_name: str | None = None,
        display: str = "table",
    ) -> int | None:
        """Create a Query Builder card that uses a model as its source.

        This creates an MBQL query with source-table: "card__<model_id>" (v56)
        or source-card: <model_id> (v57), which is how Metabase represents
        Query Builder questions that reference models.

        Args:
            name: Card name
            database_id: Target database ID
            model_id: The ID of the model to use as source
            collection_id: Optional collection ID
            aggregation: Optional (agg_type, field_name) tuple for aggregation
            breakout_field_name: Optional field name for GROUP BY
            display: Visualization type (default: "table")

        Returns:
            Card ID if successful, None otherwise
        """
        try:
            query_dict: dict[str, Any] = {
                "source-table": f"card__{model_id}",
            }

            if aggregation:
                agg_type, field_name = aggregation
                if agg_type == "count":
                    query_dict["aggregation"] = [["count"]]
                elif field_name:
                    query_dict["aggregation"] = [
                        [agg_type, ["field", field_name, {"base-type": "type/Integer"}]]
                    ]

            if breakout_field_name:
                query_dict["breakout"] = [
                    ["field", breakout_field_name, {"base-type": "type/Text"}]
                ]

            query = {
                "database": database_id,
                "type": "query",
                "query": query_dict,
            }

            return self.create_card(name, database_id, collection_id, query, display=display)
        except Exception as e:
            logger.error(f"Error creating query builder card from model: {e}")
            return None

    # =========================================================================
    # Dashboard Tab Methods
    # =========================================================================

    def create_dashboard_with_tabs(
        self,
        name: str,
        collection_id: int | None,
        tab_names: list[str],
        card_ids_per_tab: list[list[int]],
    ) -> int | None:
        """Create a dashboard with multiple tabs.

        In Metabase v57, tabs must be created along with dashcards in a single
        PUT request to the dashboard endpoint. Sending tabs alone doesn't work.

        Args:
            name: Dashboard name
            collection_id: Collection to place the dashboard in
            tab_names: List of tab names
            card_ids_per_tab: List of card ID lists, one per tab

        Returns:
            Dashboard ID if successful, None otherwise
        """
        try:
            # Create the dashboard first
            dashboard_id = self.create_dashboard(
                name=name,
                collection_id=collection_id,
            )

            if not dashboard_id:
                return None

            # Build tabs with negative IDs (Metabase will assign real IDs)
            tabs_to_create = []
            for idx, tab_name in enumerate(tab_names):
                tabs_to_create.append(
                    {
                        "id": -(idx + 1),  # Negative IDs for new tabs
                        "name": tab_name,
                        "position": idx,
                    }
                )

            # Build dashcards referencing the temporary tab IDs
            all_dashcards = []
            dashcard_id = -1
            for tab_idx, card_ids in enumerate(card_ids_per_tab):
                temp_tab_id = -(tab_idx + 1)  # Same negative ID as the tab
                for card_idx, card_id in enumerate(card_ids):
                    all_dashcards.append(
                        {
                            "id": dashcard_id,  # Negative ID for new dashcard
                            "card_id": card_id,
                            "row": card_idx * 4,
                            "col": 0,
                            "size_x": 8,
                            "size_y": 4,
                            "dashboard_tab_id": temp_tab_id,
                        }
                    )
                    dashcard_id -= 1

            # In v57, tabs and dashcards must be sent together in one PUT request
            response = requests.put(
                f"{self.api_url}/dashboard/{dashboard_id}",
                json={"tabs": tabs_to_create, "dashcards": all_dashcards},
                headers=self._get_headers(),
                timeout=10,
            )

            if response.status_code not in [200, 201]:
                logger.error(f"Failed to add tabs to dashboard: {response.text}")
                return dashboard_id

            updated_dashboard = response.json()
            actual_tabs = updated_dashboard.get("tabs", [])
            actual_dashcards = updated_dashboard.get("dashcards", [])

            logger.info(f"Created {len(actual_tabs)} tabs and {len(actual_dashcards)} dashcards")

            return dashboard_id

        except Exception as e:
            logger.error(f"Error creating dashboard with tabs: {e}")
            return None

    def create_card_with_multiple_aggregations(
        self,
        name: str,
        database_id: int,
        table_id: int,
        aggregations: list[tuple[str, int | None]],
        breakout_field_id: int | None = None,
        collection_id: int | None = None,
        display: str = "bar",
    ) -> int | None:
        """Create a card with multiple aggregations.

        Args:
            name: Card name
            database_id: Database ID
            table_id: Table ID to query
            aggregations: List of (agg_type, field_id) tuples.
                          agg_type: "count", "sum", "avg", "min", "max"
                          field_id: Field ID for aggregation (None for count)
            breakout_field_id: Optional field ID for GROUP BY
            collection_id: Optional collection ID
            display: Visualization type

        Returns:
            Card ID if successful, None otherwise
        """
        try:
            agg_list = []
            for agg_type, field_id in aggregations:
                if agg_type == "count":
                    agg_list.append(["count"])
                elif field_id is not None:
                    agg_list.append([agg_type, ["field", field_id, None]])  # type: ignore[list-item]

            query_dict: dict[str, Any] = {
                "source-table": table_id,
                "aggregation": agg_list,
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
            logger.error(f"Error creating card with multiple aggregations: {e}")
            return None

    def create_native_query_with_parameters(
        self,
        name: str,
        database_id: int,
        sql: str,
        parameters: list[dict[str, Any]],
        collection_id: int | None = None,
    ) -> int | None:
        """Create a native SQL query with template tag parameters.

        Args:
            name: Card name
            database_id: Database ID
            sql: SQL query with {{param_name}} placeholders
            parameters: List of parameter definitions with keys:
                       - name: str (matches {{name}} in SQL)
                       - display_name: str
                       - type: str ("text", "number", "date", etc.)
                       - default: Any (optional default value)
            collection_id: Optional collection ID

        Returns:
            Card ID if successful, None otherwise
        """
        try:
            template_tags = {}
            for param in parameters:
                param_name = param["name"]
                template_tags[param_name] = {
                    "id": f"{param_name}_tag",
                    "name": param_name,
                    "display-name": param.get("display_name", param_name),
                    "type": param.get("type", "text"),
                }
                if "default" in param:
                    template_tags[param_name]["default"] = param["default"]

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
            logger.error(f"Error creating native query with parameters: {e}")
            return None

    # =========================================================================
    # Verification Methods for ID Remapping
    # =========================================================================

    def verify_table_id_in_query(
        self,
        card_id: int,
        expected_table_id: int,
    ) -> bool:
        """Verify that a card's query uses the expected table ID.

        Args:
            card_id: Card ID to check
            expected_table_id: Expected table ID in the query

        Returns:
            True if table ID matches, False otherwise
        """
        card = self.get_card(card_id)
        if not card:
            logger.error(f"Card {card_id} not found")
            return False

        dataset_query = card.get("dataset_query", {})

        # Check v56 format
        query = dataset_query.get("query", {})
        source_table = query.get("source-table")

        # Check v57 format (stages)
        if source_table is None:
            stages = dataset_query.get("stages", [])
            if stages:
                source_table = stages[0].get("source-table")

        if source_table != expected_table_id:
            logger.error(
                f"Card {card_id} has source-table {source_table}, expected {expected_table_id}"
            )
            return False

        return True

    def verify_query_builder_model_reference(
        self,
        card_id: int,
        expected_model_id: int,
    ) -> tuple[bool, str]:
        """Verify that a Query Builder card's model reference has been correctly remapped.

        Checks that:
        1. The query uses source-table: "card__<model_id>" (v56) or source-card: <model_id> (v57)
        2. The model ID matches the expected value
        3. The card can be executed without errors

        Args:
            card_id: The ID of the card to verify
            expected_model_id: The expected model ID in the remapped card

        Returns:
            Tuple of (success, error_message)
        """
        card = self.get_card(card_id)
        if not card:
            return False, f"Card {card_id} not found"

        dataset_query = card.get("dataset_query", {})
        errors = []

        # Check v57 format first: source-card (integer)
        stages = dataset_query.get("stages", [])
        if stages:
            stage = stages[0]
            source_card = stage.get("source-card")
            if source_card is not None:
                if source_card != expected_model_id:
                    errors.append(f"v57 source-card is {source_card}, expected {expected_model_id}")
            else:
                source_table = stage.get("source-table")
                if isinstance(source_table, str) and source_table.startswith("card__"):
                    actual_model_id = int(source_table.replace("card__", ""))
                    if actual_model_id != expected_model_id:
                        errors.append(
                            f"v57 source-table is {source_table}, expected card__{expected_model_id}"
                        )
                else:
                    errors.append(
                        f"v57 stage has no source-card or card__ reference. "
                        f"source-table: {source_table}"
                    )
        else:
            # v56 format: source-table with "card__" prefix
            query = dataset_query.get("query", {})
            source_table = query.get("source-table")

            if isinstance(source_table, str) and source_table.startswith("card__"):
                actual_model_id = int(source_table.replace("card__", ""))
                if actual_model_id != expected_model_id:
                    errors.append(
                        f"v56 source-table is {source_table}, expected card__{expected_model_id}"
                    )
            else:
                errors.append(
                    f"v56 query has no card__ reference in source-table. "
                    f"source-table: {source_table}"
                )

        # Try to execute the card
        try:
            response = requests.post(
                f"{self.api_url}/card/{card_id}/query",
                headers=self._get_headers(),
                timeout=30,
            )
            if response.status_code not in [200, 202]:
                error_msg = response.json().get("message", response.text)
                if "missing required parameters" in error_msg.lower():
                    errors.append(f"Card execution failed with missing parameters: {error_msg}")
        except Exception as e:
            logger.warning(f"Could not execute card {card_id}: {e}")

        if errors:
            return False, "; ".join(errors)
        return True, ""

    def verify_field_id_in_filter(
        self,
        card_id: int,
        expected_field_id: int,
    ) -> bool:
        """Verify that a card's filter uses the expected field ID.

        Args:
            card_id: Card ID to check
            expected_field_id: Expected field ID in the filter

        Returns:
            True if field ID matches, False otherwise
        """
        card = self.get_card(card_id)
        if not card:
            logger.error(f"Card {card_id} not found")
            return False

        dataset_query = card.get("dataset_query", {})
        query = dataset_query.get("query", {})

        # v56: filter
        filter_clause = query.get("filter")
        if filter_clause is None:
            # v57: filters array or stages
            stages = dataset_query.get("stages", [])
            if stages:
                filter_clause = (
                    stages[0].get("filters", [None])[0] if stages[0].get("filters") else None
                )

        if filter_clause is None:
            logger.error(f"Card {card_id} has no filter clause")
            return False

        # Extract field ID from filter (format: [op, ["field", id, opts], value])
        field_ref = filter_clause[1] if len(filter_clause) > 1 else None
        if not isinstance(field_ref, list) or len(field_ref) < 2:
            logger.error(f"Card {card_id} has unexpected filter format: {filter_clause}")
            return False

        # v56: field_id at index 1
        actual_field_id = field_ref[1] if isinstance(field_ref[1], int) else None
        # v57: field_id might be at index 2 if index 1 is metadata dict
        if actual_field_id is None and isinstance(field_ref[1], dict) and len(field_ref) >= 3:
            actual_field_id = field_ref[2]

        if actual_field_id != expected_field_id:
            logger.error(
                f"Card {card_id} has filter field_id {actual_field_id}, expected {expected_field_id}"
            )
            return False

        return True

    def verify_field_id_in_aggregation(
        self,
        card_id: int,
        expected_field_id: int,
    ) -> bool:
        """Verify that a card's aggregation uses the expected field ID.

        Args:
            card_id: Card ID to check
            expected_field_id: Expected field ID in the aggregation

        Returns:
            True if field ID matches, False otherwise
        """
        card = self.get_card(card_id)
        if not card:
            logger.error(f"Card {card_id} not found")
            return False

        dataset_query = card.get("dataset_query", {})
        query = dataset_query.get("query", {})

        # v56: aggregation
        aggregation = query.get("aggregation")
        if aggregation is None:
            # v57: stages
            stages = dataset_query.get("stages", [])
            if stages:
                aggregation = stages[0].get("aggregation")

        if not aggregation or not aggregation[0]:
            logger.error(f"Card {card_id} has no aggregation")
            return False

        # Find field reference in first aggregation
        agg = aggregation[0]
        if len(agg) < 2:
            # count aggregation has no field
            return True

        field_ref = agg[1]
        if not isinstance(field_ref, list) or field_ref[0] != "field":
            logger.error(f"Card {card_id} has unexpected aggregation format: {agg}")
            return False

        actual_field_id = field_ref[1] if isinstance(field_ref[1], int) else None
        if actual_field_id is None and isinstance(field_ref[1], dict) and len(field_ref) >= 3:
            actual_field_id = field_ref[2]

        if actual_field_id != expected_field_id:
            logger.error(
                f"Card {card_id} has aggregation field_id {actual_field_id}, expected {expected_field_id}"
            )
            return False

        return True

    def verify_field_id_in_order_by(
        self,
        card_id: int,
        expected_field_id: int,
    ) -> bool:
        """Verify that a card's order-by uses the expected field ID.

        Args:
            card_id: Card ID to check
            expected_field_id: Expected field ID in the order-by

        Returns:
            True if field ID matches, False otherwise
        """
        card = self.get_card(card_id)
        if not card:
            logger.error(f"Card {card_id} not found")
            return False

        dataset_query = card.get("dataset_query", {})
        query = dataset_query.get("query", {})

        # v56: order-by
        order_by = query.get("order-by")
        if order_by is None:
            # v57: stages
            stages = dataset_query.get("stages", [])
            if stages:
                order_by = stages[0].get("order-by")

        if not order_by or not order_by[0]:
            logger.error(f"Card {card_id} has no order-by")
            return False

        # Format: [["direction", ["field", id, opts]]]
        order_clause = order_by[0]
        if len(order_clause) < 2:
            logger.error(f"Card {card_id} has unexpected order-by format: {order_by}")
            return False

        field_ref = order_clause[1]
        if not isinstance(field_ref, list) or field_ref[0] != "field":
            logger.error(f"Card {card_id} has unexpected order-by field format: {order_clause}")
            return False

        actual_field_id = field_ref[1] if isinstance(field_ref[1], int) else None
        if actual_field_id is None and isinstance(field_ref[1], dict) and len(field_ref) >= 3:
            actual_field_id = field_ref[2]

        if actual_field_id != expected_field_id:
            logger.error(
                f"Card {card_id} has order-by field_id {actual_field_id}, expected {expected_field_id}"
            )
            return False

        return True

    def verify_dashboard_parameter_field_id(
        self,
        dashboard_id: int,
        parameter_id: str,
        expected_field_id: int,
    ) -> bool:
        """Verify that a dashboard parameter mapping uses the expected field ID.

        Args:
            dashboard_id: Dashboard ID to check
            parameter_id: Parameter ID to check
            expected_field_id: Expected field ID in the parameter mapping

        Returns:
            True if field ID matches, False otherwise
        """
        dashboard = self.get_dashboard(dashboard_id)
        if not dashboard:
            logger.error(f"Dashboard {dashboard_id} not found")
            return False

        dashcards = dashboard.get("dashcards", []) or dashboard.get("ordered_cards", [])

        for dashcard in dashcards:
            mappings = dashcard.get("parameter_mappings", [])
            for mapping in mappings:
                if mapping.get("parameter_id") == parameter_id:
                    target = mapping.get("target", [])
                    # Format: ["dimension", ["field", id, opts]]
                    if len(target) >= 2 and isinstance(target[1], list):
                        field_ref = target[1]
                        if field_ref[0] == "field":
                            actual_field_id = (
                                field_ref[1] if isinstance(field_ref[1], int) else None
                            )
                            if actual_field_id is None and isinstance(field_ref[1], dict):
                                actual_field_id = field_ref[2] if len(field_ref) >= 3 else None

                            if actual_field_id == expected_field_id:
                                return True

        logger.error(
            f"Dashboard {dashboard_id} parameter {parameter_id} does not have field_id {expected_field_id}"
        )
        return False

    def count_items_in_collection(
        self,
        collection_id: int,
        item_types: list[str] | None = None,
    ) -> int:
        """Count items in a collection.

        Args:
            collection_id: Collection ID to count items in
            item_types: List of item types to count (e.g., ["card", "dashboard"])
                       If None, counts all items.

        Returns:
            Number of items in the collection
        """
        items = self.get_collection_items(collection_id, models=item_types)
        return len(items)

    def find_card_by_name(
        self,
        collection_id: int,
        card_name: str,
    ) -> dict[str, Any] | None:
        """Find a card by name in a collection.

        Args:
            collection_id: Collection ID to search in
            card_name: Name of the card to find

        Returns:
            Card data if found, None otherwise
        """
        items = self.get_cards_in_collection(collection_id)
        for item in items:
            if item.get("name") == card_name:
                return self.get_card(item["id"])
        return None

    def find_dashboard_by_name(
        self,
        collection_id: int,
        dashboard_name: str,
    ) -> dict[str, Any] | None:
        """Find a dashboard by name in a collection.

        Args:
            collection_id: Collection ID to search in
            dashboard_name: Name of the dashboard to find

        Returns:
            Dashboard data if found, None otherwise
        """
        items = self.get_dashboards_in_collection(collection_id)
        for item in items:
            if item.get("name") == dashboard_name:
                return self.get_dashboard(item["id"])
        return None
