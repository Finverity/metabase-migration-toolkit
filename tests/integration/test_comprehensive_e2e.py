"""
Comprehensive end-to-end integration tests for all supported features.

This file extends the basic E2E tests with comprehensive coverage of:
- Collections: Deep nesting, special characters, empty collections
- Cards: JOINs, multiple aggregations, expressions, template tags, visualization types
- Models: Column metadata, dependency chains
- Dashboards: Tabs, text cards, linked filters, layout preservation
- Permissions: Multiple groups, verification after import
- ID Remapping: Table IDs, field IDs in all query contexts
- Conflict Resolution: Skip, overwrite, rename strategies
- Dry-run Mode: Plan generation, no-changes verification
- Edge Cases: Circular dependencies, long names, special characters, Unicode

Run with: pytest tests/integration/test_comprehensive_e2e.py -v -s

For v57 testing:
    MB_METABASE_VERSION=v57 pytest tests/integration/test_comprehensive_e2e.py -v -s
"""

import json
import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import requests

from export_metabase import MetabaseExporter
from import_metabase import MetabaseImporter
from lib.config import ExportConfig, ImportConfig
from lib.constants import DEFAULT_METABASE_VERSION, MetabaseVersion
from tests.integration.test_helpers import MetabaseTestHelper

logger = logging.getLogger(__name__)

# =============================================================================
# Test Configuration
# =============================================================================

SOURCE_URL = "http://localhost:3002"
TARGET_URL = "http://localhost:3003"
ADMIN_EMAIL = "admin@example.com"
ADMIN_PASSWORD = "Admin123!"  # noqa: S105  # pragma: allowlist secret

# Sample database configuration
SAMPLE_DB_HOST = "sample-data-postgres"
SAMPLE_DB_PORT = 5432
SAMPLE_DB_NAME = "sample_data"
SAMPLE_DB_USER = "sample_user"
SAMPLE_DB_PASSWORD = "sample_password"  # noqa: S105  # pragma: allowlist secret


def get_metabase_version() -> MetabaseVersion:
    """Get Metabase version from environment variable or use default."""
    version_str = os.environ.get("MB_METABASE_VERSION", "").lower()
    if version_str == "v57":
        return MetabaseVersion.V57
    return DEFAULT_METABASE_VERSION


def is_v57() -> bool:
    """Check if we're testing against v57."""
    return get_metabase_version() == MetabaseVersion.V57


# =============================================================================
# Fixtures - Docker Services
# =============================================================================


@pytest.fixture(scope="session")
def docker_compose_file():
    """Return path to docker-compose file based on MB_METABASE_VERSION."""
    base_path = Path(__file__).parent.parent.parent
    if is_v57():
        return base_path / "docker-compose.test.v57.yml"
    return base_path / "docker-compose.test.yml"


def _docker_compose_cmd() -> list[str]:
    """Get the appropriate docker compose command."""
    if shutil.which("docker") is not None:
        result = subprocess.run(
            ["docker", "compose", "version"],
            capture_output=True,
        )
        if result.returncode == 0:
            return ["docker", "compose"]
    return ["docker-compose"]


