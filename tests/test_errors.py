"""
Unit tests for the error types in lib/errors.py.

Tests cover all custom exception classes and their properties.
"""

import pytest

from lib.errors import (
    CardMappingError,
    CircularDependencyError,
    ConflictError,
    DatabaseMappingError,
    DependencyError,
    ExportError,
    FieldMappingError,
    ManifestValidationError,
    MappingError,
    MigrationError,
    TableMappingError,
    ValidationError,
)
from lib.errors import (
    ImportError as MigrationImportError,  # Avoid shadowing builtins
)


class TestMigrationError:
    """Tests for the base MigrationError class."""

    def test_basic_init(self):
        """Test basic initialization with just a message."""
        error = MigrationError("Something went wrong")
        assert str(error) == "Something went wrong"
        assert error.message == "Something went wrong"
        assert error.details == {}

    def test_init_with_details(self):
        """Test initialization with details dict."""
        details = {"key": "value", "count": 42}
        error = MigrationError("Error occurred", details=details)
        assert error.message == "Error occurred"
        assert error.details == details
        assert error.details["key"] == "value"
        assert error.details["count"] == 42

    def test_exception_inheritance(self):
        """Test that MigrationError inherits from Exception."""
        error = MigrationError("Test")
        assert isinstance(error, Exception)

    def test_can_be_raised_and_caught(self):
        """Test that the error can be raised and caught."""
        with pytest.raises(MigrationError) as exc_info:
            raise MigrationError("Test error", details={"foo": "bar"})

        assert exc_info.value.message == "Test error"
        assert exc_info.value.details == {"foo": "bar"}


class TestMappingError:
    """Tests for the MappingError class."""

    def test_basic_init(self):
        """Test basic initialization."""
        error = MappingError("Mapping failed")
        assert error.message == "Mapping failed"
        assert error.source_id is None
        assert error.source_type == "unknown"

    def test_init_with_source_info(self):
        """Test initialization with source ID and type."""
        error = MappingError(
            "Mapping failed", source_id=123, source_type="table", details={"db": "test"}
        )
        assert error.source_id == 123
        assert error.source_type == "table"
        assert error.details == {"db": "test"}

    def test_inheritance(self):
        """Test that MappingError inherits from MigrationError."""
        error = MappingError("Test")
        assert isinstance(error, MigrationError)
        assert isinstance(error, Exception)


class TestDatabaseMappingError:
    """Tests for the DatabaseMappingError class."""

    def test_basic_init(self):
        """Test basic initialization with just database ID."""
        error = DatabaseMappingError(source_db_id=5)
        assert "5" in str(error)
        assert error.source_id == 5
        assert error.source_type == "database"
        assert error.source_db_name is None

    def test_init_with_db_name(self):
        """Test initialization with database name."""
        error = DatabaseMappingError(source_db_id=10, source_db_name="Production DB")
        assert "10" in str(error)
        assert "Production DB" in str(error)
        assert error.source_db_name == "Production DB"

    def test_init_with_details(self):
        """Test initialization with additional details."""
        error = DatabaseMappingError(
            source_db_id=3, source_db_name="TestDB", details={"available_dbs": [1, 2]}
        )
        assert error.details == {"available_dbs": [1, 2]}

    def test_inheritance(self):
        """Test inheritance chain."""
        error = DatabaseMappingError(source_db_id=1)
        assert isinstance(error, MappingError)
        assert isinstance(error, MigrationError)


class TestTableMappingError:
    """Tests for the TableMappingError class."""

    def test_basic_init(self):
        """Test basic initialization."""
        error = TableMappingError(source_table_id=100, source_db_id=5)
        assert "100" in str(error)
        assert "5" in str(error)
        assert error.source_id == 100
        assert error.source_db_id == 5
        assert error.source_type == "table"
        assert error.table_name is None

    def test_init_with_table_name(self):
        """Test initialization with table name."""
        error = TableMappingError(source_table_id=200, source_db_id=10, table_name="users")
        assert "users" in str(error)
        assert error.table_name == "users"

    def test_init_with_details(self):
        """Test initialization with details."""
        error = TableMappingError(
            source_table_id=50, source_db_id=2, table_name="orders", details={"schema": "public"}
        )
        assert error.details == {"schema": "public"}


