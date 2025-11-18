"""A robust, production-ready client for interacting with the Metabase API.

Handles authentication, pagination, retries, and error handling.
"""

import json
import logging
from typing import Any

import requests
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from lib.utils import TOOL_VERSION

logger = logging.getLogger("metabase_migration")


class MetabaseAPIError(Exception):
    """Custom exception for Metabase API errors."""

    def __init__(self, message: str, status_code: int | None = None, response_data: Any = None):
        """Initialize the MetabaseAPIError with message, status code, and response data."""
        self.message = message
        self.status_code = status_code
        self.response_data = response_data
        super().__init__(f"Metabase API Error: {message} (Status: {status_code})")

    def __str__(self) -> str:
        """Return a formatted string representation of the error."""
        return f"Metabase API request failed [{self.status_code}]: {self.message}"


class MetabaseClient:
    """Client for the Metabase API."""

    def __init__(
        self,
        base_url: str,
        username: str | None = None,
        password: str | None = None,
        session_token: str | None = None,
        personal_token: str | None = None,
    ) -> None:
        """Initialize the MetabaseClient with authentication credentials."""
        self.base_url = base_url.rstrip("/")
        self.api_url = f"{self.base_url}/api"
        self._username = username
        self._password = password
        self._session_token = session_token
        self._personal_token = personal_token
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": f"MetabaseMigrationToolkit/{TOOL_VERSION}"})

    def _authenticate(self) -> None:
        """Authenticates with the Metabase API and stores the session token."""
        if self._session_token or self._personal_token:
            logger.info("Using provided session or personal token for authentication.")
            return

        if not self._username or not self._password:
            raise MetabaseAPIError(
                "Authentication required: Please provide username/password or a session/personal token."
            )

        logger.info(f"Authenticating as user {self._username}...")
        try:
            response = self._session.post(
                f"{self.api_url}/session",
                json={"username": self._username, "password": self._password},
            )
            response.raise_for_status()
            self._session_token = response.json().get("id")
            if not self._session_token:
                raise MetabaseAPIError("Authentication successful, but no session ID returned.")
            logger.info("Authentication successful.")
        except requests.exceptions.RequestException as e:
            logger.error(f"Authentication failed: {e.response.text if e.response else e}")
            raise MetabaseAPIError(
                f"Authentication failed for user {self._username}",
                status_code=e.response.status_code if e.response else None,
            ) from e

    def _prepare_headers(self) -> dict[str, str]:
        """Prepares headers for an API request, authenticating if necessary."""
        if not self._session.headers.get("X-Metabase-Session") and not self._session.headers.get(
            "X-Metabase-API-Key"
        ):
            if self._personal_token:
                self._session.headers.update({"X-Metabase-API-Key": self._personal_token})
            elif self._session_token:
                self._session.headers.update({"X-Metabase-Session": self._session_token})
            else:
                self._authenticate()
                if self._session_token:  # Re-check after authentication
                    self._session.headers.update({"X-Metabase-Session": self._session_token})

        # Return the authentication headers that were set
        headers = {}
        if "X-Metabase-Session" in self._session.headers:
            headers["X-Metabase-Session"] = str(self._session.headers["X-Metabase-Session"])
        if "X-Metabase-API-Key" in self._session.headers:
            headers["X-Metabase-API-Key"] = str(self._session.headers["X-Metabase-API-Key"])
        return headers

    def _should_retry(self, exception: BaseException) -> bool:
        """Determines if a request should be retried."""
        if isinstance(exception, requests.exceptions.ConnectionError | requests.exceptions.Timeout):
            return True
        if isinstance(exception, MetabaseAPIError) and exception.status_code in [
            429,
            500,
            502,
            503,
            504,
        ]:
            return True
        return False

    @retry(
        wait=wait_exponential(multiplier=1, min=2, max=30),
        stop=stop_after_attempt(5),
        retry=retry_if_exception_type(
            (requests.exceptions.ConnectionError, requests.exceptions.Timeout, MetabaseAPIError)
        ),
        before_sleep=lambda retry_state: logger.warning(
            f"Retrying API call due to "
            f"{retry_state.outcome.exception() if retry_state.outcome is not None else 'unknown error'} "
            f"(Attempt {retry_state.attempt_number})",
        ),
    )
    def _request(self, method: str, endpoint: str, **kwargs: Any) -> requests.Response:
        """Makes a request to the Metabase API with authentication and retries."""
        self._prepare_headers()
        url = f"{self.api_url}/{endpoint.lstrip('/')}"
        logger.debug(f"Request: {method.upper()} {url} with params {kwargs.get('params')}")

        try:
            response = self._session.request(method, url, **kwargs)
            response.raise_for_status()
            return response
        except requests.exceptions.HTTPError as e:
            # Log request body for debugging
            request_body = kwargs.get("json") or kwargs.get("data")
            if request_body:
                logger.error(f"Request body: {request_body}")

            # Format response body for better readability
            response_text = e.response.text
            try:
                # Try to parse as JSON for pretty printing
                response_json = e.response.json()
                formatted_response = json.dumps(response_json, indent=2)
            except (ValueError, json.JSONDecodeError):
                # Fall back to raw text if not JSON
                formatted_response = response_text

            logger.error(
                f"{method} API request to {url} failed with status {e.response.status_code}: {formatted_response}"
            )
            raise MetabaseAPIError(
                message=f"Request to {endpoint} failed",
                status_code=e.response.status_code,
                response_data=response_text,
            ) from e

    def _get_paginated(self, endpoint: str, params: dict | None = None) -> list[dict]:
        """Handles Metabase's pagination to fetch all items from an endpoint.

        NOTE: Metabase pagination is inconsistent. This handles common cases but may need adjustment.
        Many core endpoints like /api/collection/items surprisingly do not paginate and return all results.
        This function assumes that if pagination exists, it will be in the response metadata.
        """
        all_items = []
        page = 1
        params = params or {}

        while True:
            current_params = params.copy()
            # This is a guess; Metabase API docs are not explicit on pagination for all endpoints.
            # We'll rely on the fact that for many endpoints, it just returns all items.
            # A more robust solution might inspect response headers or a metadata block if available.
            # For now, we will not add page parameter unless we know it's needed.

            response = self._request("get", endpoint, params=current_params)
            data = response.json()

            # Handle different response structures
            if isinstance(data, list):
                # Simple list response, assume no more pages
                all_items.extend(data)
                break
            elif isinstance(data, dict) and "data" in data:
                items = data.get("data", [])
                all_items.extend(items)
                total = data.get("total")
                limit = data.get("limit", len(items))
                if total is None or limit == 0 or len(all_items) >= total:
                    break
                page += 1
            else:
                raise MetabaseAPIError(
                    f"Unexpected pagination response format from {endpoint}", response_data=data
                )

        return all_items

    # --- Public API Methods ---

    def get_collections_tree(self, params: dict | None = None) -> Any:
        """Fetches the entire collection tree."""
        return self._request("get", "/collection/tree", params=params or {}).json()

    def get_collection(self, collection_id: int) -> Any:
        """Fetches the full details for a single collection."""
        return self._request("get", f"/collection/{collection_id}").json()

    def get_collection_items(self, collection_id: int | str, params: dict | None = None) -> Any:
        """Fetches items within a specific collection."""
        return self._request(
            "get", f"/collection/{collection_id}/items", params=params or {}
        ).json()

    def get_card(self, card_id: int) -> Any:
        """Fetches the full details for a single card."""
        return self._request("get", f"/card/{card_id}").json()

    def get_dashboard(self, dashboard_id: int) -> Any:
        """Fetches the full details for a single dashboard."""
        return self._request("get", f"/dashboard/{dashboard_id}").json()

    def get_databases(self) -> Any:
        """Fetches a list of all databases."""
        response = self._request("get", "/database").json()

        # Handle different response formats
        if isinstance(response, dict) and "data" in response:
            return response["data"]
        elif isinstance(response, list):
            return response
        else:
            logger.warning(f"Unexpected databases response format: {type(response)}")
            logger.debug(f"Response: {response}")
            return []

    def create_collection(self, payload: dict) -> Any:
        """Creates a new collection."""
        return self._request("post", "/collection", json=payload).json()

    def update_collection(self, collection_id: int, payload: dict) -> Any:
        """Updates an existing collection."""
        return self._request("put", f"/collection/{collection_id}", json=payload).json()

    def create_card(self, payload: dict) -> Any:
        """Creates a new card."""
        return self._request("post", "/card", json=payload).json()

    def update_card(self, card_id: int, payload: dict) -> Any:
        """Updates an existing card."""
        return self._request("put", f"/card/{card_id}", json=payload).json()

    def create_dashboard(self, payload: dict) -> Any:
        """Creates a new dashboard."""
        return self._request("post", "/dashboard", json=payload).json()

    def update_dashboard(self, dashboard_id: int, payload: dict) -> Any:
        """Updates an existing dashboard and its dashcards."""
        # The main PUT endpoint handles dashcard and tab updates
        return self._request("put", f"/dashboard/{dashboard_id}", json=payload).json()

    # --- Permissions API Methods ---

    def get_permission_groups(self) -> Any:
        """Fetches all permission groups."""
        return self._request("get", "/permissions/group").json()

    def get_permissions_graph(self) -> Any:
        """Fetches the complete permissions graph for data access."""
        return self._request("get", "/permissions/graph").json()

    def update_permissions_graph(self, graph: dict) -> Any:
        """Updates the permissions graph for data access."""
        return self._request("put", "/permissions/graph", json=graph).json()

    def get_collection_permissions_graph(self) -> Any:
        """Fetches the permissions graph for collection access."""
        return self._request("get", "/collection/graph").json()

    def update_collection_permissions_graph(self, graph: dict) -> Any:
        """Updates the permissions graph for collection access."""
        return self._request("put", "/collection/graph", json=graph).json()

    def get_database_metadata(self, database_id: int) -> Any:
        """Fetches metadata for a specific database, including tables and fields."""
        return self._request("get", f"/database/{database_id}/metadata").json()

    def get_table(self, table_id: int) -> Any:
        """Fetches metadata for a specific table."""
        return self._request("get", f"/table/{table_id}").json()

    def get_field(self, field_id: int) -> Any:
        """Fetches metadata for a specific field."""
        return self._request("get", f"/field/{field_id}").json()
