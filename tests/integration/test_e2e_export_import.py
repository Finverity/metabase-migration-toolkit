"""
End-to-end integration tests for export/import workflow.

These tests use Docker Compose to spin up source and target Metabase instances,
create test data, export from source, and import to target.

Run with: pytest tests/integration/test_e2e_export_import.py -v -s
"""

import json
import logging
import shutil
import subprocess
from pathlib import Path

import pytest

from export_metabase import MetabaseExporter
from import_metabase import MetabaseImporter
from lib.config import ExportConfig, ImportConfig
from tests.integration.test_helpers import MetabaseTestHelper

logger = logging.getLogger(__name__)

# Test configuration
SOURCE_URL = "http://localhost:3000"
TARGET_URL = "http://localhost:3001"
ADMIN_EMAIL = "admin@example.com"
ADMIN_PASSWORD = "Admin123!"

# Sample database configuration
SAMPLE_DB_HOST = "sample-data-postgres"
SAMPLE_DB_PORT = 5432
SAMPLE_DB_NAME = "sample_data"
SAMPLE_DB_USER = "sample_user"
SAMPLE_DB_PASSWORD = "sample_password"


@pytest.fixture(scope="module")
def docker_compose_file():
    """Return path to docker-compose file."""
    return Path(__file__).parent.parent.parent / "docker-compose.test.yml"


@pytest.fixture(scope="module")
def docker_services(docker_compose_file):
    """
    Start Docker Compose services and ensure they're ready.
    This fixture has module scope to avoid restarting services for each test.
    """
    logger.info("Starting Docker Compose services...")

    # Start services
    subprocess.run(
        ["docker-compose", "-f", str(docker_compose_file), "up", "-d"],
        check=True,
        capture_output=True,
    )

    # Wait for services to be ready
    source_helper = MetabaseTestHelper(SOURCE_URL, ADMIN_EMAIL, ADMIN_PASSWORD)
    target_helper = MetabaseTestHelper(TARGET_URL, ADMIN_EMAIL, ADMIN_PASSWORD)

    # Wait for both instances
    assert source_helper.wait_for_metabase(timeout=300), "Source Metabase did not start"
    assert target_helper.wait_for_metabase(timeout=300), "Target Metabase did not start"

    # Setup both instances
    assert source_helper.setup_metabase(), "Failed to setup source Metabase"
    assert target_helper.setup_metabase(), "Failed to setup target Metabase"

    # Login to both instances
    assert source_helper.login(), "Failed to login to source Metabase"
    assert target_helper.login(), "Failed to login to target Metabase"

    yield {"source": source_helper, "target": target_helper}

    # Cleanup: Stop services
    logger.info("Stopping Docker Compose services...")
    subprocess.run(
        ["docker-compose", "-f", str(docker_compose_file), "down", "-v"],
        check=True,
        capture_output=True,
    )


@pytest.fixture(scope="module")
def source_database_id(docker_services):
    """Add sample database to source Metabase and return its ID."""
    source = docker_services["source"]

    db_id = source.add_database(
        name="Sample Data",
        host=SAMPLE_DB_HOST,
        port=SAMPLE_DB_PORT,
        dbname=SAMPLE_DB_NAME,
        user=SAMPLE_DB_USER,
        password=SAMPLE_DB_PASSWORD,
    )

    assert db_id is not None, "Failed to add database to source"
    return db_id


@pytest.fixture(scope="module")
def target_database_id(docker_services):
    """Add sample database to target Metabase and return its ID."""
    target = docker_services["target"]

    db_id = target.add_database(
        name="Sample Data",
        host=SAMPLE_DB_HOST,
        port=SAMPLE_DB_PORT,
        dbname=SAMPLE_DB_NAME,
        user=SAMPLE_DB_USER,
        password=SAMPLE_DB_PASSWORD,
    )

    assert db_id is not None, "Failed to add database to target"
    return db_id


