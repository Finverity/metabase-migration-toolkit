"""
Metabase Migration Toolkit

A robust toolkit for exporting and importing Metabase content (collections,
questions, and dashboards) between instances.

Features:
- Recursive export of collection hierarchies
- Intelligent database remapping
- Conflict resolution strategies
- Dry-run mode for safe previews
- Comprehensive logging and error handling
- Retry logic with exponential backoff
"""

__version__ = "1.0.0"
__author__ = "Metabase Migration Toolkit Contributors"
__license__ = "MIT"

from lib.client import MetabaseAPIError, MetabaseClient
from lib.config import ExportConfig, ImportConfig
from lib.models import Card, Collection, Dashboard, Manifest

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
]
