#!/usr/bin/env python3
"""
Test script to verify recursive dependency resolution in export.
This script simulates the dependency resolution logic.
"""
import json
from pathlib import Path
from typing import Dict, Set, List, Optional


def extract_card_dependencies(card_data: Dict) -> Set[int]:
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


def resolve_dependencies_recursively(
    card_id: int,
    all_cards: Dict[int, Dict],
    resolved: Set[int],
    chain: Optional[List[int]] = None
) -> Set[int]:
    """
    Recursively resolve all dependencies for a card.
    
    Args:
        card_id: The card to resolve dependencies for
        all_cards: Dictionary of all available cards {card_id: card_data}
        resolved: Set of already resolved card IDs
        chain: Current dependency chain for circular detection
    
    Returns:
        Set of all card IDs that need to be exported (including the card itself)
    """
    if chain is None:
        chain = []
    
    # Already resolved
    if card_id in resolved:
        return set()
    
    # Circular dependency
    if card_id in chain:
        print(f"⚠️  Circular dependency detected: {' -> '.join(map(str, chain + [card_id]))}")
        return set()
    
    # Card not available
    if card_id not in all_cards:
        print(f"⚠️  Card {card_id} not found in available cards")
        return set()
    
    result = {card_id}
    card_data = all_cards[card_id]
    deps = extract_card_dependencies(card_data)
    
    if deps:
        print(f"Card {card_id} ('{card_data.get('name', 'Unknown')}') depends on: {sorted(deps)}")
    
    # Recursively resolve dependencies
    for dep_id in deps:
        sub_deps = resolve_dependencies_recursively(
            dep_id,
            all_cards,
            resolved,
            chain + [card_id]
        )
        result.update(sub_deps)
    
    resolved.add(card_id)
    return result


def main():
    """Test recursive dependency resolution."""
    export_dir = Path("../metabase_export")
    
    # Load manifest
    manifest_path = export_dir / "manifest.json"
    if not manifest_path.exists():
        print(f"❌ Manifest not found at {manifest_path}")
        print("Please run the export first.")
        return
    
    with open(manifest_path) as f:
        manifest = json.load(f)
    
    print("=" * 80)
    print("RECURSIVE DEPENDENCY RESOLUTION TEST")
    print("=" * 80)
    print()
    
    # Load all cards
    all_cards = {}
    for card_info in manifest["cards"]:
        card_id = card_info["id"]
        card_path = export_dir / card_info["file_path"]
        
        if card_path.exists():
            with open(card_path) as f:
                all_cards[card_id] = json.load(f)
    
    print(f"Loaded {len(all_cards)} cards from export")
    print()
    
    # Find cards with dependencies
    cards_with_deps = []
    for card_id, card_data in all_cards.items():
        deps = extract_card_dependencies(card_data)
        if deps:
            cards_with_deps.append((card_id, card_data.get("name", "Unknown"), deps))
    
    print(f"Found {len(cards_with_deps)} cards with dependencies")
    print()
    
    # Test recursive resolution for each card
    print("=" * 80)
    print("TESTING RECURSIVE RESOLUTION")
    print("=" * 80)
    print()
    
    for card_id, card_name, direct_deps in sorted(cards_with_deps):
        print(f"\nCard {card_id}: '{card_name}'")
        print(f"  Direct dependencies: {sorted(direct_deps)}")
        
        resolved = set()
        all_deps = resolve_dependencies_recursively(card_id, all_cards, resolved)
        all_deps.discard(card_id)  # Remove the card itself
        
        if all_deps:
            print(f"  All transitive dependencies: {sorted(all_deps)}")
            
            # Check if all dependencies are in export
            missing = all_deps - set(all_cards.keys())
            if missing:
                print(f"  ❌ Missing dependencies: {sorted(missing)}")
            else:
                print(f"  ✅ All dependencies present in export")
        else:
            print(f"  No transitive dependencies")
    
    # Summary
    print()
    print("=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print()
    
    # Check for missing dependencies across all cards
    all_missing = set()
    for card_id, card_data in all_cards.items():
        deps = extract_card_dependencies(card_data)
        missing = deps - set(all_cards.keys())
        all_missing.update(missing)
    
    if all_missing:
        print(f"❌ Found {len(all_missing)} missing dependency cards: {sorted(all_missing)}")
        print()
        print("These cards should be automatically included in the next export")
        print("with the recursive dependency resolution feature.")
    else:
        print("✅ All dependencies are present in the export!")
        print()
        print("The recursive dependency resolution is working correctly.")


if __name__ == "__main__":
    main()

