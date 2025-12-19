"""
Unit tests for the PermissionsHandler class.

Tests cover permission group mapping, data permissions, and collection permissions.
"""

from unittest.mock import Mock

import pytest

from lib.client import MetabaseAPIError
from lib.config import ImportConfig
from lib.handlers.base import ImportContext
from lib.handlers.permissions import PermissionsHandler
from lib.models_core import ImportReport, Manifest, PermissionGroup
from lib.remapping.id_mapper import IDMapper
from lib.remapping.query_remapper import QueryRemapper


@pytest.fixture
def mock_client():
    """Create a mock MetabaseClient."""
    client = Mock()
    client.base_url = "https://target.example.com"
    return client


@pytest.fixture
def mock_id_mapper():
    """Create a mock IDMapper."""
    mapper = Mock(spec=IDMapper)
    mapper.group_map = {}
    mapper.db_map = {}
    mapper.collection_map = {}
    return mapper


@pytest.fixture
def mock_query_remapper():
    """Create a mock QueryRemapper."""
    return Mock(spec=QueryRemapper)


@pytest.fixture
def mock_manifest():
    """Create a mock Manifest with permission data."""
    manifest = Mock(spec=Manifest)
    manifest.permission_groups = [
        PermissionGroup(id=3, name="Analysts", member_count=5),
        PermissionGroup(id=4, name="Viewers", member_count=10),
        PermissionGroup(id=1, name="All Users", member_count=100),  # Built-in
    ]
    manifest.permissions_graph = {
        "revision": 1,
        "groups": {
            "3": {"1": {"view-data": "all", "create-queries": "query-builder-and-native"}},
            "4": {"1": {"view-data": "unrestricted", "create-queries": "no"}},
        },
    }
    manifest.collection_permissions_graph = {
        "revision": 1,
        "groups": {
            "3": {"10": "write", "20": "read"},
            "4": {"10": "read", "root": "none"},
        },
    }
    manifest.databases = {1: "Sample Database"}
    return manifest


@pytest.fixture
def mock_config(tmp_path):
    """Create a mock ImportConfig."""
    config = Mock(spec=ImportConfig)
    config.conflict_strategy = "skip"
    config.include_archived = False
    config.dry_run = False
    return config


@pytest.fixture
def mock_report():
    """Create a mock ImportReport."""
    return Mock(spec=ImportReport)


@pytest.fixture
def import_context(
    mock_config,
    mock_client,
    mock_manifest,
    mock_id_mapper,
    mock_query_remapper,
    mock_report,
    tmp_path,
):
    """Create a mock ImportContext."""
    context = Mock(spec=ImportContext)
    context.config = mock_config
    context.client = mock_client
    context.manifest = mock_manifest
    context.export_dir = tmp_path
    context.id_mapper = mock_id_mapper
    context.query_remapper = mock_query_remapper
    context.report = mock_report
    return context


class TestPermissionsHandlerInit:
    """Tests for PermissionsHandler initialization."""

    def test_init(self, import_context):
        """Test handler initialization."""
        handler = PermissionsHandler(import_context)
        assert handler.context == import_context
        assert handler.client == import_context.client
        assert handler.id_mapper == import_context.id_mapper


class TestPermissionGroupMapping:
    """Tests for permission group mapping."""

    def test_map_permission_groups_success(self, import_context, mock_client, mock_id_mapper):
        """Test successful mapping of permission groups."""
        # Setup target groups
        mock_client.get_permission_groups.return_value = [
            {"id": 100, "name": "Analysts"},
            {"id": 101, "name": "Viewers"},
            {"id": 1, "name": "All Users"},
        ]

        handler = PermissionsHandler(import_context)
        handler._map_permission_groups()

        # Verify mappings were created
        assert mock_id_mapper.set_group_mapping.call_count == 3
        mock_id_mapper.set_group_mapping.assert_any_call(3, 100)  # Analysts
        mock_id_mapper.set_group_mapping.assert_any_call(4, 101)  # Viewers
        mock_id_mapper.set_group_mapping.assert_any_call(1, 1)  # All Users

    def test_map_permission_groups_missing_group(self, import_context, mock_client, mock_id_mapper):
        """Test handling of missing permission groups on target."""
        # Only Analysts exists on target
        mock_client.get_permission_groups.return_value = [
            {"id": 100, "name": "Analysts"},
            {"id": 1, "name": "All Users"},
        ]

        handler = PermissionsHandler(import_context)
        handler._map_permission_groups()

        # Only Analysts and All Users should be mapped
        assert mock_id_mapper.set_group_mapping.call_count == 2
        mock_id_mapper.set_group_mapping.assert_any_call(3, 100)
        mock_id_mapper.set_group_mapping.assert_any_call(1, 1)

    def test_map_permission_groups_empty_target(self, import_context, mock_client, mock_id_mapper):
        """Test handling when no groups exist on target."""
        mock_client.get_permission_groups.return_value = []

        handler = PermissionsHandler(import_context)
        handler._map_permission_groups()

        # No mappings should be created
        mock_id_mapper.set_group_mapping.assert_not_called()


