"""
Unit tests for lib/client.py

Tests the MetabaseClient class and API interaction logic.
"""

from unittest.mock import Mock, patch

import pytest
import requests

from lib.client import MetabaseAPIError, MetabaseClient


class TestMetabaseAPIError:
    """Test suite for MetabaseAPIError exception."""

    def test_error_creation(self):
        """Test creating a MetabaseAPIError."""
        error = MetabaseAPIError("Test error", status_code=404)

        assert error.message == "Test error"
        assert error.status_code == 404
        assert "Test error" in str(error)
        assert "404" in str(error)

    def test_error_without_status_code(self):
        """Test creating a MetabaseAPIError without status code."""
        error = MetabaseAPIError("Test error")

        assert error.message == "Test error"
        assert error.status_code is None

    def test_error_with_response_data(self):
        """Test creating a MetabaseAPIError with response data."""
        response_data = {"error": "Not found"}
        error = MetabaseAPIError("Test error", status_code=404, response_data=response_data)

        assert error.response_data == response_data


class TestMetabaseClientInit:
    """Test suite for MetabaseClient initialization."""

    def test_init_with_session_token(self):
        """Test client initialization with session token."""
        client = MetabaseClient(base_url="https://example.com", session_token="test-token")

        assert client.base_url == "https://example.com"
        assert client.api_url == "https://example.com/api"
        assert client._session_token == "test-token"

    def test_init_with_username_password(self):
        """Test client initialization with username and password."""
        client = MetabaseClient(
            base_url="https://example.com",
            username="user@example.com",
            password="password123",  # pragma: allowlist secret
        )

        assert client._username == "user@example.com"
        assert client._password == "password123"  # pragma: allowlist secret

    def test_init_with_personal_token(self):
        """Test client initialization with personal token."""
        client = MetabaseClient(base_url="https://example.com", personal_token="personal-token-123")

        assert client._personal_token == "personal-token-123"

    def test_init_strips_trailing_slash(self):
        """Test that trailing slash is removed from base_url."""
        client = MetabaseClient(base_url="https://example.com/", session_token="test-token")

        assert client.base_url == "https://example.com"
        assert client.api_url == "https://example.com/api"

    def test_init_sets_user_agent(self):
        """Test that User-Agent header is set."""
        client = MetabaseClient(base_url="https://example.com", session_token="test-token")

        assert "User-Agent" in client._session.headers
        assert "MetabaseMigrationToolkit" in client._session.headers["User-Agent"]


class TestMetabaseClientAuthentication:
    """Test suite for MetabaseClient authentication."""

    def test_authenticate_with_existing_session_token(self):
        """Test that authentication is skipped when session token exists."""
        client = MetabaseClient(base_url="https://example.com", session_token="existing-token")

        # Should not raise an error
        client._authenticate()
        assert client._session_token == "existing-token"

    def test_authenticate_with_existing_personal_token(self):
        """Test that authentication is skipped when personal token exists."""
        client = MetabaseClient(base_url="https://example.com", personal_token="personal-token")

        # Should not raise an error
        client._authenticate()
        assert client._personal_token == "personal-token"

    def test_authenticate_without_credentials(self):
        """Test that error is raised when no credentials provided."""
        client = MetabaseClient(base_url="https://example.com")

        with pytest.raises(MetabaseAPIError, match="Authentication required"):
            client._authenticate()

    @patch("requests.Session.post")
    def test_authenticate_success(self, mock_post):
        """Test successful authentication with username/password."""
        mock_response = Mock()
        mock_response.json.return_value = {"id": "session-123"}
        mock_response.raise_for_status = Mock()
        mock_post.return_value = mock_response

        client = MetabaseClient(
            base_url="https://example.com",
            username="user@example.com",
            password="password123",  # pragma: allowlist secret
        )
        client._authenticate()

        assert client._session_token == "session-123"
        mock_post.assert_called_once()

    @patch("requests.Session.post")
    def test_authenticate_no_session_id_returned(self, mock_post):
        """Test authentication failure when no session ID returned."""
        mock_response = Mock()
        mock_response.json.return_value = {}
        mock_response.raise_for_status = Mock()
        mock_post.return_value = mock_response

        client = MetabaseClient(
            base_url="https://example.com",
            username="user@example.com",
            password="password123",  # pragma: allowlist secret
        )

        with pytest.raises(MetabaseAPIError, match="no session ID returned"):
            client._authenticate()

    @patch("requests.Session.post")
    def test_authenticate_request_exception(self, mock_post):
        """Test authentication failure with request exception."""
        mock_response = Mock()
        mock_response.status_code = 401
        mock_response.text = "Unauthorized"

        mock_post.side_effect = requests.exceptions.RequestException(response=mock_response)

        client = MetabaseClient(
            base_url="https://example.com",
            username="user@example.com",
            password="wrong-password",  # pragma: allowlist secret
        )

        with pytest.raises(MetabaseAPIError, match="Authentication failed"):
            client._authenticate()


