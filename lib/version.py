"""Version-specific behavior adapters for Metabase API compatibility.

This module provides version-aware configurations for handling differences
in API endpoints, MBQL query formats, and dashboard structures across
different Metabase versions.

The toolkit uses strict version validation to ensure compatibility
between source and target Metabase instances during migration.
"""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from lib.constants import MetabaseVersion

logger = logging.getLogger("metabase_migration")


# =============================================================================
# Version-Specific Configuration Data Classes
# =============================================================================


@dataclass(frozen=True)
class APIEndpoints:
    """API endpoint paths for a specific Metabase version.

    These endpoints may change between Metabase versions. This class
    centralizes all endpoint definitions for consistent version handling.
    """

    # Collection endpoints
    collection_tree: str = "/collection/tree"
    collection: str = "/collection"
    collection_items: str = "/collection/{id}/items"
    collection_graph: str = "/collection/graph"

    # Card endpoints
    card: str = "/card"
    card_by_id: str = "/card/{id}"

    # Dashboard endpoints
    dashboard: str = "/dashboard"
    dashboard_by_id: str = "/dashboard/{id}"

    # Database endpoints
    database: str = "/database"
    database_metadata: str = "/database/{id}/metadata"
    table: str = "/table/{id}"
    field: str = "/field/{id}"

    # Permission endpoints
    permissions_group: str = "/permissions/group"
    permissions_graph: str = "/permissions/graph"

    # Session endpoints
    session: str = "/session"


@dataclass(frozen=True)
class MBQLConfig:
    """MBQL query format configuration for a specific Metabase version.

    MBQL (Metabase Query Language) structure may vary between versions.
    This class defines the expected query structure for proper parsing
    and remapping.
    """

    # Field reference formats
    field_ref_types: tuple[str, ...] = ("field", "field-id")

    # Query structure keys
    source_table_key: str = "source-table"
    query_key: str = "query"
    database_key: str = "database"
    joins_key: str = "joins"

    # Field-containing clause keys
    field_clauses: tuple[str, ...] = (
        "filter",
        "aggregation",
        "breakout",
        "order-by",
        "fields",
        "expressions",
    )

    # Card reference prefix (e.g., "card__123")
    card_ref_prefix: str = "card__"

    # Native query key
    native_query_key: str = "native"

    # Template tags key for native queries
    template_tags_key: str = "template-tags"

    # MBQL 5 specific keys (v57+)
    stages_key: str = "stages"
    lib_type_key: str = "lib/type"

    # Whether this version uses MBQL 5 format with stages
    uses_stages: bool = False

    # Filter key (singular in v56, plural in v57)
    filter_key: str = "filter"


@dataclass(frozen=True)
class DashboardConfig:
    """Dashboard structure configuration for a specific Metabase version.

    Dashboard structure (tabs, filters, dashcards) may vary between versions.
    This class defines the expected dashboard structure for proper handling.
    """

    # Dashcard fields to exclude when creating/updating
    dashcard_excluded_fields: frozenset[str] = field(
        default_factory=lambda: frozenset(
            {
                "dashboard_id",
                "created_at",
                "updated_at",
                "entity_id",
                "card",
                "action_id",
                "collection_authority_level",
                "dashboard_tab_id",
            }
        )
    )

    # Essential dashcard positioning fields
    dashcard_position_fields: tuple[str, ...] = ("col", "row", "size_x", "size_y")

    # Dashboard tabs support
    supports_tabs: bool = True

    # Dashboard parameter structure key
    parameters_key: str = "parameters"

    # Dashcards key in dashboard payload
    dashcards_key: str = "dashcards"

    # Ordered cards key (legacy, still used in some contexts)
    ordered_cards_key: str = "ordered_cards"


