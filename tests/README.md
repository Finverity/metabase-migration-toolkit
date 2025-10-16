# Test Suite

This directory contains the test suite for the Metabase Migration Toolkit.

## Structure

```
tests/
├── __init__.py                 # Test package initialization
├── conftest.py                 # Shared pytest fixtures
├── README.md                   # This file
├── test_client.py              # Tests for MetabaseClient
├── test_config.py              # Tests for configuration loading
├── test_models.py              # Tests for data models
├── test_utils.py               # Tests for utility functions
├── fixtures/                   # Test data and fixtures
│   ├── __init__.py
│   └── sample_responses.py     # Sample API responses
└── integration/                # Integration tests
    ├── __init__.py
    └── test_export_import_flow.py
```

## Running Tests

### Run all tests

```bash
pytest
```

### Run with coverage report

```bash
pytest --cov=lib --cov-report=html
```

### Run specific test file

```bash
pytest tests/test_utils.py
```

### Run specific test class

```bash
pytest tests/test_utils.py::TestSanitizeFilename
```

### Run specific test function

```bash
pytest tests/test_utils.py::TestSanitizeFilename::test_sanitize_basic_string
```

### Run tests matching a pattern

```bash
pytest -k "sanitize"
```

### Run with verbose output

```bash
pytest -v
```

### Run with extra verbose output (show all test names)

```bash
pytest -vv
```

## Test Markers

Tests are organized using pytest markers:

### Skip integration tests (default)

```bash
pytest -m "not integration"
```

### Run only integration tests

```bash
pytest -m integration
```

### Skip slow tests

```bash
pytest -m "not slow"
```

### Run only unit tests (skip integration and slow)

```bash
pytest -m "not integration and not slow"
```

## Integration Tests

Integration tests require actual Metabase instances and are skipped by default.

To run integration tests:

1. Set up a test Metabase instance
2. Set environment variables:

   ```bash
   export METABASE_TEST_URL="https://test.metabase.example.com"
   export METABASE_TEST_USERNAME="test@example.com"
   export METABASE_TEST_PASSWORD=""
   ```

3. Run integration tests:

   ```bash
   pytest -m integration
   ```

**Warning**: Integration tests may modify the test instance. Use a dedicated test environment.

## Coverage

### Generate HTML coverage report

```bash
pytest --cov=lib --cov-report=html
open htmlcov/index.html  # macOS
xdg-open htmlcov/index.html  # Linux
```

### Generate terminal coverage report

```bash
pytest --cov=lib --cov-report=term-missing
```

### Generate XML coverage report (for CI/CD)

```bash
pytest --cov=lib --cov-report=xml
```

### Coverage goals

- **Minimum**: 80% overall coverage
- **Target**: 90% overall coverage
- **Critical modules**: 95%+ coverage (client, models, utils)

## Writing Tests

### Test naming conventions

- Test files: `test_*.py`
- Test classes: `Test*`
- Test functions: `test_*`

### Example test structure

```python
import pytest
from lib.utils import sanitize_filename

class TestSanitizeFilename:
    """Test suite for sanitize_filename function."""

    def test_basic_case(self):
        """Test basic functionality."""
        result = sanitize_filename("Test File")
        assert result == "Test-File"

    def test_edge_case(self):
        """Test edge case."""
        result = sanitize_filename("")
        assert result == ""
```

### Using fixtures

```python
def test_with_fixture(temp_dir):
    """Test using a fixture from conftest.py."""
    test_file = temp_dir / "test.txt"
    test_file.write_text("content")
    assert test_file.exists()
```

### Mocking external calls

```python
from unittest.mock import Mock, patch

@patch('requests.Session.get')
def test_api_call(mock_get):
    """Test with mocked API call."""
    mock_response = Mock()
    mock_response.json.return_value = {"data": "test"}
    mock_get.return_value = mock_response

    # Your test code here
```

### Parametrized tests

```python
@pytest.mark.parametrize("input,expected", [
    ("Test File", "Test-File"),
    ("Test/File", "Test-File"),
    ("Test  File", "Test-File"),
])
def test_sanitize_variations(input, expected):
    """Test multiple input variations."""
    assert sanitize_filename(input) == expected
```

## Continuous Integration

Tests are automatically run on:

- Every push to main branch
- Every pull request
- Scheduled daily runs

See `.github/workflows/tests.yml` for CI configuration.

## Troubleshooting

### Tests fail with import errors

```bash
# Install package in development mode
pip install -e .

# Or install test dependencies
pip install -e ".[dev]"
```

### Coverage report not generated

```bash
# Install coverage plugin
pip install pytest-cov
```

### Tests are slow

```bash
# Run in parallel (requires pytest-xdist)
pip install pytest-xdist
pytest -n auto
```

### Clear pytest cache

```bash
pytest --cache-clear
```

## Best Practices

1. **One assertion per test** (when possible)
2. **Use descriptive test names** that explain what is being tested
3. **Test edge cases** and error conditions
4. **Mock external dependencies** (API calls, file system, etc.)
5. **Keep tests independent** - each test should be able to run alone
6. **Use fixtures** for common setup/teardown
7. **Add docstrings** to test classes and functions
8. **Test both success and failure paths**
9. **Aim for high coverage** but focus on meaningful tests
10. **Keep tests fast** - mock slow operations

## Resources

- [Pytest Documentation](https://docs.pytest.org/)
- [Pytest Fixtures](https://docs.pytest.org/en/stable/fixture.html)
- [Pytest Markers](https://docs.pytest.org/en/stable/mark.html)
- [Coverage.py](https://coverage.readthedocs.io/)
