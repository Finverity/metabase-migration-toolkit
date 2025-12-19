"""
Unit tests for error handling across the application.

Tests error conditions, edge cases, and exception handling.
"""

import json
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
import requests
from tenacity import RetryError

from lib.client import MetabaseAPIError, MetabaseClient
from lib.config import ExportConfig, ImportConfig


class TestAPIErrorHandling:
    """Test suite for API error handling."""

    @patch("requests.Session.request")
    def test_handle_404_error(self, mock_request):
        """Test handling of 404 Not Found errors."""
        mock_response = Mock()
        mock_response.status_code = 404
        mock_response.text = "Not Found"
        # Make json() raise an exception since error responses are typically not JSON
        mock_response.json.side_effect = ValueError("Not JSON")
        mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError(
            response=mock_response
        )
        mock_request.return_value = mock_response

        client = MetabaseClient(base_url="https://example.com", session_token="test-token")

        # The retry decorator will retry MetabaseAPIError and eventually raise RetryError
        with pytest.raises(RetryError):
            client._request("get", "/nonexistent")

    @patch("requests.Session.request")
    def test_handle_401_unauthorized(self, mock_request):
        """Test handling of 401 Unauthorized errors."""
        mock_response = Mock()
        mock_response.status_code = 401
        mock_response.text = "Unauthorized"
        # Make json() raise an exception since error responses are typically not JSON
        mock_response.json.side_effect = ValueError("Not JSON")
        mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError(
            response=mock_response
        )
        mock_request.return_value = mock_response

        client = MetabaseClient(base_url="https://example.com", session_token="invalid-token")

        # The retry decorator will retry MetabaseAPIError and eventually raise RetryError
        with pytest.raises(RetryError):
            client._request("get", "/test")

    @patch("requests.Session.request")
    def test_handle_500_server_error(self, mock_request):
        """Test handling of 500 Internal Server Error."""
        mock_response = Mock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"
        # Make json() raise an exception since error responses are typically not JSON
        mock_response.json.side_effect = ValueError("Not JSON")
        mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError(
            response=mock_response
        )
        mock_request.return_value = mock_response

        client = MetabaseClient(base_url="https://example.com", session_token="test-token")

        # The retry decorator will retry MetabaseAPIError and eventually raise RetryError
        with pytest.raises(RetryError):
            client._request("get", "/test")

    @patch("requests.Session.request")
    def test_handle_network_timeout(self, mock_request):
        """Test handling of network timeout errors."""
        mock_request.side_effect = requests.exceptions.Timeout()

        client = MetabaseClient(base_url="https://example.com", session_token="test-token")

        # The retry decorator will retry Timeout and eventually raise RetryError
        with pytest.raises(RetryError):
            client._request("get", "/test")

    @patch("requests.Session.request")
    def test_handle_connection_error(self, mock_request):
        """Test handling of connection errors."""
        mock_request.side_effect = requests.exceptions.ConnectionError()

        client = MetabaseClient(base_url="https://example.com", session_token="test-token")

        # The retry decorator will retry ConnectionError and eventually raise RetryError
        with pytest.raises(RetryError):
            client._request("get", "/test")


class TestFileErrorHandling:
    """Test suite for file operation error handling."""

    def test_read_nonexistent_file(self):
        """Test reading a file that doesn't exist."""
        from lib.utils import read_json_file

        with pytest.raises(FileNotFoundError):
            read_json_file(Path("/nonexistent/file.json"))

    def test_write_to_readonly_directory(self, tmp_path):
        """Test writing to a read-only directory."""
        from lib.utils import write_json_file

        readonly_dir = tmp_path / "readonly"
        readonly_dir.mkdir()
        readonly_dir.chmod(0o444)  # Read-only

        test_file = readonly_dir / "test.json"

        try:
            with pytest.raises(PermissionError):
                write_json_file({"test": "data"}, test_file)
        finally:
            # Cleanup: restore write permissions
            readonly_dir.chmod(0o755)

    def test_read_invalid_json(self, tmp_path):
        """Test reading a file with invalid JSON."""
        from lib.utils import read_json_file

        invalid_json_file = tmp_path / "invalid.json"
        invalid_json_file.write_text("{ invalid json }")

        with pytest.raises(json.JSONDecodeError):
            read_json_file(invalid_json_file)

    def test_read_empty_json_file(self, tmp_path):
        """Test reading an empty JSON file."""
        from lib.utils import read_json_file

        empty_file = tmp_path / "empty.json"
        empty_file.write_text("")

        with pytest.raises(json.JSONDecodeError):
            read_json_file(empty_file)