class TestFieldMappingError:
    """Tests for the FieldMappingError class."""

    def test_basic_init(self):
        """Test basic initialization."""
        error = FieldMappingError(source_field_id=500, source_db_id=10)
        assert "500" in str(error)
        assert "10" in str(error)
        assert error.source_id == 500
        assert error.source_db_id == 10
        assert error.source_type == "field"
        assert error.field_name is None

    def test_init_with_field_name(self):
        """Test initialization with field name."""
        error = FieldMappingError(source_field_id=600, source_db_id=20, field_name="email")
        assert "email" in str(error)
        assert error.field_name == "email"

    def test_init_with_details(self):
        """Test initialization with details."""
        error = FieldMappingError(
            source_field_id=700,
            source_db_id=30,
            field_name="created_at",
            details={"type": "timestamp"},
        )
        assert error.details == {"type": "timestamp"}


class TestCardMappingError:
    """Tests for the CardMappingError class."""

    def test_basic_init(self):
        """Test basic initialization."""
        error = CardMappingError(source_card_id=42)
        assert "42" in str(error)
        assert error.source_id == 42
        assert error.source_type == "card"
        assert error.card_name is None

    def test_init_with_card_name(self):
        """Test initialization with card name."""
        error = CardMappingError(source_card_id=99, card_name="Revenue Report")
        assert "99" in str(error)
        assert "Revenue Report" in str(error)
        assert error.card_name == "Revenue Report"

    def test_init_with_details(self):
        """Test initialization with details."""
        error = CardMappingError(
            source_card_id=150, card_name="Sales Chart", details={"collection_id": 5}
        )
        assert error.details == {"collection_id": 5}


class TestDependencyError:
    """Tests for the DependencyError class."""

    def test_basic_init(self):
        """Test basic initialization."""
        error = DependencyError("Missing dependencies")
        assert error.message == "Missing dependencies"
        assert error.missing_ids == set()
        assert error.entity_type == "card"

    def test_init_with_missing_ids(self):
        """Test initialization with missing IDs."""
        error = DependencyError("Cards not found", missing_ids={1, 2, 3}, entity_type="dashboard")
        assert error.missing_ids == {1, 2, 3}
        assert error.entity_type == "dashboard"

    def test_inheritance(self):
        """Test inheritance from MigrationError."""
        error = DependencyError("Test")
        assert isinstance(error, MigrationError)


class TestCircularDependencyError:
    """Tests for the CircularDependencyError class."""

    def test_basic_init(self):
        """Test basic initialization with dependency chain."""
        chain = [1, 2, 3, 1]
        error = CircularDependencyError(dependency_chain=chain)
        assert error.dependency_chain == chain
        assert "1 -> 2 -> 3 -> 1" in str(error)
        assert "Circular dependency" in str(error)

    def test_inheritance(self):
        """Test inheritance from DependencyError."""
        error = CircularDependencyError(dependency_chain=[1, 2, 1])
        assert isinstance(error, DependencyError)
        assert isinstance(error, MigrationError)
        assert error.entity_type == "card"

    def test_with_details(self):
        """Test initialization with details."""
        error = CircularDependencyError(
            dependency_chain=[5, 10, 15, 5], details={"detected_at": "import"}
        )
        assert error.details == {"detected_at": "import"}


class TestConflictError:
    """Tests for the ConflictError class."""

    def test_basic_init(self):
        """Test basic initialization."""
        error = ConflictError(
            message="Entity already exists", entity_type="card", entity_name="Revenue Report"
        )
        assert error.message == "Entity already exists"
        assert error.entity_type == "card"
        assert error.entity_name == "Revenue Report"
        assert error.existing_id is None

    def test_init_with_existing_id(self):
        """Test initialization with existing ID."""
        error = ConflictError(
            message="Collection exists",
            entity_type="collection",
            entity_name="Analytics",
            existing_id=42,
        )
        assert error.existing_id == 42

    def test_init_with_details(self):
        """Test initialization with details."""
        error = ConflictError(
            message="Dashboard conflict",
            entity_type="dashboard",
            entity_name="Sales Overview",
            existing_id=100,
            details={"strategy": "skip"},
        )
        assert error.details == {"strategy": "skip"}


class TestValidationError:
    """Tests for the ValidationError class."""

    def test_basic_init(self):
        """Test basic initialization."""
        error = ValidationError("Validation failed")
        assert error.message == "Validation failed"
        assert error.field is None
        assert error.expected is None
        assert error.actual is None

    def test_init_with_field_info(self):
        """Test initialization with field information."""
        error = ValidationError(
            message="Invalid value", field="database_id", expected="integer", actual="string"
        )
        assert error.field == "database_id"
        assert error.expected == "integer"
        assert error.actual == "string"

    def test_init_with_details(self):
        """Test initialization with details."""
        error = ValidationError(
            message="Schema mismatch",
            field="version",
            expected="2.0",
            actual="1.0",
            details={"path": "/manifest.json"},
        )
        assert error.details == {"path": "/manifest.json"}


