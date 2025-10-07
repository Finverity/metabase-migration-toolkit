# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Preparing for initial PyPI release
- Comprehensive test suite
- CI/CD pipeline with GitHub Actions
- Code quality tools (black, ruff, mypy)
- Community guidelines and contribution documentation

## [1.0.0] - 2025-10-07

### Added
- Initial release of Metabase Migration Toolkit
- Export Metabase collections, cards (questions), and dashboards
- Import with intelligent database remapping
- Recursive dependency resolution for cards
- Conflict resolution strategies (skip, overwrite, rename)
- Dry-run mode for safe preview of import actions
- Comprehensive structured logging with configurable levels
- Retry logic with exponential backoff for API requests
- Multiple authentication methods (username/password, session token, personal token)
- Environment variable support via .env files
- Progress bars for long-running operations
- Manifest file generation for export tracking
- Collection hierarchy preservation
- Support for archived items (optional inclusion)
- Selective export by root collection IDs

### Security
- Credentials handled securely via environment variables
- Passwords and tokens masked in logs and export files
- No sensitive data exposed in error messages

[Unreleased]: https://github.com/yourusername/metabase-migration-toolkit/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/yourusername/metabase-migration-toolkit/releases/tag/v1.0.0