class TestMetabaseClientPrepareHeaders:
    """Test suite for MetabaseClient._prepare_headers."""

    def test_prepare_headers_with_session_token(self):
        """Test header preparation with session token."""
        client = MetabaseClient(base_url="https://example.com", session_token="test-token")

        headers = client._prepare_headers()

        assert headers["X-Metabase-Session"] == "test-token"

    def test_prepare_headers_with_personal_token(self):
        """Test header preparation with personal token."""
        client = MetabaseClient(base_url="https://example.com", personal_token="personal-token")

        headers = client._prepare_headers()

        assert headers["X-Metabase-API-Key"] == "personal-token"

    @patch("lib.client.requests.Session.post")
    def test_prepare_headers_without_token(self, mock_post):
        """Test header preparation without any token - should authenticate."""
        # Mock successful authentication
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"id": "test-session-token"}
        mock_post.return_value = mock_response

        client = MetabaseClient(
            base_url="https://example.com",
            username="user@example.com",
            password="password123",  # pragma: allowlist secret
        )

        headers = client._prepare_headers()

        # Should have session token after authentication
        assert headers["X-Metabase-Session"] == "test-session-token"
        # Should have called authentication endpoint
        mock_post.assert_called_once()


class TestMetabaseClientRequest:
    """Test suite for MetabaseClient._request method."""

    @patch("requests.Session.request")
    def test_request_success(self, mock_request):
        """Test successful API request."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": "test"}
        mock_response.raise_for_status = Mock()
        mock_request.return_value = mock_response

        client = MetabaseClient(base_url="https://example.com", session_token="test-token")

        response = client._request("get", "/test")

        assert response.status_code == 200
        assert response.json() == {"data": "test"}

    @patch("requests.Session.request")
    def test_request_with_params(self, mock_request):
        """Test API request with query parameters."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.raise_for_status = Mock()
        mock_request.return_value = mock_response

        client = MetabaseClient(base_url="https://example.com", session_token="test-token")

        client._request("get", "/test", params={"key": "value"})

        mock_request.assert_called_once()
        call_kwargs = mock_request.call_args[1]
        assert call_kwargs["params"] == {"key": "value"}

    @patch("requests.Session.request")
    def test_request_with_json_data(self, mock_request):
        """Test API request with JSON data."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.raise_for_status = Mock()
        mock_request.return_value = mock_response

        client = MetabaseClient(base_url="https://example.com", session_token="test-token")

        data = {"key": "value"}
        client._request("post", "/test", json=data)

        mock_request.assert_called_once()
        call_kwargs = mock_request.call_args[1]
        assert call_kwargs["json"] == data


class TestMetabaseClientShouldRetry:
    """Test suite for MetabaseClient._should_retry method."""

    def test_should_retry_on_connection_error(self):
        """Test that connection errors trigger retry."""
        client = MetabaseClient(base_url="https://example.com", session_token="test-token")
        error = requests.exceptions.ConnectionError()

        assert client._should_retry(error) is True

    def test_should_retry_on_timeout(self):
        """Test that timeout errors trigger retry."""
        client = MetabaseClient(base_url="https://example.com", session_token="test-token")
        error = requests.exceptions.Timeout()

        assert client._should_retry(error) is True

    def test_should_retry_on_rate_limit(self):
        """Test that 429 rate limit errors trigger retry."""
        client = MetabaseClient(base_url="https://example.com", session_token="test-token")
        error = MetabaseAPIError("Rate limited", status_code=429)

        assert client._should_retry(error) is True

    def test_should_retry_on_server_errors(self):
        """Test that 5xx server errors trigger retry."""
        client = MetabaseClient(base_url="https://example.com", session_token="test-token")

        for status_code in [500, 502, 503, 504]:
            error = MetabaseAPIError("Server error", status_code=status_code)
            assert client._should_retry(error) is True, f"Should retry on {status_code}"

    def test_should_not_retry_on_client_error(self):
        """Test that client errors (4xx except 429) don't trigger retry."""
        client = MetabaseClient(base_url="https://example.com", session_token="test-token")

        for status_code in [400, 401, 403, 404]:
            error = MetabaseAPIError("Client error", status_code=status_code)
            assert client._should_retry(error) is False, f"Should not retry on {status_code}"

    def test_should_not_retry_on_generic_exception(self):
        """Test that generic exceptions don't trigger retry."""
        client = MetabaseClient(base_url="https://example.com", session_token="test-token")
        error = ValueError("Some error")

        assert client._should_retry(error) is False


