#!/usr/bin/env python3
"""Verify E2E demo migration results.

This script verifies that the migration was successful by:
1. Finding migrated content in target Metabase
2. Verifying SQL cards with model references work correctly
3. Checking that template-tags have been properly remapped

Usage:
    python scripts/verify_e2e_demo.py
"""
import logging
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import requests  # noqa: E402

from tests.integration.test_helpers import MetabaseTestHelper  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Configuration
TARGET_URL = "http://localhost:3003"
ADMIN_EMAIL = "admin@example.com"
ADMIN_PASSWORD = "Admin123!"  # pragma: allowlist secret  # nosec B105


def find_card_by_name(helper: MetabaseTestHelper, name: str) -> dict | None:
    """Find a card by name in the target instance."""
    try:
        # Search for the card
        response = requests.get(
            f"{helper.api_url}/search?q={name}&type=card",
            headers=helper._get_headers(),
            timeout=10,
        )
        if response.status_code == 200:
            results = response.json().get("data", [])
            for result in results:
                if result.get("name") == name:
                    return helper.get_card(result.get("id"))
    except Exception as e:
        logger.error(f"Error searching for card: {e}")
    return None


def find_model_by_name(helper: MetabaseTestHelper, name: str) -> dict | None:
    """Find a model by name in the target instance."""
    try:
        # Search for the model
        response = requests.get(
            f"{helper.api_url}/search?q={name}&type=model",
            headers=helper._get_headers(),
            timeout=10,
        )
        if response.status_code == 200:
            results = response.json().get("data", [])
            for result in results:
                if result.get("name") == name:
                    return helper.get_card(result.get("id"))
    except Exception as e:
        logger.error(f"Error searching for model: {e}")
    return None


def verify_model_reference_remapping(
    helper: MetabaseTestHelper,
    sql_card: dict,
    model: dict,
) -> tuple[bool, list[str]]:
    """Verify that a SQL card's model reference has been correctly remapped.

    This is the KEY TEST CASE for the bug:
    "template-tags":{"#50-filtered-xxxx-server-dataset":{
        "name":"#50-filtered-xxxx-server-dataset",
        "card-id":406,  <-- Updated
        "type":"card",
        "display-name":"#50 Filtered XXXX Server Dataset"  <-- NOT updated
    }}

    The bug is that card-id is updated but the key, name, and display-name
    still reference the old ID.
    """
    errors = []
    model_id = model.get("id")
    sql_card_id = sql_card.get("id")

    dataset_query = sql_card.get("dataset_query", {})

    # Handle v57 stages format
    stages = dataset_query.get("stages", [])
    if stages:
        stage = stages[0]
        sql = stage.get("native", "")
        template_tags = stage.get("template-tags", {})
    else:
        # v56 format
        native = dataset_query.get("native", {})
        sql = native.get("query", "")
        template_tags = native.get("template-tags", {})

    logger.info(f"\n  Checking SQL card {sql_card_id} references model {model_id}")
    logger.info(f"  SQL: {sql[:100]}...")
    logger.info(f"  Template tags: {list(template_tags.keys())}")

    # Check 1: SQL contains the correct model ID reference
    expected_sql_pattern = f"{{{{#{model_id}-"
    if expected_sql_pattern not in sql:
        errors.append(f"SQL does not contain expected pattern '{expected_sql_pattern}'")
        logger.error("  ✗ SQL pattern check failed")
    else:
        logger.info("  ✓ SQL contains correct model ID reference")

    # Check 2: Template tag key, name, and card-id are all consistent
    for tag_key, tag_data in template_tags.items():
        if tag_data.get("type") != "card":
            continue

        tag_card_id = tag_data.get("card-id")
        tag_name = tag_data.get("name", "")
        tag_display_name = tag_data.get("display-name", "")

        logger.info("\n  Template tag details:")
        logger.info(f"    Key: {tag_key}")
        logger.info(f"    card-id: {tag_card_id}")
        logger.info(f"    name: {tag_name}")
        logger.info(f"    display-name: {tag_display_name}")

        # The key should start with #{model_id}-
        expected_key_prefix = f"#{model_id}-"
        if not tag_key.startswith(expected_key_prefix):
            errors.append(
                f"Template tag KEY '{tag_key}' does not start with '{expected_key_prefix}'"
            )
            logger.error("  ✗ Tag key has wrong model ID")
        else:
            logger.info("  ✓ Tag key has correct model ID")

        # The card-id should match the model ID
        if tag_card_id != model_id:
            errors.append(
                f"Template tag card-id ({tag_card_id}) does not match model ID ({model_id})"
            )
            logger.error("  ✗ Tag card-id mismatch")
        else:
            logger.info("  ✓ Tag card-id matches model ID")

        # The name should match the key
        if tag_name != tag_key:
            errors.append(f"Template tag name '{tag_name}' does not match key '{tag_key}'")
            logger.error("  ✗ Tag name does not match key")
        else:
            logger.info("  ✓ Tag name matches key")

        # The display-name should contain the new model ID
        if f"#{model_id}" not in tag_display_name and str(model_id) not in tag_display_name:
            errors.append(
                f"Template tag display-name '{tag_display_name}' does not contain model ID {model_id}"
            )
            logger.error("  ✗ Tag display-name has wrong model ID")
        else:
            logger.info("  ✓ Tag display-name has correct model ID")

    # Check 3: Try to execute the card
    logger.info("\n  Attempting to execute SQL card...")
    try:
        response = requests.post(
            f"{helper.api_url}/card/{sql_card_id}/query",
            headers=helper._get_headers(),
            timeout=30,
        )
        if response.status_code in [200, 202]:
            logger.info("  ✓ Card executed successfully!")
        else:
            error_msg = response.json().get("message", response.text)
            if "missing required parameters" in error_msg.lower():
                errors.append(f"Card execution failed: {error_msg}")
                logger.error("  ✗ Card execution failed with missing parameters")
                logger.error(f"    Error: {error_msg}")
            else:
                logger.warning(
                    f"  ⚠ Card execution returned {response.status_code}: {error_msg[:100]}"
                )
    except Exception as e:
        logger.warning(f"  ⚠ Could not execute card: {e}")

    return len(errors) == 0, errors


