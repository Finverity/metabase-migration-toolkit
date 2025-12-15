# Quick Start Guide - Metabase Migration Toolkit

## Recent Updates (2025-10-22)

✅ **Metabase v57 Support**: Full support for Metabase v0.57.x with MBQL 5 query format (NEW!)
✅ **Table & Field ID Remapping**: Automatically remaps table and field IDs during import
✅ **Permissions Migration**: Export and import permissions to avoid 403 errors
✅ **Authentication Fixed**: Corrected `.env` file format
✅ **Dashboard Import Fixed**: Removed false error messages
✅ **Recursive Dependencies**: Automatic inclusion of all card dependencies

---

## Setup (5 minutes)

### 1. Install the Package

#### Option A: Install from PyPI (Recommended)

```bash
pip install metabase-migration-toolkit
```

#### Option B: Install from Source

```bash
git clone <your-repo-url>
cd metabase-migration-toolkit
pip install -e .
```

After installation, the `metabase-export` and `metabase-import` commands will be available globally.

### 2. Configure Environment

```bash
cp .env.example .env
# Edit .env with your credentials (NO QUOTES around passwords!)
```

**Important**: Do NOT use quotes around passwords in `.env`:

```bash
# ❌ WRONG
MB_SOURCE_PASSWORD=""

# ✅ CORRECT
MB_SOURCE_PASSWORD=
```

### 3. Configure Database Mapping

```bash
cp db_map.example.json db_map.json
# Edit db_map.json to map source DB IDs to target DB IDs
```

---

## Export (Simple)

### Basic Export

```bash
metabase-export \
    --export-dir "./metabase_export" \
    --include-dashboards \
    --include-permissions
```

This will:

- ✅ Export all collections, cards, and dashboards
- ✅ **Automatically include all card dependencies**
- ✅ **Export permissions to avoid 403 errors** (NEW!)
- ✅ Create a self-contained export package

### Export Specific Collections

```bash
metabase-export \
    --export-dir "./metabase_export" \
    --root-collections "24,13,26" \
    --include-dashboards \
    --include-archived
```

### What's New: Automatic Dependency Resolution

The export now **automatically includes all card dependencies**:

```text
Exporting Collection A:
  - Card 1 (no dependencies)
  - Card 2 (depends on Card 100)
    → Card 100 automatically exported to dependencies/
  - Card 3 (depends on Card 200)
    → Card 200 automatically exported to dependencies/
    → Card 200 depends on Card 300
      → Card 300 automatically exported to dependencies/
```

**Result**: Complete, self-contained export that imports without errors!

### What's New: Table & Field ID Remapping

The import now **automatically remaps table and field IDs**:

When you have the same table name in different databases (e.g., "companies" in both `company_service` and
`deal_service`), the toolkit ensures cards reference the correct table:

```text
Source Instance:
- company_service (DB ID: 3) → companies table (ID: 27)
- deal_service (DB ID: 4) → companies table (ID: 35)

Target Instance:
- company_service (DB ID: 4) → companies table (ID: 42)
- deal_service (DB ID: 3) → companies table (ID: 51)

After Import:
- Card from company_service: DB 3→4 ✓, Table 27→42 ✓
- Card from deal_service: DB 4→3 ✓, Table 35→51 ✓
```

**Result**: Cards correctly reference tables in the target instance, even when table IDs differ!

---

## Import (Simple)

### Basic Import

```bash
metabase-import \
    --export-dir "./metabase_export" \
    --db-map "./db_map.json" \
    --conflict skip \
    --apply-permissions
```

**Note**: Use `--apply-permissions` to avoid "403 Forbidden" errors after migration.

### Dry Run (Preview Changes)

```bash
metabase-import \
    --export-dir "./metabase_export" \
    --db-map "./db_map.json" \
    --dry-run
```

### Import with Overwrite

```bash
metabase-import \
    --export-dir "./metabase_export" \
    --db-map "./db_map.json" \
    --conflict overwrite
```

---

## Common Scenarios

### Scenario 1: Migrate Specific Collections

**Goal**: Move collections 24, 13, and 26 to a new Metabase instance

```bash
# 1. Export
metabase-export \
    --export-dir "./migration_2025" \
    --root-collections "24,13,26" \
    --include-dashboards \
    --include-archived

# 2. Import
metabase-import \
    --export-dir "./migration_2025" \
    --db-map "./db_map.json" \
    --conflict skip
```

### Scenario 2: Backup Everything

**Goal**: Complete backup of all Metabase content

```bash
# Export everything
metabase-export \
    --export-dir "./backup_$(date +%Y%m%d)" \
    --include-dashboards \
    --include-archived
```

### Scenario 3: Clone to Development Environment

**Goal**: Copy production content to dev environment

```bash
# 1. Export from production (using MB_SOURCE_* vars in .env)
metabase-export \
    --export-dir "./prod_export" \
    --include-dashboards

# 2. Import to dev (using MB_TARGET_* vars in .env)
metabase-import \
    --export-dir "./prod_export" \
    --db-map "./db_map_prod_to_dev.json" \
    --conflict overwrite
```

---

## Troubleshooting

### Issue: Authentication Failed

**Solution**: Check `.env` file - remove quotes around passwords

```bash
# ❌ WRONG
MB_TARGET_PASSWORD="-"

# ✅ CORRECT
MB_TARGET_PASSWORD=-
```

### Issue: "Card depends on missing cards"

**Solution**: This should no longer happen! The export now automatically includes dependencies.

If you still see this with an old export, re-export with the updated script:

```bash
metabase-export \
    --export-dir "./new_export" \
    --root-collections "24" \
    --include-dashboards
```

### Issue: "Dashcard still has 'id' field"

**Solution**: This is a false error that has been fixed. Update to the latest version of the package.

