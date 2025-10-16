#!/usr/bin/env python3
"""
Test script to verify card dependency extraction and topological sorting.
"""
import json
from pathlib import Path


def extract_card_dependencies(card_data):
    """Extract card IDs that this card depends on."""
    dependencies = set()

    dataset_query = card_data.get("dataset_query", {})
    query = dataset_query.get("query", {})

    # Check source-table for card references
    source_table = query.get("source-table")
    if isinstance(source_table, str) and source_table.startswith("card__"):
        try:
            card_id = int(source_table.replace("card__", ""))
            dependencies.add(card_id)
        except ValueError:
            pass

    # Check joins for card references
    joins = query.get("joins", [])
    for join in joins:
        join_source_table = join.get("source-table")
        if isinstance(join_source_table, str) and join_source_table.startswith("card__"):
            try:
                card_id = int(join_source_table.replace("card__", ""))
                dependencies.add(card_id)
            except ValueError:
                pass

    return dependencies


def main():
    """Test dependency extraction on exported cards."""
    export_dir = Path("../metabase_export")

    # Load manifest
    manifest_path = export_dir / "manifest.json"
    with open(manifest_path) as f:
        manifest = json.load(f)

    print("=" * 80)
    print("CARD DEPENDENCY ANALYSIS")
    print("=" * 80)
    print()

    # Analyze each card
    cards_with_deps = []
    missing_deps = {}

    for card_info in manifest["cards"]:
        card_id = card_info["id"]
        card_name = card_info["name"]
        card_path = export_dir / card_info["file_path"]

        with open(card_path) as f:
            card_data = json.load(f)

        deps = extract_card_dependencies(card_data)

        if deps:
            cards_with_deps.append((card_id, card_name, deps))

            # Check for missing dependencies
            card_ids_in_export = {c["id"] for c in manifest["cards"]}
            missing = deps - card_ids_in_export
            if missing:
                missing_deps[card_id] = {"name": card_name, "missing": missing}

    # Print cards with dependencies
    print(f"Found {len(cards_with_deps)} cards with dependencies:")
    print()
    for card_id, card_name, deps in sorted(cards_with_deps):
        print(f"Card {card_id}: '{card_name}'")
        print(f"  Depends on: {sorted(deps)}")
        print()

    # Print missing dependencies
    if missing_deps:
        print("=" * 80)
        print("⚠️  WARNING: MISSING DEPENDENCIES DETECTED")
        print("=" * 80)
        print()
        for card_id, info in missing_deps.items():
            print(f"Card {card_id}: '{info['name']}'")
            print(f"  Missing dependencies: {sorted(info['missing'])}")
            print("  These cards are NOT in the export!")
            print()

        print("RECOMMENDATION:")
        print("Re-export with --include-archived flag to include all dependencies")
        print()
    else:
        print("✅ All dependencies are present in the export")
        print()

    # Print dependency graph
    print("=" * 80)
    print("DEPENDENCY GRAPH")
    print("=" * 80)
    print()

    # Build reverse dependency map (who depends on whom)
    reverse_deps = {}
    for card_id, card_name, deps in cards_with_deps:
        for dep_id in deps:
            if dep_id not in reverse_deps:
                reverse_deps[dep_id] = []
            reverse_deps[dep_id].append((card_id, card_name))

    # Print cards that are depended upon
    for dep_id in sorted(reverse_deps.keys()):
        # Find the card name
        dep_name = "MISSING"
        for card_info in manifest["cards"]:
            if card_info["id"] == dep_id:
                dep_name = card_info["name"]
                break

        print(f"Card {dep_id}: '{dep_name}'")
        print(f"  Required by {len(reverse_deps[dep_id])} card(s):")
        for card_id, card_name in sorted(reverse_deps[dep_id]):
            print(f"    - Card {card_id}: '{card_name}'")
        print()


if __name__ == "__main__":
    main()
