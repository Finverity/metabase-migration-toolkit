"""Data models for Metabase Migration Toolkit.

Re-exports all models from the original models.py for backward compatibility.
"""

# Re-export everything from the original models module
from lib.models_core import (
    Card,
    Collection,
    Dashboard,
    DatabaseMap,
    ImportAction,
    ImportPlan,
    ImportReport,
    ImportReportItem,
    Manifest,
    ManifestMeta,
    PermissionGroup,
    UnmappedDatabase,
)

__all__ = [
    # Core Metabase objects
    "Collection",
    "Card",
    "Dashboard",
    "PermissionGroup",
    # Manifest
    "ManifestMeta",
    "Manifest",
    # Import-specific
    "DatabaseMap",
    "UnmappedDatabase",
    "ImportAction",
    "ImportPlan",
    "ImportReportItem",
    "ImportReport",
]
