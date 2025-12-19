"""Constants used throughout the Metabase Migration Toolkit.

Centralizes magic strings and values to improve maintainability.
"""

from enum import Enum
from typing import Literal

__all__ = [
    "SUPPORTED_METABASE_VERSIONS",
]
# =============================================================================
# Metabase Version Support
# =============================================================================


class MetabaseVersion(str, Enum):
    """Supported Metabase versions.

    Each version may have different API endpoints, MBQL query formats,
    and dashboard structures. The toolkit adjusts its behavior based on
    the configured version.

    Version differences:
    - V56: Legacy MBQL 4 format with `:type` field, `:native.query` structure
    - V57: MBQL 5 format with `:lib/type`, `:stages` array structure
    """

    V56 = "v56"
    V57 = "v57"

    def __str__(self) -> str:
        """Return the version string for display."""
        return self.value


# Default Metabase version (current supported version)
DEFAULT_METABASE_VERSION = MetabaseVersion.V56

# Supported version strings for CLI validation
SUPPORTED_METABASE_VERSIONS: tuple[str, ...] = tuple(v.value for v in MetabaseVersion)

# Type alias for version literals
MetabaseVersionLiteral = Literal["v56", "v57"]


# =============================================================================
# Card and Query Constants
# =============================================================================

# Card reference prefix used in source-table references (e.g., "card__123")
CARD_REF_PREFIX = "card__"

# MBQL query keys
SOURCE_TABLE_KEY = "source-table"
QUERY_KEY = "query"
DATABASE_KEY = "database"  # pragma: allowlist secret
JOINS_KEY = "joins"

# Field reference types in MBQL
FIELD_REF_TYPES = ("field", "field-id")

# Query clause keys that may contain field references
FIELD_CONTAINING_CLAUSES = (
    "filter",
    "aggregation",
    "breakout",
    "order-by",
    "fields",
    "expressions",
)

# Fields to remove when creating new items via API
IMMUTABLE_FIELDS = frozenset(
    {
        "id",
        "creator_id",
        "creator",
        "created_at",
        "updated_at",
        "made_public_by_id",
        "public_uuid",
        "moderation_reviews",
        "can_write",
    }
)

# Fields to exclude from dashcard payloads
# Note: dashboard_tab_id is NOT excluded - it's remapped during import
DASHCARD_EXCLUDED_FIELDS = frozenset(
    {
        "dashboard_id",
        "created_at",
        "updated_at",
        "entity_id",
        "card",
        "action_id",
        "collection_authority_level",
    }
)

# Essential dashcard positioning fields
DASHCARD_POSITION_FIELDS = ("col", "row", "size_x", "size_y")

# Built-in permission groups
BUILTIN_PERMISSION_GROUPS = frozenset({"All Users", "Administrators"})

# Model types in Metabase API
MODEL_TYPE_CARD = "card"
MODEL_TYPE_DATASET = "dataset"
MODEL_TYPE_DASHBOARD = "dashboard"

# Conflict resolution strategies
CONFLICT_SKIP = "skip"
CONFLICT_OVERWRITE = "overwrite"
CONFLICT_RENAME = "rename"

# Collection constants
ROOT_COLLECTION = "root"
COLLECTIONS_BASE_PATH = "collections"
DEPENDENCIES_FOLDER = "dependencies"

# File naming patterns
CARD_FILE_PATTERN = "card_{id}_{slug}.json"
DASHBOARD_FILE_PATTERN = "dash_{id}_{slug}.json"
COLLECTION_META_FILE = "_collection.json"
MANIFEST_FILE = "manifest.json"

# Native query constants
NATIVE_KEY = "native"
TEMPLATE_TAGS_KEY = "template-tags"
STAGES_KEY = "stages"
LIB_TYPE_KEY = "lib/type"

# MBQL 5 (v57+) stage types
MBQL_QUERY_TYPE = "mbql/query"
MBQL_STAGE_NATIVE = "mbql.stage/native"
MBQL_STAGE_MBQL = "mbql.stage/mbql"

# v57 MBQL 5 filter key (plural instead of singular)
FILTERS_KEY = "filters"

# v57 MBQL 5 specific keys
V57_LIB_EXPRESSION_NAME = "lib/expression-name"
V57_LIB_UUID = "lib/uuid"
V57_BASE_TYPE = "base-type"
V57_EFFECTIVE_TYPE = "effective-type"
V57_SOURCE_CARD_KEY = "source-card"  # v57 uses source-card (int) instead of source-table: "card__N"

# v57 query clause keys that may contain field references
# Some clauses use different names or structures in v57
V57_FIELD_CONTAINING_CLAUSES = (
    "filters",  # v57 uses "filters" (plural) instead of "filter"
    "aggregation",
    "breakout",
    "order-by",
    "fields",
    "expressions",
)

# Native query card reference pattern: {{#123-model-name}}
# Regex pattern to match card references in SQL queries
NATIVE_CARD_REF_PATTERN = r"\{\{#(\d+)-[^}]+\}\}"
NATIVE_CARD_REF_FULL_PATTERN = r"\{\{#(\d+)(-[^}]+)\}\}"

# API endpoints
API_COLLECTION_TREE = "/collection/tree"
API_COLLECTION = "/collection"
API_CARD = "/card"
API_DASHBOARD = "/dashboard"
API_DATABASE = "/database"
API_PERMISSIONS_GROUP = "/permissions/group"
API_PERMISSIONS_GRAPH = "/permissions/graph"
API_COLLECTION_GRAPH = "/collection/graph"
