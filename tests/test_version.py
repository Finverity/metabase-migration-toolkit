"""Tests for Metabase version support functionality."""

import pytest

from lib.config import ExportConfig, ImportConfig, _parse_metabase_version
from lib.constants import (
    DEFAULT_METABASE_VERSION,
    SUPPORTED_METABASE_VERSIONS,
    MetabaseVersion,
)
from lib.version import (
    APIEndpoints,
    DashboardConfig,
    MBQLConfig,
    V56Adapter,
    V57Adapter,
    get_version_adapter,
    get_version_config,
    validate_version_compatibility,
)


class TestMetabaseVersion:
    """Tests for MetabaseVersion enum."""

    def test_v56_value(self):
        """Test V56 version has correct value."""
        assert MetabaseVersion.V56.value == "v56"

    def test_v56_string(self):
        """Test V56 version string representation."""
        assert str(MetabaseVersion.V56) == "v56"

    def test_v57_value(self):
        """Test V57 version has correct value."""
        assert MetabaseVersion.V57.value == "v57"

    def test_v57_string(self):
        """Test V57 version string representation."""
        assert str(MetabaseVersion.V57) == "v57"

    def test_default_version(self):
        """Test default version is V56."""
        assert DEFAULT_METABASE_VERSION == MetabaseVersion.V56

    def test_supported_versions(self):
        """Test supported versions tuple."""
        assert "v56" in SUPPORTED_METABASE_VERSIONS
        assert "v57" in SUPPORTED_METABASE_VERSIONS
        assert len(SUPPORTED_METABASE_VERSIONS) >= 2


class TestParseMetabaseVersion:
    """Tests for version parsing function."""

    def test_parse_valid_version(self):
        """Test parsing valid version string."""
        version = _parse_metabase_version("v56")
        assert version == MetabaseVersion.V56

    def test_parse_uppercase_version(self):
        """Test parsing uppercase version string."""
        version = _parse_metabase_version("V56")
        assert version == MetabaseVersion.V56

    def test_parse_with_whitespace(self):
        """Test parsing version with whitespace."""
        version = _parse_metabase_version("  v56  ")
        assert version == MetabaseVersion.V56

    def test_parse_none_returns_default(self):
        """Test parsing None returns default version."""
        version = _parse_metabase_version(None)
        assert version == DEFAULT_METABASE_VERSION

    def test_parse_invalid_version_raises(self):
        """Test parsing invalid version raises ValueError."""
        with pytest.raises(ValueError, match="Unsupported Metabase version"):
            _parse_metabase_version("v99")


class TestExportConfigVersion:
    """Tests for ExportConfig with version support."""

    def test_default_version(self):
        """Test ExportConfig has default version."""
        config = ExportConfig(
            source_url="http://localhost:3000",
            export_dir="/tmp/export",
            source_session_token="token",
        )
        assert config.metabase_version == DEFAULT_METABASE_VERSION

    def test_explicit_version(self):
        """Test ExportConfig with explicit version."""
        config = ExportConfig(
            source_url="http://localhost:3000",
            export_dir="/tmp/export",
            source_session_token="token",
            metabase_version=MetabaseVersion.V56,
        )
        assert config.metabase_version == MetabaseVersion.V56


class TestImportConfigVersion:
    """Tests for ImportConfig with version support."""

    def test_default_version(self):
        """Test ImportConfig has default version."""
        config = ImportConfig(
            target_url="http://localhost:3001",
            export_dir="/tmp/export",
            db_map_path="/tmp/db_map.json",
            target_session_token="token",
        )
        assert config.metabase_version == DEFAULT_METABASE_VERSION

    def test_explicit_version(self):
        """Test ImportConfig with explicit version."""
        config = ImportConfig(
            target_url="http://localhost:3001",
            export_dir="/tmp/export",
            db_map_path="/tmp/db_map.json",
            target_session_token="token",
            metabase_version=MetabaseVersion.V56,
        )
        assert config.metabase_version == MetabaseVersion.V56


class TestAPIEndpoints:
    """Tests for APIEndpoints configuration."""

    def test_default_endpoints(self):
        """Test default endpoint values."""
        endpoints = APIEndpoints()
        assert endpoints.collection_tree == "/collection/tree"
        assert endpoints.collection == "/collection"
        assert endpoints.card == "/card"
        assert endpoints.dashboard == "/dashboard"
        assert endpoints.database == "/database"

    def test_endpoints_are_frozen(self):
        """Test APIEndpoints is frozen dataclass."""
        from dataclasses import FrozenInstanceError

        endpoints = APIEndpoints()
        with pytest.raises(FrozenInstanceError):
            endpoints.card = "/modified"


