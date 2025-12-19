"""
Unit tests for lib/handlers/collection.py

Tests for the CollectionHandler class covering collection import, conflict handling,
hierarchy traversal, and error scenarios.
"""

from unittest.mock import Mock, patch

import pytest

from lib.config import ImportConfig
from lib.handlers.base import ImportContext
from lib.handlers.collection import CollectionHandler
from lib.models_core import Collection, ImportReport, Manifest
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
    mapper.collection_map = {}
    mapper.resolve_collection_id.return_value = 100
    return mapper


@pytest.fixture
def mock_query_remapper():
    """Create a mock QueryRemapper."""
    return Mock(spec=QueryRemapper)


@pytest.fixture
def mock_manifest():
    """Create a mock Manifest."""
    manifest = Mock(spec=Manifest)
    manifest.collections = [
        Collection(
            id=1,
            name="Test Collection",
            slug="test-collection",
            path="collections/Test-Collection",
            description="A test collection",
            parent_id=None,
        ),
    ]
    return manifest


@pytest.fixture
def mock_config():
    """Create a mock ImportConfig."""
    config = Mock(spec=ImportConfig)
    config.conflict_strategy = "skip"
    config.include_archived = False
    config.dry_run = False
    return config


@pytest.fixture
def mock_report():
    """Create a mock ImportReport."""
    report = Mock(spec=ImportReport)
    report.add = Mock()
    return report


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
    context.should_include_archived.return_value = False
    context.get_conflict_strategy.return_value = "skip"
    context.target_collections = []
    return context


class TestCollectionHandlerInit:
    """Tests for CollectionHandler initialization."""

    def test_init(self, import_context):
        """Test handler initialization."""
        handler = CollectionHandler(import_context)
        assert handler.context == import_context
        assert handler.client == import_context.client
        assert handler.id_mapper == import_context.id_mapper
        assert handler._flat_target_collections == []


class TestFlattenCollectionTree:
    """Tests for collection tree flattening."""

    def test_flatten_empty_tree(self, import_context):
        """Test flattening an empty tree."""
        handler = CollectionHandler(import_context)
        result = handler._flatten_collection_tree([])
        assert result == []

    def test_flatten_single_collection(self, import_context):
        """Test flattening a single collection."""
        handler = CollectionHandler(import_context)
        collections = [{"id": 1, "name": "Test Collection"}]

        result = handler._flatten_collection_tree(collections)

        assert len(result) == 1
        assert result[0]["id"] == 1
        assert result[0]["name"] == "Test Collection"
        assert result[0]["parent_id"] is None

    def test_flatten_nested_collections(self, import_context):
        """Test flattening nested collections."""
        handler = CollectionHandler(import_context)
        collections = [
            {
                "id": 1,
                "name": "Parent",
                "children": [
                    {"id": 2, "name": "Child"},
                ],
            }
        ]

        result = handler._flatten_collection_tree(collections)

        assert len(result) == 2
        parent = next(c for c in result if c["id"] == 1)
        child = next(c for c in result if c["id"] == 2)
        assert parent["parent_id"] is None
        assert child["parent_id"] == 1

    def test_flatten_deeply_nested_collections(self, import_context):
        """Test flattening deeply nested collections."""
        handler = CollectionHandler(import_context)
        collections = [
            {
                "id": 1,
                "name": "Level 1",
                "children": [
                    {
                        "id": 2,
                        "name": "Level 2",
                        "children": [
                            {"id": 3, "name": "Level 3"},
                        ],
                    }
                ],
            }
        ]

        result = handler._flatten_collection_tree(collections)

        assert len(result) == 3
        level3 = next(c for c in result if c["id"] == 3)
        assert level3["parent_id"] == 2

    def test_flatten_root_collection_skipped(self, import_context):
        """Test that root collection is skipped but its children are processed."""
        handler = CollectionHandler(import_context)
        collections = [
            {
                "id": "root",
                "name": "Root",
                "children": [
                    {"id": 1, "name": "Child of Root"},
                ],
            }
        ]

        result = handler._flatten_collection_tree(collections)

        assert len(result) == 1
        assert result[0]["id"] == 1
        assert result[0]["parent_id"] is None

    def test_flatten_multiple_root_children(self, import_context):
        """Test flattening multiple collections at root level."""
        handler = CollectionHandler(import_context)
        collections = [
            {"id": 1, "name": "Collection A"},
            {"id": 2, "name": "Collection B"},
            {"id": 3, "name": "Collection C"},
        ]

        result = handler._flatten_collection_tree(collections)

        assert len(result) == 3
        for c in result:
            assert c["parent_id"] is None


