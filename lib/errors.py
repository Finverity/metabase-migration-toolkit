"""Structured exception types for the Metabase Migration Toolkit.

Provides specific error types for different failure scenarios,
enabling better error handling and reporting.
"""

from typing import Any


class MigrationError(Exception):
    """Base exception for all migration operations."""

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        """Initialize migration error with message and optional details."""
        self.message = message
        self.details = details or {}
        super().__init__(message)


class MappingError(MigrationError):
    """Error when ID mapping fails (database, table, field, or card)."""

    def __init__(
        self,
        message: str,
        source_id: int | None = None,
        source_type: str = "unknown",
        details: dict[str, Any] | None = None,
    ) -> None:
        """Initialize mapping error with source ID and type information."""
        self.source_id = source_id
        self.source_type = source_type
        super().__init__(message, details)


class DatabaseMappingError(MappingError):
    """Error when database ID mapping fails."""

    def __init__(
        self,
        source_db_id: int,
        source_db_name: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Initialize database mapping error with source database information."""
        self.source_db_name = source_db_name
        message = f"No mapping found for source database ID {source_db_id}"
        if source_db_name:
            message += f" ('{source_db_name}')"
        super().__init__(message, source_id=source_db_id, source_type="database", details=details)


class TableMappingError(MappingError):
    """Error when table ID mapping fails."""

    def __init__(
        self,
        source_table_id: int,
        source_db_id: int,
        table_name: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Initialize table mapping error with table and database information."""
        self.source_db_id = source_db_id
        self.table_name = table_name
        message = f"No mapping found for table ID {source_table_id} in database {source_db_id}"
        if table_name:
            message += f" (table: '{table_name}')"
        super().__init__(message, source_id=source_table_id, source_type="table", details=details)


class FieldMappingError(MappingError):
    """Error when field ID mapping fails."""

    def __init__(
        self,
        source_field_id: int,
        source_db_id: int,
        field_name: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Initialize field mapping error with field and database information."""
        self.source_db_id = source_db_id
        self.field_name = field_name
        message = f"No mapping found for field ID {source_field_id} in database {source_db_id}"
        if field_name:
            message += f" (field: '{field_name}')"
        super().__init__(message, source_id=source_field_id, source_type="field", details=details)


class CardMappingError(MappingError):
    """Error when card ID mapping fails (for card references)."""

    def __init__(
        self,
        source_card_id: int,
        card_name: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Initialize card mapping error with card information."""
        self.card_name = card_name
        message = f"No mapping found for source card ID {source_card_id}"
        if card_name:
            message += f" ('{card_name}')"
        super().__init__(message, source_id=source_card_id, source_type="card", details=details)


class DependencyError(MigrationError):
    """Error when required dependencies are missing."""

    def __init__(
        self,
        message: str,
        missing_ids: set[int] | None = None,
        entity_type: str = "card",
        details: dict[str, Any] | None = None,
    ) -> None:
        """Initialize dependency error with missing IDs and entity type."""
        self.missing_ids = missing_ids or set()
        self.entity_type = entity_type
        super().__init__(message, details)


class CircularDependencyError(DependencyError):
    """Error when circular dependencies are detected."""

    def __init__(
        self,
        dependency_chain: list[int],
        details: dict[str, Any] | None = None,
    ) -> None:
        """Initialize circular dependency error with the dependency chain."""
        self.dependency_chain = dependency_chain
        chain_str = " -> ".join(str(c) for c in dependency_chain)
        message = f"Circular dependency detected: {chain_str}"
        super().__init__(message, entity_type="card", details=details)


class ConflictError(MigrationError):
    """Error when entity conflicts with existing item on target."""

    def __init__(
        self,
        message: str,
        entity_type: str,
        entity_name: str,
        existing_id: int | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Initialize conflict error with entity information."""
        self.entity_type = entity_type
        self.entity_name = entity_name
        self.existing_id = existing_id
        super().__init__(message, details)


class ValidationError(MigrationError):
    """Error when validation fails (manifest, config, etc.)."""

    def __init__(
        self,
        message: str,
        field: str | None = None,
        expected: Any = None,
        actual: Any = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Initialize validation error with field and expected/actual values."""
        self.field = field
        self.expected = expected
        self.actual = actual
        super().__init__(message, details)


class ManifestValidationError(ValidationError):
    """Error when manifest validation fails."""

    pass


class ExportError(MigrationError):
    """Error during export operations."""

    def __init__(
        self,
        message: str,
        entity_type: str | None = None,
        entity_id: int | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Initialize export error with entity type and ID."""
        self.entity_type = entity_type
        self.entity_id = entity_id
        super().__init__(message, details)


class ImportError(MigrationError):
    """Error during import operations."""

    def __init__(
        self,
        message: str,
        entity_type: str | None = None,
        entity_id: int | None = None,
        entity_name: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Initialize import error with entity type, ID, and name."""
        self.entity_type = entity_type
        self.entity_id = entity_id
        self.entity_name = entity_name
        super().__init__(message, details)
