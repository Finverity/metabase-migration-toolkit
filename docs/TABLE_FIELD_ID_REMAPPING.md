# Table & Field ID Remapping Guide

## Overview

The Metabase Migration Toolkit automatically remaps table IDs and field IDs during import,
ensuring cards reference the correct tables and fields in the target instance.
This is a critical feature when migrating between instances where table and field IDs differ.

## Why Table & Field ID Remapping is Necessary

### The Problem

In Metabase, each table and field has an **instance-specific ID**. These IDs are:

- Assigned sequentially when tables/fields are created
- Different across instances (even for the same table name)
- Used internally in card queries and filters

When you have the same table name in different databases (e.g., "companies" in both `company_service`
and `deal_service`), the table IDs will be different:

```text
Source Instance:
- company_service (DB ID: 3)
  - companies table (ID: 27)
- deal_service (DB ID: 4)
  - companies table (ID: 35)

Target Instance:
- company_service (DB ID: 4)
  - companies table (ID: 42)
- deal_service (DB ID: 3)
  - companies table (ID: 51)
```

### Without Remapping

If you only remap database IDs but not table IDs:

- Card from source DB 3 (company_service) gets remapped to target DB 4 ✓
- BUT the card still references table ID 27 ✗
- Metabase looks for table 27 in target DB 4
- Table 27 doesn't exist in target DB 4 (it's table 42)
- Card breaks or shows data from wrong table

### With Remapping

The toolkit remaps both database IDs AND table IDs:

- Card database_id: 3 → 4 ✓
- Card table_id: 27 → 42 ✓
- Card now correctly references the "companies" table in company_service

## How It Works

### Phase 1: Export (Capture Metadata)

During export, the toolkit captures:

- Table metadata: ID, name, database ID
- Field metadata: ID, name, table ID, type

This metadata is stored in `manifest.json`:

```json
{
  "database_metadata": {
    "3": {
      "tables": [
        {
          "id": 27,
          "name": "companies",
          "fields": [
            {"id": 201, "name": "company_type"},
            {"id": 204, "name": "kyc_status"}
          ]
        }
      ]
    }
  }
}
```

### Phase 2: Import (Build Mappings)

During import, the toolkit:

1. Loads source metadata from manifest.json
2. Fetches target instance metadata via API
3. Builds mappings by matching table/field names:
   - Source table "companies" (ID: 27) → Target table "companies" (ID: 42)
   - Source field "company_type" (ID: 201) → Target field "company_type" (ID: 301)

### Phase 3: Remap (Update Card Queries)

For each card, the toolkit remaps:

- `card.database_id` - Database ID
- `card.table_id` - Table ID
- `card.dataset_query.database` - Query database ID
- `card.dataset_query.query.source-table` - Query table ID
- Field IDs in filter expressions

## What Gets Remapped

### Card Properties

```python
# Before import
card = {
    "database_id": 3,
    "table_id": 27,
    "dataset_query": {
        "database": 3,
        "query": {
            "source-table": 27,
            "filter": ["=", ["field", 201, None], "value"]
        }
    }
}

# After import
card = {
    "database_id": 4,      # 3 → 4 (database remapping)
    "table_id": 42,        # 27 → 42 (table remapping)
    "dataset_query": {
        "database": 4,     # 3 → 4 (database remapping)
        "query": {
            "source-table": 42,  # 27 → 42 (table remapping)
            "filter": ["=", ["field", 301, None], "value"]  # 201 → 301 (field remapping)
        }
    }
}
```

### Filter Expressions

Field IDs in filter expressions are recursively remapped:

```python
# Before
["and",
  ["=", ["field", 201, None], "Active"],
  [">", ["field", 204, None], 100]
]

# After
["and",
  ["=", ["field", 301, None], "Active"],
  [">", ["field", 304, None], 100]
]
```

## Usage

### Export

The export automatically captures table and field metadata:

```bash
metabase-export \
    --export-dir "./metabase_export" \
    --include-dashboards
```

The manifest.json will include `database_metadata` with table and field information.

### Import

The import automatically builds mappings and remaps IDs:

```bash
metabase-import \
    --export-dir "./metabase_export" \
    --db-map "./db_map.json"
```

No additional configuration needed - remapping happens automatically!

## Troubleshooting

### Cards Still Reference Wrong Tables

**Symptom**: After import, cards show data from wrong table

**Causes**:

1. Export doesn't have `database_metadata` (old export)
2. Table names don't match between source and target
3. Database mapping is incorrect

**Solution**:

1. Re-export from source (new export will have metadata)
2. Verify table names match in both instances
3. Check db_map.json is correct

### Field IDs Not Remapped

**Symptom**: Filters in cards are broken after import

**Causes**:

1. Field names don't match between source and target
2. Fields were deleted/renamed in target

**Solution**:

1. Verify field names match in both instances
2. Recreate missing fields in target
3. Re-import

## Implementation Details

### Key Files

- `export_metabase.py` - Captures table/field metadata during export
- `import_metabase.py` - Builds mappings and remaps IDs during import
- `lib/client.py` - Fetches metadata from Metabase API
- `tests/test_import.py` - Tests for remapping functionality

### Mapping Storage

Mappings are stored in memory during import:

```python
self._table_map: dict[tuple[int, int], int] = {}  # (source_db_id, source_table_id) -> target_table_id
self._field_map: dict[tuple[int, int], int] = {}  # (source_db_id, source_field_id) -> target_field_id
```