class TestFindExistingCollection:
    """Tests for finding existing collections."""

    def test_find_existing_collection_found(self, import_context):
        """Test finding an existing collection."""
        handler = CollectionHandler(import_context)
        handler._flat_target_collections = [
            {"id": 999, "name": "Test Collection", "parent_id": None},
        ]

        result = handler._find_existing_collection("Test Collection", None)

        assert result is not None
        assert result["id"] == 999

    def test_find_existing_collection_not_found(self, import_context):
        """Test when collection is not found."""
        handler = CollectionHandler(import_context)
        handler._flat_target_collections = [
            {"id": 999, "name": "Other Collection", "parent_id": None},
        ]

        result = handler._find_existing_collection("Test Collection", None)

        assert result is None

    def test_find_existing_collection_same_name_different_parent(self, import_context):
        """Test that parent_id is matched correctly."""
        handler = CollectionHandler(import_context)
        handler._flat_target_collections = [
            {"id": 999, "name": "Test Collection", "parent_id": None},
            {"id": 1000, "name": "Test Collection", "parent_id": 500},
        ]

        result = handler._find_existing_collection("Test Collection", 500)

        assert result is not None
        assert result["id"] == 1000


class TestHandleExistingCollection:
    """Tests for conflict handling when collection exists."""

    def test_skip_strategy(self, import_context, mock_id_mapper):
        """Test skip conflict strategy."""
        import_context.get_conflict_strategy.return_value = "skip"

        handler = CollectionHandler(import_context)
        collection = Collection(
            id=1,
            name="Test",
            slug="test",
            path="collections/Test",
            description="Test collection",
            parent_id=None,
        )
        existing = {"id": 999, "name": "Test"}

        handler._handle_existing_collection(collection, existing, None)

        mock_id_mapper.set_collection_mapping.assert_called_once_with(1, 999)

    def test_overwrite_strategy(self, import_context, mock_client, mock_id_mapper):
        """Test overwrite conflict strategy."""
        import_context.get_conflict_strategy.return_value = "overwrite"
        mock_client.update_collection.return_value = {"id": 999, "name": "Test"}

        handler = CollectionHandler(import_context)
        collection = Collection(
            id=1,
            name="Test",
            slug="test",
            path="collections/Test",
            description="Test collection",
            parent_id=None,
        )
        existing = {"id": 999, "name": "Test"}

        handler._handle_existing_collection(collection, existing, None)

        mock_client.update_collection.assert_called_once()
        mock_id_mapper.set_collection_mapping.assert_called_once_with(1, 999)

    def test_rename_strategy(self, import_context, mock_client, mock_id_mapper):
        """Test rename conflict strategy."""
        import_context.get_conflict_strategy.return_value = "rename"
        mock_client.get_collections_tree.return_value = []
        mock_client.create_collection.return_value = {"id": 1000, "name": "Test (1)"}

        handler = CollectionHandler(import_context)
        collection = Collection(
            id=1,
            name="Test",
            slug="test",
            path="collections/Test",
            description="Test collection",
            parent_id=None,
        )
        existing = {"id": 999, "name": "Test"}

        handler._handle_existing_collection(collection, existing, None)

        mock_client.create_collection.assert_called_once()


