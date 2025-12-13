"""Metabase Migration Toolkit.

A robust toolkit for exporting and importing Metabase content (collections,
questions, and dashboards) between instances.

Features:
- Recursive export of collection hierarchies
- Intelligent database remapping
- Conflict resolution strategies
- Dry-run mode for safe previews
- Comprehensive logging and error handling
- Retry logic with exponential backoff
- Version-aware migration support
"""

__version__ = "1.0.0"
__author__ = "Metabase Migration Toolkit Contributors"
__license__ = "MIT"

from lib.client import MetabaseAPIError, MetabaseClient
from lib.config import ExportConfig, ImportConfig
from lib.constants import (
    DEFAULT_METABASE_VERSION,
    SUPPORTED_METABASE_VERSIONS,
    MetabaseVersion,
)
from lib.models_core import Card, Collection, Dashboard, Manifest
from lib.version import (
    VersionAdapter,
    VersionConfig,
    get_version_adapter,
    get_version_config,
    validate_version_compatibility,
)

__all__ = [
    # Version info
    "__version__",
    "__author__",
    "__license__",
    # Client
    "MetabaseClient",
    "MetabaseAPIError",
    # Configuration
    "ExportConfig",
    "ImportConfig",
    # Models
    "Collection",
    "Card",
    "Dashboard",
    "Manifest",
    # Metabase Version Support
    "MetabaseVersion",
    "DEFAULT_METABASE_VERSION",
    "SUPPORTED_METABASE_VERSIONS",
    "VersionConfig",
    "VersionAdapter",
    "get_version_config",
    "get_version_adapter",
    "validate_version_compatibility",
]
