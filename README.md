# Metabase Migration Toolkit

[![Tests](https://github.com/Finverity/metabase-migration-toolkit/actions/workflows/tests.yml/badge.svg)](https://github.com/Finverity/metabase-migration-toolkit/actions/workflows/tests.yml)
[![codecov](https://codecov.io/gh/Finverity/metabase-migration-toolkit/branch/main/graph/badge.svg?token=YOUR_CODECOV_TOKEN)](https://codecov.io/gh/Finverity/metabase-migration-toolkit)
[![Coverage Status](https://img.shields.io/codecov/c/github/Finverity/metabase-migration-toolkit/main.svg)](https://codecov.io/gh/Finverity/metabase-migration-toolkit)
[![PyPI version](https://badge.fury.io/py/metabase-migration-toolkit.svg)](https://badge.fury.io/py/metabase-migration-toolkit)
[![Python Versions](https://img.shields.io/pypi/pyversions/metabase-migration-toolkit.svg)](https://pypi.org/project/metabase-migration-toolkit/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

This toolkit provides three command-line tools designed for exporting and importing Metabase content
(collections, questions, models, and dashboards) between instances:

- `metabase-export` - Export content from a source Metabase instance
- `metabase-import` - Import content to a target Metabase instance
- `metabase-sync` - Combined export and import in a single operation

It's built to be robust, handling API rate limits, pagination, and providing clear logging and error handling for
production use.

## Features

- **Recursive Export:** Traverses the entire collection tree, preserving hierarchy.
- **Selective Content:** Choose to include dashboards and archived items.
- **Model Support:** Fully supports Metabase models (cards with `dataset=true`), preserving their model status during migration.
- **Permissions Migration:** Export and import permission groups and access control settings.
- **Database Remapping:** Intelligently remaps questions and cards to new database IDs on the target instance.
- **Table & Field ID Remapping:** Automatically remaps table IDs and field IDs in card queries.
  - Captures table and field metadata during export
  - Builds intelligent mappings between source and target instances
  - Remaps table IDs in card queries and filters
  - Remaps field IDs in filter expressions
- **Dashboard Tab Support:** Fully migrates dashboard tabs with proper ID remapping.
  - Creates tabs on target dashboard after initial creation
  - Remaps `dashboard_tab_id` on dashcards to maintain card-tab assignments
- **Embedded Card Support:** Handles "Visualize another way" dashcards with embedded card objects.
- **Conflict Resolution:** Strategies for handling items that already exist on the target (`skip`, `overwrite`, `rename`).
- **Idempotent Import:** Re-running an import with `skip` or `overwrite` produces a consistent state.
- **Dry Run Mode:** Preview all import actions without making any changes to the target instance.
- **Secure:** Handles credentials via environment variables or CLI flags and never logs or exports sensitive information.
- **Reliable:** Implements exponential backoff and retries for network requests.

## Supported Metabase Versions

The toolkit supports the following Metabase versions:

| Version | Metabase Release | Query Format        | Status                   |
|---------|------------------|---------------------|--------------------------|
| `v56`   | v0.56.x          | MBQL 4              | Default, fully supported |
| `v57`   | v0.57.x          | MBQL 5 (stages)     | Fully supported          |
| `v58`   | v0.58.x          | MBQL 5 (stages)     | Fully supported          |

### Key Differences Between Versions

**v56 (MBQL 4):**

- Legacy query format with `:type` field
- Native queries use `:native.query` structure
- Card references: `source-table: "card__123"`

**v57 (MBQL 5):**

- Modern query format with `:lib/type` field
- Uses `:stages` array structure for queries
- Card references: `source-card: 123` (integer)
- Template tags use `#` prefix: `#123-model-name`

**v58 (MBQL 5):**

- Same query format as v57 (`:stages` array)
- Card fields `dashboard_tab_id`, `entity_id`, `parameter_mappings` are now nullable
- New MBQL clauses: `measure` (aggregation reference) and `collate` (SQL collation)

### Version Compatibility

**Important:** Source and target Metabase instances must be the same version. Cross-version migration (e.g., v56 to
v57) is not supported.

### Specifying Version

Use the `--metabase-version` flag or `MB_METABASE_VERSION` environment variable:

```bash
# Via CLI flag
metabase-export --metabase-version v58 ...
metabase-import --metabase-version v58 ...
metabase-sync --metabase-version v58 ...

# Via environment variable
export MB_METABASE_VERSION=v58
```

## Prerequisites

- Python 3.10+
- Access to source and target Metabase instances with appropriate permissions (API access, ideally admin).

## Installation

### Option 1: Install from PyPI (Recommended)

```bash
pip install metabase-migration-toolkit
```

After installation, the `metabase-export`, `metabase-import`, and `metabase-sync` commands will be available
globally in your environment.

### Option 2: Install from TestPyPI (for testing)

```bash
pip install --index-url https://test.pypi.org/simple/ \
            --extra-index-url https://pypi.org/simple/ \
            metabase-migration-toolkit
```

### Option 3: Install from Source

1. **Clone the repository:**

    ```bash
    git clone <your-repo-url>
    cd metabase-migration-toolkit
    ```

2. **Install the package:**

    ```bash
    pip install -e .
    ```

## Configuration

1. **Configure Environment Variables (Recommended):**
    Copy the example `.env` file and fill in your credentials. This is the most secure way to provide credentials.

    ```bash
    cp .env.example .env
    # Edit .env with your details
    ```

2. **Create a Database Mapping File:**
    Copy the example `db_map.example.json` and configure it to map your source database IDs/names to the target
    database IDs.

    ```bash
    cp db_map.example.json db_map.json
    # Edit db_map.json with your mappings
    ```

    If you need richer starting points, see also `samples/db_map/db_map.single_db.json` and
    `samples/db_map/db_map.multi_db.json`.

    **This is the most critical step for a successful import.** You must map every source database ID used by an
    exported card to a valid target database ID.

    Only `by_id` and `by_name` are read from `db_map.json`. The importer looks up `by_id` first (matching
    against the source database ID as a string key) and falls back to `by_name` if no ID match is found.
    Table and field IDs are remapped automatically by the importer using the Metabase metadata API, and
    collection IDs are remapped as collections are created during the import — so you do not need to (and
    cannot) configure `table_map`/`field_map`/`collection_map` in this file.

    **How to find database IDs:**

    - In the Metabase UI, open *Admin settings → Databases* and click a database — the URL contains its ID
      (e.g., `/admin/databases/7` means database ID `7`).
    - Or query the API: `GET /api/database` returns every database with its `id` and `name` on each instance.
      Run it once against the source and once against the target, then map source `id` → target `id`.

    If JOINs fail after import with errors about missing table or field IDs, it almost always means a source
    database has no entry (by ID or by name) in `db_map.json` — the importer cannot derive table/field mappings
    for an unmapped database.

## Usage

### 1. Exporting from a Source Metabase

The `metabase-export` command connects to a source instance and exports its content into a local directory.

**Example using .env file (Recommended):**

```bash
# All credentials are read from .env file
metabase-export \
    --export-dir "./metabase_export" \
    --include-dashboards \
    --include-archived \
    --include-permissions \
    --log-level INFO \
    --root-collections "24"
```

**Example using CLI flags:**

```bash
metabase-export \
    --source-url "https://your-source-metabase.com/" \
    --source-username "user@example.com" \
    --source-password "your_password" \
    --export-dir "./metabase_export" \
    --include-dashboards \
    --root-collections "123,456"
```

**Available options:**

- `--source-url` - Source Metabase URL (or use `MB_SOURCE_URL` in .env)
- `--source-username` - Username (or use `MB_SOURCE_USERNAME` in .env)
- `--source-password` - Password (or use `MB_SOURCE_PASSWORD` in .env)
- `--source-session` - Session token (or use `MB_SOURCE_SESSION_TOKEN` in .env)
- `--source-token` - Personal API token (or use `MB_SOURCE_PERSONAL_TOKEN` in .env)
- `--export-dir` - Directory to save exported files (required)
- `--include-dashboards` - Include dashboards in export
- `--include-archived` - Include archived items
- `--include-permissions` - Include permissions (groups and access control) in export
- `--root-collections` - Comma-separated collection IDs to export (optional)
- `--log-level` - Logging level: DEBUG, INFO, WARNING, ERROR

### 2. Importing to a Target Metabase

The `metabase-import` command reads the export package and recreates the content on a target instance.

**Example using .env file (Recommended):**

```bash
# All credentials are read from .env file
metabase-import \
    --export-dir "./metabase_export" \
    --db-map "./db_map.json" \
    --conflict skip \
    --apply-permissions \
    --log-level INFO
```

**Example using CLI flags:**

```bash
metabase-import \
    --target-url "https://your-target-metabase.com/" \
    --target-username "user@example.com" \
    --target-password "your_password" \
    --export-dir "./metabase_export" \
    --db-map "./db_map.json" \
    --conflict overwrite \
    --log-level INFO
```

**Available options:**

- `--target-url` - Target Metabase URL (or use `MB_TARGET_URL` in .env)
- `--target-username` - Username (or use `MB_TARGET_USERNAME` in .env)
- `--target-password` - Password (or use `MB_TARGET_PASSWORD` in .env)
- `--target-session` - Session token (or use `MB_TARGET_SESSION_TOKEN` in .env)
- `--target-token` - Personal API token (or use `MB_TARGET_PERSONAL_TOKEN` in .env)
- `--export-dir` - Directory with exported files (required)
- `--db-map` - Path to database mapping JSON file (required)
- `--conflict` - Conflict resolution: `skip`, `overwrite`, or `rename` (default: skip)
- `--dry-run` - Preview changes without applying them
- `--include-archived` - Include archived items in the import
- `--apply-permissions` - Apply permissions from the export (requires admin privileges)
- `--log-level` - Logging level: DEBUG, INFO, WARNING, ERROR

### 3. Syncing (Export + Import in One Operation)

The `metabase-sync` command combines export and import into a single operation, making it easy to synchronize
content between Metabase instances.

**Example using .env file (Recommended):**

```bash
# All credentials are read from .env file
metabase-sync \
    --export-dir "./metabase_export" \
    --db-map "./db_map.json" \
    --include-dashboards \
    --include-permissions \
    --apply-permissions \
    --conflict overwrite \
    --log-level INFO
```

**Example using CLI flags:**

```bash
metabase-sync \
    --source-url "https://source-metabase.example.com/" \
    --source-username "user@example.com" \
    --source-password "source_password" \
    --target-url "https://target-metabase.example.com/" \
    --target-username "user@example.com" \
    --target-password "target_password" \
    --export-dir "./metabase_export" \
    --db-map "./db_map.json" \
    --include-dashboards \
    --include-permissions \
    --apply-permissions \
    --conflict overwrite \
    --root-collections "24" \
    --log-level INFO
```

**Available options:**

*Source Instance:*

- `--source-url` - Source Metabase URL (or use `MB_SOURCE_URL` in .env)
- `--source-username` - Source username (or use `MB_SOURCE_USERNAME` in .env)
- `--source-password` - Source password (or use `MB_SOURCE_PASSWORD` in .env)
- `--source-session` - Source session token (or use `MB_SOURCE_SESSION_TOKEN` in .env)
- `--source-token` - Source personal API token (or use `MB_SOURCE_PERSONAL_TOKEN` in .env)

*Target Instance:*

- `--target-url` - Target Metabase URL (or use `MB_TARGET_URL` in .env)
- `--target-username` - Target username (or use `MB_TARGET_USERNAME` in .env)
- `--target-password` - Target password (or use `MB_TARGET_PASSWORD` in .env)
- `--target-session` - Target session token (or use `MB_TARGET_SESSION_TOKEN` in .env)
- `--target-token` - Target personal API token (or use `MB_TARGET_PERSONAL_TOKEN` in .env)

*Shared Options:*

- `--export-dir` - Directory to save/load exported files (required)
- `--db-map` - Path to database mapping JSON file (required)
- `--metabase-version` - Metabase version (or use `MB_METABASE_VERSION` in .env)
- `--log-level` - Logging level: DEBUG, INFO, WARNING, ERROR

*Export Options:*

- `--include-dashboards` - Include dashboards in the export
- `--include-archived` - Include archived items
- `--include-permissions` - Include permissions (groups and access control)
- `--root-collections` - Comma-separated list of root collection IDs to export

*Import Options:*

- `--conflict` - Conflict resolution: `skip`, `overwrite`, or `rename` (default: skip)
- `--dry-run` - Perform a dry run without making any changes
- `--apply-permissions` - Apply permissions from the export (requires admin privileges)

## Table & Field ID Remapping

The toolkit automatically remaps table IDs and field IDs during import, ensuring cards reference the correct
tables and fields in the target instance.

### Why This Matters

In Metabase, each table and field has an instance-specific ID. When you have the same table name in different
databases (e.g., "companies" in both `company_service` and `deal_service`), the table IDs will be different.
Without proper remapping:

- Cards would reference the wrong table
- Filters with field IDs would break
- Cards would appear to work but show data from the wrong source

### How It Works

1. **Export Phase**: The toolkit captures table and field metadata from the source instance
2. **Mapping Phase**: During import, it builds intelligent mappings between source and target IDs based on table/field names
3. **Remapping Phase**: All card queries are updated to use the correct target IDs

### Example

```text
Source Instance:
- Database: company_service (ID: 3)
  - Table: companies (ID: 27)
    - Field: company_type (ID: 201)

Target Instance:
- Database: company_service (ID: 4)
  - Table: companies (ID: 42)
    - Field: company_type (ID: 301)

After Import:
- Card database_id: 3 → 4 ✓
- Card table_id: 27 → 42 ✓
- Filter field_id: 201 → 301 ✓
```

For more details, see [Table ID Remapping Guide](TABLE_ID_REMAPPING_FIX.md).

## Permissions Migration

The toolkit supports exporting and importing permissions to solve the common "403 Forbidden" errors after migration.
See the [Permissions Migration Guide](docs/PERMISSIONS_MIGRATION.md) for detailed instructions.

**Quick example:**

```bash
# Export with permissions
metabase-export --export-dir "./export" --include-permissions

# Import with permissions
metabase-import --export-dir "./export" --db-map "./db_map.json" --apply-permissions
```

## Samples and Examples

The repository includes a `samples/` directory with ready-to-use templates:

- `db_map.example.json` – minimal `db_map.json` template at the project root (copy-and-edit starter)
- `samples/db_map/db_map.single_db.json` – minimal single-database mapping example
- `samples/db_map/db_map.multi_db.json` – example mapping for multiple databases
- `samples/flows/export_import_basic.sh` – basic end-to-end export/import flow using `.env`
- `samples/flows/export_import_multi_env.sh` – example promotion flow between environments
- `samples/cicd/github-actions-export-import.yml` – minimal GitHub Actions workflow showing export/import in CI

Use these as starting points and adapt them to your own environments and naming conventions.