class TestCreateCollection:
    """Tests for collection creation."""

    def test_create_collection_success(self, import_context, mock_client, mock_id_mapper):
        """Test successful collection creation."""
        mock_client.create_collection.return_value = {"id": 1000, "name": "Test Collection"}

        handler = CollectionHandler(import_context)
        collection = Collection(
            id=1,
            name="Test Collection",
            slug="test-collection",
            path="collections/Test-Collection",
            description="A test collection",
            parent_id=None,
        )

        handler._create_collection(collection, "Test Collection", None)

        mock_client.create_collection.assert_called_once()
        mock_id_mapper.set_collection_mapping.assert_called_once_with(1, 1000)

    def test_create_collection_with_parent(self, import_context, mock_client, mock_id_mapper):
        """Test creating collection with parent."""
        mock_client.create_collection.return_value = {"id": 1000, "name": "Child"}

        handler = CollectionHandler(import_context)
        collection = Collection(
            id=2,
            name="Child",
            slug="child",
            path="collections/Parent/Child",
            description="Child collection",
            parent_id=1,
        )

        handler._create_collection(collection, "Child", 100)

        call_args = mock_client.create_collection.call_args[0][0]
        assert call_args["parent_id"] == 100


class TestGenerateUniqueCollectionName:
    """Tests for unique collection name generation."""

    def test_generate_unique_name(self, import_context, mock_client):
        """Test generating unique name when conflict exists."""
        # First call returns existing collection, second call returns empty
        mock_client.get_collections_tree.side_effect = [
            [{"name": "Test (1)", "parent_id": None}],
            [],
        ]

        handler = CollectionHandler(import_context)
        result = handler._generate_unique_collection_name("Test", None)

        assert result == "Test (2)"

    def test_generate_unique_name_first_try(self, import_context, mock_client):
        """Test when first unique name works."""
        mock_client.get_collections_tree.return_value = []

        handler = CollectionHandler(import_context)
        result = handler._generate_unique_collection_name("Test", None)

        assert result == "Test (1)"

    def test_generate_unique_name_with_parent(self, import_context, mock_client):
        """Test generating unique name with parent."""
        mock_client.get_collections_tree.return_value = [
            {"name": "Test (1)", "parent_id": 100},
        ]

        handler = CollectionHandler(import_context)
        result = handler._generate_unique_collection_name("Test", 100)

        assert result == "Test (2)"


class TestImportSingleCollection:
    """Tests for importing a single collection."""

    def test_import_collection_success(self, import_context, mock_client, mock_id_mapper):
        """Test successful collection import."""
        mock_id_mapper.resolve_collection_id.return_value = None
        mock_client.create_collection.return_value = {"id": 1000, "name": "Test"}

        handler = CollectionHandler(import_context)
        handler._flat_target_collections = []

        collection = Collection(
            id=1,
            name="Test",
            slug="test",
            path="collections/Test",
            description="Test collection",
            parent_id=None,
        )

        handler._import_single_collection(collection)

        mock_client.create_collection.assert_called_once()

    def test_import_collection_existing_skip(self, import_context, mock_client, mock_id_mapper):
        """Test import when collection exists and strategy is skip."""
        mock_id_mapper.resolve_collection_id.return_value = None

        handler = CollectionHandler(import_context)
        handler._flat_target_collections = [{"id": 999, "name": "Test", "parent_id": None}]

        collection = Collection(
            id=1,
            name="Test",
            slug="test",
            path="collections/Test",
            description="Test collection",
            parent_id=None,
        )

        handler._import_single_collection(collection)

        # Should not create
        mock_client.create_collection.assert_not_called()

    def test_import_collection_error(self, import_context, mock_client, mock_id_mapper):
        """Test import when error occurs."""
        mock_id_mapper.resolve_collection_id.return_value = None
        mock_client.create_collection.side_effect = Exception("API Error")

        handler = CollectionHandler(import_context)
        handler._flat_target_collections = []

        collection = Collection(
            id=1,
            name="Test",
            slug="test",
            path="collections/Test",
            description="Test collection",
            parent_id=None,
        )

        handler._import_single_collection(collection)

        # Should report failure
        import_context.report.add.assert_called()


