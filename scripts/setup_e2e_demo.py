#!/usr/bin/env python3
"""Setup E2E demo environment with test data for migration testing.

This script:
1. Sets up source and target Metabase instances
2. Creates sample database connections
3. Creates test collections, models, cards, and dashboards in source
4. Generates db_map.json for migration

Usage:
    python scripts/setup_e2e_demo.py
"""

import json
import logging
import sys
import time
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from tests.integration.test_helpers import MetabaseTestHelper

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Configuration
SOURCE_URL = "http://localhost:3002"
TARGET_URL = "http://localhost:3003"
ADMIN_EMAIL = "admin@example.com"
ADMIN_PASSWORD = "Admin123!"

# Sample database connection details (inside Docker network)
SAMPLE_DB_CONFIG = {
    "name": "Sample Data",
    "host": "sample-data-postgres",
    "port": 5432,
    "dbname": "sample_data",
    "user": "sample_user",
    "password": "sample_password",
}


def wait_for_metabase(helper: MetabaseTestHelper, timeout: int = 300) -> bool:
    """Wait for Metabase to be ready."""
    logger.info(f"Waiting for Metabase at {helper.base_url}...")
    start = time.time()
    while time.time() - start < timeout:
        if helper.wait_for_metabase(timeout=10, interval=5):
            return True
    return False


def setup_metabase_instance(helper: MetabaseTestHelper, name: str) -> int | None:
    """Setup a Metabase instance and return the sample database ID."""
    logger.info(f"\n{'='*60}")
    logger.info(f"Setting up {name} Metabase ({helper.base_url})")
    logger.info("=" * 60)

    # Wait for Metabase to be ready
    if not wait_for_metabase(helper):
        logger.error(f"{name} Metabase did not become ready")
        return None

    # Try to login first - if it works, setup is already complete
    if helper.login():
        logger.info("Metabase already configured, logged in successfully")
    else:
        # Setup admin user if needed
        logger.info("Running initial setup...")
        if helper.setup_metabase():
            # Login after setup
            if not helper.login():
                logger.error("Failed to login after setup")
                return None
        else:
            # Setup failed - try to login anyway (might already be configured)
            if not helper.login():
                logger.error("Failed to setup and login to Metabase")
                return None
            logger.info("Setup skipped (already configured), logged in successfully")

    # Add sample database if not exists
    databases = helper.get_databases()
    sample_db = next(
        (db for db in databases if db.get("name") == SAMPLE_DB_CONFIG["name"]), None
    )

    if sample_db:
        db_id = sample_db["id"]
        logger.info(f"Sample database already exists with ID: {db_id}")
    else:
        db_id = helper.add_database(**SAMPLE_DB_CONFIG)
        if db_id:
            logger.info(f"Added Sample Data database with ID: {db_id}")
        else:
            logger.error("Failed to add sample database")
            return None

    return db_id


