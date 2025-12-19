"""Defines the data classes for Metabase objects and the migration manifest.

Using typed dataclasses provides clarity and reduces errors.
"""

from __future__ import annotations

import dataclasses
from typing import Any, Literal

# --- Core Metabase Object Models ---


@dataclasses.dataclass
class Collection:
    """Represents a Metabase collection."""

    id: int
    name: str
    slug: str
    description: str | None = None
    parent_id: int | None = None
    personal_owner_id: int | None = None
    path: str = ""  # Filesystem path, populated during export


@dataclasses.dataclass
class Card:
    """Represents a Metabase card (question/model)."""

    id: int
    name: str
    collection_id: int | None = None
    database_id: int | None = None
    file_path: str = ""
    checksum: str = ""
    archived: bool = False
    dataset_query: dict[str, Any] | None = None
    dataset: bool = False  # True if this card is a model (dataset)


@dataclasses.dataclass
class Dashboard:
    """Represents a Metabase dashboard."""

    id: int
    name: str
    collection_id: int | None = None
    ordered_cards: list[int] = dataclasses.field(default_factory=list)
    file_path: str = ""
    checksum: str = ""
    archived: bool = False


@dataclasses.dataclass
class PermissionGroup:
    """Represents a Metabase permission group."""

    id: int
    name: str
    member_count: int = 0


# --- Manifest Models ---


@dataclasses.dataclass
class ManifestMeta:
    """Metadata about the export process."""

    source_url: str
    export_timestamp: str
    tool_version: str
    cli_args: dict[str, Any]
    metabase_version: str | None = None  # Metabase version used during export (e.g., "v56")


@dataclasses.dataclass
class Manifest:
    """The root object for the manifest.json file."""

    meta: ManifestMeta
    databases: dict[int, str] = dataclasses.field(default_factory=dict)
    collections: list[Collection] = dataclasses.field(default_factory=list)
    cards: list[Card] = dataclasses.field(default_factory=list)
    dashboards: list[Dashboard] = dataclasses.field(default_factory=list)
    permission_groups: list[PermissionGroup] = dataclasses.field(default_factory=list)
    permissions_graph: dict[str, Any] = dataclasses.field(default_factory=dict)
    collection_permissions_graph: dict[str, Any] = dataclasses.field(default_factory=dict)
    # Database metadata: db_id -> {tables: [{id, name, fields: [{id, name}, ...]}, ...]}
    database_metadata: dict[int, dict[str, Any]] = dataclasses.field(default_factory=dict)


# --- Import-specific Models ---


@dataclasses.dataclass
class DatabaseMap:
    """Represents the database mapping file."""

    by_id: dict[str, int] = dataclasses.field(default_factory=dict)
    by_name: dict[str, int] = dataclasses.field(default_factory=dict)


@dataclasses.dataclass
class UnmappedDatabase:
    """Represents a source database that could not be mapped to a target."""

    source_db_id: int
    source_db_name: str
    card_ids: set[int] = dataclasses.field(default_factory=set)


@dataclasses.dataclass
class ImportAction:
    """Represents a single planned action for an import dry-run."""

    entity_type: Literal["collection", "card", "dashboard"]
    action: Literal["create", "update", "skip", "rename"]
    source_id: int
    name: str
    target_path: str


@dataclasses.dataclass
class ImportPlan:
    """Represents the full plan for an import operation."""

    actions: list[ImportAction] = dataclasses.field(default_factory=list)
    unmapped_databases: list[UnmappedDatabase] = dataclasses.field(default_factory=list)


@dataclasses.dataclass
class ImportReportItem:
    """Represents the result of a single item import."""

    entity_type: Literal["collection", "card", "dashboard"]
    status: Literal["created", "updated", "skipped", "failed", "success", "error"]
    source_id: int
    target_id: int | None
    name: str
    reason: str | None = None
    error_message: str | None = None  # Alias for reason, kept for backward compatibility

    def __post_init__(self) -> None:
        """Sync error_message and reason fields."""
        # If error_message is provided but not reason, use error_message
        if self.error_message is not None and self.reason is None:
            self.reason = self.error_message
        # If reason is provided but not error_message, sync error_message
        elif self.reason is not None and self.error_message is None:
            self.error_message = self.reason


@dataclasses.dataclass
class ImportReport:
    """Summarizes the results of an import operation."""

    summary: dict[str, dict[str, int]] = dataclasses.field(
        default_factory=lambda: {
            "collections": {"created": 0, "updated": 0, "skipped": 0, "failed": 0},
            "cards": {"created": 0, "updated": 0, "skipped": 0, "failed": 0},
            "dashboards": {"created": 0, "updated": 0, "skipped": 0, "failed": 0},
        }
    )
    results: list[ImportReportItem] = dataclasses.field(default_factory=list)
    items: list[ImportReportItem] = dataclasses.field(default_factory=list)

    def __post_init__(self) -> None:
        """Sync items and results fields for backward compatibility."""
        # If items is provided but results is empty, use items for results
        if self.items and not self.results:
            self.results = self.items
        # If results is provided but items is empty, use results for items
        elif self.results and not self.items:
            self.items = self.results
        # If both are empty, make them point to the same list
        elif not self.items and not self.results:
            shared_list: list[ImportReportItem] = []
            object.__setattr__(self, "items", shared_list)
            object.__setattr__(self, "results", shared_list)

    def add(self, item: ImportReportItem) -> None:
        """Adds an item to the report and updates the summary."""
        self.results.append(item)
        # Keep items in sync
        if self.items is not self.results:
            self.items.append(item)
        entity_key = f"{item.entity_type}s"
        if entity_key in self.summary:
            self.summary[entity_key][item.status] += 1