class TestConfigurationErrors:
    """Test suite for configuration error handling with Pydantic validation."""

    def test_missing_required_config_fields(self):
        """Test that missing required fields raise errors."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            ExportConfig()

    def test_invalid_log_level(self):
        """Test handling of invalid log level - now validated by Pydantic."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError) as exc_info:
            ExportConfig(
                source_url="https://example.com",
                export_dir="./export",
                source_session_token="token",
                log_level="INVALID",
            )

        assert "log_level" in str(exc_info.value)

    def test_invalid_conflict_strategy(self):
        """Test that invalid conflict strategy is rejected by Pydantic."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError) as exc_info:
            ImportConfig(
                target_url="https://example.com",
                export_dir="./export",
                db_map_path="./db_map.json",
                target_session_token="token",
                conflict_strategy="invalid",
            )

        # Pydantic will reject the invalid literal value
        assert "conflict" in str(exc_info.value).lower() or "literal" in str(exc_info.value).lower()

    def test_missing_authentication(self):
        """Test that missing authentication is rejected."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError) as exc_info:
            ExportConfig(
                source_url="https://example.com",
                export_dir="./export",
            )

        assert "authentication" in str(exc_info.value).lower()

    def test_invalid_url_scheme(self):
        """Test that invalid URL scheme is rejected."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError) as exc_info:
            ExportConfig(
                source_url="ftp://example.com",
                export_dir="./export",
                source_session_token="token",
            )

        assert "http or https" in str(exc_info.value)

    def test_path_traversal_rejected(self):
        """Test that path traversal patterns are rejected."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError) as exc_info:
            ExportConfig(
                source_url="https://example.com",
                export_dir="../../../etc",
                source_session_token="token",
            )

        assert "traversal" in str(exc_info.value)


class TestDataValidationErrors:
    """Test suite for data validation errors."""

    def test_invalid_collection_id_type(self):
        """Test handling of invalid collection ID type."""
        from lib.models import Collection

        # Should accept any type that dataclass allows
        collection = Collection(id="invalid", name="Test", slug="test")  # Should be int

        assert collection.id == "invalid"

    def test_missing_required_card_fields(self):
        """Test creating card with missing required fields."""
        from lib.models import Card

        with pytest.raises(TypeError):
            Card(name="Test Card")  # Missing required fields


class TestDatabaseMappingErrors:
    """Test suite for database mapping errors."""

    def test_empty_database_map(self, tmp_path):
        """Test handling of empty database map."""
        db_map_data = {"by_id": {}, "by_name": {}}

        db_map_path = tmp_path / "db_map.json"
        with open(db_map_path, "w") as f:
            json.dump(db_map_data, f)

        from lib.models import DatabaseMap
        from lib.utils import read_json_file

        data = read_json_file(db_map_path)
        db_map = DatabaseMap(by_id=data.get("by_id", {}), by_name=data.get("by_name", {}))

        assert db_map.by_id == {}
        assert db_map.by_name == {}

    def test_malformed_database_map(self, tmp_path):
        """Test handling of malformed database map."""
        db_map_data = {"invalid_key": "invalid_value"}

        db_map_path = tmp_path / "db_map.json"
        with open(db_map_path, "w") as f:
            json.dump(db_map_data, f)

        from lib.models import DatabaseMap
        from lib.utils import read_json_file

        data = read_json_file(db_map_path)
        db_map = DatabaseMap(by_id=data.get("by_id", {}), by_name=data.get("by_name", {}))

        # Should use defaults for missing keys
        assert db_map.by_id == {}
        assert db_map.by_name == {}