### Issue: Circular Dependency Warning

**Example**: `Circular dependency detected: 100 -> 200 -> 300 -> 100`

**Solution**: This is expected behavior. The script breaks the cycle and continues. Review your card structure if
this is unintended.

---

## Testing

### Test Dependency Resolution

```bash
python scripts/test_recursive_dependencies.py
```

### Analyze Dependencies in Export

```bash
python scripts/test_card_dependencies.py
```

---

## Environment Variables Reference

### Source Metabase (for export)

```bash
MB_SOURCE_URL=https://your-source-metabase.com
MB_SOURCE_USERNAME=user@example.com
MB_SOURCE_PASSWORD=password123
# OR use session token:
# MB_SOURCE_SESSION_TOKEN=abc123...
# OR use personal API token:
# MB_SOURCE_PERSONAL_TOKEN=mb_xyz...
```

### Target Metabase (for import)

```bash
MB_TARGET_URL=https://your-target-metabase.com
MB_TARGET_USERNAME=user@example.com
MB_TARGET_PASSWORD=password123
# OR use session token:
# MB_TARGET_SESSION_TOKEN=abc123...
# OR use personal API token:
# MB_TARGET_PERSONAL_TOKEN=mb_xyz...
```

### Metabase Version

```bash
# Specify the Metabase version (determines query format)
# Supported: v56 (default), v57
MB_METABASE_VERSION=v56
```

**Version compatibility:**

- `v56`: Metabase v0.56.x (MBQL 4 format)
- `v57`: Metabase v0.57.x (MBQL 5 format with stages)

**Important:** Source and target must be the same version.

---

## CLI Options Reference

### Export Options

```text
--source-url          Source Metabase URL
--source-username     Username for authentication
--source-password     Password for authentication
--source-session      Session token (alternative to username/password)
--source-token        Personal API token (alternative to username/password)
--export-dir          Directory to save exported files (required)
--include-dashboards  Include dashboards in export
--include-archived    Include archived items
--root-collections    Comma-separated collection IDs to export
--log-level          Logging level: DEBUG, INFO, WARNING, ERROR
```

### Import Options

```text
--target-url          Target Metabase URL
--target-username     Username for authentication
--target-password     Password for authentication
--target-session      Session token (alternative to username/password)
--target-token        Personal API token (alternative to username/password)
--export-dir          Directory with exported files (required)
--db-map              Path to database mapping JSON file (required)
--conflict            Conflict resolution: skip, overwrite, or rename
--dry-run             Preview changes without applying them
--log-level          Logging level: DEBUG, INFO, WARNING, ERROR
```

---

## Database Mapping Format

`db_map.json` maps source database IDs to target database IDs:

```json
{
  "by_id": {
    "1": 10,
    "2": 20
  },
  "by_name": {
    "Production DB": 10,
    "Analytics DB": 20
  }
}
```

**How it works**:

1. First checks `by_id` for exact ID match
2. Falls back to `by_name` for name-based mapping
3. Fails if no mapping found

For concrete examples, see the sample mapping files in the repository:

- `samples/db_map/db_map.single_db.json` – minimal single-database mapping
- `samples/db_map/db_map.multi_db.json` – multi-database mapping, useful for complex environments

You can also look at the example flows in `samples/flows/` and the CI/CD template in
`samples/cicd/github-actions-export-import.yml` for end-to-end usage patterns.

---

## Best Practices

### ✅ Do's

- ✅ Use `.env` file for credentials (more secure)
- ✅ Test with `--dry-run` first
- ✅ Use `--include-archived` for complete exports
- ✅ Keep database mappings in version control (without credentials)
- ✅ Run test scripts to verify exports
- ✅ Use `--conflict skip` for initial imports
- ✅ Use `--conflict overwrite` for updates

### ❌ Don'ts

- ❌ Don't use quotes around passwords in `.env`
- ❌ Don't commit `.env` file to version control
- ❌ Don't skip database mapping configuration
- ❌ Don't import without testing with `--dry-run` first
- ❌ Don't manually edit manifest.json

---

## Support

### Documentation

- `README.md` - Full documentation
- `doc/RECURSIVE_DEPENDENCY_RESOLUTION.md` - Dependency resolution details
- `doc/CHANGES_SUMMARY.md` - Recent changes and fixes
- `doc/DASHBOARD_FIXES_APPLIED.md` - Dashboard import fixes

### Test Scripts

- `scripts/test_recursive_dependencies.py` - Test dependency resolution
- `scripts/test_card_dependencies.py` - Analyze dependencies
- `scripts/test_dashcard_cleaning.py` - Test dashcard cleaning
- `scripts/find_missing_cards.py` - Find missing cards in export
- `scripts/test_database_fetch.py` - Test database fetching

---

## Summary

The Metabase Migration Toolkit now provides:

✅ **Table & Field ID Remapping**: Automatically remaps table and field IDs during import
✅ **Reliable Authentication**: Fixed `.env` parsing
✅ **Clean Dashboard Import**: No false error messages
✅ **Automatic Dependencies**: All card dependencies included automatically
✅ **Self-Contained Exports**: Import without missing dependency errors
✅ **Permissions Migration**: Export and import permissions to avoid 403 errors
✅ **Robust Error Handling**: Graceful handling of edge cases
✅ **Clear Logging**: Detailed information about what's being exported/imported

**Ready to migrate? Start with the export command above!**

## Learn More

- **Table & Field ID Remapping**: See [docs/TABLE_FIELD_ID_REMAPPING.md](TABLE_FIELD_ID_REMAPPING.md)
- **Permissions Migration**: See [docs/PERMISSIONS_MIGRATION.md](PERMISSIONS_MIGRATION.md)
- **Full Documentation**: See [README.md](../README.md)