class TestDataPermissionsImport:
    """Tests for data permissions import."""

    def test_apply_data_permissions_success(self, import_context, mock_client, mock_id_mapper):
        """Test successful application of data permissions."""
        mock_id_mapper.group_map = {3: 100, 4: 101}
        mock_id_mapper.resolve_db_id.return_value = 50  # Target DB ID
        mock_client.get_permissions_graph.return_value = {"revision": 5}
        mock_client.update_permissions_graph.return_value = None

        handler = PermissionsHandler(import_context)
        result = handler._apply_data_permissions()

        assert result is True
        mock_client.update_permissions_graph.assert_called_once()

    def test_apply_data_permissions_no_graph(self, import_context, mock_manifest):
        """Test when no permissions graph exists."""
        mock_manifest.permissions_graph = None

        handler = PermissionsHandler(import_context)
        result = handler._apply_data_permissions()

        assert result is False

    def test_apply_data_permissions_empty_graph(self, import_context, mock_manifest):
        """Test when permissions graph is empty."""
        mock_manifest.permissions_graph = {}

        handler = PermissionsHandler(import_context)
        result = handler._apply_data_permissions()

        assert result is False

    def test_apply_data_permissions_api_error(self, import_context, mock_client, mock_id_mapper):
        """Test handling of API error during permissions update."""
        mock_id_mapper.group_map = {3: 100}
        mock_id_mapper.resolve_db_id.return_value = 50
        mock_client.get_permissions_graph.return_value = {"revision": 5}
        mock_client.update_permissions_graph.side_effect = MetabaseAPIError("API Error")

        handler = PermissionsHandler(import_context)
        result = handler._apply_data_permissions()

        assert result is False


class TestCollectionPermissionsImport:
    """Tests for collection permissions import."""

    def test_apply_collection_permissions_success(
        self, import_context, mock_client, mock_id_mapper
    ):
        """Test successful application of collection permissions."""
        mock_id_mapper.group_map = {3: 100, 4: 101}
        mock_id_mapper.resolve_collection_id.side_effect = lambda x: x + 1000  # Simple mapping
        mock_client.get_collection_permissions_graph.return_value = {"revision": 3}
        mock_client.update_collection_permissions_graph.return_value = None

        handler = PermissionsHandler(import_context)
        result = handler._apply_collection_permissions()

        assert result is True
        mock_client.update_collection_permissions_graph.assert_called_once()

    def test_apply_collection_permissions_no_graph(self, import_context, mock_manifest):
        """Test when no collection permissions graph exists."""
        mock_manifest.collection_permissions_graph = None

        handler = PermissionsHandler(import_context)
        result = handler._apply_collection_permissions()

        assert result is False

    def test_apply_collection_permissions_api_error(
        self, import_context, mock_client, mock_id_mapper
    ):
        """Test handling of API error during collection permissions update."""
        mock_id_mapper.group_map = {3: 100}
        mock_id_mapper.resolve_collection_id.return_value = 1010
        mock_client.get_collection_permissions_graph.return_value = {"revision": 3}
        mock_client.update_collection_permissions_graph.side_effect = MetabaseAPIError("API Error")

        handler = PermissionsHandler(import_context)
        result = handler._apply_collection_permissions()

        assert result is False