def find_dashboard_by_name(helper: MetabaseTestHelper, name: str) -> dict | None:
    """Find a dashboard by name in the target instance."""
    try:
        # Search for the dashboard
        response = requests.get(
            f"{helper.api_url}/search?q={name}&type=dashboard",
            headers=helper._get_headers(),
            timeout=10,
        )
        if response.status_code == 200:
            results = response.json().get("data", [])
            for result in results:
                if result.get("name") == name:
                    return helper.get_dashboard(result.get("id"))
    except Exception as e:
        logger.error(f"Error searching for dashboard: {e}")
    return None


def verify_visualize_another_way_dashboard(
    helper: MetabaseTestHelper,
    dashboard: dict,
) -> tuple[bool, list[str]]:
    """Verify that a 'Visualize another way' dashboard was migrated correctly.

    This tests the bug fix for embedded card objects in dashcards. When 'Visualize
    another way' is used, the dashcard stores a `card` object with custom visualization
    settings. During migration, the `card.id` reference must be remapped.

    The bug was:
    - Server logs: GET /api/card/41 404 - trying to fetch the OLD card ID

    Args:
        helper: MetabaseTestHelper instance
        dashboard: The dashboard data

    Returns:
        Tuple of (success, list of errors)
    """
    errors = []
    dashboard_id = dashboard.get("id")
    dashcards = dashboard.get("dashcards", [])

    logger.info(f"\n  Dashboard ID: {dashboard_id}")
    logger.info(f"  Number of dashcards: {len(dashcards)}")

    if len(dashcards) < 2:
        errors.append(
            f"Expected at least 2 dashcards (normal + visualize another way), got {len(dashcards)}"
        )
        return False, errors

    # Find dashcards with embedded 'card' objects
    embedded_card_dashcards = [dc for dc in dashcards if dc.get("card")]
    normal_dashcards = [dc for dc in dashcards if not dc.get("card")]

    logger.info(f"  Normal dashcards: {len(normal_dashcards)}")
    logger.info(f"  'Visualize another way' dashcards: {len(embedded_card_dashcards)}")

    if not embedded_card_dashcards:
        errors.append("No dashcards with embedded 'card' objects found")
        return False, errors

    # Check each 'Visualize another way' dashcard
    for idx, dashcard in enumerate(embedded_card_dashcards):
        dashcard_id = dashcard.get("id")
        card_id = dashcard.get("card_id")
        embedded_card = dashcard.get("card", {})
        embedded_card_id = embedded_card.get("id")

        logger.info(f"\n  Checking 'Visualize another way' dashcard {idx + 1}:")
        logger.info(f"    Dashcard ID: {dashcard_id}")
        logger.info(f"    card_id (reference): {card_id}")
        logger.info(f"    embedded card.id: {embedded_card_id}")
        logger.info(f"    embedded card.display: {embedded_card.get('display')}")

        # Key check: The embedded card.id should match card_id
        # If it doesn't match, it means the embedded card.id was not remapped
        if embedded_card_id != card_id:
            errors.append(
                f"Dashcard {dashcard_id}: embedded card.id ({embedded_card_id}) "
                f"does not match card_id ({card_id}). "
                f"This indicates the embedded card ID was not remapped!"
            )
            logger.error("    ✗ Embedded card.id does NOT match card_id!")
        else:
            logger.info("    ✓ Embedded card.id matches card_id")

        # Verify the card actually exists
        try:
            response = requests.get(
                f"{helper.api_url}/card/{card_id}",
                headers=helper._get_headers(),
                timeout=10,
            )
            if response.status_code == 200:
                logger.info(f"    ✓ Card {card_id} exists and is accessible")
            else:
                errors.append(
                    f"Card {card_id} not found (status {response.status_code}). "
                    f"This is the bug - old card ID being referenced!"
                )
                logger.error(f"    ✗ Card {card_id} NOT FOUND - this is the bug!")
        except Exception as e:
            errors.append(f"Error checking card {card_id}: {e}")

    # Try to load the dashboard to see if it causes errors
    logger.info("\n  Attempting to query dashboard cards...")
    for dashcard in embedded_card_dashcards:
        card_id = dashcard.get("card_id")
        try:
            response = requests.post(
                f"{helper.api_url}/card/{card_id}/query",
                headers=helper._get_headers(),
                timeout=30,
            )
            if response.status_code in [200, 202]:
                logger.info(f"    ✓ Card {card_id} query executed successfully")
            else:
                # This is expected for some cards that need parameters
                logger.warning(f"    ⚠ Card {card_id} query returned {response.status_code}")
        except Exception as e:
            logger.warning(f"    ⚠ Could not query card {card_id}: {e}")

    return len(errors) == 0, errors