class TestMetabaseClientGetPaginated:
    """Test suite for MetabaseClient._get_paginated method."""

    @patch.object(MetabaseClient, "_request")
    def test_get_paginated_list_response(self, mock_request):
        """Test pagination with simple list response."""
        mock_response = Mock()
        mock_response.json.return_value = [{"id": 1}, {"id": 2}]
        mock_request.return_value = mock_response

        client = MetabaseClient(base_url="https://example.com", session_token="test-token")

        result = client._get_paginated("/test")

        assert result == [{"id": 1}, {"id": 2}]
        mock_request.assert_called_once()

    @patch.object(MetabaseClient, "_request")
    def test_get_paginated_dict_response_single_page(self, mock_request):
        """Test pagination with dict response containing all data."""
        mock_response = Mock()
        mock_response.json.return_value = {
            "data": [{"id": 1}, {"id": 2}],
            "total": 2,
            "limit": 10,
        }
        mock_request.return_value = mock_response

        client = MetabaseClient(base_url="https://example.com", session_token="test-token")

        result = client._get_paginated("/test")

        assert result == [{"id": 1}, {"id": 2}]

    @patch.object(MetabaseClient, "_request")
    def test_get_paginated_unexpected_format(self, mock_request):
        """Test pagination with unexpected response format raises error."""
        mock_response = Mock()
        mock_response.json.return_value = "unexpected string"
        mock_request.return_value = mock_response

        client = MetabaseClient(base_url="https://example.com", session_token="test-token")

        with pytest.raises(MetabaseAPIError, match="Unexpected pagination response format"):
            client._get_paginated("/test")

    @patch.object(MetabaseClient, "_request")
    def test_get_paginated_with_params(self, mock_request):
        """Test pagination passes through params."""
        mock_response = Mock()
        mock_response.json.return_value = [{"id": 1}]
        mock_request.return_value = mock_response

        client = MetabaseClient(base_url="https://example.com", session_token="test-token")

        result = client._get_paginated("/test", params={"filter": "active"})

        assert result == [{"id": 1}]
        mock_request.assert_called_once_with("get", "/test", params={"filter": "active"})

    @patch.object(MetabaseClient, "_request")
    def test_get_paginated_dict_no_total(self, mock_request):
        """Test pagination with dict response without total stops after first page."""
        mock_response = Mock()
        mock_response.json.return_value = {
            "data": [{"id": 1}, {"id": 2}],
        }
        mock_request.return_value = mock_response

        client = MetabaseClient(base_url="https://example.com", session_token="test-token")

        result = client._get_paginated("/test")

        assert result == [{"id": 1}, {"id": 2}]
        assert mock_request.call_count == 1


