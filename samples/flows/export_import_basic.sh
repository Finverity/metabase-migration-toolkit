#!/usr/bin/env bash
# Basic export/import example using .env configuration.
# This script is intended as a template; adjust paths and flags to your needs.

set -euo pipefail

EXPORT_DIR="${EXPORT_DIR:-./metabase_export_basic}"

echo "Exporting from source Metabase to ${EXPORT_DIR}..."
metabase-export \
  --export-dir "${EXPORT_DIR}" \
  --include-dashboards \
  --include-permissions

echo "Importing into target Metabase..."
metabase-import \
  --export-dir "${EXPORT_DIR}" \
  --db-map "./db_map.json" \
  --conflict skip \
  --apply-permissions

echo "Done."
