# Metabase Migration Toolkit

[![Tests](https://github.com/YOUR_USERNAME/metabase-migration-toolkit/actions/workflows/tests.yml/badge.svg)](https://github.com/YOUR_USERNAME/metabase-migration-toolkit/actions/workflows/tests.yml)
[![codecov](https://codecov.io/gh/YOUR_USERNAME/metabase-migration-toolkit/branch/main/graph/badge.svg)](https://codecov.io/gh/YOUR_USERNAME/metabase-migration-toolkit)
[![PyPI version](https://badge.fury.io/py/metabase-migration-toolkit.svg)](https://badge.fury.io/py/metabase-migration-toolkit)
[![Python Versions](https://img.shields.io/pypi/pyversions/metabase-migration-toolkit.svg)](https://pypi.org/project/metabase-migration-toolkit/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

This toolkit consists of two Python CLI scripts, `export_metabase.py` and `import_metabase.py`, designed for exporting and importing Metabase content (collections, questions, and dashboards) between instances.

It's built to be robust, handling API rate limits, pagination, and providing clear logging and error handling for production use.

## Features

- **Recursive Export:** Traverses the entire collection tree, preserving hierarchy.
- **Selective Content:** Choose to include dashboards and archived items.
- **Database Remapping:** Intelligently remaps questions and cards to new database IDs on the target instance.
- **Conflict Resolution:** Strategies for handling items that already exist on the target (`skip`, `overwrite`, `rename`).
- **Idempotent Import:** Re-running an import with `skip` or `overwrite` produces a consistent state.
- **Dry Run Mode:** Preview all import actions without making any changes to the target instance.
- **Secure:** Handles credentials via environment variables or CLI flags and never logs or exports sensitive information.
- **Reliable:** Implements exponential backoff and retries for network requests.

## Prerequisites

- Python 3.10+
- Access to source and target Metabase instances with appropriate permissions (API access, ideally admin).

## Setup

1.  **Clone the repository:**
    ```bash
    git clone <your-repo-url>
    cd metabase-migration-toolkit
    ```

2.  **Install dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

3.  **Configure Environment Variables (Recommended):**
    Copy the example `.env` file and fill in your credentials. This is the most secure way to provide credentials.
    ```bash
    cp .env.example .env
    # Edit .env with your details
    ```

4.  **Create a Database Mapping File:**
    Copy the example `db_map.example.json` and configure it to map your source database IDs/names to the target database IDs.
    ```bash
    cp db_map.example.json db_map.json
    # Edit db_map.json with your mappings
    ```
    **This is the most critical step for a successful import.** You must map every source database ID used by an exported card to a valid target database ID.

## Usage

### 1. Exporting from a Source Metabase

The `export_metabase.py` script connects to a source instance and exports its content into a local directory.

**Example using .env file (Recommended):**

```bash
# All credentials are read from .env file
python export_metabase.py \
    --include-archived \
    --export-dir "./metabase_export" \
    --include-dashboards \
    --log-level INFO \
    --root-collections "24" \
    --source-session "8ac852de-4d46-4ad9-a574-402994e92ef1" \
    --include-archived
```

**Example using CLI flags:**

```bash
python export_metabase.py \
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
- `--root-collections` - Comma-separated collection IDs to export (optional)
- `--log-level` - Logging level: DEBUG, INFO, WARNING, ERROR

### 2. Importing to a Target Metabase

The `import_metabase.py` script reads the export package and recreates the content on a target instance.

**Example using .env file (Recommended):**

```bash
# All credentials are read from .env file
python import_metabase.py \
    --export-dir "./metabase_export" \
    --db-map "./db_map.json" \
    --conflict skip \
    --log-level INFO
```

**Example using CLI flags:**

```bash
python import_metabase.py \
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
- `--log-level` - Logging level: DEBUG, INFO, WARNING, ERROR