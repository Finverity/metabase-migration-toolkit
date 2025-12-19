# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Metabase Migration Toolkit** is a Python CLI tool for exporting and importing Metabase content (collections, questions/cards, models, dashboards) between instances. It handles complex remapping of database IDs, table IDs, field IDs, and card references to ensure content works correctly when migrated.

Three CLI entry points:
- `metabase-export` - Export from source Metabase
- `metabase-import` - Import to target Metabase
- `metabase-sync` - Combined export and import

Supports Metabase v56 (MBQL 4, default) and v57 (MBQL 5 with stages).

## Commands

### Development
```bash
make install-dev      # Install with dev dependencies and pre-commit hooks
make test             # Run all tests
make test-cov         # Tests with coverage (HTML in htmlcov/, 80% threshold)
make test-unit        # Unit tests only (skip integration)
make lint             # Run ruff and black checks
make format           # Format with black and ruff
make type-check       # Run mypy
make quality          # All quality checks (lint, type-check, security)
make ci               # Full CI: lint, type-check, test-cov
```

### Run Single Test
```bash
python3 -m pytest tests/test_card_handler.py::test_name -v
python3 -m pytest tests/ -k "pattern" -v
```

### E2E Demo (v57)
```bash
make demo-up          # Start v57 Metabase containers
make demo-setup       # Start + create test data
make demo-migrate     # Export then import
make demo-verify      # Verify remapping worked
make demo             # Full E2E: setup, migrate, verify
make demo-down        # Stop containers
```

### Integration Tests (Docker)
```bash
make docker-up                 # Start services
make test-integration-only     # Run integration tests
make docker-down               # Stop services
```

## Architecture

### Entry Points
- `export_metabase.py`, `import_metabase.py`, `sync_metabase.py` - Thin CLI wrappers around services

### Core (`lib/`)

**config.py** - `ExportConfig`, `ImportConfig`, `SyncConfig` Pydantic models; `get_*_args()` functions for CLI parsing; env var support via python-dotenv

**client.py** - `MetabaseClient` HTTP wrapper with tenacity retry logic

**models_core.py** - `Collection`, `Card`, `Dashboard`, `Manifest` Pydantic models

**version.py**, **constants.py** - `MetabaseVersion` enum (V56, V57), `VersionAdapter` for API differences

**errors.py** - `MetabaseAPIError` and custom exceptions

### Services (`lib/services/`)

**ExportService** - Traverses collection tree, fetches cards/dashboards, captures table/field metadata, writes manifest

**ImportService** - Reads manifest, creates content on target, applies ID remapping, handles conflicts (skip/overwrite/rename), supports dry-run

### Handlers (`lib/handlers/`)
- `CollectionHandler` - Collection hierarchy
- `CardHandler` - Cards/questions/models with remapping
- `DashboardHandler` - Dashboards, dashboard cards, tabs, and embedded cards
- `PermissionsHandler` - Permission groups and access rules

All extend `BaseHandler` with common import context.

**DashboardHandler specifics:**
- Creates dashboard tabs via PUT after initial dashboard creation (Metabase API limitation)
- Remaps `dashboard_tab_id` on dashcards using source→target tab ID mapping
- Handles "Visualize another way" embedded `card` objects with ID remapping

### Remapping (`lib/remapping/`)

**IDMapper** - Builds source→target ID mappings for databases, tables, fields, cards by name matching

**QueryRemapper** - Rewrites card queries with new IDs:
- Native SQL queries: `{{#123-model}}` references
- Structured MBQL: `source-table`, field refs, filters
- Handles v56 vs v57 format differences

### Utils (`lib/utils/`)
- `logging.py` - Structured logging setup
- `file_io.py` - JSON read/write with checksums
- `payload.py` - Clean payloads for API create/update
- `sanitization.py` - Mask sensitive data

## Key Concepts

### ID Remapping Flow
1. **Export**: Captures metadata (table names, field names by database)
2. **Import**: Builds mappings by name matching, rewrites all card queries

Remapping handles:
- Database IDs, table IDs, field IDs
- Card references (`card__123` format in MBQL, `{{#123-name}}` in SQL)
- Dashboard tab IDs (`dashboard_tab_id` on dashcards)
- Embedded card IDs ("Visualize another way" feature)

### Version Differences
- **v56**: MBQL 4 with `:type` field, `source-table: "card__123"`, `filter` (singular)
- **v57**: MBQL 5 with `:lib/type`, `:stages` array, `source-card: 123` (integer), `filters` (plural)

### Conflict Strategies
- `skip` - Don't overwrite existing items (default)
- `overwrite` - Replace existing items
- `rename` - Create with modified name

## Testing

Tests in `tests/`:
- `test_card_handler.py` - Card creation, remapping
- `test_native_query_remapping.py` - SQL query remapping
- `test_dashboard_handler.py` - Dashboard handling
- `test_collection_handler.py` - Collection hierarchy
- `test_config.py` - CLI argument parsing
- `test_sync.py` - Full export+import flows

Integration tests in `tests/integration/` require Docker.

Markers: `@pytest.mark.integration`, `@pytest.mark.slow`

## Code Standards

- **Black**: 100 char line length
- **Ruff**: Linting, import sorting (isort)
- **MyPy**: Strict type checking (`disallow_untyped_defs`)
- Coverage threshold: 80%

Pre-commit hooks enforce all standards.

## Python Requirements

- Python 3.10+
- Key deps: requests, tenacity, pydantic, python-dotenv
- Dev: pytest, black, ruff, mypy, pre-commit
