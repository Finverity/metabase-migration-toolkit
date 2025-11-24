"""
Unit tests for lib/models.py

Tests data models and dataclasses used throughout the application.
"""

import dataclasses

from lib.models import (
    Card,
    Collection,
    Dashboard,
    DatabaseMap,
    ImportAction,
    ImportPlan,
    ImportReport,
    ImportReportItem,
    Manifest,
    ManifestMeta,
    UnmappedDatabase,
)


class TestCollection:
    """Test suite for Collection dataclass."""

    def test_collection_creation(self):
        """Test creating a Collection instance."""
        collection = Collection(id=1, name="Test Collection", slug="test-collection")

        assert collection.id == 1
        assert collection.name == "Test Collection"
        assert collection.slug == "test-collection"

    def test_collection_is_dataclass(self):
        """Test that Collection is a dataclass."""
        assert dataclasses.is_dataclass(Collection)

    def test_collection_with_parent(self):
        """Test creating a Collection with parent_id."""
        collection = Collection(id=2, name="Child Collection", slug="child-collection", parent_id=1)

        assert collection.parent_id == 1

    def test_collection_fields(self):
        """Test that Collection has expected fields."""
        fields = {f.name for f in dataclasses.fields(Collection)}

        assert "id" in fields
        assert "name" in fields
        assert "slug" in fields


class TestCard:
    """Test suite for Card dataclass."""

    def test_card_creation(self):
        """Test creating a Card instance."""
        card = Card(id=100, name="Test Card", collection_id=1, database_id=1)

        assert card.id == 100
        assert card.name == "Test Card"
        assert card.collection_id == 1
        assert card.database_id == 1

    def test_card_is_dataclass(self):
        """Test that Card is a dataclass."""
        assert dataclasses.is_dataclass(Card)

    def test_card_with_dataset_query(self):
        """Test creating a Card with dataset_query."""
        dataset_query = {"type": "query", "database": 1, "query": {"source-table": 1}}

        card = Card(
            id=100, name="Test Card", collection_id=1, database_id=1, dataset_query=dataset_query
        )

        assert card.dataset_query == dataset_query

    def test_card_fields(self):
        """Test that Card has expected fields."""
        fields = {f.name for f in dataclasses.fields(Card)}

        assert "id" in fields
        assert "name" in fields
        assert "collection_id" in fields
        assert "database_id" in fields
        assert "dataset" in fields

    def test_card_as_model(self):
        """Test creating a Card as a model (dataset=True)."""
        model = Card(id=100, name="Test Model", collection_id=1, database_id=1, dataset=True)

        assert model.id == 100
        assert model.name == "Test Model"
        assert model.dataset is True

    def test_card_as_question(self):
        """Test creating a Card as a question (dataset=False, default)."""
        question = Card(id=101, name="Test Question", collection_id=1, database_id=1)

        assert question.id == 101
        assert question.name == "Test Question"
        assert question.dataset is False  # Default value

    def test_card_dataset_field_explicit_false(self):
        """Test creating a Card with dataset explicitly set to False."""
        card = Card(id=102, name="Test Card", collection_id=1, database_id=1, dataset=False)

        assert card.dataset is False


class TestDashboard:
    """Test suite for Dashboard dataclass."""

    def test_dashboard_creation(self):
        """Test creating a Dashboard instance."""
        dashboard = Dashboard(id=200, name="Test Dashboard", collection_id=1)

        assert dashboard.id == 200
        assert dashboard.name == "Test Dashboard"
        assert dashboard.collection_id == 1

    def test_dashboard_is_dataclass(self):
        """Test that Dashboard is a dataclass."""
        assert dataclasses.is_dataclass(Dashboard)

    def test_dashboard_fields(self):
        """Test that Dashboard has expected fields."""
        fields = {f.name for f in dataclasses.fields(Dashboard)}

        assert "id" in fields
        assert "name" in fields
        assert "collection_id" in fields


class TestManifestMeta:
    """Test suite for ManifestMeta dataclass."""

    def test_manifest_meta_creation(self):
        """Test creating a ManifestMeta instance."""
        meta = ManifestMeta(
            source_url="https://example.com",
            export_timestamp="2025-10-07T12:00:00",
            tool_version="1.0.0",
            cli_args={"arg1": "value1"},
        )

        assert meta.source_url == "https://example.com"
        assert meta.export_timestamp == "2025-10-07T12:00:00"
        assert meta.tool_version == "1.0.0"
        assert meta.cli_args == {"arg1": "value1"}

    def test_manifest_meta_is_dataclass(self):
        """Test that ManifestMeta is a dataclass."""
        assert dataclasses.is_dataclass(ManifestMeta)


class TestManifest:
    """Test suite for Manifest dataclass."""

    def test_manifest_creation(self):
        """Test creating a Manifest instance."""
        meta = ManifestMeta(
            source_url="https://example.com",
            export_timestamp="2025-10-07T12:00:00",
            tool_version="1.0.0",
            cli_args={},
        )

        manifest = Manifest(meta=meta)

        assert manifest.meta == meta
        assert manifest.databases == {}
        assert manifest.collections == []
        assert manifest.cards == []
        assert manifest.dashboards == []

    def test_manifest_with_data(self):
        """Test creating a Manifest with data."""
        meta = ManifestMeta(
            source_url="https://example.com",
            export_timestamp="2025-10-07T12:00:00",
            tool_version="1.0.0",
            cli_args={},
        )

        collection = Collection(id=1, name="Test", slug="test")
        card = Card(id=100, name="Card", collection_id=1, database_id=1)

        manifest = Manifest(
            meta=meta,
            databases={1: "Test DB"},
            collections=[collection],
            cards=[card],
            dashboards=[],
        )

        assert manifest.databases == {1: "Test DB"}
        assert len(manifest.collections) == 1
        assert len(manifest.cards) == 1
        assert manifest.dashboards == []

    def test_manifest_is_dataclass(self):
        """Test that Manifest is a dataclass."""
        assert dataclasses.is_dataclass(Manifest)