class TestMBQLConfig:
    """Tests for MBQLConfig configuration."""

    def test_default_config(self):
        """Test default MBQL config values."""
        config = MBQLConfig()
        assert config.source_table_key == "source-table"
        assert config.query_key == "query"
        assert config.database_key == "database"  # pragma: allowlist secret
        assert config.card_ref_prefix == "card__"
        assert "field" in config.field_ref_types
        assert "filter" in config.field_clauses


class TestDashboardConfig:
    """Tests for DashboardConfig configuration."""

    def test_default_config(self):
        """Test default dashboard config values."""
        config = DashboardConfig()
        assert config.supports_tabs is True
        assert config.parameters_key == "parameters"
        assert config.dashcards_key == "dashcards"
        assert "dashboard_id" in config.dashcard_excluded_fields


class TestVersionConfig:
    """Tests for VersionConfig configuration."""

    def test_get_v56_config(self):
        """Test getting V56 configuration."""
        config = get_version_config(MetabaseVersion.V56)
        assert config.version == MetabaseVersion.V56
        assert isinstance(config.api_endpoints, APIEndpoints)
        assert isinstance(config.mbql_config, MBQLConfig)
        assert isinstance(config.dashboard_config, DashboardConfig)

    def test_immutable_fields(self):
        """Test immutable fields are defined."""
        config = get_version_config(MetabaseVersion.V56)
        assert "id" in config.immutable_fields
        assert "created_at" in config.immutable_fields
        assert "creator_id" in config.immutable_fields


class TestV56Adapter:
    """Tests for V56 version adapter."""

    def test_adapter_creation(self):
        """Test creating V56 adapter."""
        adapter = get_version_adapter(MetabaseVersion.V56)
        assert isinstance(adapter, V56Adapter)
        assert adapter.version == MetabaseVersion.V56

    def test_transform_card_for_create(self):
        """Test card transformation for create."""
        adapter = get_version_adapter(MetabaseVersion.V56)
        card_data = {
            "id": 123,
            "name": "Test Card",
            "database_id": 1,
            "created_at": "2024-01-01",
        }
        result = adapter.transform_card_for_create(card_data)

        # Should remove immutable fields
        assert "id" not in result
        assert "created_at" not in result

        # Should preserve other fields
        assert result["name"] == "Test Card"
        assert result["database_id"] == 1

        # Should set table_id to None
        assert result["table_id"] is None

    def test_transform_dashboard_for_create(self):
        """Test dashboard transformation for create."""
        adapter = get_version_adapter(MetabaseVersion.V56)
        dashboard_data = {
            "id": 456,
            "name": "Test Dashboard",
            "dashcards": [{"id": 1}],
            "tabs": [{"id": 1}],
            "created_at": "2024-01-01",
        }
        result = adapter.transform_dashboard_for_create(dashboard_data)

        # Should remove immutable fields
        assert "id" not in result
        assert "created_at" not in result

        # Should remove dashcards and tabs
        assert "dashcards" not in result
        assert "tabs" not in result

        # Should preserve other fields
        assert result["name"] == "Test Dashboard"

    def test_extract_card_dependencies_single(self):
        """Test extracting single card dependency."""
        adapter = get_version_adapter(MetabaseVersion.V56)
        card_data = {"dataset_query": {"query": {"source-table": "card__123"}}}
        deps = adapter.extract_card_dependencies(card_data)
        assert deps == {123}

    def test_extract_card_dependencies_joins(self):
        """Test extracting dependencies from joins."""
        adapter = get_version_adapter(MetabaseVersion.V56)
        card_data = {
            "dataset_query": {
                "query": {
                    "source-table": 1,
                    "joins": [
                        {"source-table": "card__456"},
                        {"source-table": "card__789"},
                    ],
                }
            }
        }
        deps = adapter.extract_card_dependencies(card_data)
        assert deps == {456, 789}

    def test_extract_card_dependencies_mixed(self):
        """Test extracting mixed dependencies."""
        adapter = get_version_adapter(MetabaseVersion.V56)
        card_data = {
            "dataset_query": {
                "query": {
                    "source-table": "card__100",
                    "joins": [
                        {"source-table": "card__200"},
                    ],
                }
            }
        }
        deps = adapter.extract_card_dependencies(card_data)
        assert deps == {100, 200}

    def test_extract_card_dependencies_no_deps(self):
        """Test extracting dependencies when there are none."""
        adapter = get_version_adapter(MetabaseVersion.V56)
        card_data = {"dataset_query": {"query": {"source-table": 1}}}
        deps = adapter.extract_card_dependencies(card_data)
        assert deps == set()


