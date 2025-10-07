#!/usr/bin/env python3
"""
Quick test script to verify database fetching works correctly.
"""
import os
from dotenv import load_dotenv
from lib.client import MetabaseClient
from lib.utils import setup_logging

# Load environment variables
load_dotenv()

# Setup logging
logger = setup_logging("DEBUG")

# Create client
client = MetabaseClient(
    base_url=os.getenv("MB_TARGET_URL"),
    username=os.getenv("MB_TARGET_USERNAME"),
    password=os.getenv("MB_TARGET_PASSWORD"),
)

print("=" * 80)
print("Testing database fetch...")
print("=" * 80)

try:
    databases = client.get_databases()
    print(f"\n✅ Successfully fetched {len(databases)} database(s):")
    for db in databases:
        print(f"  - ID: {db['id']}, Name: '{db['name']}'")
    print("\n" + "=" * 80)
    print("Test PASSED!")
    print("=" * 80)
except Exception as e:
    print(f"\n❌ Test FAILED: {e}")
    import traceback
    traceback.print_exc()
    print("=" * 80)