@pytest.fixture(scope="module")
def test_data_setup(docker_services, source_database_id):
    """
    Create test collections, cards, and dashboards in source Metabase.
    Returns a dict with IDs of created items.
    """
    source = docker_services["source"]

    # Create test collections
    root_collection_id = source.create_collection(
        name="Test Root Collection", description="Root collection for integration tests"
    )
    assert root_collection_id is not None

    child_collection_id = source.create_collection(
        name="Test Child Collection",
        description="Child collection for integration tests",
        parent_id=root_collection_id,
    )
    assert child_collection_id is not None

    # Create test cards
    card1_id = source.create_card(
        name="Test Card 1 - Users",
        database_id=source_database_id,
        collection_id=root_collection_id,
        query={
            "database": source_database_id,
            "type": "query",
            "query": {"source-table": 1},  # users table
        },
    )
    assert card1_id is not None

    card2_id = source.create_card(
        name="Test Card 2 - Products",
        database_id=source_database_id,
        collection_id=root_collection_id,
        query={
            "database": source_database_id,
            "type": "query",
            "query": {"source-table": 2},  # products table
        },
    )
    assert card2_id is not None

    card3_id = source.create_card(
        name="Test Card 3 - Orders",
        database_id=source_database_id,
        collection_id=child_collection_id,
        query={
            "database": source_database_id,
            "type": "query",
            "query": {"source-table": 3},  # orders table
        },
    )
    assert card3_id is not None

    # Create a card with dependency (based on another card)
    card4_id = source.create_card(
        name="Test Card 4 - Based on Card 1",
        database_id=source_database_id,
        collection_id=child_collection_id,
        query={
            "database": source_database_id,
            "type": "query",
            "query": {"source-table": f"card__{card1_id}"},
        },
    )
    assert card4_id is not None

    # Create test dashboard
    dashboard_id = source.create_dashboard(
        name="Test Dashboard", collection_id=root_collection_id, card_ids=[card1_id, card2_id]
    )
    assert dashboard_id is not None

    return {
        "root_collection_id": root_collection_id,
        "child_collection_id": child_collection_id,
        "card_ids": [card1_id, card2_id, card3_id, card4_id],
        "dashboard_id": dashboard_id,
    }


@pytest.fixture
def export_dir(tmp_path):
    """Create a temporary export directory."""
    export_path = tmp_path / "test_export"
    export_path.mkdir()
    yield export_path
    # Cleanup
    if export_path.exists():
        shutil.rmtree(export_path)


@pytest.fixture
def db_map_file(tmp_path, source_database_id, target_database_id):
    """Create a database mapping file."""
    db_map = {
        "by_id": {str(source_database_id): target_database_id},
        "by_name": {"Sample Data": target_database_id},
    }

    db_map_path = tmp_path / "db_map.json"
    with open(db_map_path, "w") as f:
        json.dump(db_map, f, indent=2)

    return db_map_path