class TestDatabaseMap:
    """Test suite for DatabaseMap dataclass."""

    def test_database_map_creation(self):
        """Test creating a DatabaseMap instance."""
        db_map = DatabaseMap(by_id={"1": 10, "2": 20}, by_name={"DB1": 10, "DB2": 20})

        assert db_map.by_id == {"1": 10, "2": 20}
        assert db_map.by_name == {"DB1": 10, "DB2": 20}

    def test_database_map_empty(self):
        """Test creating an empty DatabaseMap."""
        db_map = DatabaseMap()

        assert db_map.by_id == {}
        assert db_map.by_name == {}

    def test_database_map_is_dataclass(self):
        """Test that DatabaseMap is a dataclass."""
        assert dataclasses.is_dataclass(DatabaseMap)


class TestUnmappedDatabase:
    """Test suite for UnmappedDatabase dataclass."""

    def test_unmapped_database_creation(self):
        """Test creating an UnmappedDatabase instance."""
        unmapped = UnmappedDatabase(source_db_id=1, source_db_name="Test DB")

        assert unmapped.source_db_id == 1
        assert unmapped.source_db_name == "Test DB"
        assert unmapped.card_ids == set()

    def test_unmapped_database_with_cards(self):
        """Test creating an UnmappedDatabase with card IDs."""
        unmapped = UnmappedDatabase(
            source_db_id=1, source_db_name="Test DB", card_ids={100, 101, 102}
        )

        assert unmapped.card_ids == {100, 101, 102}

    def test_unmapped_database_is_dataclass(self):
        """Test that UnmappedDatabase is a dataclass."""
        assert dataclasses.is_dataclass(UnmappedDatabase)


class TestImportAction:
    """Test suite for ImportAction dataclass."""

    def test_import_action_creation(self):
        """Test creating an ImportAction instance."""
        action = ImportAction(
            entity_type="card",
            action="create",
            source_id=100,
            name="Test Card",
            target_path="/Test Collection",
        )

        assert action.entity_type == "card"
        assert action.action == "create"
        assert action.source_id == 100
        assert action.name == "Test Card"
        assert action.target_path == "/Test Collection"

    def test_import_action_is_dataclass(self):
        """Test that ImportAction is a dataclass."""
        assert dataclasses.is_dataclass(ImportAction)


class TestImportPlan:
    """Test suite for ImportPlan dataclass."""

    def test_import_plan_creation(self):
        """Test creating an ImportPlan instance."""
        plan = ImportPlan()

        assert plan.actions == []
        assert plan.unmapped_databases == []

    def test_import_plan_with_data(self):
        """Test creating an ImportPlan with data."""
        action = ImportAction(
            entity_type="card", action="create", source_id=100, name="Test", target_path="/"
        )

        unmapped = UnmappedDatabase(source_db_id=1, source_db_name="Test DB")

        plan = ImportPlan(actions=[action], unmapped_databases=[unmapped])

        assert len(plan.actions) == 1
        assert len(plan.unmapped_databases) == 1

    def test_import_plan_is_dataclass(self):
        """Test that ImportPlan is a dataclass."""
        assert dataclasses.is_dataclass(ImportPlan)


class TestImportReportItem:
    """Test suite for ImportReportItem dataclass."""

    def test_import_report_item_creation(self):
        """Test creating an ImportReportItem instance."""
        item = ImportReportItem(
            entity_type="card", source_id=100, target_id=200, name="Test Card", status="success"
        )

        assert item.entity_type == "card"
        assert item.source_id == 100
        assert item.target_id == 200
        assert item.name == "Test Card"
        assert item.status == "success"

    def test_import_report_item_with_error(self):
        """Test creating an ImportReportItem with error."""
        item = ImportReportItem(
            entity_type="card",
            source_id=100,
            target_id=None,
            name="Test Card",
            status="error",
            error_message="Failed to create",
        )

        assert item.status == "error"
        assert item.error_message == "Failed to create"
        assert item.target_id is None

    def test_import_report_item_is_dataclass(self):
        """Test that ImportReportItem is a dataclass."""
        assert dataclasses.is_dataclass(ImportReportItem)


class TestImportReport:
    """Test suite for ImportReport dataclass."""

    def test_import_report_creation(self):
        """Test creating an ImportReport instance."""
        report = ImportReport()

        assert report.items == []

    def test_import_report_with_items(self):
        """Test creating an ImportReport with items."""
        item1 = ImportReportItem(
            entity_type="card", source_id=100, target_id=200, name="Card 1", status="success"
        )

        item2 = ImportReportItem(
            entity_type="dashboard",
            source_id=300,
            target_id=400,
            name="Dashboard 1",
            status="success",
        )

        report = ImportReport(items=[item1, item2])

        assert len(report.items) == 2

    def test_import_report_is_dataclass(self):
        """Test that ImportReport is a dataclass."""
        assert dataclasses.is_dataclass(ImportReport)