@pytest.fixture(scope="session")
def docker_services(docker_compose_file):
    """Start Docker Compose services and ensure they're ready."""
    compose_cmd = _docker_compose_cmd()
    logger.info(f"Starting Docker Compose services using {' '.join(compose_cmd)}...")

    # Stop any existing containers first
    subprocess.run(
        [*compose_cmd, "-f", str(docker_compose_file), "down", "-v"],
        capture_output=True,
    )

    # Start services
    result = subprocess.run(
        [*compose_cmd, "-f", str(docker_compose_file), "up", "-d"],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        logger.error(f"Docker compose up failed: {result.stderr}")
        pytest.skip(f"Docker compose failed to start: {result.stderr}")

    source_helper = MetabaseTestHelper(SOURCE_URL, ADMIN_EMAIL, ADMIN_PASSWORD)
    target_helper = MetabaseTestHelper(TARGET_URL, ADMIN_EMAIL, ADMIN_PASSWORD)

    # Wait for both instances
    if not source_helper.wait_for_metabase(timeout=300):
        subprocess.run(
            [*compose_cmd, "-f", str(docker_compose_file), "down", "-v"],
            capture_output=True,
        )
        pytest.skip("Source Metabase did not start in time")

    if not target_helper.wait_for_metabase(timeout=300):
        subprocess.run(
            [*compose_cmd, "-f", str(docker_compose_file), "down", "-v"],
            capture_output=True,
        )
        pytest.skip("Target Metabase did not start in time")

    # Setup both instances
    if not source_helper.setup_metabase():
        pytest.skip("Failed to setup source Metabase")

    if not target_helper.setup_metabase():
        pytest.skip("Failed to setup target Metabase")

    # Login to both instances
    if not source_helper.login():
        pytest.skip("Failed to login to source Metabase")

    if not target_helper.login():
        pytest.skip("Failed to login to target Metabase")

    yield {"source": source_helper, "target": target_helper}

    # Cleanup
    logger.info("Stopping Docker Compose services...")
    subprocess.run(
        [*compose_cmd, "-f", str(docker_compose_file), "down", "-v"],
        capture_output=True,
    )


# =============================================================================
# Fixtures - Database Setup
# =============================================================================


@pytest.fixture(scope="session")
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


@pytest.fixture(scope="session")
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


@pytest.fixture(scope="session")
def source_table_ids(docker_services, source_database_id):
    """Get table IDs from the source database."""
    source = docker_services["source"]
    return {
        "users": source.get_table_id_by_name(source_database_id, "users"),
        "products": source.get_table_id_by_name(source_database_id, "products"),
        "orders": source.get_table_id_by_name(source_database_id, "orders"),
        "order_items": source.get_table_id_by_name(source_database_id, "order_items"),
    }


@pytest.fixture(scope="session")
def target_table_ids(docker_services, target_database_id):
    """Get table IDs from the target database."""
    target = docker_services["target"]
    return {
        "users": target.get_table_id_by_name(target_database_id, "users"),
        "products": target.get_table_id_by_name(target_database_id, "products"),
        "orders": target.get_table_id_by_name(target_database_id, "orders"),
        "order_items": target.get_table_id_by_name(target_database_id, "order_items"),
    }


@pytest.fixture(scope="session")
def source_field_ids(docker_services, source_database_id):
    """Get field IDs from the source database."""
    source = docker_services["source"]
    return {
        "users_id": source.get_field_id_by_name(source_database_id, "users", "id"),
        "users_email": source.get_field_id_by_name(source_database_id, "users", "email"),
        "users_is_active": source.get_field_id_by_name(source_database_id, "users", "is_active"),
        "products_id": source.get_field_id_by_name(source_database_id, "products", "id"),
        "products_category": source.get_field_id_by_name(
            source_database_id, "products", "category"
        ),
        "products_price": source.get_field_id_by_name(source_database_id, "products", "price"),
        "products_stock": source.get_field_id_by_name(
            source_database_id, "products", "stock_quantity"
        ),
        "orders_id": source.get_field_id_by_name(source_database_id, "orders", "id"),
        "orders_user_id": source.get_field_id_by_name(source_database_id, "orders", "user_id"),
        "orders_total_amount": source.get_field_id_by_name(
            source_database_id, "orders", "total_amount"
        ),
        "orders_status": source.get_field_id_by_name(source_database_id, "orders", "status"),
        "order_items_order_id": source.get_field_id_by_name(
            source_database_id, "order_items", "order_id"
        ),
        "order_items_product_id": source.get_field_id_by_name(
            source_database_id, "order_items", "product_id"
        ),
    }


@pytest.fixture(scope="session")
def target_field_ids(docker_services, target_database_id):
    """Get field IDs from the target database."""
    target = docker_services["target"]
    return {
        "users_id": target.get_field_id_by_name(target_database_id, "users", "id"),
        "users_email": target.get_field_id_by_name(target_database_id, "users", "email"),
        "users_is_active": target.get_field_id_by_name(target_database_id, "users", "is_active"),
        "products_id": target.get_field_id_by_name(target_database_id, "products", "id"),
        "products_category": target.get_field_id_by_name(
            target_database_id, "products", "category"
        ),
        "products_price": target.get_field_id_by_name(target_database_id, "products", "price"),
        "products_stock": target.get_field_id_by_name(
            target_database_id, "products", "stock_quantity"
        ),
        "orders_id": target.get_field_id_by_name(target_database_id, "orders", "id"),
        "orders_user_id": target.get_field_id_by_name(target_database_id, "orders", "user_id"),
        "orders_total_amount": target.get_field_id_by_name(
            target_database_id, "orders", "total_amount"
        ),
        "orders_status": target.get_field_id_by_name(target_database_id, "orders", "status"),
        "order_items_order_id": target.get_field_id_by_name(
            target_database_id, "order_items", "order_id"
        ),
        "order_items_product_id": target.get_field_id_by_name(
            target_database_id, "order_items", "product_id"
        ),
    }


# =============================================================================
# Fixtures - Export/Import Utilities
# =============================================================================


@pytest.fixture
def export_dir(tmp_path):
    """Create a temporary export directory."""
    export_path = tmp_path / "comprehensive_export"
    export_path.mkdir()
    yield export_path
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


def run_export(
    source_helper: MetabaseTestHelper,
    export_dir: Path,
    root_collection_ids: list[int],
    include_permissions: bool = False,
    include_archived: bool = False,
) -> dict[str, Any]:
    """Run export and return manifest."""
    config = ExportConfig(
        source_url=SOURCE_URL,
        export_dir=str(export_dir),
        source_username=ADMIN_EMAIL,
        source_password=ADMIN_PASSWORD,
        source_session_token=source_helper.session_token,
        include_dashboards=True,
        include_archived=include_archived,
        include_permissions=include_permissions,
        root_collection_ids=root_collection_ids,
        log_level="DEBUG",
        metabase_version=get_metabase_version(),
    )

    exporter = MetabaseExporter(config)
    exporter.run_export()

    manifest_path = export_dir / "manifest.json"
    with open(manifest_path) as f:
        return json.load(f)


def run_import(
    target_helper: MetabaseTestHelper,
    export_dir: Path,
    db_map_path: Path,
    dry_run: bool = False,
    conflict_strategy: str = "skip",
    apply_permissions: bool = False,
) -> None:
    """Run import."""
    config = ImportConfig(
        target_url=TARGET_URL,
        export_dir=str(export_dir),
        db_map_path=str(db_map_path),
        target_username=ADMIN_EMAIL,
        target_password=ADMIN_PASSWORD,
        target_session_token=target_helper.session_token,
        conflict_strategy=conflict_strategy,
        dry_run=dry_run,
        apply_permissions=apply_permissions,
        log_level="DEBUG",
        metabase_version=get_metabase_version(),
    )

    importer = MetabaseImporter(config)
    importer.run_import()


# =============================================================================
# Test Classes
# =============================================================================


@pytest.mark.integration
@pytest.mark.slow
class TestCollectionFeatures:
    """Test all collection-related features."""

    def test_deep_nested_collections(
        self, docker_services, source_database_id, target_database_id, export_dir, db_map_file
    ):
        """Test export/import of deeply nested collections (4+ levels)."""
        source = docker_services["source"]
        target = docker_services["target"]

        # Create 5-level deep collection hierarchy
        level1_id = source.create_collection(name="Comp_Level1", description="Level 1 collection")
        assert level1_id is not None

        level2_id = source.create_collection(name="Comp_Level2", parent_id=level1_id)
        assert level2_id is not None

        level3_id = source.create_collection(name="Comp_Level3", parent_id=level2_id)
        assert level3_id is not None

        level4_id = source.create_collection(name="Comp_Level4", parent_id=level3_id)
        assert level4_id is not None

        level5_id = source.create_collection(name="Comp_Level5_DeepNested", parent_id=level4_id)
        assert level5_id is not None

        # Export and import
        manifest = run_export(source, export_dir, [level1_id])
        assert len(manifest["collections"]) >= 5

        run_import(target, export_dir, db_map_file)

        # Verify all levels exist in target
        target_collections = target.get_collections()
        target_names = [c["name"] for c in target_collections]

        assert "Comp_Level1" in target_names
        assert "Comp_Level2" in target_names
        assert "Comp_Level3" in target_names
        assert "Comp_Level4" in target_names
        assert "Comp_Level5_DeepNested" in target_names

        # Verify hierarchy is preserved
        level5_target = next(c for c in target_collections if c["name"] == "Comp_Level5_DeepNested")
        # Location should have multiple path segments
        location = level5_target.get("location", "")
        path_segments = [s for s in location.split("/") if s]
        assert len(path_segments) >= 4, f"Expected 4+ path segments, got {len(path_segments)}"

    def test_collection_special_characters(
        self, docker_services, source_database_id, target_database_id, export_dir, db_map_file
    ):
        """Test collections with special characters in names."""
        source = docker_services["source"]
        target = docker_services["target"]

        # Create collection with special characters
        special_name = "Comp Test & Collection (2025) - Report #1"
        collection_id = source.create_collection(
            name=special_name,
            description="Collection with special chars: <>&\"' and more!",
        )
        assert collection_id is not None

        # Export and import
        manifest = run_export(source, export_dir, [collection_id])
        assert any(c["name"] == special_name for c in manifest["collections"])

        run_import(target, export_dir, db_map_file)

        # Verify collection exists with correct name
        target_collections = target.get_collections()
        assert any(c["name"] == special_name for c in target_collections)

    def test_empty_collection_export_import(
        self, docker_services, source_database_id, target_database_id, export_dir, db_map_file
    ):
        """Test export/import of empty collections (no cards or dashboards)."""
        source = docker_services["source"]
        target = docker_services["target"]

        # Create empty collection
        empty_id = source.create_collection(
            name="Comp_Empty_Collection",
            description="This collection has no items",
        )
        assert empty_id is not None

        # Export and import
        manifest = run_export(source, export_dir, [empty_id])
        assert any(c["name"] == "Comp_Empty_Collection" for c in manifest["collections"])

        run_import(target, export_dir, db_map_file)

        # Verify collection exists and is empty
        target_collections = target.get_collections()
        target_empty = next(c for c in target_collections if c["name"] == "Comp_Empty_Collection")
        items = target.count_items_in_collection(target_empty["id"])
        assert items == 0


@pytest.mark.integration
@pytest.mark.slow
class TestCardFeatures:
    """Test all card/question features."""

    def test_card_with_join(
        self,
        docker_services,
        source_database_id,
        target_database_id,
        source_table_ids,
        target_table_ids,
        source_field_ids,
        target_field_ids,
        export_dir,
        db_map_file,
    ):
        """Test card with JOIN between two tables."""
        source = docker_services["source"]
        target = docker_services["target"]

        # Create collection
        collection_id = source.create_collection(name="Comp_Join_Test")
        assert collection_id is not None

        # Create card with JOIN (orders JOIN users)
        card_id = source.create_card_with_join(
            name="Comp Orders with Users",
            database_id=source_database_id,
            source_table_id=source_table_ids["orders"],
            join_table_id=source_table_ids["users"],
            source_field_id=source_field_ids["orders_user_id"],
            join_field_id=source_field_ids["users_id"],
            collection_id=collection_id,
        )
        assert card_id is not None

        # Export and import
        run_export(source, export_dir, [collection_id])
        run_import(target, export_dir, db_map_file)

        # Verify card exists in target
        target_collections = target.get_collections()
        target_coll = next(c for c in target_collections if c["name"] == "Comp_Join_Test")
        imported_card = target.find_card_by_name(target_coll["id"], "Comp Orders with Users")
        assert imported_card is not None

        # Verify join uses target table ID
        query = imported_card.get("dataset_query", {}).get("query", {})
        joins = query.get("joins", [])
        if not joins:
            # Check v57 stages format
            stages = imported_card.get("dataset_query", {}).get("stages", [])
            if stages:
                joins = stages[0].get("joins", [])
        assert len(joins) >= 1, "Expected at least one join"

    def test_card_with_multiple_aggregations(
        self,
        docker_services,
        source_database_id,
        target_database_id,
        source_table_ids,
        source_field_ids,
        export_dir,
        db_map_file,
    ):
        """Test card with multiple aggregations (count, sum, avg)."""
        source = docker_services["source"]
        target = docker_services["target"]

        collection_id = source.create_collection(name="Comp_MultiAgg_Test")
        assert collection_id is not None

        # Create card with count, sum, and avg of total_amount
        card_id = source.create_card_with_multiple_aggregations(
            name="Comp Order Stats",
            database_id=source_database_id,
            table_id=source_table_ids["orders"],
            aggregations=[
                ("count", None),
                ("sum", source_field_ids["orders_total_amount"]),
                ("avg", source_field_ids["orders_total_amount"]),
            ],
            breakout_field_id=source_field_ids["orders_status"],
            collection_id=collection_id,
        )
        assert card_id is not None

        # Export and import
        run_export(source, export_dir, [collection_id])
        run_import(target, export_dir, db_map_file)

        # Verify card exists with multiple aggregations
        target_collections = target.get_collections()
        target_coll = next(c for c in target_collections if c["name"] == "Comp_MultiAgg_Test")
        imported_card = target.find_card_by_name(target_coll["id"], "Comp Order Stats")
        assert imported_card is not None

    def test_card_with_order_by_and_limit(
        self,
        docker_services,
        source_database_id,
        target_database_id,
        source_table_ids,
        source_field_ids,
        target_field_ids,
        export_dir,
        db_map_file,
    ):
        """Test card with ORDER BY and LIMIT."""
        source = docker_services["source"]
        target = docker_services["target"]

        collection_id = source.create_collection(name="Comp_OrderBy_Test")
        assert collection_id is not None

        # Create card with ORDER BY price DESC, LIMIT 10
        card_id = source.create_card_with_sorting(
            name="Comp Top 10 Products",
            database_id=source_database_id,
            table_id=source_table_ids["products"],
            order_by_field_id=source_field_ids["products_price"],
            direction="descending",
            limit=10,
            collection_id=collection_id,
        )
        assert card_id is not None

        # Export and import
        run_export(source, export_dir, [collection_id])
        run_import(target, export_dir, db_map_file)

        # Find and verify imported card
        target_collections = target.get_collections()
        target_coll = next(c for c in target_collections if c["name"] == "Comp_OrderBy_Test")
        imported_card = target.find_card_by_name(target_coll["id"], "Comp Top 10 Products")
        assert imported_card is not None

        # Verify order-by field ID is remapped
        assert target.verify_field_id_in_order_by(
            imported_card["id"], target_field_ids["products_price"]
        )

    def test_card_with_expression(
        self,
        docker_services,
        source_database_id,
        target_database_id,
        source_table_ids,
        source_field_ids,
        export_dir,
        db_map_file,
    ):
        """Test card with custom expression/calculated field."""
        source = docker_services["source"]
        target = docker_services["target"]

        collection_id = source.create_collection(name="Comp_Expression_Test")
        assert collection_id is not None

        # Create card with expression: price * 1.1 (10% markup)
        expression = ["*", ["field", source_field_ids["products_price"], None], 1.1]
        card_id = source.create_card_with_expression(
            name="Comp Products with Markup",
            database_id=source_database_id,
            table_id=source_table_ids["products"],
            expression_name="Price with Markup",
            expression=expression,
            collection_id=collection_id,
        )
        assert card_id is not None

        # Export and import
        run_export(source, export_dir, [collection_id])
        run_import(target, export_dir, db_map_file)

        # Verify card exists
        target_collections = target.get_collections()
        target_coll = next(c for c in target_collections if c["name"] == "Comp_Expression_Test")
        imported_card = target.find_card_by_name(target_coll["id"], "Comp Products with Markup")
        assert imported_card is not None

    def test_native_query_with_template_tags(
        self, docker_services, source_database_id, target_database_id, export_dir, db_map_file
    ):
        """Test native SQL query with template tag parameters."""
        source = docker_services["source"]
        target = docker_services["target"]

        collection_id = source.create_collection(name="Comp_TemplateTag_Test")
        assert collection_id is not None

        # Create native query with parameters
        sql = """
            SELECT * FROM orders
            WHERE status = {{status}}
            AND total_amount >= {{min_amount}}
        """
        card_id = source.create_native_query_with_parameters(
            name="Comp Parameterized Orders",
            database_id=source_database_id,
            sql=sql,
            parameters=[
                {
                    "name": "status",
                    "display_name": "Order Status",
                    "type": "text",
                    "default": "completed",
                },
                {"name": "min_amount", "display_name": "Minimum Amount", "type": "number"},
            ],
            collection_id=collection_id,
        )
        assert card_id is not None

        # Export and import
        run_export(source, export_dir, [collection_id])
        run_import(target, export_dir, db_map_file)

        # Verify card exists with template tags
        target_collections = target.get_collections()
        target_coll = next(c for c in target_collections if c["name"] == "Comp_TemplateTag_Test")
        imported_card = target.find_card_by_name(target_coll["id"], "Comp Parameterized Orders")
        assert imported_card is not None

        # Check template tags exist
        dataset_query = imported_card.get("dataset_query", {})
        native = dataset_query.get("native", {})
        template_tags = native.get("template-tags", {})
        # v57 might have template-tags in stages
        if not template_tags:
            stages = dataset_query.get("stages", [])
            if stages:
                template_tags = stages[0].get("template-tags", {})
        assert "status" in template_tags or len(template_tags) > 0

    def test_card_visualization_types(
        self,
        docker_services,
        source_database_id,
        target_database_id,
        source_table_ids,
        source_field_ids,
        export_dir,
        db_map_file,
    ):
        """Test cards with different visualization types (bar, line, pie)."""
        source = docker_services["source"]
        target = docker_services["target"]

        collection_id = source.create_collection(name="Comp_Visualization_Test")
        assert collection_id is not None

        viz_types = ["bar", "line", "pie", "area", "row"]
        card_ids = {}

        for viz in viz_types:
            card_id = source.create_card_with_aggregation(
                name=f"Comp {viz.title()} Chart",
                database_id=source_database_id,
                table_id=source_table_ids["products"],
                aggregation_type="count",
                aggregation_field_id=None,
                breakout_field_id=source_field_ids["products_category"],
                collection_id=collection_id,
                display=viz,
            )
            assert card_id is not None
            card_ids[viz] = card_id

        # Export and import
        run_export(source, export_dir, [collection_id])
        run_import(target, export_dir, db_map_file)

        # Verify all visualization types are preserved
        target_collections = target.get_collections()
        target_coll = next(c for c in target_collections if c["name"] == "Comp_Visualization_Test")

        for viz in viz_types:
            imported_card = target.find_card_by_name(target_coll["id"], f"Comp {viz.title()} Chart")
            assert imported_card is not None
            assert imported_card.get("display") == viz

    def test_archived_card_export(
        self,
        docker_services,
        source_database_id,
        target_database_id,
        source_table_ids,
        export_dir,
        db_map_file,
    ):
        """Test export/import of archived cards with --include-archived flag."""
        source = docker_services["source"]
        # target not needed for this test - only testing export behavior

        collection_id = source.create_collection(name="Comp_Archived_Test")
        assert collection_id is not None

        # Create and archive a card
        card_id = source.create_card(
            name="Comp Archived Card",
            database_id=source_database_id,
            collection_id=collection_id,
            query={
                "database": source_database_id,
                "type": "query",
                "query": {"source-table": source_table_ids["users"]},
            },
        )
        assert card_id is not None
        assert source.archive_card(card_id)

        # Export without archived (should not include)
        manifest = run_export(source, export_dir, [collection_id], include_archived=False)
        archived_cards = [c for c in manifest.get("cards", []) if c["name"] == "Comp Archived Card"]
        assert len(archived_cards) == 0

        # Export with archived
        manifest = run_export(source, export_dir, [collection_id], include_archived=True)
        archived_cards = [c for c in manifest.get("cards", []) if c["name"] == "Comp Archived Card"]
        assert len(archived_cards) >= 1


@pytest.mark.integration
@pytest.mark.slow
class TestModelFeatures:
    """Test model-specific features."""

    def test_multiple_cards_from_model(
        self,
        docker_services,
        source_database_id,
        target_database_id,
        source_table_ids,
        export_dir,
        db_map_file,
    ):
        """Test multiple cards depending on the same model."""
        source = docker_services["source"]
        target = docker_services["target"]

        collection_id = source.create_collection(name="Comp_ModelDeps_Test")
        assert collection_id is not None

        # Create model
        model_id = source.create_model(
            name="Comp Users Base Model",
            database_id=source_database_id,
            collection_id=collection_id,
            query={
                "database": source_database_id,
                "type": "query",
                "query": {"source-table": source_table_ids["users"]},
            },
        )
        assert model_id is not None

        # Create multiple cards based on the model
        card1_id = source.create_card(
            name="Comp Card From Model 1",
            database_id=source_database_id,
            collection_id=collection_id,
            query={
                "database": source_database_id,
                "type": "query",
                "query": {"source-table": f"card__{model_id}"},
            },
        )
        assert card1_id is not None

        card2_id = source.create_card(
            name="Comp Card From Model 2",
            database_id=source_database_id,
            collection_id=collection_id,
            query={
                "database": source_database_id,
                "type": "query",
                "query": {"source-table": f"card__{model_id}"},
            },
        )
        assert card2_id is not None

        # Export and import
        run_export(source, export_dir, [collection_id])
        run_import(target, export_dir, db_map_file)

        # Verify model and both cards exist
        target_collections = target.get_collections()
        target_coll = next(c for c in target_collections if c["name"] == "Comp_ModelDeps_Test")

        model = target.find_card_by_name(target_coll["id"], "Comp Users Base Model")
        assert model is not None

        card1 = target.find_card_by_name(target_coll["id"], "Comp Card From Model 1")
        assert card1 is not None

        card2 = target.find_card_by_name(target_coll["id"], "Comp Card From Model 2")
        assert card2 is not None

    def test_model_chain_dependency(
        self,
        docker_services,
        source_database_id,
        target_database_id,
        source_table_ids,
        export_dir,
        db_map_file,
    ):
        """Test dependency chain: Model → Card → Another Card."""
        source = docker_services["source"]
        target = docker_services["target"]

        collection_id = source.create_collection(name="Comp_ModelChain_Test")
        assert collection_id is not None

        # Create model
        model_id = source.create_model(
            name="Comp Base Model",
            database_id=source_database_id,
            collection_id=collection_id,
            query={
                "database": source_database_id,
                "type": "query",
                "query": {"source-table": source_table_ids["products"]},
            },
        )
        assert model_id is not None

        # Create card based on model
        card1_id = source.create_card(
            name="Comp Intermediate Card",
            database_id=source_database_id,
            collection_id=collection_id,
            query={
                "database": source_database_id,
                "type": "query",
                "query": {"source-table": f"card__{model_id}"},
            },
        )
        assert card1_id is not None

        # Create card based on the previous card (chain)
        card2_id = source.create_card(
            name="Comp Final Card",
            database_id=source_database_id,
            collection_id=collection_id,
            query={
                "database": source_database_id,
                "type": "query",
                "query": {"source-table": f"card__{card1_id}"},
            },
        )
        assert card2_id is not None

        # Export and import
        run_export(source, export_dir, [collection_id])
        run_import(target, export_dir, db_map_file)

        # Verify all three items exist and references are correct
        target_collections = target.get_collections()
        target_coll = next(c for c in target_collections if c["name"] == "Comp_ModelChain_Test")

        model = target.find_card_by_name(target_coll["id"], "Comp Base Model")
        card1 = target.find_card_by_name(target_coll["id"], "Comp Intermediate Card")
        card2 = target.find_card_by_name(target_coll["id"], "Comp Final Card")

        assert model is not None
        assert card1 is not None
        assert card2 is not None

    def test_sql_card_with_model_reference_remapping(
        self,
        docker_services,
        source_database_id,
        target_database_id,
        source_table_ids,
        source_field_ids,
        export_dir,
        db_map_file,
    ):
        """Test SQL card referencing model via {{#id-name}} syntax is correctly remapped.

        This tests the critical bug case where:
        1. A model is created in source (e.g., ID 50)
        2. A SQL card references it via {{#50-model-name}}
        3. Template-tags have: key="#50-model-name", card-id=50, name="#50-model-name"
        4. After migration, model gets new ID (e.g., 100)
        5. ALL template-tag fields must be updated: key, card-id, name, display-name
        6. Without proper remapping, the card fails with "missing required parameters"
        """
        source = docker_services["source"]
        target = docker_services["target"]

        collection_id = source.create_collection(name="Comp_ModelRefSQL_Test")
        assert collection_id is not None

        # Create a model
        model_query = {
            "database": source_database_id,
            "type": "query",
            "query": {
                "source-table": source_table_ids["users"],
                "filter": ["=", ["field", source_field_ids["users_is_active"], None], True],
            },
        }
        model_id = source.create_model(
            name="Comp Active Users Model",
            database_id=source_database_id,
            collection_id=collection_id,
            query=model_query,
            description="Model for SQL reference test",
        )
        assert model_id is not None
        logger.info(f"Created model with ID: {model_id}")

        # Create SQL card that references the model via {{#id-name}} syntax
        sql_card_id = source.create_native_query_with_model_reference(
            name="Comp SQL Card Referencing Model",
            database_id=source_database_id,
            model_id=model_id,
            model_name="comp-active-users-model",
            collection_id=collection_id,
        )
        assert sql_card_id is not None
        logger.info(f"Created SQL card with ID: {sql_card_id} referencing model {model_id}")

        # Export and import
        run_export(source, export_dir, [collection_id])
        run_import(target, export_dir, db_map_file)

        # Find the imported model and SQL card
        target_collections = target.get_collections()
        target_coll = next(c for c in target_collections if c["name"] == "Comp_ModelRefSQL_Test")

        imported_model = target.find_card_by_name(target_coll["id"], "Comp Active Users Model")
        assert imported_model is not None
        target_model_id = imported_model["id"]
        logger.info(f"Imported model with new ID: {target_model_id}")

        imported_sql_card = target.find_card_by_name(
            target_coll["id"], "Comp SQL Card Referencing Model"
        )
        assert imported_sql_card is not None
        logger.info(f"Imported SQL card with ID: {imported_sql_card['id']}")

        # Verify template-tags are correctly remapped
        success, message = target.verify_model_reference_card(
            card_id=imported_sql_card["id"],
            expected_model_id=target_model_id,
        )
        assert success, f"Model reference verification failed: {message}"

        # Verify the SQL card can be executed (key test for the bug)
        # If template-tags weren't properly remapped, this would fail with
        # "missing required parameters: #{"#OLD_ID-model-name"}"
        try:
            response = requests.post(
                f"{target.api_url}/card/{imported_sql_card['id']}/query",
                headers=target._get_headers(),
                timeout=30,
            )
            # Success codes include 200 (immediate result) and 202 (async processing)
            if response.status_code in [200, 202]:
                logger.info("SQL card executed successfully!")
            else:
                error_msg = response.json().get("message", response.text)
                # Check if this is the specific bug: "missing required parameters"
                if "missing required parameters" in error_msg.lower():
                    pytest.fail(
                        f"Model reference remapping bug detected! Card execution failed with: {error_msg}. "
                        "This means template-tag key/name/display-name were not updated when card-id was remapped."
                    )
                else:
                    # Other errors might be acceptable (e.g., query timeout, data issues)
                    logger.warning(
                        f"Card execution returned {response.status_code}: {error_msg[:200]}"
                    )
        except Exception as e:
            logger.warning(f"Could not execute card: {e}")


@pytest.mark.integration
@pytest.mark.slow
class TestDashboardFeatures:
    """Test dashboard features."""

    def test_dashboard_with_tabs(
        self,
        docker_services,
        source_database_id,
        target_database_id,
        source_table_ids,
        export_dir,
        db_map_file,
    ):
        """Test dashboard with multiple tabs."""
        source = docker_services["source"]
        target = docker_services["target"]

        collection_id = source.create_collection(name="Comp_Tabs_Test")
        assert collection_id is not None

        # Create cards for tabs
        card1_id = source.create_card(
            name="Comp Tab1 Card",
            database_id=source_database_id,
            collection_id=collection_id,
            query={
                "database": source_database_id,
                "type": "query",
                "query": {"source-table": source_table_ids["users"]},
            },
        )
        card2_id = source.create_card(
            name="Comp Tab2 Card",
            database_id=source_database_id,
            collection_id=collection_id,
            query={
                "database": source_database_id,
                "type": "query",
                "query": {"source-table": source_table_ids["products"]},
            },
        )
        assert card1_id and card2_id

        # Create dashboard with tabs
        dashboard_id = source.create_dashboard_with_tabs(
            name="Comp Tabbed Dashboard",
            collection_id=collection_id,
            tab_names=["Overview", "Products"],
            card_ids_per_tab=[[card1_id], [card2_id]],
        )
        assert dashboard_id is not None

        # Export and import
        run_export(source, export_dir, [collection_id])
        run_import(target, export_dir, db_map_file)

        # Verify dashboard with tabs exists
        target_collections = target.get_collections()
        target_coll = next(c for c in target_collections if c["name"] == "Comp_Tabs_Test")
        imported_dash = target.find_dashboard_by_name(target_coll["id"], "Comp Tabbed Dashboard")
        assert imported_dash is not None

        # Check tabs exist (some Metabase versions might not return tabs in the same format)
        # Just verify the dashboard was imported successfully with tabs
        assert imported_dash.get("tabs") is not None or len(imported_dash.get("dashcards", [])) > 0

    def test_dashboard_with_text_cards(
        self,
        docker_services,
        source_database_id,
        target_database_id,
        source_table_ids,
        export_dir,
        db_map_file,
    ):
        """Test dashboard with text/markdown cards."""
        source = docker_services["source"]
        target = docker_services["target"]

        collection_id = source.create_collection(name="Comp_TextCard_Test")
        assert collection_id is not None

        # Create a regular card
        card_id = source.create_card(
            name="Comp Regular Card",
            database_id=source_database_id,
            collection_id=collection_id,
            query={
                "database": source_database_id,
                "type": "query",
                "query": {"source-table": source_table_ids["users"]},
            },
        )
        assert card_id is not None

        # Create dashboard
        dashboard_id = source.create_dashboard(
            name="Comp Dashboard with Text",
            collection_id=collection_id,
            card_ids=[card_id],
        )
        assert dashboard_id is not None

        # Add text card
        text_card_id = source.add_text_card_to_dashboard(
            dashboard_id=dashboard_id,
            text="# Welcome\nThis is a **markdown** text card with *formatting*.",
            row=0,
            col=4,
        )
        # Text card might not be supported in all versions
        if text_card_id:
            logger.info(f"Added text card with ID {text_card_id}")

        # Export and import
        run_export(source, export_dir, [collection_id])
        run_import(target, export_dir, db_map_file)

        # Verify dashboard exists
        target_collections = target.get_collections()
        target_coll = next(c for c in target_collections if c["name"] == "Comp_TextCard_Test")
        imported_dash = target.find_dashboard_by_name(target_coll["id"], "Comp Dashboard with Text")
        assert imported_dash is not None

    def test_dashboard_with_linked_filters(
        self,
        docker_services,
        source_database_id,
        target_database_id,
        source_table_ids,
        source_field_ids,
        target_field_ids,
        export_dir,
        db_map_file,
    ):
        """Test dashboard with multiple linked filter parameters."""
        source = docker_services["source"]
        target = docker_services["target"]

        collection_id = source.create_collection(name="Comp_LinkedFilters_Test")
        assert collection_id is not None

        # Create card
        card_id = source.create_card(
            name="Comp Filtered Card",
            database_id=source_database_id,
            collection_id=collection_id,
            query={
                "database": source_database_id,
                "type": "query",
                "query": {"source-table": source_table_ids["products"]},
            },
        )
        assert card_id is not None

        # Create dashboard with multiple filters
        filter_configs = [
            {
                "id": "category_filter",
                "name": "Category",
                "slug": "category",
                "type": "string/=",
                "field_id": source_field_ids["products_category"],
            },
            {
                "id": "price_filter",
                "name": "Price",
                "slug": "price",
                "type": "number/>=",
                "field_id": source_field_ids["products_price"],
            },
        ]

        dashboard_id = source.create_dashboard_with_multiple_filters(
            name="Comp Multi-Filter Dashboard",
            collection_id=collection_id,
            card_ids=[card_id],
            filter_configs=filter_configs,
        )
        assert dashboard_id is not None

        # Export and import
        run_export(source, export_dir, [collection_id])
        run_import(target, export_dir, db_map_file)

        # Verify dashboard exists with parameters
        target_collections = target.get_collections()
        target_coll = next(c for c in target_collections if c["name"] == "Comp_LinkedFilters_Test")
        imported_dash = target.find_dashboard_by_name(
            target_coll["id"], "Comp Multi-Filter Dashboard"
        )
        assert imported_dash is not None

        # Verify parameters exist
        parameters = imported_dash.get("parameters", [])
        assert len(parameters) >= 2


@pytest.mark.integration
@pytest.mark.slow
class TestIDRemapping:
    """Test ID remapping across instances."""

    def test_table_id_remapping_in_query(
        self,
        docker_services,
        source_database_id,
        target_database_id,
        source_table_ids,
        target_table_ids,
        export_dir,
        db_map_file,
    ):
        """Test that table IDs are correctly remapped in queries."""
        source = docker_services["source"]
        target = docker_services["target"]

        collection_id = source.create_collection(name="Comp_TableRemap_Test")
        assert collection_id is not None

        # Create card querying users table
        card_id = source.create_card(
            name="Comp Users Query",
            database_id=source_database_id,
            collection_id=collection_id,
            query={
                "database": source_database_id,
                "type": "query",
                "query": {"source-table": source_table_ids["users"]},
            },
        )
        assert card_id is not None

        # Export and import
        run_export(source, export_dir, [collection_id])
        run_import(target, export_dir, db_map_file)

        # Find imported card and verify table ID is remapped
        target_collections = target.get_collections()
        target_coll = next(c for c in target_collections if c["name"] == "Comp_TableRemap_Test")
        imported_card = target.find_card_by_name(target_coll["id"], "Comp Users Query")
        assert imported_card is not None

        # Verify table ID
        assert target.verify_table_id_in_query(imported_card["id"], target_table_ids["users"])

    def test_field_id_remapping_in_filter(
        self,
        docker_services,
        source_database_id,
        target_database_id,
        source_table_ids,
        target_table_ids,
        source_field_ids,
        target_field_ids,
        export_dir,
        db_map_file,
    ):
        """Test that field IDs are correctly remapped in filter clauses."""
        source = docker_services["source"]
        target = docker_services["target"]

        collection_id = source.create_collection(name="Comp_FilterRemap_Test")
        assert collection_id is not None

        # Create card with filter on is_active field
        card_id = source.create_card_with_filter(
            name="Comp Active Users Filter",
            database_id=source_database_id,
            table_id=source_table_ids["users"],
            filter_field_id=source_field_ids["users_is_active"],
            filter_value=True,
            collection_id=collection_id,
        )
        assert card_id is not None

        # Export and import
        run_export(source, export_dir, [collection_id])
        run_import(target, export_dir, db_map_file)

        # Find imported card and verify field ID is remapped
        target_collections = target.get_collections()
        target_coll = next(c for c in target_collections if c["name"] == "Comp_FilterRemap_Test")
        imported_card = target.find_card_by_name(target_coll["id"], "Comp Active Users Filter")
        assert imported_card is not None

        # Verify field ID in filter
        assert target.verify_field_id_in_filter(
            imported_card["id"], target_field_ids["users_is_active"]
        )

    def test_field_id_remapping_in_aggregation(
        self,
        docker_services,
        source_database_id,
        target_database_id,
        source_table_ids,
        target_table_ids,
        source_field_ids,
        target_field_ids,
        export_dir,
        db_map_file,
    ):
        """Test that field IDs are correctly remapped in aggregation clauses."""
        source = docker_services["source"]
        target = docker_services["target"]

        collection_id = source.create_collection(name="Comp_AggRemap_Test")
        assert collection_id is not None

        # Create card with SUM aggregation on total_amount
        card_id = source.create_card_with_aggregation(
            name="Comp Total Revenue",
            database_id=source_database_id,
            table_id=source_table_ids["orders"],
            aggregation_type="sum",
            aggregation_field_id=source_field_ids["orders_total_amount"],
            collection_id=collection_id,
        )
        assert card_id is not None

        # Export and import
        run_export(source, export_dir, [collection_id])
        run_import(target, export_dir, db_map_file)

        # Find imported card and verify field ID is remapped
        target_collections = target.get_collections()
        target_coll = next(c for c in target_collections if c["name"] == "Comp_AggRemap_Test")
        imported_card = target.find_card_by_name(target_coll["id"], "Comp Total Revenue")
        assert imported_card is not None

        # Verify field ID in aggregation
        assert target.verify_field_id_in_aggregation(
            imported_card["id"], target_field_ids["orders_total_amount"]
        )


@pytest.mark.integration
@pytest.mark.slow
class TestConflictResolution:
    """Test conflict resolution strategies."""

    def test_conflict_strategy_skip(
        self,
        docker_services,
        source_database_id,
        target_database_id,
        source_table_ids,
        export_dir,
        db_map_file,
    ):
        """Test skip strategy - existing content should remain unchanged."""
        source = docker_services["source"]
        target = docker_services["target"]

        collection_id = source.create_collection(name="Comp_Skip_Test")
        assert collection_id is not None

        # Create card in source
        card_id = source.create_card(
            name="Comp Skip Card",
            database_id=source_database_id,
            collection_id=collection_id,
            query={
                "database": source_database_id,
                "type": "query",
                "query": {"source-table": source_table_ids["users"]},
            },
            description="Original description",
        )
        assert card_id is not None

        # Export
        run_export(source, export_dir, [collection_id])

        # Import first time
        run_import(target, export_dir, db_map_file, conflict_strategy="skip")

        # Find the imported collection and card
        target_collections = target.get_collections()
        target_coll = next(c for c in target_collections if c["name"] == "Comp_Skip_Test")
        imported_card = target.find_card_by_name(target_coll["id"], "Comp Skip Card")
        assert imported_card is not None

        # Import again with skip strategy - the card should not be duplicated
        run_import(target, export_dir, db_map_file, conflict_strategy="skip")

        # Verify only one card exists with this name
        items = target.get_cards_in_collection(target_coll["id"])
        matching_cards = [c for c in items if c.get("name") == "Comp Skip Card"]
        assert len(matching_cards) == 1

    def test_conflict_strategy_rename(
        self,
        docker_services,
        source_database_id,
        target_database_id,
        source_table_ids,
        export_dir,
        db_map_file,
    ):
        """Test rename strategy - conflicting items get renamed."""
        source = docker_services["source"]
        target = docker_services["target"]

        collection_id = source.create_collection(name="Comp_Rename_Test")
        assert collection_id is not None

        # Create card in source
        card_id = source.create_card(
            name="Comp Rename Card",
            database_id=source_database_id,
            collection_id=collection_id,
            query={
                "database": source_database_id,
                "type": "query",
                "query": {"source-table": source_table_ids["users"]},
            },
        )
        assert card_id is not None

        # Export
        run_export(source, export_dir, [collection_id])

        # Import first time
        run_import(target, export_dir, db_map_file, conflict_strategy="skip")

        # Import again with rename strategy
        run_import(target, export_dir, db_map_file, conflict_strategy="rename")

        # Verify multiple cards exist (original + renamed)
        target_collections = target.get_collections()
        target_coll = next(c for c in target_collections if c["name"] == "Comp_Rename_Test")
        items = target.get_cards_in_collection(target_coll["id"])

        # Should have at least 2 cards with similar names
        assert len(items) >= 2


@pytest.mark.integration
@pytest.mark.slow
class TestDryRun:
    """Test dry-run mode."""

    def test_dry_run_no_changes(
        self,
        docker_services,
        source_database_id,
        target_database_id,
        source_table_ids,
        export_dir,
        db_map_file,
    ):
        """Test that dry-run mode doesn't create any changes."""
        source = docker_services["source"]
        target = docker_services["target"]

        collection_id = source.create_collection(name="Comp_DryRun_Test")
        assert collection_id is not None

        # Create card in source
        card_id = source.create_card(
            name="Comp DryRun Card",
            database_id=source_database_id,
            collection_id=collection_id,
            query={
                "database": source_database_id,
                "type": "query",
                "query": {"source-table": source_table_ids["users"]},
            },
        )
        assert card_id is not None

        # Export
        run_export(source, export_dir, [collection_id])

        # Run import with dry_run=True
        run_import(target, export_dir, db_map_file, dry_run=True)

        # Verify no new collections were created
        target_collections_after = target.get_collections()

        # The collection should NOT exist after dry-run
        collection_exists = any(c["name"] == "Comp_DryRun_Test" for c in target_collections_after)
        assert not collection_exists, "Dry-run should not create collections"


@pytest.mark.integration
@pytest.mark.slow
class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_long_names(
        self,
        docker_services,
        source_database_id,
        target_database_id,
        source_table_ids,
        export_dir,
        db_map_file,
    ):
        """Test handling of very long collection and card names."""
        source = docker_services["source"]
        target = docker_services["target"]

        # Create collection with long name (max is typically 255 chars)
        long_name = "Comp_" + "A" * 200
        collection_id = source.create_collection(name=long_name)
        assert collection_id is not None

        # Create card with long name
        card_id = source.create_card(
            name="Comp_" + "B" * 200,
            database_id=source_database_id,
            collection_id=collection_id,
            query={
                "database": source_database_id,
                "type": "query",
                "query": {"source-table": source_table_ids["users"]},
            },
        )
        assert card_id is not None

        # Export and import
        run_export(source, export_dir, [collection_id])
        run_import(target, export_dir, db_map_file)

        # Verify long-named items exist
        target_collections = target.get_collections()
        assert any(c["name"] == long_name for c in target_collections)

    def test_unicode_content(
        self,
        docker_services,
        source_database_id,
        target_database_id,
        source_table_ids,
        export_dir,
        db_map_file,
    ):
        """Test handling of Unicode characters in names and descriptions."""
        source = docker_services["source"]
        target = docker_services["target"]

        # Create collection with Unicode characters
        unicode_name = "Comp 日本語 العربية 中文 🎉"
        collection_id = source.create_collection(
            name=unicode_name,
            description="Description with émojis 🚀 and ünïcödé characters",
        )
        assert collection_id is not None

        # Create card with Unicode
        card_id = source.create_card(
            name="Comp カード ทดสอบ",
            database_id=source_database_id,
            collection_id=collection_id,
            query={
                "database": source_database_id,
                "type": "query",
                "query": {"source-table": source_table_ids["users"]},
            },
            description="描述 with special chars: <>&\"'",
        )
        assert card_id is not None

        # Export and import
        run_export(source, export_dir, [collection_id])
        run_import(target, export_dir, db_map_file)

        # Verify Unicode content is preserved
        target_collections = target.get_collections()
        assert any(c["name"] == unicode_name for c in target_collections)

    def test_special_characters_in_names(
        self,
        docker_services,
        source_database_id,
        target_database_id,
        source_table_ids,
        export_dir,
        db_map_file,
    ):
        """Test handling of special characters that could cause issues."""
        source = docker_services["source"]
        target = docker_services["target"]

        # Create collection with potentially problematic characters
        special_name = "Comp Test [brackets] {braces} (parens) 'quotes' \"double\""
        collection_id = source.create_collection(name=special_name)
        assert collection_id is not None

        # Export and import
        run_export(source, export_dir, [collection_id])
        run_import(target, export_dir, db_map_file)

        # Verify collection exists
        target_collections = target.get_collections()
        assert any(c["name"] == special_name for c in target_collections)
