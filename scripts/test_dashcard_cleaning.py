#!/usr/bin/env python3
"""
Test script to verify dashcard cleaning logic removes problematic fields.
"""

import json
from pathlib import Path


def clean_dashcard_for_import(dashcard, card_map):
    """
    Simulates the dashcard cleaning logic from import_metabase.py
    """
    clean_dashcard = {}
    
    # Fields to explicitly exclude
    excluded_fields = {
        "id",
        "dashboard_id",
        "created_at",
        "updated_at",
        "entity_id",
        "card",
        "action_id",
        "collection_authority_level",
        "dashboard_tab_id"
    }
    
    # Copy positioning and size fields
    for field in ["col", "row", "size_x", "size_y"]:
        if field in dashcard and dashcard[field] is not None:
            clean_dashcard[field] = dashcard[field]
    
    # Copy visualization_settings
    if "visualization_settings" in dashcard:
        clean_dashcard["visualization_settings"] = dashcard["visualization_settings"]
    
    # Copy parameter_mappings (with card_id remapping)
    if "parameter_mappings" in dashcard and dashcard["parameter_mappings"]:
        clean_dashcard["parameter_mappings"] = []
        for param_mapping in dashcard["parameter_mappings"]:
            clean_param = param_mapping.copy()
            if "card_id" in clean_param:
                source_param_card_id = clean_param["card_id"]
                if source_param_card_id in card_map:
                    clean_param["card_id"] = card_map[source_param_card_id]
            clean_dashcard["parameter_mappings"].append(clean_param)
    
    # Copy series (with card_id remapping)
    if "series" in dashcard and dashcard["series"]:
        clean_dashcard["series"] = []
        for series_card in dashcard["series"]:
            if isinstance(series_card, dict) and "id" in series_card:
                series_card_id = series_card["id"]
                if series_card_id in card_map:
                    clean_dashcard["series"].append({"id": card_map[series_card_id]})
    
    # Remap card_id
    source_card_id = dashcard.get("card_id")
    if source_card_id:
        if source_card_id in card_map:
            clean_dashcard["card_id"] = card_map[source_card_id]
        else:
            return None  # Skip if card not mapped
    
    # Final safety check
    for excluded_field in excluded_fields:
        if excluded_field in clean_dashcard:
            del clean_dashcard[excluded_field]
    
    return clean_dashcard


def test_dashboard_cleaning():
    """Test the dashcard cleaning with the actual exported dashboard"""
    
    # Load the dashboard file
    dashboard_file = Path(
        "../metabase_export/Standard-Reports/Customer-Reports/dashboards/dash_17_Customer-Dashboard.json")
    
    if not dashboard_file.exists():
        print(f"❌ Dashboard file not found: {dashboard_file}")
        return False
    
    with open(dashboard_file, 'r') as f:
        dashboard_data = json.load(f)
    
    # Create a mock card mapping (source_id -> target_id)
    card_map = {
        300: 1001,
        307: 1002,
        295: 1003,
        288: 1004,
        296: 1005,
        316: 1006,
        314: 1007,
        315: 1008,
        318: 1009,
        317: 1010,
        319: 1011,
        320: 1012,
        321: 1013,
        322: 1014,
        323: 1015,
        324: 1016,
        325: 1017,
        334: 1018,
        335: 1019,
    }
    
    dashcards = dashboard_data.get("dashcards", [])
    print(f"📊 Testing {len(dashcards)} dashcards from dashboard '{dashboard_data.get('name')}'")
    print()
    
    problematic_fields = ["id", "dashboard_id", "created_at", "updated_at", "entity_id", "card"]
    issues_found = 0
    cleaned_count = 0
    
    for idx, dashcard in enumerate(dashcards):
        original_keys = set(dashcard.keys())
        cleaned = clean_dashcard_for_import(dashcard, card_map)
        
        if cleaned is None:
            print(f"⚠️  Dashcard {idx}: Skipped (unmapped card_id)")
            continue
        
        cleaned_count += 1
        cleaned_keys = set(cleaned.keys())
        
        # Check for problematic fields
        has_issues = False
        for field in problematic_fields:
            if field in cleaned_keys:
                print(f"❌ Dashcard {idx}: Still contains '{field}' field!")
                has_issues = True
                issues_found += 1
        
        if not has_issues:
            removed_fields = original_keys - cleaned_keys
            print(f"✅ Dashcard {idx}: Clean (removed {len(removed_fields)} fields: {', '.join(sorted(removed_fields))})")
            print(f"   Kept fields: {', '.join(sorted(cleaned_keys))}")
    
    print()
    print("=" * 80)
    print(f"📈 Summary:")
    print(f"   Total dashcards: {len(dashcards)}")
    print(f"   Cleaned successfully: {cleaned_count}")
    print(f"   Issues found: {issues_found}")
    
    if issues_found == 0:
        print()
        print("✅ SUCCESS: All dashcards are properly cleaned!")
        return True
    else:
        print()
        print("❌ FAILURE: Some dashcards still contain problematic fields!")
        return False


if __name__ == "__main__":
    success = test_dashboard_cleaning()
    exit(0 if success else 1)