class TestCircularDependencyDetection:
    """Test suite for circular dependency detection."""

    def test_detect_simple_circular_dependency(self):
        """Test detection of simple circular dependency (A -> B -> A)."""
        # This would be tested in the export module
        # Card A depends on Card B, Card B depends on Card A
        pytest.skip("Circular dependency detection not yet implemented")

    def test_detect_complex_circular_dependency(self):
        """Test detection of complex circular dependency (A -> B -> C -> A)."""
        pytest.skip("Circular dependency detection not yet implemented")


class TestEdgeCases:
    """Test suite for edge cases."""

    def test_empty_collection_name(self):
        """Test handling of empty collection name."""
        from lib.utils import sanitize_filename

        result = sanitize_filename("")
        assert result == ""

    def test_very_long_collection_name(self):
        """Test handling of very long collection name."""
        from lib.utils import sanitize_filename

        long_name = "a" * 200
        result = sanitize_filename(long_name)

        # Should be truncated to 100 characters
        assert len(result) == 100

    def test_collection_name_with_unicode(self):
        """Test handling of collection name with unicode characters."""
        from lib.utils import sanitize_filename

        unicode_name = "Test 世界 🌍"
        result = sanitize_filename(unicode_name)

        # Should handle unicode gracefully
        assert isinstance(result, str)

    def test_zero_database_id(self):
        """Test handling of database ID 0."""
        from lib.models import Card

        card = Card(id=100, name="Test Card", collection_id=1, database_id=0)  # Edge case: DB ID 0

        assert card.database_id == 0

    def test_negative_collection_id(self):
        """Test handling of negative collection ID."""
        from lib.models import Collection

        collection = Collection(id=-1, name="Test", slug="test")  # Edge case: negative ID

        assert collection.id == -1


class TestRetryLogic:
    """Test suite for retry logic."""

    @patch("requests.Session.request")
    def test_retry_on_rate_limit(self, mock_request):
        """Test that requests are retried on rate limit (429)."""
        # First call returns 429, second call succeeds
        mock_response_429 = Mock()
        mock_response_429.status_code = 429
        mock_response_429.raise_for_status.side_effect = requests.exceptions.HTTPError(
            response=mock_response_429
        )

        mock_response_200 = Mock()
        mock_response_200.status_code = 200
        mock_response_200.json.return_value = {"data": "success"}
        mock_response_200.raise_for_status = Mock()

        mock_request.side_effect = [mock_response_429, mock_response_200]

        MetabaseClient(base_url="https://example.com", session_token="test-token")

        # Should retry and eventually succeed
        # Note: This depends on retry decorator implementation
        pytest.skip("Retry logic testing requires tenacity mock")


class TestAuthenticationErrors:
    """Test suite for authentication error handling."""

    def test_no_credentials_provided(self):
        """Test error when no credentials are provided."""
        client = MetabaseClient(base_url="https://example.com")

        with pytest.raises(MetabaseAPIError, match="Authentication required"):
            client._authenticate()

    def test_invalid_credentials(self):
        """Test error with invalid credentials."""
        with patch("requests.Session.post") as mock_post:
            mock_response = Mock()
            mock_response.status_code = 401
            mock_response.text = "Invalid credentials"
            mock_post.side_effect = requests.exceptions.RequestException(response=mock_response)

            client = MetabaseClient(
                base_url="https://example.com",
                username="invalid@example.com",
                password="wrong",  # pragma: allowlist secret
            )

            with pytest.raises(MetabaseAPIError, match="Authentication failed"):
                client._authenticate()