class TestV57Adapter:
    """Tests for V57 version adapter."""

    def test_adapter_creation(self):
        """Test creating V57 adapter."""
        adapter = get_version_adapter(MetabaseVersion.V57)
        assert isinstance(adapter, V57Adapter)
        assert adapter.version == MetabaseVersion.V57

    def test_v57_config_uses_stages(self):
        """Test V57 config has uses_stages=True."""
        config = get_version_config(MetabaseVersion.V57)
        assert config.mbql_config.uses_stages is True

    def test_v57_config_filter_key(self):
        """Test V57 config has filters key (plural)."""
        config = get_version_config(MetabaseVersion.V57)
        assert config.mbql_config.filter_key == "filters"

    def test_transform_card_for_create(self):
        """Test card transformation for v57 create."""
        adapter = get_version_adapter(MetabaseVersion.V57)
        card_data = {
            "id": 123,
            "name": "Test Card",
            "database_id": 1,
            "created_at": "2024-01-01",
        }
        result = adapter.transform_card_for_create(card_data)

        assert "id" not in result
        assert "created_at" not in result
        assert result["name"] == "Test Card"
        assert result["table_id"] is None

    def test_transform_dashboard_for_create(self):
        """Test dashboard transformation for v57 create."""
        adapter = get_version_adapter(MetabaseVersion.V57)
        dashboard_data = {
            "id": 456,
            "name": "Test Dashboard",
            "dashcards": [{"id": 1}],
            "tabs": [{"id": 1}],
        }
        result = adapter.transform_dashboard_for_create(dashboard_data)

        assert "id" not in result
        assert "dashcards" not in result
        assert "tabs" not in result
        assert result["name"] == "Test Dashboard"

    def test_extract_card_dependencies_v57_stages(self):
        """Test extracting card dependencies from v57 stages."""
        adapter = get_version_adapter(MetabaseVersion.V57)
        card_data = {
            "dataset_query": {
                "lib/type": "mbql/query",
                "stages": [
                    {"source-table": "card__123"},
                    {"joins": [{"source-table": "card__456"}]},
                ],
            }
        }
        deps = adapter.extract_card_dependencies(card_data)
        assert deps == {123, 456}

    def test_extract_card_dependencies_v57_native(self):
        """Test extracting card dependencies from v57 native queries."""
        adapter = get_version_adapter(MetabaseVersion.V57)
        card_data = {
            "dataset_query": {
                "lib/type": "mbql/query",
                "stages": [
                    {
                        "lib/type": "mbql.stage/native",
                        "template-tags": {"50-model": {"type": "card", "card-id": 50}},
                    }
                ],
            }
        }
        deps = adapter.extract_card_dependencies(card_data)
        assert deps == {50}

    def test_extract_card_dependencies_v57_fallback(self):
        """Test v57 adapter falls back to v56 style if no stages."""
        adapter = get_version_adapter(MetabaseVersion.V57)
        card_data = {"dataset_query": {"query": {"source-table": "card__789"}}}
        deps = adapter.extract_card_dependencies(card_data)
        assert deps == {789}


class TestVersionCompatibility:
    """Tests for version compatibility validation."""

    def test_same_version_compatible_v56(self):
        """Test same versions are compatible (v56)."""
        validate_version_compatibility(MetabaseVersion.V56, MetabaseVersion.V56)

    def test_same_version_compatible_v57(self):
        """Test same versions are compatible (v57)."""
        validate_version_compatibility(MetabaseVersion.V57, MetabaseVersion.V57)

    def test_different_versions_incompatible(self):
        """Test different versions raise error."""
        with pytest.raises(ValueError, match="Version mismatch"):
            validate_version_compatibility(MetabaseVersion.V56, MetabaseVersion.V57)