class TestManifestValidationError:
    """Tests for the ManifestValidationError class."""

    def test_basic_init(self):
        """Test basic initialization."""
        error = ManifestValidationError("Invalid manifest")
        assert error.message == "Invalid manifest"

    def test_inheritance(self):
        """Test inheritance from ValidationError."""
        error = ManifestValidationError("Missing required field")
        assert isinstance(error, ValidationError)
        assert isinstance(error, MigrationError)

    def test_with_field_info(self):
        """Test with field information."""
        error = ManifestValidationError(
            message="Missing field", field="meta.source_url", expected="string", actual=None
        )
        assert error.field == "meta.source_url"
        assert error.expected == "string"
        assert error.actual is None


class TestExportError:
    """Tests for the ExportError class."""

    def test_basic_init(self):
        """Test basic initialization."""
        error = ExportError("Export failed")
        assert error.message == "Export failed"
        assert error.entity_type is None
        assert error.entity_id is None

    def test_init_with_entity_info(self):
        """Test initialization with entity information."""
        error = ExportError(message="Failed to export card", entity_type="card", entity_id=123)
        assert error.entity_type == "card"
        assert error.entity_id == 123

    def test_init_with_details(self):
        """Test initialization with details."""
        error = ExportError(
            message="Collection export failed",
            entity_type="collection",
            entity_id=50,
            details={"reason": "permission denied"},
        )
        assert error.details == {"reason": "permission denied"}


class TestMigrationImportError:
    """Tests for the ImportError class (renamed to avoid shadowing builtins)."""

    def test_basic_init(self):
        """Test basic initialization."""
        error = MigrationImportError("Import failed")
        assert error.message == "Import failed"
        assert error.entity_type is None
        assert error.entity_id is None
        assert error.entity_name is None

    def test_init_with_entity_info(self):
        """Test initialization with entity information."""
        error = MigrationImportError(
            message="Failed to import dashboard",
            entity_type="dashboard",
            entity_id=456,
            entity_name="Sales Overview",
        )
        assert error.entity_type == "dashboard"
        assert error.entity_id == 456
        assert error.entity_name == "Sales Overview"

    def test_init_with_details(self):
        """Test initialization with details."""
        error = MigrationImportError(
            message="Card import failed",
            entity_type="card",
            entity_id=789,
            entity_name="Revenue Report",
            details={"conflict": True, "existing_id": 100},
        )
        assert error.details == {"conflict": True, "existing_id": 100}

    def test_inheritance(self):
        """Test inheritance from MigrationError."""
        error = MigrationImportError("Test")
        assert isinstance(error, MigrationError)


class TestErrorHierarchy:
    """Tests for the overall error hierarchy."""

    def test_all_errors_inherit_from_migration_error(self):
        """Test that all custom errors inherit from MigrationError."""
        errors = [
            MappingError("test"),
            DatabaseMappingError(1),
            TableMappingError(1, 1),
            FieldMappingError(1, 1),
            CardMappingError(1),
            DependencyError("test"),
            CircularDependencyError([1, 2, 1]),
            ConflictError("test", "card", "name"),
            ValidationError("test"),
            ManifestValidationError("test"),
            ExportError("test"),
            MigrationImportError("test"),
        ]

        for error in errors:
            assert isinstance(
                error, MigrationError
            ), f"{type(error).__name__} should inherit from MigrationError"
            assert isinstance(
                error, Exception
            ), f"{type(error).__name__} should inherit from Exception"

    def test_mapping_errors_hierarchy(self):
        """Test that specific mapping errors inherit from MappingError."""
        mapping_errors = [
            DatabaseMappingError(1),
            TableMappingError(1, 1),
            FieldMappingError(1, 1),
            CardMappingError(1),
        ]

        for error in mapping_errors:
            assert isinstance(
                error, MappingError
            ), f"{type(error).__name__} should inherit from MappingError"

    def test_circular_dependency_inherits_from_dependency(self):
        """Test CircularDependencyError inherits from DependencyError."""
        error = CircularDependencyError([1, 2, 1])
        assert isinstance(error, DependencyError)

    def test_manifest_validation_inherits_from_validation(self):
        """Test ManifestValidationError inherits from ValidationError."""
        error = ManifestValidationError("test")
        assert isinstance(error, ValidationError)
