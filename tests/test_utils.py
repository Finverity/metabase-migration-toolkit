"""
Unit tests for lib/utils.py

Tests utility functions for logging, file operations, and string manipulation.
"""

import json
import logging
from pathlib import Path

from lib.utils import (
    TOOL_VERSION,
    CustomJsonEncoder,
    calculate_checksum,
    clean_for_create,
    sanitize_filename,
    setup_logging,
    write_json_file,
)


class TestSanitizeFilename:
    """Test suite for sanitize_filename function."""

    def test_sanitize_basic_string(self):
        """Test sanitization of a basic string."""
        result = sanitize_filename("Test File")
        assert result == "Test-File"

    def test_sanitize_with_slashes(self):
        """Test sanitization removes slashes."""
        result = sanitize_filename("Test/File\\Name")
        assert result == "Test-File-Name"

    def test_sanitize_with_invalid_chars(self):
        """Test sanitization removes invalid filename characters."""
        result = sanitize_filename('Test<>:"|?*File')
        assert result == "TestFile"

    def test_sanitize_multiple_spaces(self):
        """Test sanitization collapses multiple spaces."""
        result = sanitize_filename("Test    Multiple   Spaces")
        assert result == "Test-Multiple-Spaces"

    def test_sanitize_leading_trailing_hyphens(self):
        """Test sanitization removes leading/trailing hyphens."""
        result = sanitize_filename("  Test File  ")
        assert result == "Test-File"

    def test_sanitize_long_filename(self):
        """Test sanitization truncates long filenames."""
        long_name = "a" * 150
        result = sanitize_filename(long_name)
        assert len(result) == 100

    def test_sanitize_empty_string(self):
        """Test sanitization of empty string."""
        result = sanitize_filename("")
        assert result == ""

    def test_sanitize_special_characters(self):
        """Test sanitization with various special characters."""
        result = sanitize_filename("Test_File-Name.txt")
        assert result == "Test-File-Name.txt"