def create_test_content(helper: MetabaseTestHelper, db_id: int) -> dict:
    """Create test content in source Metabase and return created IDs."""
    logger.info("\n" + "=" * 60)
    logger.info("Creating test content in source Metabase")
    logger.info("=" * 60)

    # Get table and field IDs
    metadata = helper.get_database_metadata(db_id)
    if not metadata:
        logger.error("Failed to get database metadata")
        return {}

    tables = {t["name"]: t for t in metadata.get("tables", [])}
    users_table_id = tables["users"]["id"]
    products_table_id = tables["products"]["id"]
    orders_table_id = tables["orders"]["id"]

    def get_field_id(table_name: str, field_name: str) -> int | None:
        for field in tables[table_name].get("fields", []):
            if field["name"] == field_name:
                return field["id"]
        return None

    # Field IDs
    users_id_field = get_field_id("users", "id")
    users_is_active_field = get_field_id("users", "is_active")
    products_category_field = get_field_id("products", "category")
    products_price_field = get_field_id("products", "price")
    orders_user_id_field = get_field_id("orders", "user_id")

    created = {"collections": [], "cards": [], "models": [], "dashboards": []}

    # Create collections
    logger.info("\nCreating collections...")
    main_collection = helper.create_collection(
        name="E2E Migration Test",
        description="Main collection for E2E migration testing",
    )
    created["collections"].append(main_collection)

    analytics_collection = helper.create_collection(
        name="Analytics",
        description="Analytics reports",
        parent_id=main_collection,
    )
    created["collections"].append(analytics_collection)

    # Create a model (to test model reference migration)
    logger.info("\nCreating models...")
    model_query = {
        "database": db_id,
        "type": "query",
        "query": {
            "source-table": users_table_id,
            "filter": ["=", ["field", users_is_active_field, None], True],
        },
    }
    active_users_model = helper.create_model(
        name="Active Users Model",
        database_id=db_id,
        collection_id=main_collection,
        query=model_query,
        description="Model containing only active users",
    )
    created["models"].append(active_users_model)
    logger.info(f"  Created 'Active Users Model' (id={active_users_model})")

    # Create cards
    logger.info("\nCreating cards...")

    # Simple card
    all_users_card = helper.create_card(
        name="All Users",
        database_id=db_id,
        collection_id=main_collection,
        query={
            "database": db_id,
            "type": "query",
            "query": {"source-table": users_table_id},
        },
        description="List of all users",
    )
    created["cards"].append(all_users_card)
    logger.info(f"  Created 'All Users' (id={all_users_card})")

    # Card with filter
    active_users_card = helper.create_card_with_filter(
        name="Active Users Only",
        database_id=db_id,
        table_id=users_table_id,
        filter_field_id=users_is_active_field,
        filter_value=True,
        collection_id=analytics_collection,
    )
    created["cards"].append(active_users_card)
    logger.info(f"  Created 'Active Users Only' (id={active_users_card})")

    # Card with aggregation
    products_by_category = helper.create_card_with_aggregation(
        name="Products by Category",
        database_id=db_id,
        table_id=products_table_id,
        aggregation_type="count",
        aggregation_field_id=None,
        breakout_field_id=products_category_field,
        collection_id=analytics_collection,
        display="bar",
    )
    created["cards"].append(products_by_category)
    logger.info(f"  Created 'Products by Category' (id={products_by_category})")

    # Native SQL card
    native_card = helper.create_native_query_card(
        name="Monthly Orders Summary",
        database_id=db_id,
        sql="""
SELECT
    DATE_TRUNC('month', order_date) as month,
    COUNT(*) as order_count,
    SUM(total_amount) as total_revenue
FROM orders
GROUP BY DATE_TRUNC('month', order_date)
ORDER BY month DESC
        """,
        collection_id=analytics_collection,
    )
    created["cards"].append(native_card)
    logger.info(f"  Created 'Monthly Orders Summary' (id={native_card})")

    # SQL card that references the model (key test case!)
    if active_users_model:
        model_ref_card = helper.create_native_query_with_model_reference(
            name="SQL Card Referencing Model",
            database_id=db_id,
            model_id=active_users_model,
            model_name="active-users-model",
            collection_id=main_collection,
        )
        created["cards"].append(model_ref_card)
        logger.info(
            f"  Created 'SQL Card Referencing Model' (id={model_ref_card}) - "
            f"references model #{active_users_model}"
        )

    # Card with join
    join_card = helper.create_card_with_join(
        name="Orders with Users",
        database_id=db_id,
        source_table_id=orders_table_id,
        join_table_id=users_table_id,
        source_field_id=orders_user_id_field,
        join_field_id=users_id_field,
        collection_id=analytics_collection,
    )
    created["cards"].append(join_card)
    logger.info(f"  Created 'Orders with Users' (id={join_card})")

    # Create dashboards
    logger.info("\nCreating dashboards...")

    # Simple dashboard
    overview_dashboard = helper.create_dashboard(
        name="Overview Dashboard",
        collection_id=main_collection,
        card_ids=[c for c in [all_users_card, products_by_category] if c],
        description="Overview of users and products",
    )
    created["dashboards"].append(overview_dashboard)
    logger.info(f"  Created 'Overview Dashboard' (id={overview_dashboard})")

    # Dashboard with filter
    if active_users_card and users_is_active_field:
        filter_dashboard = helper.create_dashboard_with_filter(
            name="User Analytics Dashboard",
            collection_id=analytics_collection,
            card_id=active_users_card,
            filter_field_id=users_is_active_field,
            filter_table_id=users_table_id,
        )
        created["dashboards"].append(filter_dashboard)
        logger.info(f"  Created 'User Analytics Dashboard' (id={filter_dashboard})")

    return created


