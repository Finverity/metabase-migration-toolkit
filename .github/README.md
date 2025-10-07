# GitHub Actions CI/CD Setup

This directory contains GitHub Actions workflows and configuration for automated testing, security scanning, and publishing.

## Workflows

### 1. Tests (`tests.yml`)

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

### 2. Publish (`publish.yml`)

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
   - Go to https://pypi.org/manage/account/publishing/
   - Add GitHub repository
   - Set workflow name: `publish.yml`
   - Set environment name: `pypi`

2. Configure TestPyPI trusted publishing:
   - Go to https://test.pypi.org/manage/account/publishing/
   - Add GitHub repository
   - Set workflow name: `publish.yml`
   - Set environment name: `testpypi`

3. Create GitHub environments:
   - Go to repository Settings → Environments
   - Create `pypi` environment
   - Create `testpypi` environment
   - Add protection rules as needed

### 3. Dependency Review (`dependency-review.yml`)

**Triggers:**
- Pull requests to `main` or `develop` branches

**Jobs:**
- Reviews dependency changes in PRs
- Fails on moderate or higher severity vulnerabilities
- Posts summary comment in PR

### 4. CodeQL Security Analysis (`codeql.yml`)

**Triggers:**
- Push to `main` or `develop` branches
- Pull requests to `main` or `develop` branches
- Weekly schedule (Mondays at midnight)

**Jobs:**
- Runs CodeQL security analysis
- Checks for security vulnerabilities
- Uploads results to GitHub Security tab

## Dependabot Configuration

The `dependabot.yml` file configures automatic dependency updates:

- **Python dependencies**: Weekly updates on Mondays at 9 AM
- **GitHub Actions**: Weekly updates on Mondays at 9 AM
- Groups patch updates together
- Assigns PRs to repository owner
- Labels PRs appropriately

**Setup:**
1. Update the `reviewers` and `assignees` fields in `dependabot.yml` with your GitHub username
2. Dependabot will automatically create PRs for dependency updates

## Issue Templates

### Bug Report (`bug_report.yml`)
Structured form for reporting bugs with:
- Bug description
- Reproduction steps
- Expected vs actual behavior
- Error logs
- Version information
- Environment details

### Feature Request (`feature_request.yml`)
Structured form for suggesting features with:
- Problem statement
- Proposed solution
- Alternatives considered
- Use case
- Priority level

### Configuration (`config.yml`)
- Disables blank issues
- Provides links to discussions and security reporting

## Pull Request Template

The `PULL_REQUEST_TEMPLATE.md` provides a structured format for PRs including:
- Description and type of change
- Related issues
- Testing information
- Checklist for code quality
- Breaking changes documentation

## Badges for README

Add these badges to your main README.md:

```markdown
[![Tests](https://github.com/YOUR_USERNAME/metabase-migration-toolkit/actions/workflows/tests.yml/badge.svg)](https://github.com/YOUR_USERNAME/metabase-migration-toolkit/actions/workflows/tests.yml)
[![codecov](https://codecov.io/gh/YOUR_USERNAME/metabase-migration-toolkit/branch/main/graph/badge.svg)](https://codecov.io/gh/YOUR_USERNAME/metabase-migration-toolkit)
[![PyPI version](https://badge.fury.io/py/metabase-migration-toolkit.svg)](https://badge.fury.io/py/metabase-migration-toolkit)
[![Python Versions](https://img.shields.io/pypi/pyversions/metabase-migration-toolkit.svg)](https://pypi.org/project/metabase-migration-toolkit/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
```

## Setup Checklist

- [ ] Update `dependabot.yml` with your GitHub username
- [ ] Update `.github/ISSUE_TEMPLATE/config.yml` with correct repository URLs
- [ ] Set up PyPI trusted publishing
- [ ] Set up TestPyPI trusted publishing
- [ ] Create GitHub environments (`pypi`, `testpypi`)
- [ ] Set up Codecov account and add `CODECOV_TOKEN` secret (optional)
- [ ] Enable GitHub Actions in repository settings
- [ ] Enable Dependabot in repository settings
- [ ] Enable CodeQL scanning in repository settings
- [ ] Add badges to main README.md

## Testing Workflows Locally

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

## Troubleshooting

### Tests failing on specific Python version
- Check if dependencies are compatible with that Python version
- Review test output for version-specific issues
- Update `pyproject.toml` if needed

### Publishing fails
- Verify PyPI trusted publishing is configured correctly
- Check that version number in `lib/__init__.py` is updated
- Ensure GitHub environments are created
- Verify workflow permissions are correct

### Dependabot PRs not appearing
- Check Dependabot is enabled in repository settings
- Verify `dependabot.yml` syntax is correct
- Check Dependabot logs in Insights → Dependency graph → Dependabot

### CodeQL analysis fails
- Ensure Python code is valid
- Check CodeQL logs for specific errors
- Verify CodeQL is enabled in repository settings

## Additional Resources

- [GitHub Actions Documentation](https://docs.github.com/en/actions)
- [PyPI Trusted Publishing Guide](https://docs.pypi.org/trusted-publishers/)
- [Dependabot Documentation](https://docs.github.com/en/code-security/dependabot)
- [CodeQL Documentation](https://codeql.github.com/docs/)