class TestMetabaseClientPublicMethods:
    """Test suite for MetabaseClient public API methods."""

    @patch.object(MetabaseClient, "_request")
    def test_get_collections_tree(self, mock_request):
        """Test get_collections_tree method."""
        mock_response = Mock()
        mock_response.json.return_value = [{"id": 1, "name": "Test"}]
        mock_request.return_value = mock_response

        client = MetabaseClient(base_url="https://example.com", session_token="test-token")

        result = client.get_collections_tree()

        assert result == [{"id": 1, "name": "Test"}]
        mock_request.assert_called_once_with("get", "/collection/tree", params={})

    @patch.object(MetabaseClient, "_request")
    def test_get_collection(self, mock_request):
        """Test get_collection method."""
        mock_response = Mock()
        mock_response.json.return_value = {"id": 1, "name": "Test Collection"}
        mock_request.return_value = mock_response

        client = MetabaseClient(base_url="https://example.com", session_token="test-token")

        result = client.get_collection(1)

        assert result == {"id": 1, "name": "Test Collection"}
        mock_request.assert_called_once_with("get", "/collection/1")

    @patch.object(MetabaseClient, "_request")
    def test_get_card(self, mock_request):
        """Test get_card method."""
        mock_response = Mock()
        mock_response.json.return_value = {"id": 100, "name": "Test Card"}
        mock_request.return_value = mock_response

        client = MetabaseClient(base_url="https://example.com", session_token="test-token")

        result = client.get_card(100)

        assert result == {"id": 100, "name": "Test Card"}
        mock_request.assert_called_once_with("get", "/card/100")

    @patch.object(MetabaseClient, "_request")
    def test_get_dashboard(self, mock_request):
        """Test get_dashboard method."""
        mock_response = Mock()
        mock_response.json.return_value = {"id": 200, "name": "Test Dashboard"}
        mock_request.return_value = mock_response

        client = MetabaseClient(base_url="https://example.com", session_token="test-token")

        result = client.get_dashboard(200)

        assert result == {"id": 200, "name": "Test Dashboard"}
        mock_request.assert_called_once_with("get", "/dashboard/200")

    @patch.object(MetabaseClient, "_request")
    def test_get_collection_items(self, mock_request):
        """Test get_collection_items method."""
        mock_response = Mock()
        mock_response.json.return_value = {"data": [{"id": 1, "model": "card"}]}
        mock_request.return_value = mock_response

        client = MetabaseClient(base_url="https://example.com", session_token="test-token")

        result = client.get_collection_items(1)

        assert result == {"data": [{"id": 1, "model": "card"}]}
        mock_request.assert_called_once_with("get", "/collection/1/items", params={})

    @patch.object(MetabaseClient, "_request")
    def test_get_collection_items_with_params(self, mock_request):
        """Test get_collection_items method with custom params."""
        mock_response = Mock()
        mock_response.json.return_value = {"data": []}
        mock_request.return_value = mock_response

        client = MetabaseClient(base_url="https://example.com", session_token="test-token")

        client.get_collection_items(1, params={"models": "card"})

        mock_request.assert_called_once_with(
            "get", "/collection/1/items", params={"models": "card"}
        )

    @patch.object(MetabaseClient, "_request")
    def test_get_databases_list_format(self, mock_request):
        """Test get_databases with list response format."""
        mock_response = Mock()
        mock_response.json.return_value = [{"id": 1, "name": "DB1"}]
        mock_request.return_value = mock_response

        client = MetabaseClient(base_url="https://example.com", session_token="test-token")

        result = client.get_databases()

        assert result == [{"id": 1, "name": "DB1"}]

    @patch.object(MetabaseClient, "_request")
    def test_get_databases_dict_format(self, mock_request):
        """Test get_databases with dict response format containing data key."""
        mock_response = Mock()
        mock_response.json.return_value = {"data": [{"id": 1, "name": "DB1"}]}
        mock_request.return_value = mock_response

        client = MetabaseClient(base_url="https://example.com", session_token="test-token")

        result = client.get_databases()

        assert result == [{"id": 1, "name": "DB1"}]

    @patch.object(MetabaseClient, "_request")
    def test_get_databases_unexpected_format(self, mock_request):
        """Test get_databases with unexpected response format returns empty list."""
        mock_response = Mock()
        mock_response.json.return_value = "unexpected"
        mock_request.return_value = mock_response

        client = MetabaseClient(base_url="https://example.com", session_token="test-token")

        result = client.get_databases()

        assert result == []

    @patch.object(MetabaseClient, "_request")
    def test_create_collection(self, mock_request):
        """Test create_collection method."""
        mock_response = Mock()
        mock_response.json.return_value = {"id": 10, "name": "New Collection"}
        mock_request.return_value = mock_response

        client = MetabaseClient(base_url="https://example.com", session_token="test-token")
        payload = {"name": "New Collection", "parent_id": None}

        result = client.create_collection(payload)

        assert result == {"id": 10, "name": "New Collection"}
        mock_request.assert_called_once_with("post", "/collection", json=payload)

    @patch.object(MetabaseClient, "_request")
    def test_update_collection(self, mock_request):
        """Test update_collection method."""
        mock_response = Mock()
        mock_response.json.return_value = {"id": 10, "name": "Updated Collection"}
        mock_request.return_value = mock_response

        client = MetabaseClient(base_url="https://example.com", session_token="test-token")
        payload = {"name": "Updated Collection"}

        result = client.update_collection(10, payload)

        assert result == {"id": 10, "name": "Updated Collection"}
        mock_request.assert_called_once_with("put", "/collection/10", json=payload)

    @patch.object(MetabaseClient, "_request")
    def test_create_card(self, mock_request):
        """Test create_card method."""
        mock_response = Mock()
        mock_response.json.return_value = {"id": 100, "name": "New Card"}
        mock_request.return_value = mock_response

        client = MetabaseClient(base_url="https://example.com", session_token="test-token")
        payload = {"name": "New Card", "dataset_query": {}}

        result = client.create_card(payload)

        assert result == {"id": 100, "name": "New Card"}
        mock_request.assert_called_once_with("post", "/card", json=payload)

    @patch.object(MetabaseClient, "_request")
    def test_update_card(self, mock_request):
        """Test update_card method."""
        mock_response = Mock()
        mock_response.json.return_value = {"id": 100, "name": "Updated Card"}
        mock_request.return_value = mock_response

        client = MetabaseClient(base_url="https://example.com", session_token="test-token")
        payload = {"name": "Updated Card"}

        result = client.update_card(100, payload)

        assert result == {"id": 100, "name": "Updated Card"}
        mock_request.assert_called_once_with("put", "/card/100", json=payload)

    @patch.object(MetabaseClient, "_request")
    def test_create_dashboard(self, mock_request):
        """Test create_dashboard method."""
        mock_response = Mock()
        mock_response.json.return_value = {"id": 200, "name": "New Dashboard"}
        mock_request.return_value = mock_response

        client = MetabaseClient(base_url="https://example.com", session_token="test-token")
        payload = {"name": "New Dashboard"}

        result = client.create_dashboard(payload)

        assert result == {"id": 200, "name": "New Dashboard"}
        mock_request.assert_called_once_with("post", "/dashboard", json=payload)

    @patch.object(MetabaseClient, "_request")
    def test_update_dashboard(self, mock_request):
        """Test update_dashboard method."""
        mock_response = Mock()
        mock_response.json.return_value = {"id": 200, "name": "Updated Dashboard"}
        mock_request.return_value = mock_response

        client = MetabaseClient(base_url="https://example.com", session_token="test-token")
        payload = {"name": "Updated Dashboard", "dashcards": []}

        result = client.update_dashboard(200, payload)

        assert result == {"id": 200, "name": "Updated Dashboard"}
        mock_request.assert_called_once_with("put", "/dashboard/200", json=payload)

    @patch.object(MetabaseClient, "_request")
    def test_get_permission_groups(self, mock_request):
        """Test get_permission_groups method."""
        mock_response = Mock()
        mock_response.json.return_value = [{"id": 1, "name": "All Users"}]
        mock_request.return_value = mock_response

        client = MetabaseClient(base_url="https://example.com", session_token="test-token")

        result = client.get_permission_groups()

        assert result == [{"id": 1, "name": "All Users"}]
        mock_request.assert_called_once_with("get", "/permissions/group")

    @patch.object(MetabaseClient, "_request")
    def test_get_permissions_graph(self, mock_request):
        """Test get_permissions_graph method."""
        mock_response = Mock()
        mock_response.json.return_value = {"groups": {}}
        mock_request.return_value = mock_response

        client = MetabaseClient(base_url="https://example.com", session_token="test-token")

        result = client.get_permissions_graph()

        assert result == {"groups": {}}
        mock_request.assert_called_once_with("get", "/permissions/graph")

    @patch.object(MetabaseClient, "_request")
    def test_update_permissions_graph(self, mock_request):
        """Test update_permissions_graph method."""
        mock_response = Mock()
        mock_response.json.return_value = {"groups": {}}
        mock_request.return_value = mock_response

        client = MetabaseClient(base_url="https://example.com", session_token="test-token")
        graph = {"groups": {"1": {}}}

        result = client.update_permissions_graph(graph)

        assert result == {"groups": {}}
        mock_request.assert_called_once_with("put", "/permissions/graph", json=graph)

    @patch.object(MetabaseClient, "_request")
    def test_get_collection_permissions_graph(self, mock_request):
        """Test get_collection_permissions_graph method."""
        mock_response = Mock()
        mock_response.json.return_value = {"groups": {}}
        mock_request.return_value = mock_response

        client = MetabaseClient(base_url="https://example.com", session_token="test-token")

        result = client.get_collection_permissions_graph()

        assert result == {"groups": {}}
        mock_request.assert_called_once_with("get", "/collection/graph")

    @patch.object(MetabaseClient, "_request")
    def test_update_collection_permissions_graph(self, mock_request):
        """Test update_collection_permissions_graph method."""
        mock_response = Mock()
        mock_response.json.return_value = {"groups": {}}
        mock_request.return_value = mock_response

        client = MetabaseClient(base_url="https://example.com", session_token="test-token")
        graph = {"groups": {"1": {}}}

        result = client.update_collection_permissions_graph(graph)

        assert result == {"groups": {}}
        mock_request.assert_called_once_with("put", "/collection/graph", json=graph)

    @patch.object(MetabaseClient, "_request")
    def test_get_database_metadata(self, mock_request):
        """Test get_database_metadata method."""
        mock_response = Mock()
        mock_response.json.return_value = {"id": 1, "tables": []}
        mock_request.return_value = mock_response

        client = MetabaseClient(base_url="https://example.com", session_token="test-token")

        result = client.get_database_metadata(1)

        assert result == {"id": 1, "tables": []}
        mock_request.assert_called_once_with("get", "/database/1/metadata")

    @patch.object(MetabaseClient, "_request")
    def test_get_table(self, mock_request):
        """Test get_table method."""
        mock_response = Mock()
        mock_response.json.return_value = {"id": 10, "name": "users"}
        mock_request.return_value = mock_response

        client = MetabaseClient(base_url="https://example.com", session_token="test-token")

        result = client.get_table(10)

        assert result == {"id": 10, "name": "users"}
        mock_request.assert_called_once_with("get", "/table/10")

    @patch.object(MetabaseClient, "_request")
    def test_get_field(self, mock_request):
        """Test get_field method."""
        mock_response = Mock()
        mock_response.json.return_value = {"id": 100, "name": "email"}
        mock_request.return_value = mock_response

        client = MetabaseClient(base_url="https://example.com", session_token="test-token")

        result = client.get_field(100)

        assert result == {"id": 100, "name": "email"}
        mock_request.assert_called_once_with("get", "/field/100")
