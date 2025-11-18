#!/usr/bin/env bash
# Example multi-environment promotion: dev -> staging -> prod.
# In CI you would typically run the import steps in separate jobs with
# different MB_* environment variables or .env files per environment.

set -euo pipefail

EXPORT_DIR="${EXPORT_DIR:-./metabase_export_release}"

echo "Exporting from dev..."
metabase-export \
  --export-dir "${EXPORT_DIR}" \
  --include-dashboards \
  --include-permissions

echo "Importing into staging..."
metabase-import \
  --export-dir "${EXPORT_DIR}" \
  --db-map "./db_map.dev_to_staging.json" \
  --conflict overwrite \
  --apply-permissions

echo "Importing into production..."
metabase-import \
  --export-dir "${EXPORT_DIR}" \
  --db-map "./db_map.staging_to_prod.json" \
  --conflict skip \
  --apply-permissions

echo "Done."
