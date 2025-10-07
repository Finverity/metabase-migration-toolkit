"""
Integration tests for the complete export/import workflow.

These tests require actual Metabase instances and are skipped by default.
Set METABASE_TEST_URL environment variable to enable these tests.
"""

import os

import pytest

from lib.client import MetabaseClient


@pytest.mark.integration
@pytest.mark.skipif(not os.getenv("METABASE_TEST_URL"), reason="METABASE_TEST_URL not set")
class TestExportImportFlow:
    """Integration tests for export/import workflow."""

    @pytest.fixture
    def test_client(self):
        """Create a test Metabase client."""
        url = os.getenv("METABASE_TEST_URL")
        username = os.getenv("METABASE_TEST_USERNAME")
        password = os.getenv("METABASE_TEST_PASSWORD")

        client = MetabaseClient(base_url=url, username=username, password=password)
        client._authenticate()
        return client

    def test_client_connection(self, test_client):
        """Test that we can connect to the test Metabase instance."""
        # Try to fetch collections tree
        collections = test_client.get_collections_tree()
        assert isinstance(collections, list)

    def test_fetch_databases(self, test_client):
        """Test fetching databases from Metabase."""
        databases = test_client.get_databases()
        assert isinstance(databases, list)
        assert len(databases) > 0

    def test_fetch_collections(self, test_client):
        """Test fetching collections from Metabase."""
        collections = test_client.get_collections_tree()
        assert isinstance(collections, list)

    @pytest.mark.slow
    def test_full_export_import_cycle(self, test_client, tmp_path):
        """
        Test a complete export and import cycle.

        This test:
        1. Exports a small collection
        2. Imports it to the same instance (with rename)
        3. Verifies the import was successful

        Note: This is a slow test and modifies the test instance.
        """
        pytest.skip("Requires careful setup to avoid data corruption")

        # TODO: Implement full cycle test
        # 1. Create a test collection
        # 2. Export it
        # 3. Import to a different collection
        # 4. Verify all items were created
        # 5. Clean up test data


@pytest.mark.integration
class TestClientRetries:
    """Integration tests for client retry logic."""

    def test_retry_on_rate_limit(self):
        """Test that client retries on rate limit errors."""
        pytest.skip("Requires rate limit simulation")

    def test_retry_on_network_error(self):
        """Test that client retries on network errors."""
        pytest.skip("Requires network error simulation")


@pytest.mark.integration
class TestDatabaseMapping:
    """Integration tests for database mapping."""

    def test_database_id_mapping(self):
        """Test mapping database IDs between instances."""
        pytest.skip("Requires two Metabase instances")

    def test_database_name_mapping(self):
        """Test mapping database names between instances."""
        pytest.skip("Requires two Metabase instances")


# Note: These are placeholder tests. Real integration tests would require:
# 1. A test Metabase instance (or Docker container)
# 2. Test data setup and teardown
# 3. Careful handling to avoid data corruption
# 4. Longer timeouts for API calls
# 5. Network error simulation for retry testing