class TestImportCollections:
    """Tests for importing multiple collections."""

    def test_import_collections_sorted_by_path(self, import_context, mock_client, mock_id_mapper):
        """Test that collections are imported in path order."""
        mock_id_mapper.resolve_collection_id.return_value = None
        mock_client.create_collection.return_value = {"id": 1000, "name": "Test"}

        handler = CollectionHandler(import_context)

        collections = [
            Collection(
                id=2,
                name="Child",
                slug="child",
                path="collections/Parent/Child",
                description="",
                parent_id=1,
            ),
            Collection(
                id=1,
                name="Parent",
                slug="parent",
                path="collections/Parent",
                description="",
                parent_id=None,
            ),
        ]

        import_order = []

        def track_import(coll):
            import_order.append(coll.path)

        with patch.object(handler, "_import_single_collection", side_effect=track_import):
            handler.import_collections(collections)

        # Should be sorted by path
        assert import_order == ["collections/Parent", "collections/Parent/Child"]


class TestFindCollectionByPath:
    """Tests for find_collection_by_path static method."""

    def test_find_collection_by_path_simple(self):
        """Test finding collection by simple path."""
        collections = [{"id": 1, "name": "Test Collection", "parent_id": None}]

        result = CollectionHandler.find_collection_by_path(
            collections, "collections/Test-Collection"
        )

        assert result is not None
        assert result["id"] == 1

    def test_find_collection_by_path_nested(self):
        """Test finding collection by nested path."""
        collections = [
            {
                "id": 1,
                "name": "Parent",
                "parent_id": None,
                "children": [
                    {"id": 2, "name": "Child", "parent_id": 1, "children": []},
                ],
            }
        ]

        result = CollectionHandler.find_collection_by_path(collections, "collections/Parent/Child")

        assert result is not None
        assert result["id"] == 2

    def test_find_collection_by_path_not_found(self):
        """Test when collection path is not found."""
        collections = [{"id": 1, "name": "Other Collection", "parent_id": None}]

        result = CollectionHandler.find_collection_by_path(
            collections, "collections/Test-Collection"
        )

        assert result is None

    def test_find_collection_by_path_partial_match(self):
        """Test when only part of path matches."""
        collections = [
            {
                "id": 1,
                "name": "Parent",
                "parent_id": None,
                "children": [],
            }
        ]

        result = CollectionHandler.find_collection_by_path(collections, "collections/Parent/Child")

        assert result is None

    def test_find_collection_by_path_sanitized_names(self):
        """Test finding collection with sanitized names."""
        collections = [{"id": 1, "name": "Test Collection", "parent_id": None}]

        # Path uses sanitized name (spaces become hyphens)
        result = CollectionHandler.find_collection_by_path(
            collections, "collections/Test-Collection"
        )

        assert result is not None
        assert result["id"] == 1

    def test_find_collection_by_path_empty_collections(self):
        """Test with empty collections list."""
        result = CollectionHandler.find_collection_by_path([], "collections/Test")

        assert result is None

    def test_find_collection_by_path_deep_nesting(self):
        """Test finding deeply nested collection."""
        collections = [
            {
                "id": 1,
                "name": "Level1",
                "parent_id": None,
                "children": [
                    {
                        "id": 2,
                        "name": "Level2",
                        "parent_id": 1,
                        "children": [
                            {
                                "id": 3,
                                "name": "Level3",
                                "parent_id": 2,
                                "children": [],
                            }
                        ],
                    }
                ],
            }
        ]

        result = CollectionHandler.find_collection_by_path(
            collections, "collections/Level1/Level2/Level3"
        )

        assert result is not None
        assert result["id"] == 3

    def test_find_collection_by_path_wrong_parent(self):
        """Test that parent must match."""
        collections = [
            {"id": 1, "name": "Parent1", "parent_id": None, "children": []},
            {
                "id": 2,
                "name": "Parent2",
                "parent_id": None,
                "children": [
                    {"id": 3, "name": "Child", "parent_id": 2, "children": []},
                ],
            },
        ]

        # Looking for Child under Parent1, but it's under Parent2
        result = CollectionHandler.find_collection_by_path(collections, "collections/Parent1/Child")

        assert result is None
