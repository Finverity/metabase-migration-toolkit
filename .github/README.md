# Metabase Migration Toolkit

[![Tests](https://github.com/Finverity/metabase-migration-toolkit/actions/workflows/tests.yml/badge.svg)](https://github.com/Finverity/metabase-migration-toolkit/actions/workflows/tests.yml)
[![Python Version](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

A comprehensive Python toolkit for migrating Metabase content (collections, questions, and dashboards) between
instances. Built for production use with robust error handling, API rate limiting, and intelligent database remapping.

## Table of Contents

- [Overview](#overview)
- [Features](#features)
- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Usage](#usage)
  - [Exporting from Source](#exporting-from-source)
  - [Importing to Target](#importing-to-target)
  - [Syncing (Export + Import)](#syncing-export--import)
- [Development](#development)
  - [Running Tests](#running-tests)
  - [CI/CD Pipeline](#cicd-pipeline)
  - [Contributing](#contributing)
- [Troubleshooting](#troubleshooting)
- [Resources](#resources)

## Overview

This toolkit provides three command-line tools designed for exporting and importing Metabase content between instances:

- `metabase-export` - Export content from a source Metabase instance
- `metabase-import` - Import content to a target Metabase instance
- `metabase-sync` - Combined export and import in a single operation

It's built to be robust, handling API rate limits, pagination, and providing clear logging
and error handling for production use.

## Features

- **Recursive Export:** Traverses the entire collection tree, preserving hierarchy.
- **Selective Content:** Choose to include dashboards and archived items.
- **Permissions Migration:** Export and import permission groups and access control settings to avoid 403 errors (NEW!).
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
git clone https://github.com/Finverity/metabase-migration-toolkit.git
cd metabase-migration-toolkit
```

1. **Install the package:**

```bash
pip install -e .
```

## Configuration

### 1. Configure Environment Variables (Recommended)

Copy the example `.env` file and fill in your credentials. This is the most secure way to provide credentials.

```bash
cp .env.example .env
# Edit .env with your details
```

### 2. Create a Database Mapping File

Copy the example `db_map.example.json` and configure it to map your source database IDs/names to the target database IDs.

```bash
cp db_map.example.json db_map.json
# Edit db_map.json with your mappings
```

**This is the most critical step for a successful import.** You must map every source database ID used by an
exported card to a valid target database ID.

## Usage

### Exporting from Source

The `metabase-export` command connects to a source instance and exports its content into a local directory.

#### Example using .env file (Recommended)

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

#### Example using CLI flags

```bash
metabase-export \
    --source-url "https://your-source-metabase.com/" \
    --source-username "user@example.com" \
    --source-password "your_password" \
    --export-dir "./metabase_export" \
    --include-dashboards \
    --root-collections "123,456"
```

#### Available Export Options

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

### Importing to Target

The `metabase-import` command reads the export package and recreates the content on a target instance.

#### Example using .env file (Recommended)

```bash
# All credentials are read from .env file
metabase-import \
    --export-dir "./metabase_export" \
    --db-map "./db_map.json" \
    --conflict skip \
    --apply-permissions \
    --log-level INFO
```

#### Example using CLI flags

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

#### Available Import Options

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

### Syncing (Export + Import)

The `metabase-sync` command combines export and import into a single operation, making it easy to synchronize
content between Metabase instances.

#### Example using .env file (Recommended)

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

#### Example using CLI flags

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

#### Available Sync Options

**Source Instance:**

- `--source-url` - Source Metabase URL (or use `MB_SOURCE_URL` in .env)
- `--source-username` - Source username (or use `MB_SOURCE_USERNAME` in .env)
- `--source-password` - Source password (or use `MB_SOURCE_PASSWORD` in .env)
- `--source-session` - Source session token (or use `MB_SOURCE_SESSION_TOKEN` in .env)
- `--source-token` - Source personal API token (or use `MB_SOURCE_PERSONAL_TOKEN` in .env)

**Target Instance:**

- `--target-url` - Target Metabase URL (or use `MB_TARGET_URL` in .env)
- `--target-username` - Target username (or use `MB_TARGET_USERNAME` in .env)
- `--target-password` - Target password (or use `MB_TARGET_PASSWORD` in .env)
- `--target-session` - Target session token (or use `MB_TARGET_SESSION_TOKEN` in .env)
- `--target-token` - Target personal API token (or use `MB_TARGET_PERSONAL_TOKEN` in .env)

**Shared Options:**

- `--export-dir` - Directory to save/load exported files (required)
- `--db-map` - Path to database mapping JSON file (required)
- `--metabase-version` - Metabase version (or use `MB_METABASE_VERSION` in .env)
- `--log-level` - Logging level: DEBUG, INFO, WARNING, ERROR

**Export Options:**

- `--include-dashboards` - Include dashboards in the export
- `--include-archived` - Include archived items
- `--include-permissions` - Include permissions (groups and access control)
- `--root-collections` - Comma-separated list of root collection IDs to export

**Import Options:**

- `--conflict` - Conflict resolution: `skip`, `overwrite`, or `rename` (default: skip)
- `--dry-run` - Perform a dry run without making any changes
- `--apply-permissions` - Apply permissions from the export (requires admin privileges)

## Permissions Migration

The toolkit now supports exporting and importing permissions to solve the common "403 Forbidden" errors after migration.

**Quick example:**

```bash
# Export with permissions
metabase-export --export-dir "./export" --include-permissions

# Import with permissions
metabase-import --export-dir "./export" --db-map "./db_map.json" --apply-permissions
```

**Documentation:**

- [Permissions Migration Guide](../docs/PERMISSIONS_MIGRATION.md) - Comprehensive guide

## Development

### Running Tests

The project includes comprehensive unit and integration tests. See the [tests/README.md](../tests/README.md) for
detailed testing documentation.

#### Quick Start

```bash
# Run all unit tests
pytest

# Run with coverage
pytest --cov=lib --cov-report=html

# Run integration tests (requires Docker)
make test-integration
```

For more details on integration tests, see [tests/integration/README.md](../tests/integration/README.md).

### CI/CD Pipeline

This repository uses GitHub Actions for automated testing, security scanning, and publishing.

#### Workflows

##### 1. Tests (`tests.yml`)

**Triggers:**

- Push to `main` or `develop` branches
- Pull requests to `main` or `develop` branches
- Manual trigger via workflow_dispatch

**Jobs:**

- **test**: Runs tests on Python 3.8, 3.9, 3.10, 3.11, 3.12
  - Installs dependencies
  - Runs pytest with coverage
  - Uploads coverage to Codecov (Python 3.11 only)

- **lint**: Code quality checks
  - Black formatting check
  - Ruff linting
  - Mypy type checking

- **security**: Security scanning
  - Bandit security scan
  - Safety dependency vulnerability check

- **build**: Package building
  - Builds wheel and source distribution
  - Validates with twine
  - Uploads artifacts

- **test-install**: Installation testing
  - Tests on Ubuntu, macOS, Windows
  - Tests Python 3.9 and 3.11
  - Verifies CLI commands work
  - Verifies package imports

##### 2. Publish (`publish.yml`)

**Triggers:**

- GitHub release published
- Manual trigger with environment selection

**Jobs:**

- **build**: Builds distribution packages
- **publish-to-testpypi**: Publishes to TestPyPI (manual trigger only)
- **publish-to-pypi**: Publishes to PyPI (on release or manual trigger)
- **github-release**: Uploads artifacts to GitHub Release

**Setup Required:**

1. Configure PyPI trusted publishing:
   - Go to <https://pypi.org/manage/account/publishing/>
   - Add GitHub repository
   - Set workflow name: `publish.yml`
   - Set environment name: `pypi`

2. Configure TestPyPI trusted publishing:
   - Go to <https://test.pypi.org/manage/account/publishing/>
   - Add GitHub repository
   - Set workflow name: `publish.yml`
   - Set environment name: `testpypi`

3. Create GitHub environments:
   - Go to repository Settings → Environments
   - Create `pypi` environment
   - Create `testpypi` environment
   - Add protection rules as needed

##### 3. Dependency Review (`dependency-review.yml`)

**Triggers:**

- Pull requests to `main` or `develop` branches

**Jobs:**

- Reviews dependency changes in PRs
- Fails on moderate or higher severity vulnerabilities
- Posts summary comment in PR

##### 4. CodeQL Security Analysis (`codeql.yml`)

**Triggers:**

- Push to `main` or `develop` branches
- Pull requests to `main` or `develop` branches
- Weekly schedule (Mondays at midnight)

**Jobs:**

- Runs CodeQL security analysis
- Checks for security vulnerabilities
- Uploads results to GitHub Security tab

#### Dependabot Configuration

The `dependabot.yml` file configures automatic dependency updates:

- **Python dependencies**: Weekly updates on Mondays at 9 AM
- **GitHub Actions**: Weekly updates on Mondays at 9 AM
- Groups patch updates together
- Assigns PRs to repository owner
- Labels PRs appropriately

**Setup:**

1. Update the `reviewers` and `assignees` fields in `dependabot.yml` with your GitHub username
2. Dependabot will automatically create PRs for dependency updates

#### Issue Templates

**Bug Report (`bug_report.yml`)**
Structured form for reporting bugs with:

- Bug description
- Reproduction steps
- Expected vs actual behavior
- Error logs
- Version information
- Environment details

**Feature Request (`feature_request.yml`)**
Structured form for suggesting features with:

- Problem statement
- Proposed solution
- Alternatives considered
- Use case
- Priority level

**Configuration (`config.yml`)**

- Disables blank issues
- Provides links to discussions and security reporting

#### Pull Request Template

The `PULL_REQUEST_TEMPLATE.md` provides a structured format for PRs including:

- Description and type of change
- Related issues
- Testing information
- Checklist for code quality
- Breaking changes documentation

#### Testing Workflows Locally

You can test workflows locally using [act](https://github.com/nektos/act):

```bash
# Install act
brew install act  # macOS
# or
curl https://raw.githubusercontent.com/nektos/act/master/install.sh | sudo bash  # Linux

# Run tests workflow
act -j test

# Run lint workflow
act -j lint

# List all workflows
act -l
```

### Contributing

We welcome contributions! Here's how to get started:

1. **Fork the repository** and clone your fork
2. **Create a feature branch**: `git checkout -b feature/your-feature-name`
3. **Install development dependencies**: `pip install -e ".[dev]"`
4. **Make your changes** and add tests
5. **Run tests**: `pytest`
6. **Run linting**: `black . && ruff check . && mypy lib/`
7. **Commit your changes**: `git commit -m "Add your feature"`
8. **Push to your fork**: `git push origin feature/your-feature-name`
9. **Open a Pull Request** using the PR template

#### Development Setup Checklist

- [ ] Update `dependabot.yml` with your GitHub username
- [ ] Update `.github/ISSUE_TEMPLATE/config.yml` with correct repository URLs
- [ ] Set up PyPI trusted publishing
- [ ] Set up TestPyPI trusted publishing
- [ ] Create GitHub environments (`pypi`, `testpypi`)
- [ ] Set up Codecov account and add `CODECOV_TOKEN` secret (optional)
- [ ] Enable GitHub Actions in repository settings
- [ ] Enable Dependabot in repository settings
- [ ] Enable CodeQL scanning in repository settings

#### Code Quality Standards

- **Code Style**: Black formatting (line length 100)
- **Linting**: Ruff with strict settings
- **Type Checking**: Mypy with strict mode
- **Test Coverage**: Minimum 80%, target 90%
- **Documentation**: Docstrings for all public functions and classes

## Troubleshooting

### Export/Import Issues

#### Export fails with authentication error

- Verify credentials in `.env` file or CLI flags
- Check that the user has appropriate permissions
- Try using a session token or personal API token instead of username/password

#### Import fails with database mapping error

- Ensure `db_map.json` includes all source database IDs
- Verify target database IDs exist on the target instance
- Check database names match if using name-based mapping

#### Questions or dashboards missing after import

- Check if they were filtered during export (archived items, specific collections)
- Review import logs for skipped items
- Verify conflict resolution strategy (`skip` may skip existing items)

#### Getting 403 Forbidden errors after import

- Use `--include-permissions` during export
- Use `--apply-permissions` during import
- Ensure all custom permission groups exist on target instance
- Verify database mapping is complete in `db_map.json`
- Check that import user has admin privileges
- See [Permissions Migration Guide](../docs/PERMISSIONS_MIGRATION.md) for details

### CI/CD Issues

#### Tests failing on specific Python version

- Check if dependencies are compatible with that Python version
- Review test output for version-specific issues
- Update `pyproject.toml` if needed

#### Publishing fails

- Verify PyPI trusted publishing is configured correctly
- Check that version number in `lib/__init__.py` is updated
- Ensure GitHub environments are created
- Verify workflow permissions are correct

#### Dependabot PRs not appearing

- Check Dependabot is enabled in repository settings
- Verify `dependabot.yml` syntax is correct
- Check Dependabot logs in Insights → Dependency graph → Dependabot

#### CodeQL analysis fails

- Ensure Python code is valid
- Check CodeQL logs for specific errors
- Verify CodeQL is enabled in repository settings

### Performance Issues

#### Export is very slow

- Use `--root-collections` to export specific collections only
- Check network connectivity to source instance
- Review API rate limits on source instance

#### Import is very slow

- Use `--dry-run` first to preview changes
- Consider importing collections separately
- Check network connectivity to target instance

## Resources

### Documentation

- [Metabase API Documentation](https://www.metabase.com/docs/latest/api-documentation)
- [GitHub Actions Documentation](https://docs.github.com/en/actions)
- [Pytest Documentation](https://docs.pytest.org/)

### Tools & Services

- [PyPI Trusted Publishing Guide](https://docs.pypi.org/trusted-publishers/)
- [Dependabot Documentation](https://docs.github.com/en/code-security/dependabot)
- [CodeQL Documentation](https://codeql.github.com/docs/)
- [Codecov](https://codecov.io/)

### Related Projects

- [Metabase](https://github.com/metabase/metabase)
- [Metabase Python Client](https://github.com/vvaezian/metabase_api_python)

## License

This project is licensed under the MIT License - see the LICENSE file for details.