def generate_db_map(
    source_helper: MetabaseTestHelper,
    target_helper: MetabaseTestHelper,
    output_path: Path,
) -> None:
    """Generate db_map.json file for import by matching databases by name."""
    source_dbs = source_helper.get_databases()
    target_dbs = target_helper.get_databases()

    # Build name -> id mapping for target
    target_by_name = {db["name"]: db["id"] for db in target_dbs}

    # Map source databases to target by name
    db_map = {"by_id": {}}
    for source_db in source_dbs:
        source_id = source_db["id"]
        source_name = source_db["name"]

        if source_name in target_by_name:
            target_id = target_by_name[source_name]
            db_map["by_id"][str(source_id)] = target_id
            logger.info(f"  Mapping: {source_name} (source:{source_id} -> target:{target_id})")
        else:
            logger.warning(f"  No target database found for: {source_name} (source:{source_id})")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(db_map, f, indent=2)

    logger.info(f"\nGenerated db_map.json at {output_path}")


def main() -> int:
    """Main entry point."""
    logger.info("=" * 60)
    logger.info("E2E Demo Setup - Metabase Migration Toolkit")
    logger.info("=" * 60)

    # Setup source Metabase
    source = MetabaseTestHelper(SOURCE_URL, ADMIN_EMAIL, ADMIN_PASSWORD)
    source_db_id = setup_metabase_instance(source, "Source")
    if not source_db_id:
        logger.error("Failed to setup source Metabase")
        return 1

    # Setup target Metabase
    target = MetabaseTestHelper(TARGET_URL, ADMIN_EMAIL, ADMIN_PASSWORD)
    target_db_id = setup_metabase_instance(target, "Target")
    if not target_db_id:
        logger.error("Failed to setup target Metabase")
        return 1

    # Create test content in source
    created = create_test_content(source, source_db_id)
    if not created:
        logger.error("Failed to create test content")
        return 1

    # Generate db_map.json (maps all databases by name)
    project_root = Path(__file__).parent.parent
    export_dir = project_root / "e2e_export"
    db_map_path = export_dir / "db_map.json"
    logger.info("\nGenerating database mappings...")
    generate_db_map(source, target, db_map_path)

    # Summary
    logger.info("\n" + "=" * 60)
    logger.info("SETUP COMPLETE!")
    logger.info("=" * 60)
    logger.info(f"""
Source Metabase: {SOURCE_URL}
Target Metabase: {TARGET_URL}
Credentials: {ADMIN_EMAIL} / {ADMIN_PASSWORD}

Created in Source:
  Collections: {len([c for c in created.get('collections', []) if c])}
  Models: {len([m for m in created.get('models', []) if m])}
  Cards: {len([c for c in created.get('cards', []) if c])}
  Dashboards: {len([d for d in created.get('dashboards', []) if d])}

Export directory: {export_dir}
DB map file: {db_map_path}

Next steps - Run migration:
  1. Export: python export_metabase.py \\
       --source-url {SOURCE_URL} \\
       --source-username {ADMIN_EMAIL} \\
       --source-password {ADMIN_PASSWORD} \\
       --export-dir {export_dir} \\
       --include-dashboards \\
       --metabase-version v57

  2. Import: python import_metabase.py \\
       --target-url {TARGET_URL} \\
       --target-username {ADMIN_EMAIL} \\
       --target-password {ADMIN_PASSWORD} \\
       --export-dir {export_dir} \\
       --db-map {db_map_path} \\
       --metabase-version v57

Or use: make demo-migrate
""")

    return 0


if __name__ == "__main__":
    sys.exit(main())