@dataclass(frozen=True)
class VersionConfig:
    """Complete configuration for a specific Metabase version.

    Aggregates all version-specific configurations into a single object.
    """

    version: MetabaseVersion
    api_endpoints: APIEndpoints
    mbql_config: MBQLConfig
    dashboard_config: DashboardConfig

    # Immutable fields to remove when creating new items via API
    immutable_fields: frozenset[str] = field(
        default_factory=lambda: frozenset(
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
    )


# =============================================================================
# Version Adapter Abstract Base Class
# =============================================================================


class VersionAdapter(ABC):
    """Abstract base class for version-specific behavior adapters.

    Subclasses implement version-specific logic for API interactions,
    query transformations, and data structure handling.
    """

    def __init__(self, config: VersionConfig) -> None:
        """Initialize the version adapter.

        Args:
            config: Version-specific configuration.
        """
        self._config = config

    @property
    def version(self) -> MetabaseVersion:
        """Return the Metabase version this adapter handles."""
        return self._config.version

    @property
    def config(self) -> VersionConfig:
        """Return the version configuration."""
        return self._config

    @property
    def endpoints(self) -> APIEndpoints:
        """Return API endpoint configurations."""
        return self._config.api_endpoints

    @property
    def mbql(self) -> MBQLConfig:
        """Return MBQL query configurations."""
        return self._config.mbql_config

    @property
    def dashboard(self) -> DashboardConfig:
        """Return dashboard structure configurations."""
        return self._config.dashboard_config

    @abstractmethod
    def transform_card_for_create(self, card_data: dict[str, Any]) -> dict[str, Any]:
        """Transform card data for creation in this version.

        Args:
            card_data: Raw card data from export.

        Returns:
            Transformed card data ready for API creation.
        """
        pass

    @abstractmethod
    def transform_dashboard_for_create(self, dashboard_data: dict[str, Any]) -> dict[str, Any]:
        """Transform dashboard data for creation in this version.

        Args:
            dashboard_data: Raw dashboard data from export.

        Returns:
            Transformed dashboard data ready for API creation.
        """
        pass

    @abstractmethod
    def extract_card_dependencies(self, card_data: dict[str, Any]) -> set[int]:
        """Extract card IDs that this card depends on.

        Args:
            card_data: Card data to analyze.

        Returns:
            Set of card IDs this card references.
        """
        pass

    def clean_for_create(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Remove immutable fields before creating an item.

        Args:
            payload: Original payload with potential immutable fields.

        Returns:
            Cleaned payload suitable for creation.
        """
        return {k: v for k, v in payload.items() if k not in self._config.immutable_fields}


# =============================================================================
# Version 56 Adapter Implementation
# =============================================================================


class V56Adapter(VersionAdapter):
    """Version adapter for Metabase v56.

    Implements version-specific behaviors for Metabase version 56.
    """

    def transform_card_for_create(self, card_data: dict[str, Any]) -> dict[str, Any]:
        """Transform card data for v56 creation.

        Args:
            card_data: Raw card data from export.

        Returns:
            Transformed card data ready for v56 API creation.
        """
        result = self.clean_for_create(card_data.copy())

        # v56 specific: Set table_id to null (auto-populated by Metabase)
        result["table_id"] = None

        return result

    def transform_dashboard_for_create(self, dashboard_data: dict[str, Any]) -> dict[str, Any]:
        """Transform dashboard data for v56 creation.

        Args:
            dashboard_data: Raw dashboard data from export.

        Returns:
            Transformed dashboard data ready for v56 API creation.
        """
        result = self.clean_for_create(dashboard_data.copy())

        # v56 specific: Remove dashcards and tabs from initial creation
        # They are handled separately via PUT
        result.pop("dashcards", None)
        result.pop("tabs", None)
        result.pop("ordered_cards", None)

        return result

    def extract_card_dependencies(self, card_data: dict[str, Any]) -> set[int]:
        """Extract card dependencies for v56.

        In v56, card references appear in:
        - dataset_query.query.source-table as "card__123"
        - dataset_query.query.joins[].source-table as "card__123"

        Args:
            card_data: Card data to analyze.

        Returns:
            Set of card IDs this card references.
        """
        dependencies: set[int] = set()
        prefix = self.mbql.card_ref_prefix

        dataset_query = card_data.get("dataset_query", {})
        query = dataset_query.get(self.mbql.query_key, {})

        # Check source-table for card references
        source_table = query.get(self.mbql.source_table_key)
        if isinstance(source_table, str) and source_table.startswith(prefix):
            try:
                card_id = int(source_table.replace(prefix, ""))
                dependencies.add(card_id)
            except ValueError:
                logger.warning(f"Invalid card reference format: {source_table}")

        # Check joins for card references
        joins = query.get(self.mbql.joins_key, [])
        for join in joins:
            join_source = join.get(self.mbql.source_table_key)
            if isinstance(join_source, str) and join_source.startswith(prefix):
                try:
                    card_id = int(join_source.replace(prefix, ""))
                    dependencies.add(card_id)
                except ValueError:
                    logger.warning(f"Invalid card reference in join: {join_source}")

        return dependencies


# =============================================================================
# Version 57 Adapter Implementation
# =============================================================================


class V57Adapter(VersionAdapter):
    """Version adapter for Metabase v57.

    Implements version-specific behaviors for Metabase version 57.
    v57 uses MBQL 5 format with stages array instead of flat query structure.
    """

    def transform_card_for_create(self, card_data: dict[str, Any]) -> dict[str, Any]:
        """Transform card data for v57 creation.

        Args:
            card_data: Raw card data from export.

        Returns:
            Transformed card data ready for v57 API creation.
        """
        result = self.clean_for_create(card_data.copy())

        # v57 specific: Set table_id to null (auto-populated by Metabase)
        result["table_id"] = None

        return result

    def transform_dashboard_for_create(self, dashboard_data: dict[str, Any]) -> dict[str, Any]:
        """Transform dashboard data for v57 creation.

        Args:
            dashboard_data: Raw dashboard data from export.

        Returns:
            Transformed dashboard data ready for v57 API creation.
        """
        result = self.clean_for_create(dashboard_data.copy())

        # v57 specific: Remove dashcards and tabs from initial creation
        # They are handled separately via PUT
        result.pop("dashcards", None)
        result.pop("tabs", None)
        result.pop("ordered_cards", None)

        return result

    def extract_card_dependencies(self, card_data: dict[str, Any]) -> set[int]:
        """Extract card dependencies for v57.

        In v57 (MBQL 5), card references appear in:
        - dataset_query.stages[].source-table as "card__123"
        - dataset_query.stages[].joins[].source-table as "card__123"
        - Native queries: template-tags with type "card"

        Args:
            card_data: Card data to analyze.

        Returns:
            Set of card IDs this card references.
        """
        dependencies: set[int] = set()
        prefix = self.mbql.card_ref_prefix

        dataset_query = card_data.get("dataset_query", {})

        # Check if this is MBQL 5 format (has stages)
        stages = dataset_query.get(self.mbql.stages_key, [])
        if stages:
            for stage in stages:
                # Check source-table in each stage
                source_table = stage.get(self.mbql.source_table_key)
                if isinstance(source_table, str) and source_table.startswith(prefix):
                    try:
                        card_id = int(source_table.replace(prefix, ""))
                        dependencies.add(card_id)
                    except ValueError:
                        logger.warning(f"Invalid card reference format: {source_table}")

                # Check joins in each stage
                joins = stage.get(self.mbql.joins_key, [])
                for join in joins:
                    join_source = join.get(self.mbql.source_table_key)
                    if isinstance(join_source, str) and join_source.startswith(prefix):
                        try:
                            card_id = int(join_source.replace(prefix, ""))
                            dependencies.add(card_id)
                        except ValueError:
                            logger.warning(f"Invalid card reference in join: {join_source}")

                # Check template-tags for native stages (card references)
                template_tags = stage.get(self.mbql.template_tags_key, {})
                for _tag_name, tag_data in template_tags.items():
                    if isinstance(tag_data, dict) and tag_data.get("type") == "card":
                        card_id_value = tag_data.get("card-id")
                        if card_id_value is not None and isinstance(card_id_value, int):
                            dependencies.add(card_id_value)
        else:
            # Fallback to v56-style query structure
            query = dataset_query.get(self.mbql.query_key, {})

            # Check source-table for card references
            source_table = query.get(self.mbql.source_table_key)
            if isinstance(source_table, str) and source_table.startswith(prefix):
                try:
                    card_id = int(source_table.replace(prefix, ""))
                    dependencies.add(card_id)
                except ValueError:
                    logger.warning(f"Invalid card reference format: {source_table}")

            # Check joins for card references
            joins = query.get(self.mbql.joins_key, [])
            for join in joins:
                join_source = join.get(self.mbql.source_table_key)
                if isinstance(join_source, str) and join_source.startswith(prefix):
                    try:
                        card_id = int(join_source.replace(prefix, ""))
                        dependencies.add(card_id)
                    except ValueError:
                        logger.warning(f"Invalid card reference in join: {join_source}")

            # Check native query template-tags (v56 style)
            native = dataset_query.get(self.mbql.native_query_key, {})
            if isinstance(native, dict):
                template_tags = native.get(self.mbql.template_tags_key, {})
                for _tag_name, tag_data in template_tags.items():
                    if isinstance(tag_data, dict) and tag_data.get("type") == "card":
                        card_id_value = tag_data.get("card-id")
                        if card_id_value is not None and isinstance(card_id_value, int):
                            dependencies.add(card_id_value)

        return dependencies


# =============================================================================
# Version Adapter Factory
# =============================================================================


# Version configurations registry
_VERSION_CONFIGS: dict[MetabaseVersion, VersionConfig] = {
    MetabaseVersion.V56: VersionConfig(
        version=MetabaseVersion.V56,
        api_endpoints=APIEndpoints(),
        mbql_config=MBQLConfig(),
        dashboard_config=DashboardConfig(),
    ),
    MetabaseVersion.V57: VersionConfig(
        version=MetabaseVersion.V57,
        api_endpoints=APIEndpoints(),
        mbql_config=MBQLConfig(
            uses_stages=True,
            filter_key="filters",
        ),
        dashboard_config=DashboardConfig(),
    ),
}


def get_version_config(version: MetabaseVersion) -> VersionConfig:
    """Get the configuration for a specific Metabase version.

    Args:
        version: The Metabase version.

    Returns:
        Version-specific configuration.

    Raises:
        ValueError: If the version is not supported.
    """
    if version not in _VERSION_CONFIGS:
        raise ValueError(f"Unsupported Metabase version: {version}")
    return _VERSION_CONFIGS[version]


def get_version_adapter(version: MetabaseVersion) -> VersionAdapter:
    """Get the adapter for a specific Metabase version.

    Args:
        version: The Metabase version.

    Returns:
        Version-specific adapter instance.

    Raises:
        ValueError: If the version is not supported.
    """
    config = get_version_config(version)

    if version == MetabaseVersion.V56:
        return V56Adapter(config)

    if version == MetabaseVersion.V57:
        return V57Adapter(config)

    raise ValueError(f"No adapter implementation for version: {version}")


def validate_version_compatibility(
    source_version: MetabaseVersion,
    target_version: MetabaseVersion,
) -> None:
    """Validate that source and target versions are compatible.

    With strict validation, source and target must be the same version.

    Args:
        source_version: Version of the source Metabase instance.
        target_version: Version of the target Metabase instance.

    Raises:
        ValueError: If versions are incompatible.
    """
    if source_version != target_version:
        raise ValueError(
            f"Version mismatch: source version '{source_version}' "
            f"is not compatible with target version '{target_version}'. "
            f"Both instances must be running the same Metabase version."
        )

    logger.info(f"Version compatibility validated: {source_version}")
