"""Entity handlers for Metabase migration.

Each handler manages the import/export of a specific entity type
(collections, cards, dashboards, permissions).
"""

from lib.handlers.base import BaseHandler, ImportContext
from lib.handlers.card import CardHandler
from lib.handlers.collection import CollectionHandler
from lib.handlers.dashboard import DashboardHandler
from lib.handlers.permissions import PermissionsHandler

__all__ = [
    "BaseHandler",
    "ImportContext",
    "CollectionHandler",
    "CardHandler",
    "DashboardHandler",
    "PermissionsHandler",
]