class TestPermissionsGraphRemapping:
    """Tests for permissions graph remapping logic."""

    def test_remap_permissions_graph(self, import_context, mock_client, mock_id_mapper):
        """Test remapping of data permissions graph."""
        mock_id_mapper.group_map = {3: 100, 4: 101}
        mock_id_mapper.resolve_db_id.return_value = 50
        mock_client.get_permissions_graph.return_value = {"revision": 5}

        handler = PermissionsHandler(import_context)
        result = handler._remap_permissions_graph(import_context.manifest.permissions_graph)

        assert "groups" in result
        assert "revision" in result
        assert result["revision"] == 5
        # Check that group IDs were remapped
        assert "100" in result["groups"] or "101" in result["groups"]

    def test_remap_permissions_graph_empty(self, import_context):
        """Test remapping with empty graph."""
        handler = PermissionsHandler(import_context)
        result = handler._remap_permissions_graph({})

        assert result == {}

    def test_remap_permissions_graph_no_groups(self, import_context):
        """Test remapping with graph missing groups key."""
        handler = PermissionsHandler(import_context)
        result = handler._remap_permissions_graph({"revision": 1})

        assert result == {}

    def test_remap_permissions_graph_unmapped_database(
        self, import_context, mock_client, mock_id_mapper
    ):
        """Test handling of unmapped database IDs."""
        mock_id_mapper.group_map = {3: 100}
        mock_id_mapper.resolve_db_id.return_value = None  # Database not mapped
        mock_client.get_permissions_graph.return_value = {"revision": 5}

        handler = PermissionsHandler(import_context)
        result = handler._remap_permissions_graph(import_context.manifest.permissions_graph)

        # Should return empty because no databases were mapped
        assert result == {} or result.get("groups", {}) == {}

    def test_remap_permissions_graph_unmapped_group(
        self, import_context, mock_client, mock_id_mapper
    ):
        """Test handling of unmapped group IDs."""
        mock_id_mapper.group_map = {}  # No groups mapped
        mock_id_mapper.resolve_db_id.return_value = 50
        mock_client.get_permissions_graph.return_value = {"revision": 5}

        handler = PermissionsHandler(import_context)
        result = handler._remap_permissions_graph(import_context.manifest.permissions_graph)

        # Should return empty because no groups were mapped
        assert result == {} or result.get("groups", {}) == {}


class TestCollectionPermissionsGraphRemapping:
    """Tests for collection permissions graph remapping."""

    def test_remap_collection_permissions_graph(self, import_context, mock_client, mock_id_mapper):
        """Test remapping of collection permissions graph."""
        mock_id_mapper.group_map = {3: 100, 4: 101}
        mock_id_mapper.resolve_collection_id.side_effect = lambda x: x + 1000
        mock_client.get_collection_permissions_graph.return_value = {"revision": 3}

        handler = PermissionsHandler(import_context)
        result = handler._remap_collection_permissions_graph(
            import_context.manifest.collection_permissions_graph
        )

        assert "groups" in result
        assert "revision" in result
        assert result["revision"] == 3

    def test_remap_collection_permissions_graph_preserves_root(
        self, import_context, mock_client, mock_id_mapper
    ):
        """Test that 'root' collection key is preserved."""
        mock_id_mapper.group_map = {4: 101}
        mock_id_mapper.resolve_collection_id.return_value = None  # Other collections not mapped
        mock_client.get_collection_permissions_graph.return_value = {"revision": 3}

        handler = PermissionsHandler(import_context)
        result = handler._remap_collection_permissions_graph(
            import_context.manifest.collection_permissions_graph
        )

        # Root should be preserved if present in source
        if result and result.get("groups"):
            for group_perms in result["groups"].values():
                if "root" in import_context.manifest.collection_permissions_graph.get(
                    "groups", {}
                ).get("4", {}):
                    assert "root" in group_perms

    def test_remap_collection_permissions_graph_empty(self, import_context):
        """Test remapping with empty graph."""
        handler = PermissionsHandler(import_context)
        result = handler._remap_collection_permissions_graph({})

        assert result == {}

    def test_remap_collection_permissions_graph_unmapped_collection(
        self, import_context, mock_client, mock_id_mapper
    ):
        """Test handling of unmapped collection IDs."""
        mock_id_mapper.group_map = {3: 100}
        mock_id_mapper.resolve_collection_id.return_value = None  # Collection not mapped
        mock_client.get_collection_permissions_graph.return_value = {"revision": 3}

        handler = PermissionsHandler(import_context)
        result = handler._remap_collection_permissions_graph(
            import_context.manifest.collection_permissions_graph
        )

        # Should handle unmapped collections gracefully
        assert isinstance(result, dict)


