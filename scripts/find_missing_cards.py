#!/usr/bin/env python3
"""
Script to find the collection IDs for missing cards.
"""

from lib.client import MetabaseClient
import os
import sys
from dotenv import load_dotenv

def main():
    # Load environment variables
    load_dotenv()

    # Get credentials
    source_url = "https://reporting.support.ds.finverity.com/"
    username = "m.peshkov@finverity.com"
    password = os.getenv("MB_SOURCE_PASSWORD")

    if not password:
        print("ERROR: MB_SOURCE_PASSWORD not found in .env file")
        sys.exit(1)

    print(f"Connecting to {source_url}")
    print(f"Username: {username}")
    print("Using password from .env file...")
    
    # Create client
    client = MetabaseClient(source_url, username=username, password=password)
    
    # Missing card IDs
    missing_cards = [82, 114, 121, 134]
    
    print("\n" + "="*80)
    print("FINDING MISSING CARDS")
    print("="*80 + "\n")
    
    collections_to_export = set()
    
    for card_id in missing_cards:
        try:
            print(f"Fetching card {card_id}...")
            card = client.get_card(card_id)
            
            collection = card.get('collection')
            collection_id = collection.get('id') if collection else None
            collection_name = collection.get('name') if collection else 'Root Collection'
            
            print(f"  ✓ Card {card_id}: '{card.get('name')}'")
            print(f"    Collection ID: {collection_id}")
            print(f"    Collection Name: {collection_name}")
            print(f"    Database ID: {card.get('database_id')}")
            print()
            
            if collection_id:
                collections_to_export.add(collection_id)
                
        except Exception as e:
            print(f"  ✗ Card {card_id}: ERROR - {e}")
            print()
    
    print("="*80)
    print("SUMMARY")
    print("="*80)
    print(f"\nYou need to export these additional collections: {sorted(collections_to_export)}")
    print(f"\nRe-run export with:")
    print(f"  --root-collections \"24,{','.join(map(str, sorted(collections_to_export)))}\"")
    print()

if __name__ == "__main__":
    main()

