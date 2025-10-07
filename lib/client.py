"""
A robust, production-ready client for interacting with the Metabase API.
Handles authentication, pagination, retries, and error handling.
"""

import json
import logging
from typing import Any

import requests
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from lib.utils import TOOL_VERSION

logger = logging.getLogger("metabase_migration")


class MetabaseAPIError(Exception):
    """Custom exception for Metabase API errors."""

    def __init__(self, message: str, status_code: int | None = None, response_data: Any = None):
        self.message = message
        self.status_code = status_code
        self.response_data = response_data
        super().__init__(f"Metabase API Error: {message} (Status: {status_code})")

    def __str__(self):
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
    ):
        self.base_url = base_url.rstrip("/")
        self.api_url = f"{self.base_url}/api"
        self._username = username
        self._password = password
        self._session_token = session_token
        self._personal_token = personal_token
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": f"MetabaseMigrationToolkit/{TOOL_VERSION}"})

    def _authenticate(self):
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
        return self._session.headers

    def _should_retry(self, exception: BaseException) -> bool:
        """Determines if a request should be retried."""
        if isinstance(
            exception, (requests.exceptions.ConnectionError, requests.exceptions.Timeout)
        ):
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
            f"Retrying API call due to {retry_state.outcome.exception()} (Attempt {retry_state.attempt_number})"
        ),
    )
    def _request(self, method: str, endpoint: str, **kwargs) -> requests.Response:
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
        """
        Handles Metabase's pagination to fetch all items from an endpoint.
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

    def get_collections_tree(self, params: dict | None = None) -> list[dict]:
        """Fetches the entire collection tree."""
        return self._request("get", "/collection/tree", params=params or {}).json()

    def get_collection(self, collection_id: int) -> dict:
        """Fetches the full details for a single collection."""
        return self._request("get", f"/collection/{collection_id}").json()

    def get_collection_items(self, collection_id: int | str, params: dict | None = None) -> dict:
        """Fetches items within a specific collection."""
        return self._request(
            "get", f"/collection/{collection_id}/items", params=params or {}
        ).json()

    def get_card(self, card_id: int) -> dict:
        """Fetches the full details for a single card."""
        return self._request("get", f"/card/{card_id}").json()

    def get_dashboard(self, dashboard_id: int) -> dict:
        """Fetches the full details for a single dashboard."""
        return self._request("get", f"/dashboard/{dashboard_id}").json()

    def get_databases(self) -> list[dict]:
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

    def create_collection(self, payload: dict) -> dict:
        """Creates a new collection."""
        return self._request("post", "/collection", json=payload).json()

    def update_collection(self, collection_id: int, payload: dict) -> dict:
        """Updates an existing collection."""
        return self._request("put", f"/collection/{collection_id}", json=payload).json()

    def create_card(self, payload: dict) -> dict:
        """Creates a new card."""
        return self._request("post", "/card", json=payload).json()

    def update_card(self, card_id: int, payload: dict) -> dict:
        """Updates an existing card."""
        return self._request("put", f"/card/{card_id}", json=payload).json()

    def create_dashboard(self, payload: dict) -> dict:
        """Creates a new dashboard."""
        return self._request("post", "/dashboard", json=payload).json()

    def update_dashboard(self, dashboard_id: int, payload: dict) -> dict:
        """Updates an existing dashboard and its dashcards."""
        # The main PUT endpoint handles dashcard and tab updates
        return self._request("put", f"/dashboard/{dashboard_id}", json=payload).json()
