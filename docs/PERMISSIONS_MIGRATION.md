# Permissions Migration Guide

## Overview

The Metabase Migration Toolkit now supports exporting and importing permissions, including:

- **Permission Groups**: User groups that control access
- **Data Permissions**: Which databases and tables each group can access
- **Collection Permissions**: Which collections each group can view/edit

This feature solves the common issue where users get "403 Forbidden - You don't have permissions to do that"
errors after migrating content to a new Metabase instance.

## Why Permissions Matter

When you migrate Metabase content (collections, questions, dashboards) without permissions:

- Users may not be able to access the migrated databases
- Questions and dashboards may fail with permission errors
- You have to manually recreate all permission settings in the target instance

With permissions export/import, you can:

- Preserve your entire permission structure
- Ensure users have the same access levels after migration
- Save hours of manual permission configuration

## Quick Start

### Export with Permissions

```bash
metabase-export \
    --export-dir "./metabase_export" \
    --include-dashboards \
    --include-permissions
```

### Import with Permissions

```bash
metabase-import \
    --export-dir "./metabase_export" \
    --db-map "./db_map.json" \
    --apply-permissions
```

## Detailed Usage

### Step 1: Export Permissions

Add the `--include-permissions` flag to your export command:

```bash
metabase-export \
    --source-url "https://source-metabase.com" \
    --source-username "admin@example.com" \
    --source-password "password" \
    --export-dir "./migration_export" \
    --include-dashboards \
    --include-permissions \
    --log-level INFO
```

This will export:

- All permission groups (including custom groups)
- Data permissions graph (database access levels)
- Collection permissions graph (collection access levels)

The permissions data is stored in the `manifest.json` file.

### Step 2: Review Exported Permissions

After export, check the manifest.json to see what was exported:

```bash
cat ./migration_export/manifest.json | jq '.permission_groups'
```

You should see something like:

```json
[
  {
    "id": 1,
    "name": "All Users",
    "member_count": 10
  },
  {
    "id": 2,
    "name": "Administrators",
    "member_count": 2
  },
  {
    "id": 3,
    "name": "Analytics Team",
    "member_count": 5
  }
]
```

### Step 3: Prepare Target Instance

Before importing, ensure:

1. **Permission groups exist on target**: Create any custom groups that don't exist
   - Built-in groups (All Users, Administrators) should already exist
   - Custom groups must be created manually in the target Metabase UI

2. **Database mapping is correct**: Update `db_map.json` to map source databases to target databases

```json
{
  "by_id": {
    "1": 5,
    "2": 6
  },
  "by_name": {
    "Production DB": 5,
    "Analytics DB": 6
  }
}
```

### Step 4: Import with Permissions

Add the `--apply-permissions` flag to your import command:

```bash
metabase-import \
    --target-url "https://target-metabase.com" \
    --target-username "admin@example.com" \
    --target-password "password" \
    --export-dir "./migration_export" \
    --db-map "./db_map.json" \
    --apply-permissions \
    --log-level INFO
```

**Important**: The user performing the import must have admin privileges to update permissions.

## How It Works

### Permission Groups Mapping

The import process:

1. Fetches all permission groups from the target instance
2. Maps source group IDs to target group IDs by matching group names
3. Skips groups that don't exist on the target (with a warning)

### Data Permissions Remapping

The data permissions graph is remapped:

1. Group IDs are remapped using the group mapping
2. Database IDs are remapped using the `db_map.json` file
3. Schema and table permissions are preserved as-is

### Collection Permissions Remapping

The collection permissions graph is remapped:

1. Group IDs are remapped using the group mapping
2. Collection IDs are remapped using the collection mapping from the import process
3. Root collection permissions are preserved

## Troubleshooting

### "Group not found on target"

**Problem**: Custom permission group doesn't exist on target instance.

**Solution**:

1. Log into the target Metabase as an admin
2. Go to Settings → Admin → People → Groups
3. Create the missing group with the exact same name
4. Re-run the import with `--apply-permissions`

### "Could not map database ID"

**Problem**: Database mapping is incomplete or incorrect.

**Solution**:

1. Check your `db_map.json` file
2. Ensure all source database IDs are mapped to target database IDs
3. You can map by ID or by name

### "Failed to apply permissions"

**Problem**: User doesn't have admin privileges or API error.

**Solution**:

1. Ensure you're using an admin account for the import
2. Check the logs for specific API errors
3. Try applying permissions manually if the API fails

### Permissions Not Working After Import

**Problem**: Users still get 403 errors after import.

**Checklist**:

- [ ] Did you use `--include-permissions` during export?
- [ ] Did you use `--apply-permissions` during import?
- [ ] Are all custom groups created on the target?
- [ ] Is the database mapping correct?
- [ ] Does the import user have admin privileges?
- [ ] Check the import logs for permission-related warnings

## Best Practices

### 1. Test in a Staging Environment

Always test permissions migration in a staging environment first:

```bash
# Export from production
metabase-export --source-url "https://prod.metabase.com" \
    --export-dir "./prod_export" --include-permissions

# Import to staging
metabase-import --target-url "https://staging.metabase.com" \
    --export-dir "./prod_export" --apply-permissions
```

### 2. Create Groups Before Import

Create all custom permission groups on the target instance before running the import. This ensures proper mapping.

### 3. Use Dry Run First

Use `--dry-run` to preview what will be imported:

```bash
metabase-import \
    --export-dir "./migration_export" \
    --db-map "./db_map.json" \
    --dry-run
```

### 4. Keep Logs

Save import logs for troubleshooting:

```bash
metabase-import \
    --export-dir "./migration_export" \
    --db-map "./db_map.json" \
    --apply-permissions \
    --log-level DEBUG 2>&1 | tee import.log
```

### 5. Verify After Import

After importing, verify permissions:

1. Log in as different users
2. Test access to databases and collections
3. Verify questions and dashboards load correctly

## Limitations

1. **Group Creation**: The API doesn't support creating permission groups.
   You must create custom groups manually on the target instance.

2. **User Assignments**: User-to-group assignments are not migrated. You need to add users to groups manually.

3. **Row-Level Permissions**: Advanced row-level permissions may require manual verification.

4. **API Changes**: Metabase's permissions API may change between versions. Test thoroughly when upgrading.

## Example: Complete Migration with Permissions

```bash
# 1. Export from source (including permissions)
metabase-export \
    --export-dir "./migration_2025" \
    --include-dashboards \
    --include-permissions

# 2. Create custom groups on target (if any)
# Do this manually in the Metabase UI

# 3. Prepare database mapping
cat > db_map.json << EOF
{
  "by_id": {
    "1": 10,
    "2": 11
  }
}
EOF

# 4. Import to target (with permissions)
metabase-import \
    --export-dir "./migration_2025" \
    --db-map "./db_map.json" \
    --apply-permissions

# 5. Verify permissions work
# Log in as different users and test access
```

## Support

If you encounter issues with permissions migration:

1. Check the logs with `--log-level DEBUG`
2. Review this guide's troubleshooting section
3. Open an issue on GitHub with logs and error messages

## See Also

- [Table & Field ID Remapping Guide](TABLE_FIELD_ID_REMAPPING.md) - Learn about automatic table and field ID remapping
- [README.md](../README.md) - Full toolkit documentation
- [QUICK_START.md](QUICK_START.md) - Quick start guide with common scenarios
