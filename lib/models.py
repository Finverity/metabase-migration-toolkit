"""
Defines the data classes for Metabase objects and the migration manifest.
Using typed dataclasses provides clarity and reduces errors.
"""
from __future__ import annotations

import dataclasses
from typing import Any, Dict, List, Literal, Optional, Set

# --- Core Metabase Object Models ---

@dataclasses.dataclass
class Collection:
    """Represents a Metabase collection."""
    id: int
    name: str
    slug: str
    description: Optional[str] = None
    parent_id: Optional[int] = None
    personal_owner_id: Optional[int] = None
    path: str = ""  # Filesystem path, populated during export

@dataclasses.dataclass
class Card:
    """Represents a Metabase card (question/model)."""
    id: int
    name: str
    collection_id: Optional[int] = None
    database_id: Optional[int] = None
    file_path: str = ""
    checksum: str = ""
    archived: bool = False
    dataset_query: Optional[Dict[str, Any]] = None

@dataclasses.dataclass
class Dashboard:
    """Represents a Metabase dashboard."""
    id: int
    name: str
    collection_id: Optional[int] = None
    ordered_cards: List[int] = dataclasses.field(default_factory=list)
    file_path: str = ""
    checksum: str = ""
    archived: bool = False

# --- Manifest Models ---

@dataclasses.dataclass
class ManifestMeta:
    """Metadata about the export process."""
    source_url: str
    export_timestamp: str
    tool_version: str
    cli_args: Dict[str, Any]

@dataclasses.dataclass
class Manifest:
    """The root object for the manifest.json file."""
    meta: ManifestMeta
    databases: Dict[int, str] = dataclasses.field(default_factory=dict)
    collections: List[Collection] = dataclasses.field(default_factory=list)
    cards: List[Card] = dataclasses.field(default_factory=list)
    dashboards: List[Dashboard] = dataclasses.field(default_factory=list)

# --- Import-specific Models ---

@dataclasses.dataclass
class DatabaseMap:
    """Represents the database mapping file."""
    by_id: Dict[str, int] = dataclasses.field(default_factory=dict)
    by_name: Dict[str, int] = dataclasses.field(default_factory=dict)

@dataclasses.dataclass
class UnmappedDatabase:
    """Represents a source database that could not be mapped to a target."""
    source_db_id: int
    source_db_name: str
    card_ids: Set[int] = dataclasses.field(default_factory=set)

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
    actions: List[ImportAction] = dataclasses.field(default_factory=list)
    unmapped_databases: List[UnmappedDatabase] = dataclasses.field(default_factory=list)

@dataclasses.dataclass
class ImportReportItem:
    """Represents the result of a single item import."""
    entity_type: Literal["collection", "card", "dashboard"]
    status: Literal["created", "updated", "skipped", "failed", "success", "error"]
    source_id: int
    target_id: Optional[int]
    name: str
    reason: Optional[str] = None
    error_message: Optional[str] = None  # Alias for reason, kept for backward compatibility

    def __post_init__(self):
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
    summary: Dict[str, Dict[str, int]] = dataclasses.field(default_factory=lambda: {
        "collections": {"created": 0, "updated": 0, "skipped": 0, "failed": 0},
        "cards": {"created": 0, "updated": 0, "skipped": 0, "failed": 0},
        "dashboards": {"created": 0, "updated": 0, "skipped": 0, "failed": 0},
    })
    results: List[ImportReportItem] = dataclasses.field(default_factory=list)
    items: List[ImportReportItem] = dataclasses.field(default_factory=list)

    def __post_init__(self):
        """Sync items and results fields for backward compatibility."""
        # If items is provided but results is empty, use items for results
        if self.items and not self.results:
            self.results = self.items
        # If results is provided but items is empty, use results for items
        elif self.results and not self.items:
            self.items = self.results
        # If both are empty, make them point to the same list
        elif not self.items and not self.results:
            shared_list: List[ImportReportItem] = []
            object.__setattr__(self, 'items', shared_list)
            object.__setattr__(self, 'results', shared_list)

    def add(self, item: ImportReportItem):
        """Adds an item to the report and updates the summary."""
        self.results.append(item)
        # Keep items in sync
        if self.items is not self.results:
            self.items.append(item)
        entity_key = f"{item.entity_type}s"
        if entity_key in self.summary:
            self.summary[entity_key][item.status] += 1