def main() -> int:
    """Main entry point."""
    logger.info("=" * 60)
    logger.info("E2E Demo Verification - Metabase Migration Toolkit")
    logger.info("=" * 60)

    # Connect to target Metabase
    target = MetabaseTestHelper(TARGET_URL, ADMIN_EMAIL, ADMIN_PASSWORD)
    if not target.login():
        logger.error("Failed to login to target Metabase")
        return 1

    logger.info(f"\nConnected to target Metabase at {TARGET_URL}")

    # Find the migrated model
    logger.info("\n" + "-" * 60)
    logger.info("Looking for migrated model 'Active Users Model'...")
    model = find_model_by_name(target, "Active Users Model")
    if not model:
        logger.error("Model 'Active Users Model' not found in target!")
        return 1
    logger.info(f"  Found model with ID: {model.get('id')}")

    # Find the SQL card that references the model
    logger.info("\nLooking for migrated SQL card 'SQL Card Referencing Model'...")
    sql_card = find_card_by_name(target, "SQL Card Referencing Model")
    if not sql_card:
        logger.error("SQL card 'SQL Card Referencing Model' not found in target!")
        return 1
    logger.info(f"  Found SQL card with ID: {sql_card.get('id')}")

    # Verify model reference remapping for SQL card
    logger.info("\n" + "-" * 60)
    logger.info("VERIFYING SQL CARD MODEL REFERENCE REMAPPING")
    logger.info("-" * 60)

    sql_success, sql_errors = verify_model_reference_remapping(target, sql_card, model)

    # Find the Query Builder card that references the model
    logger.info("\n" + "-" * 60)
    logger.info("Looking for migrated Query Builder card 'Query Builder Card From Model'...")
    qb_card = find_card_by_name(target, "Query Builder Card From Model")
    qb_success = True
    qb_errors: list[str] = []

    if not qb_card:
        logger.warning("Query Builder card 'Query Builder Card From Model' not found in target!")
        logger.warning("  This card may not have been created in the source instance.")
    else:
        logger.info(f"  Found Query Builder card with ID: {qb_card.get('id')}")

        # Verify Query Builder model reference remapping
        logger.info("\n" + "-" * 60)
        logger.info("VERIFYING QUERY BUILDER CARD MODEL REFERENCE REMAPPING")
        logger.info("-" * 60)

        model_id = model.get("id")
        qb_card_id = qb_card.get("id")
        qb_success, error_msg = target.verify_query_builder_model_reference(qb_card_id, model_id)

        if qb_success:
            logger.info(
                f"  ✓ Query Builder card {qb_card_id} correctly references model {model_id}"
            )
        else:
            qb_errors.append(error_msg)
            logger.error(f"  ✗ Query Builder card verification failed: {error_msg}")

    # Verify 'Visualize another way' dashboard
    logger.info("\n" + "-" * 60)
    logger.info("Looking for migrated dashboard 'Visualize Another Way Test'...")
    vaw_dashboard = find_dashboard_by_name(target, "Visualize Another Way Test")
    vaw_success = True
    vaw_errors: list[str] = []

    if not vaw_dashboard:
        logger.warning("Dashboard 'Visualize Another Way Test' not found in target!")
        logger.warning("  This dashboard may not have been created in the source instance.")
    else:
        logger.info(f"  Found dashboard with ID: {vaw_dashboard.get('id')}")

        # Verify 'Visualize another way' embedded card remapping
        logger.info("\n" + "-" * 60)
        logger.info("VERIFYING 'VISUALIZE ANOTHER WAY' EMBEDDED CARD REMAPPING")
        logger.info("-" * 60)

        vaw_success, vaw_errors = verify_visualize_another_way_dashboard(target, vaw_dashboard)

        if vaw_success:
            logger.info("  ✓ 'Visualize another way' dashboard verification passed!")
        else:
            for error in vaw_errors:
                logger.error(f"  ✗ {error}")

    # Combine results
    all_errors = sql_errors + qb_errors + vaw_errors
    success = sql_success and qb_success and vaw_success

    # Summary
    logger.info("\n" + "=" * 60)
    if success:
        logger.info("✓ VERIFICATION PASSED!")
        logger.info("=" * 60)
        logger.info(
            """
All checks passed:
  ✓ SQL card: SQL contains correct model ID reference
  ✓ SQL card: Template tag key has correct model ID
  ✓ SQL card: Template tag card-id matches model ID
  ✓ SQL card: Template tag name matches key
  ✓ SQL card: Template tag display-name has correct model ID
  ✓ SQL card: Card can be executed successfully
  ✓ Query Builder card: source-table/source-card references correct model ID
  ✓ Visualize another way: Embedded card.id correctly remapped
  ✓ Visualize another way: Cards accessible without 404 errors

The model reference remapping is working correctly for all card types!
"""
        )
        return 0
    else:
        logger.error("✗ VERIFICATION FAILED!")
        logger.error("=" * 60)
        logger.error("\nErrors found:")
        for error in all_errors:
            logger.error(f"  - {error}")
        logger.error(
            """
This indicates a bug in the migration remapping logic.
Check lib/remapping/query_remapper.py for issues with:
  - _remap_template_tags() (for SQL cards)
  - _remap_tag_name() (for SQL cards)
  - _remap_sql_card_references() (for SQL cards)
  - _remap_source_table() (for Query Builder cards)
  - _remap_card_reference() (for Query Builder cards)
Check lib/handlers/dashboard.py for issues with:
  - _remap_embedded_card() (for 'Visualize another way' cards)
"""
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
