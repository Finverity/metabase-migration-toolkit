# Contributing to Metabase Migration Toolkit

Thank you for your interest in contributing! This document provides guidelines and instructions for contributing to
this project.

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [Getting Started](#getting-started)
- [Development Setup](#development-setup)
- [Code Quality Standards](#code-quality-standards)
- [Testing Guidelines](#testing-guidelines)
- [Submitting Changes](#submitting-changes)
- [Release Process](#release-process)

## Code of Conduct

This project adheres to a Code of Conduct that all contributors are expected to follow. Please read
[CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) before contributing.

## Getting Started

### Prerequisites

- Python 3.8 or higher (3.11 recommended for development)
- Git
- pip and virtualenv (or similar)

### Finding Issues to Work On

- Check the [Issues](https://github.com/YOUR_USERNAME/metabase-migration-toolkit/issues) page
- Look for issues labeled `good first issue` or `help wanted`
- Comment on an issue to let others know you're working on it

## Development Setup

### 1. Fork and Clone

```bash
# Fork the repository on GitHub, then clone your fork
git clone https://github.com/YOUR_USERNAME/metabase-migration-toolkit.git
cd metabase-migration-toolkit

# Add upstream remote
git remote add upstream https://github.com/ORIGINAL_OWNER/metabase-migration-toolkit.git
```

### 2. Create a Virtual Environment

```bash
# Create virtual environment
python -m venv venv

# Activate it
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

### 3. Install Development Dependencies

```bash
# Install package with development dependencies
make install-dev

# Or manually:
pip install -e ".[dev]"
pre-commit install
```

### 4. Verify Setup

```bash
# Run tests
make test

# Run all quality checks
make quality
```

## Code Quality Standards

We maintain high code quality standards using automated tools. All code must pass these checks before being merged.

### Code Formatting

We use **Black** for code formatting with a line length of 100 characters.

```bash
# Format code
make format

# Check formatting
black --check lib/ tests/ *.py
```

**Configuration:** See `pyproject.toml` for Black settings.

### Import Sorting

We use **isort** to sort imports, configured to be compatible with Black.

```bash
# Sort imports
isort lib/ tests/ *.py

# Check import sorting
isort --check-only lib/ tests/ *.py
```

### Linting

We use **Ruff** for fast Python linting.

```bash
# Run linter
make lint

# Auto-fix issues
ruff check --fix lib/ tests/ *.py
```

**Configuration:** See `pyproject.toml` for Ruff settings.

### Type Checking

We use **Mypy** for static type checking.

```bash
# Run type checker
make type-check

# Or directly
mypy lib/ --ignore-missing-imports
```

**Guidelines:**

- Add type hints to all function signatures
- Use `Optional[T]` for nullable types
- Use `List[T]`, `Dict[K, V]`, etc. for collections
- Import types from `typing` module

### Security Scanning

We use **Bandit** for security scanning.

```bash
# Run security scan
make security

# Or directly
bandit -r lib/ -f screen
```

### Pre-commit Hooks

We use pre-commit hooks to automatically check code quality before commits.

```bash
# Install hooks (done automatically with make install-dev)
pre-commit install

# Run hooks manually on all files
make pre-commit

# Update hooks
make pre-commit-update
```

**Hooks include:**

- Trailing whitespace removal
- End-of-file fixer
- YAML/JSON/TOML validation
- Black formatting
- isort import sorting
- Ruff linting
- Mypy type checking
- Bandit security scanning
- Markdown linting
- Secret detection

## Testing Guidelines

### Writing Tests

- Place tests in the `tests/` directory
- Name test files `test_*.py`
- Name test functions `test_*`
- Use descriptive test names that explain what is being tested
- Follow the Arrange-Act-Assert pattern

**Example:**

```python
def test_sanitize_filename_removes_special_characters():
    """Test that sanitize_filename removes special characters."""
    # Arrange
    filename = "test/file:name*.txt"

    # Act
    result = sanitize_filename(filename)

    # Assert
    assert result == "test_file_name_.txt"
```

### Running Tests

```bash
# Run all tests
make test

# Run with coverage
make test-cov

# Run specific test file
pytest tests/test_utils.py

# Run specific test
pytest tests/test_utils.py::test_sanitize_filename

# Run tests matching pattern
pytest -k "sanitize"
```

### Test Coverage

We aim for **80%+ test coverage**.

```bash
# Generate coverage report
make test-cov

# View HTML report
open htmlcov/index.html
```

### Test Categories

Tests are marked with pytest markers:

- `@pytest.mark.integration` - Integration tests (require external services)
- `@pytest.mark.slow` - Slow tests (> 1 second)
- `@pytest.mark.requires_api` - Tests requiring API access

```bash
# Skip slow tests
pytest -m "not slow"

# Run only integration tests
pytest -m integration
```

## Submitting Changes

### 1. Create a Branch

```bash
# Update your fork
git checkout main
git pull upstream main

# Create a feature branch
git checkout -b feature/your-feature-name
# or
git checkout -b fix/your-bug-fix
```

### 2. Make Changes

- Write clear, concise commit messages
- Keep commits focused and atomic
- Add tests for new functionality
- Update documentation as needed

### 3. Run Quality Checks

```bash
# Run all checks
make ci

# Or individually
make format      # Format code
make lint        # Run linters
make type-check  # Type checking
make test-cov    # Tests with coverage
```

### 4. Commit Changes

```bash
# Stage changes
git add .

# Commit (pre-commit hooks will run automatically)
git commit -m "feat: add new feature"

# If pre-commit hooks fail, fix issues and commit again
```

**Commit Message Format:**

We follow [Conventional Commits](https://www.conventionalcommits.org/):

- `feat:` - New feature
- `fix:` - Bug fix
- `docs:` - Documentation changes
- `style:` - Code style changes (formatting, etc.)
- `refactor:` - Code refactoring
- `test:` - Adding or updating tests
- `chore:` - Maintenance tasks
- `ci:` - CI/CD changes

### 5. Push and Create Pull Request

```bash
# Push to your fork
git push origin feature/your-feature-name

# Create a pull request on GitHub
```

### 6. Pull Request Guidelines

- Fill out the PR template completely
- Link related issues using `Fixes #123` or `Relates to #456`
- Ensure all CI checks pass
- Respond to review feedback promptly
- Keep PR scope focused and manageable

## Code Review Process

1. **Automated Checks**: All PRs must pass automated CI checks
2. **Peer Review**: At least one maintainer must approve
3. **Testing**: New features must include tests
4. **Documentation**: Update docs for user-facing changes
5. **Changelog**: Update CHANGELOG.md for notable changes

## Release Process

Releases are managed by maintainers:

1. Update version in `lib/__init__.py`
2. Update `CHANGELOG.md`
3. Create a GitHub release
4. Package is automatically published to PyPI

## Development Workflow Summary

```bash
# 1. Setup (once)
make dev-setup

# 2. Create branch
git checkout -b feature/my-feature

# 3. Make changes and test
make test

# 4. Check code quality
make quality

# 5. Commit (pre-commit hooks run automatically)
git commit -m "feat: my feature"

# 6. Push and create PR
git push origin feature/my-feature
```

## Useful Make Commands

```bash
make help           # Show all available commands
make install-dev    # Install with dev dependencies
make test           # Run tests
make test-cov       # Run tests with coverage
make lint           # Run linters
make format         # Format code
make type-check     # Run type checker
make security       # Run security checks
make quality        # Run all quality checks
make pre-commit     # Run pre-commit hooks
make build          # Build package
make clean          # Clean build artifacts
make ci             # Run all CI checks locally
```

## Getting Help

- **Questions**: Open a [Discussion](https://github.com/YOUR_USERNAME/metabase-migration-toolkit/discussions)
- **Bugs**: Open an [Issue](https://github.com/YOUR_USERNAME/metabase-migration-toolkit/issues)
- **Security**: See [SECURITY.md](SECURITY.md)

## License

By contributing, you agree that your contributions will be licensed under the MIT License.

---

Thank you for contributing! 🎉