@pytest.mark.integration
@pytest.mark.slow
class TestEndToEndExportImport:
    """End-to-end tests for the complete export/import workflow."""

    def test_docker_services_running(self, docker_services):
        """Test that Docker services are running and accessible."""
        source = docker_services["source"]
        target = docker_services["target"]

        assert source.session_token is not None
        assert target.session_token is not None

        # Verify we can get collections
        source_collections = source.get_collections()
        target_collections = target.get_collections()

        assert isinstance(source_collections, list)
        assert isinstance(target_collections, list)

    def test_sample_database_added(self, docker_services, source_database_id, target_database_id):
        """Test that sample databases were added successfully."""
        source = docker_services["source"]
        target = docker_services["target"]

        source_dbs = source.get_databases()
        target_dbs = target.get_databases()

        assert len(source_dbs) > 0
        assert len(target_dbs) > 0

        # Find our sample database
        source_db = next((db for db in source_dbs if db["id"] == source_database_id), None)
        target_db = next((db for db in target_dbs if db["id"] == target_database_id), None)

        assert source_db is not None
        assert target_db is not None
        assert source_db["name"] == "Sample Data"
        assert target_db["name"] == "Sample Data"

    def test_test_data_created(self, docker_services, test_data_setup):
        """Test that test data was created successfully."""
        source = docker_services["source"]

        # Verify collections exist
        collections = source.get_collections()
        collection_names = [c["name"] for c in collections]

        assert "Test Root Collection" in collection_names
        assert "Test Child Collection" in collection_names

        # Verify cards exist in root collection
        cards = source.get_cards_in_collection(test_data_setup["root_collection_id"])
        assert len(cards) >= 2  # At least card1 and card2

    def test_export_from_source(
        self, docker_services, test_data_setup, export_dir, source_database_id
    ):
        """Test exporting data from source Metabase."""
        source = docker_services["source"]

        # Create export config
        config = ExportConfig(
            source_url=SOURCE_URL,
            export_dir=str(export_dir),
            source_username=ADMIN_EMAIL,
            source_password=ADMIN_PASSWORD,
            source_session_token=source.session_token,
            include_dashboards=True,
            include_archived=False,
            root_collection_ids=[test_data_setup["root_collection_id"]],
            log_level="INFO",
        )

        # Run export
        exporter = MetabaseExporter(config)
        exporter.run_export()

        # Verify export artifacts
        manifest_path = export_dir / "manifest.json"
        assert manifest_path.exists(), "Manifest file not created"

        # Load and verify manifest
        with open(manifest_path) as f:
            manifest = json.load(f)

        assert "meta" in manifest
        assert "databases" in manifest
        assert "collections" in manifest
        assert "cards" in manifest
        assert "dashboards" in manifest

        # Verify database mapping
        assert str(source_database_id) in manifest["databases"]

        # Verify collections were exported
        assert len(manifest["collections"]) >= 2  # Root and child

        # Verify cards were exported (including dependencies)
        assert len(manifest["cards"]) >= 4  # All 4 cards

        # Verify dashboard was exported
        assert len(manifest["dashboards"]) >= 1

        # Verify card files exist
        for card in manifest["cards"]:
            card_file = export_dir / card["file_path"]
            assert card_file.exists(), f"Card file not found: {card['file_path']}"

    def test_import_to_target(
        self,
        docker_services,
        test_data_setup,
        export_dir,
        db_map_file,
        source_database_id,
        target_database_id,
    ):
        """Test importing data to target Metabase."""
        # First run export
        self.test_export_from_source(
            docker_services, test_data_setup, export_dir, source_database_id
        )

        target = docker_services["target"]

        # Create import config
        config = ImportConfig(
            target_url=TARGET_URL,
            export_dir=str(export_dir),
            db_map_path=str(db_map_file),
            target_username=ADMIN_EMAIL,
            target_password=ADMIN_PASSWORD,
            target_session_token=target.session_token,
            conflict_strategy="skip",
            dry_run=False,
            log_level="INFO",
        )

        # Run import
        importer = MetabaseImporter(config)
        importer.run_import()

        # Verify import results
        target_collections = target.get_collections()
        collection_names = [c["name"] for c in target_collections]

        assert "Test Root Collection" in collection_names, "Root collection not imported"
        assert "Test Child Collection" in collection_names, "Child collection not imported"

        # Find the imported root collection
        imported_root = next(c for c in target_collections if c["name"] == "Test Root Collection")

        # Verify cards were imported
        imported_cards = target.get_cards_in_collection(imported_root["id"])
        assert len(imported_cards) >= 2, "Cards not imported to root collection"

        # Verify card names
        card_names = [c["name"] for c in imported_cards]
        assert "Test Card 1 - Users" in card_names
        assert "Test Card 2 - Products" in card_names

    def test_dry_run_import(
        self, docker_services, test_data_setup, export_dir, db_map_file, source_database_id
    ):
        """Test dry-run import (no actual changes)."""
        # First run export
        self.test_export_from_source(
            docker_services, test_data_setup, export_dir, source_database_id
        )

        target = docker_services["target"]

        # Get initial state
        initial_collections = target.get_collections()
        initial_collection_count = len(initial_collections)

        # Create import config with dry_run=True
        config = ImportConfig(
            target_url=TARGET_URL,
            export_dir=str(export_dir),
            db_map_path=str(db_map_file),
            target_username=ADMIN_EMAIL,
            target_password=ADMIN_PASSWORD,
            target_session_token=target.session_token,
            conflict_strategy="skip",
            dry_run=True,
            log_level="INFO",
        )

        # Run dry-run import
        importer = MetabaseImporter(config)
        importer.run_import()

        # Verify no changes were made
        final_collections = target.get_collections()
        assert (
            len(final_collections) == initial_collection_count
        ), "Dry run should not create collections"

    def test_export_with_dependencies(
        self, docker_services, test_data_setup, export_dir, source_database_id
    ):
        """Test that card dependencies are properly exported."""
        # Run export
        self.test_export_from_source(
            docker_services, test_data_setup, export_dir, source_database_id
        )

        # Load manifest
        manifest_path = export_dir / "manifest.json"
        with open(manifest_path) as f:
            manifest = json.load(f)

        # Find the dependent card (Card 4)
        card4 = next((c for c in manifest["cards"] if "Card 4" in c["name"]), None)
        assert card4 is not None, "Dependent card not found in export"

        # Find the dependency (Card 1)
        card1 = next((c for c in manifest["cards"] if "Card 1" in c["name"]), None)
        assert card1 is not None, "Dependency card not found in export"

        # Verify both cards were exported
        card1_file = export_dir / card1["file_path"]
        card4_file = export_dir / card4["file_path"]

        assert card1_file.exists(), "Dependency card file not found"
        assert card4_file.exists(), "Dependent card file not found"

    def test_conflict_strategy_skip(
        self, docker_services, test_data_setup, export_dir, db_map_file, source_database_id
    ):
        """Test import with skip conflict strategy."""
        # First import
        self.test_import_to_target(
            docker_services, test_data_setup, export_dir, db_map_file, source_database_id, None
        )

        target = docker_services["target"]

        # Get collection count after first import
        collections_after_first = target.get_collections()
        first_import_count = len(collections_after_first)

        # Try to import again with skip strategy
        config = ImportConfig(
            target_url=TARGET_URL,
            export_dir=str(export_dir),
            db_map_path=str(db_map_file),
            target_username=ADMIN_EMAIL,
            target_password=ADMIN_PASSWORD,
            target_session_token=target.session_token,
            conflict_strategy="skip",
            dry_run=False,
            log_level="INFO",
        )

        importer = MetabaseImporter(config)
        importer.run_import()

        # Verify no duplicates were created
        collections_after_second = target.get_collections()
        assert (
            len(collections_after_second) == first_import_count
        ), "Skip strategy should not create duplicates"


@pytest.mark.integration
class TestMultipleInstances:
    """Test scenarios with multiple Metabase instances."""

    def test_different_database_ids(self, docker_services, source_database_id, target_database_id):
        """Test that source and target have different database IDs."""
        # This is expected - database IDs will differ between instances
        # The db_map.json file handles the mapping
        assert source_database_id != target_database_id
        # Either case is valid - just verify both exist
        assert source_database_id is not None
        assert target_database_id is not None

    def test_independent_instances(self, docker_services):
        """Test that source and target instances are independent."""
        source = docker_services["source"]
        target = docker_services["target"]

        # Create a collection in source
        source_collection_id = source.create_collection(
            name="Source Only Collection", description="This should only exist in source"
        )
        assert source_collection_id is not None

        # Verify it doesn't exist in target
        target_collections = target.get_collections()
        target_names = [c["name"] for c in target_collections]
        assert "Source Only Collection" not in target_names