class TestRevisionFetching:
    """Tests for fetching current revisions from target."""

    def test_get_current_permissions_revision(self, import_context, mock_client):
        """Test fetching current permissions revision."""
        mock_client.get_permissions_graph.return_value = {"revision": 42, "groups": {}}

        handler = PermissionsHandler(import_context)
        result = handler._get_current_permissions_revision()

        assert result == 42

    def test_get_current_permissions_revision_error(self, import_context, mock_client):
        """Test handling error when fetching permissions revision."""
        mock_client.get_permissions_graph.side_effect = Exception("Network error")

        handler = PermissionsHandler(import_context)
        result = handler._get_current_permissions_revision()

        assert result == 0  # Default on error

    def test_get_current_permissions_revision_missing_key(self, import_context, mock_client):
        """Test handling missing revision key."""
        mock_client.get_permissions_graph.return_value = {"groups": {}}

        handler = PermissionsHandler(import_context)
        result = handler._get_current_permissions_revision()

        assert result == 0  # Default when key missing

    def test_get_current_collection_permissions_revision(self, import_context, mock_client):
        """Test fetching current collection permissions revision."""
        mock_client.get_collection_permissions_graph.return_value = {"revision": 15, "groups": {}}

        handler = PermissionsHandler(import_context)
        result = handler._get_current_collection_permissions_revision()

        assert result == 15

    def test_get_current_collection_permissions_revision_error(self, import_context, mock_client):
        """Test handling error when fetching collection permissions revision."""
        mock_client.get_collection_permissions_graph.side_effect = Exception("Network error")

        handler = PermissionsHandler(import_context)
        result = handler._get_current_collection_permissions_revision()

        assert result == 0


class TestImportPermissions:
    """Tests for the main import_permissions method."""

    def test_import_permissions_full_flow(self, import_context, mock_client, mock_id_mapper):
        """Test full permissions import flow."""
        # Setup
        mock_client.get_permission_groups.return_value = [
            {"id": 100, "name": "Analysts"},
            {"id": 101, "name": "Viewers"},
        ]
        mock_id_mapper.group_map = {3: 100, 4: 101}
        mock_id_mapper.resolve_db_id.return_value = 50
        mock_id_mapper.resolve_collection_id.side_effect = lambda x: x + 1000
        mock_client.get_permissions_graph.return_value = {"revision": 5}
        mock_client.get_collection_permissions_graph.return_value = {"revision": 3}

        handler = PermissionsHandler(import_context)
        handler.import_permissions()

        # Verify both permission types were attempted
        mock_client.get_permission_groups.assert_called_once()

    def test_import_permissions_no_groups_mapped(self, import_context, mock_client, mock_id_mapper):
        """Test import when no groups can be mapped."""
        mock_client.get_permission_groups.return_value = []  # No matching groups
        mock_id_mapper.group_map = {}

        handler = PermissionsHandler(import_context)
        handler.import_permissions()

        # Should not attempt to update permissions
        mock_client.update_permissions_graph.assert_not_called()
        mock_client.update_collection_permissions_graph.assert_not_called()

    def test_import_permissions_handles_exception(self, import_context, mock_client):
        """Test that exceptions are handled gracefully."""
        mock_client.get_permission_groups.side_effect = Exception("Unexpected error")

        handler = PermissionsHandler(import_context)
        # Should not raise
        handler.import_permissions()


class TestLogSummary:
    """Tests for the log summary method."""

    def test_log_summary(self, import_context, mock_id_mapper):
        """Test log summary generation."""
        mock_id_mapper.group_map = {3: 100, 4: 101}

        handler = PermissionsHandler(import_context)

        # Should not raise
        handler._log_summary(data_perms_applied=True, collection_perms_applied=False)

    def test_log_summary_no_groups(self, import_context, mock_id_mapper):
        """Test log summary with no groups mapped."""
        mock_id_mapper.group_map = {}

        handler = PermissionsHandler(import_context)

        # Should not raise
        handler._log_summary(data_perms_applied=False, collection_perms_applied=False)