class TestCalculateChecksum:
    """Test suite for calculate_checksum function."""

    def test_calculate_checksum_basic(self, tmp_path: Path):
        """Test checksum calculation for a basic file."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("Hello, World!")

        checksum = calculate_checksum(test_file)

        # SHA256 of "Hello, World!"
        expected = "dffd6021bb2bd5b0af676290809ec3a53191dd81c7f70a4b28688a362182986f"
        assert checksum == expected

    def test_calculate_checksum_empty_file(self, tmp_path: Path):
        """Test checksum calculation for an empty file."""
        test_file = tmp_path / "empty.txt"
        test_file.write_text("")

        checksum = calculate_checksum(test_file)

        # SHA256 of empty string
        expected = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        assert checksum == expected

    def test_calculate_checksum_binary_file(self, tmp_path: Path):
        """Test checksum calculation for a binary file."""
        test_file = tmp_path / "binary.bin"
        test_file.write_bytes(b"\x00\x01\x02\x03\x04")

        checksum = calculate_checksum(test_file)

        assert len(checksum) == 64  # SHA256 produces 64 hex characters
        assert all(c in "0123456789abcdef" for c in checksum)


class TestWriteJsonFile:
    """Test suite for write_json_file function."""

    def test_write_json_basic(self, tmp_path: Path):
        """Test writing a basic dictionary to JSON."""
        test_file = tmp_path / "test.json"
        data = {"key": "value", "number": 42}

        write_json_file(data, test_file)

        assert test_file.exists()
        with open(test_file) as f:
            loaded = json.load(f)
        assert loaded == data

    def test_write_json_creates_parent_dirs(self, tmp_path: Path):
        """Test that write_json_file creates parent directories."""
        test_file = tmp_path / "subdir" / "nested" / "test.json"
        data = {"test": "data"}

        write_json_file(data, test_file)

        assert test_file.exists()
        assert test_file.parent.exists()

    def test_write_json_with_dataclass(self, tmp_path: Path):
        """Test writing a dataclass to JSON using CustomJsonEncoder."""
        from dataclasses import dataclass

        @dataclass
        class TestData:
            name: str
            value: int

        test_file = tmp_path / "dataclass.json"
        data = TestData(name="test", value=42)

        write_json_file(data, test_file)

        assert test_file.exists()
        with open(test_file) as f:
            loaded = json.load(f)
        assert loaded == {"name": "test", "value": 42}

    def test_write_json_unicode(self, tmp_path: Path):
        """Test writing JSON with unicode characters."""
        test_file = tmp_path / "unicode.json"
        data = {"text": "Hello 世界 🌍"}

        write_json_file(data, test_file)

        assert test_file.exists()
        with open(test_file, encoding="utf-8") as f:
            loaded = json.load(f)
        assert loaded == data


class TestCleanForCreate:
    """Test suite for clean_for_create function."""

    def test_clean_removes_id(self):
        """Test that clean_for_create removes id field."""
        payload = {"id": 123, "name": "Test", "value": "data"}
        cleaned = clean_for_create(payload)

        assert "id" not in cleaned
        assert cleaned["name"] == "Test"
        assert cleaned["value"] == "data"

    def test_clean_removes_timestamps(self):
        """Test that clean_for_create removes timestamp fields."""
        payload = {
            "id": 123,
            "name": "Test",
            "created_at": "2025-01-01T00:00:00Z",
            "updated_at": "2025-01-02T00:00:00Z",
        }
        cleaned = clean_for_create(payload)

        assert "created_at" not in cleaned
        assert "updated_at" not in cleaned
        assert cleaned["name"] == "Test"

    def test_clean_removes_creator_fields(self):
        """Test that clean_for_create removes creator fields."""
        payload = {
            "id": 123,
            "name": "Test",
            "creator_id": 456,
            "creator": {"id": 456, "name": "User"},
        }
        cleaned = clean_for_create(payload)

        assert "creator_id" not in cleaned
        assert "creator" not in cleaned
        assert cleaned["name"] == "Test"

    def test_clean_preserves_valid_fields(self):
        """Test that clean_for_create preserves valid fields."""
        payload = {
            "id": 123,
            "name": "Test",
            "description": "A test item",
            "collection_id": 1,
            "database_id": 2,
            "dataset_query": {"type": "query"},
        }
        cleaned = clean_for_create(payload)

        assert "id" not in cleaned
        assert cleaned["name"] == "Test"
        assert cleaned["description"] == "A test item"
        assert cleaned["collection_id"] == 1
        assert cleaned["database_id"] == 2
        assert cleaned["dataset_query"] == {"type": "query"}

    def test_clean_empty_payload(self):
        """Test clean_for_create with empty payload."""
        payload = {}
        cleaned = clean_for_create(payload)

        assert cleaned == {}

    def test_clean_all_fields_removed(self):
        """Test clean_for_create when all fields are removed."""
        payload = {
            "id": 123,
            "created_at": "2025-01-01T00:00:00Z",
            "updated_at": "2025-01-02T00:00:00Z",
        }
        cleaned = clean_for_create(payload)

        assert cleaned == {}


class TestCustomJsonEncoder:
    """Test suite for CustomJsonEncoder class."""

    def test_encode_dataclass(self):
        """Test encoding a dataclass."""
        from dataclasses import dataclass

        @dataclass
        class Person:
            name: str
            age: int

        person = Person(name="Alice", age=30)
        result = json.dumps(person, cls=CustomJsonEncoder)

        assert json.loads(result) == {"name": "Alice", "age": 30}

    def test_encode_nested_dataclass(self):
        """Test encoding nested dataclasses."""
        from dataclasses import dataclass

        @dataclass
        class Address:
            city: str
            country: str

        @dataclass
        class Person:
            name: str
            address: Address

        person = Person(name="Alice", address=Address(city="NYC", country="USA"))
        result = json.dumps(person, cls=CustomJsonEncoder)

        expected = {"name": "Alice", "address": {"city": "NYC", "country": "USA"}}
        assert json.loads(result) == expected

    def test_encode_regular_dict(self):
        """Test encoding a regular dictionary."""
        data = {"key": "value", "number": 42}
        result = json.dumps(data, cls=CustomJsonEncoder)

        assert json.loads(result) == data


class TestSetupLogging:
    """Test suite for setup_logging function."""

    def teardown_method(self):
        """Clean up logger handlers after each test."""
        # Clean up both the specific logger and root logger
        logger = logging.getLogger("metabase_migration")
        logger.handlers.clear()
        root_logger = logging.getLogger()
        root_logger.handlers.clear()

    def test_setup_logging_info_level(self):
        """Test setting up logging with INFO level."""
        logger = setup_logging("INFO")

        assert logger.level == logging.INFO
        # Handlers are on the root logger, not the specific logger
        root_logger = logging.getLogger()
        assert len(root_logger.handlers) > 0

    def test_setup_logging_debug_level(self):
        """Test setting up logging with DEBUG level."""
        logger = setup_logging("DEBUG")

        assert logger.level == logging.DEBUG

    def test_setup_logging_warning_level(self):
        """Test setting up logging with WARNING level."""
        logger = setup_logging("WARNING")

        assert logger.level == logging.WARNING

    def test_setup_logging_error_level(self):
        """Test setting up logging with ERROR level."""
        logger = setup_logging("ERROR")

        assert logger.level == logging.ERROR


class TestToolVersion:
    """Test suite for TOOL_VERSION constant."""

    def test_tool_version_exists(self):
        """Test that TOOL_VERSION is defined."""
        assert TOOL_VERSION is not None

    def test_tool_version_format(self):
        """Test that TOOL_VERSION follows semantic versioning."""
        parts = TOOL_VERSION.split(".")
        assert len(parts) == 3
        assert all(part.isdigit() for part in parts)

    def test_tool_version_matches_package(self):
        """Test that TOOL_VERSION matches package version."""
        from lib import __version__

        assert TOOL_VERSION == __version__
