# Metabase Migration Toolkit

[![Tests](https://github.com/YOUR_USERNAME/metabase-migration-toolkit/actions/workflows/tests.yml/badge.svg)](https://github.com/YOUR_USERNAME/metabase-migration-toolkit/actions/workflows/tests.yml)
[![codecov](https://codecov.io/gh/YOUR_USERNAME/metabase-migration-toolkit/branch/main/graph/badge.svg)](https://codecov.io/gh/YOUR_USERNAME/metabase-migration-toolkit)
[![PyPI version](https://badge.fury.io/py/metabase-migration-toolkit.svg)](https://badge.fury.io/py/metabase-migration-toolkit)
[![Python Versions](https://img.shields.io/pypi/pyversions/metabase-migration-toolkit.svg)](https://pypi.org/project/metabase-migration-toolkit/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

This toolkit provides two command-line tools, `metabase-export` and `metabase-import`, designed for exporting and importing Metabase content (collections, questions, and dashboards) between instances.

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

## Installation

### Option 1: Install from PyPI (Recommended)

```bash
pip install metabase-migration-toolkit
```

After installation, the `metabase-export` and `metabase-import` commands will be available globally in your environment.

### Option 2: Install from TestPyPI (for testing)

```bash
pip install --index-url https://test.pypi.org/simple/ \
            --extra-index-url https://pypi.org/simple/ \
            metabase-migration-toolkit
```

### Option 3: Install from Source

1.  **Clone the repository:**
    ```bash
    git clone <your-repo-url>
    cd metabase-migration-toolkit
    ```

2.  **Install the package:**
    ```bash
    pip install -e .
    ```

## Configuration

1.  **Configure Environment Variables (Recommended):**
    Copy the example `.env` file and fill in your credentials. This is the most secure way to provide credentials.
    ```bash
    cp .env.example .env
    # Edit .env with your details
    ```

2.  **Create a Database Mapping File:**
    Copy the example `db_map.example.json` and configure it to map your source database IDs/names to the target database IDs.
    ```bash
    cp db_map.example.json db_map.json
    # Edit db_map.json with your mappings
    ```
    **This is the most critical step for a successful import.** You must map every source database ID used by an exported card to a valid target database ID.

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
- `--log-level` - Logging level: DEBUG, INFO, WARNING, ERROR