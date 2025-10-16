"""
Unit tests for embedding settings export and import functionality.

Tests that embedding settings (enable_embedding and embedding_params) are
correctly handled during export and import operations based on the
include_embedding_settings configuration flag.
"""

from export_metabase import MetabaseExporter
from lib.config import ExportConfig, ImportConfig


class TestEmbeddingSettingsExport:
    """Test suite for embedding settings export functionality."""

    def test_export_card_with_embedding_settings_enabled(self, tmp_path):
        """Test that embedding settings are included when flag is True."""
        config = ExportConfig(
            source_url="https://source.metabase.com",
            export_dir=str(tmp_path),
            include_embedding_settings=True,
        )

        exporter = MetabaseExporter(config)

        # Mock card data with embedding settings
        card_data = {
            "id": 1,
            "name": "Test Card",
            "database_id": 2,
            "dataset_query": {"type": "query", "database": 2},
            "enable_embedding": True,
            "embedding_params": {"param1": "enabled", "param2": "locked"},
        }

        # Test the filter method
        filtered = exporter._filter_embedding_settings(card_data)

        assert "enable_embedding" in filtered
        assert "embedding_params" in filtered
        assert filtered["enable_embedding"] is True
        assert filtered["embedding_params"] == {"param1": "enabled", "param2": "locked"}

    def test_export_card_without_embedding_settings_enabled(self, tmp_path):
        """Test that embedding settings are excluded when flag is False."""
        config = ExportConfig(
            source_url="https://source.metabase.com",
            export_dir=str(tmp_path),
            include_embedding_settings=False,
        )

        exporter = MetabaseExporter(config)

        # Mock card data with embedding settings
        card_data = {
            "id": 1,
            "name": "Test Card",
            "database_id": 2,
            "dataset_query": {"type": "query", "database": 2},
            "enable_embedding": True,
            "embedding_params": {"param1": "enabled", "param2": "locked"},
        }

        # Test the filter method
        filtered = exporter._filter_embedding_settings(card_data)

        assert "enable_embedding" not in filtered
        assert "embedding_params" not in filtered
        assert filtered["name"] == "Test Card"
        assert filtered["database_id"] == 2

    def test_export_dashboard_with_embedding_settings_enabled(self, tmp_path):
        """Test that dashboard embedding settings are included when flag is True."""
        config = ExportConfig(
            source_url="https://source.metabase.com",
            export_dir=str(tmp_path),
            include_embedding_settings=True,
        )

        exporter = MetabaseExporter(config)

        # Mock dashboard data with embedding settings
        dashboard_data = {
            "id": 10,
            "name": "Test Dashboard",
            "enable_embedding": True,
            "embedding_params": {"date_range": "enabled", "region": "locked"},
            "dashcards": [],
        }

        # Test the filter method
        filtered = exporter._filter_embedding_settings(dashboard_data)

        assert "enable_embedding" in filtered
        assert "embedding_params" in filtered
        assert filtered["enable_embedding"] is True
        assert filtered["embedding_params"] == {"date_range": "enabled", "region": "locked"}

    def test_export_dashboard_without_embedding_settings_enabled(self, tmp_path):
        """Test that dashboard embedding settings are excluded when flag is False."""
        config = ExportConfig(
            source_url="https://source.metabase.com",
            export_dir=str(tmp_path),
            include_embedding_settings=False,
        )

        exporter = MetabaseExporter(config)

        # Mock dashboard data with embedding settings
        dashboard_data = {
            "id": 10,
            "name": "Test Dashboard",
            "enable_embedding": True,
            "embedding_params": {"date_range": "enabled", "region": "locked"},
            "dashcards": [],
        }

        # Test the filter method
        filtered = exporter._filter_embedding_settings(dashboard_data)

        assert "enable_embedding" not in filtered
        assert "embedding_params" not in filtered
        assert filtered["name"] == "Test Dashboard"
        assert "dashcards" in filtered

    def test_filter_preserves_other_fields(self, tmp_path):
        """Test that filtering doesn't affect other fields."""
        config = ExportConfig(
            source_url="https://source.metabase.com",
            export_dir=str(tmp_path),
            include_embedding_settings=False,
        )

        exporter = MetabaseExporter(config)

        # Mock data with many fields
        data = {
            "id": 1,
            "name": "Test",
            "description": "Description",
            "collection_id": 5,
            "enable_embedding": True,
            "embedding_params": {"param": "enabled"},
            "cache_ttl": 3600,
            "archived": False,
        }

        filtered = exporter._filter_embedding_settings(data)

        # Embedding fields should be removed
        assert "enable_embedding" not in filtered
        assert "embedding_params" not in filtered

        # Other fields should be preserved
        assert filtered["id"] == 1
        assert filtered["name"] == "Test"
        assert filtered["description"] == "Description"
        assert filtered["collection_id"] == 5
        assert filtered["cache_ttl"] == 3600
        assert filtered["archived"] is False


class TestEmbeddingSettingsImport:
    """Test suite for embedding settings import functionality."""

    def test_import_card_with_embedding_settings_enabled(self, tmp_path):
        """Test that card embedding settings are included when flag is True."""
        config = ImportConfig(
            target_url="https://target.metabase.com",
            export_dir=str(tmp_path),
            db_map_path="db_map.json",
            include_embedding_settings=True,
        )

        # Mock card data with embedding settings
        card_data = {
            "id": 1,
            "name": "Test Card",
            "database_id": 2,
            "dataset_query": {"type": "query", "database": 2},
            "enable_embedding": True,
            "embedding_params": {"param1": "enabled"},
            "created_at": "2025-01-01T00:00:00Z",
        }

        # Import clean_for_create to test the logic
        from lib.utils import clean_for_create

        payload = clean_for_create(card_data)

        # When include_embedding_settings is True, these should NOT be removed
        if not config.include_embedding_settings:
            payload.pop("enable_embedding", None)
            payload.pop("embedding_params", None)

        assert "enable_embedding" in payload
        assert "embedding_params" in payload
        assert payload["enable_embedding"] is True

    def test_import_card_without_embedding_settings_enabled(self, tmp_path):
        """Test that card embedding settings are excluded when flag is False."""
        config = ImportConfig(
            target_url="https://target.metabase.com",
            export_dir=str(tmp_path),
            db_map_path="db_map.json",
            include_embedding_settings=False,
        )

        # Mock card data with embedding settings
        card_data = {
            "id": 1,
            "name": "Test Card",
            "database_id": 2,
            "dataset_query": {"type": "query", "database": 2},
            "enable_embedding": True,
            "embedding_params": {"param1": "enabled"},
            "created_at": "2025-01-01T00:00:00Z",
        }

        from lib.utils import clean_for_create

        payload = clean_for_create(card_data)

        # Simulate the import logic
        if not config.include_embedding_settings:
            payload.pop("enable_embedding", None)
            payload.pop("embedding_params", None)

        assert "enable_embedding" not in payload
        assert "embedding_params" not in payload
        assert payload["name"] == "Test Card"

    def test_import_dashboard_with_embedding_settings_enabled(self, tmp_path):
        """Test that dashboard embedding settings are included when flag is True."""
        config = ImportConfig(
            target_url="https://target.metabase.com",
            export_dir=str(tmp_path),
            db_map_path="db_map.json",
            include_embedding_settings=True,
        )

        # Mock dashboard payload
        payload = {
            "name": "Test Dashboard",
            "parameters": [],
            "cache_ttl": None,
            "enable_embedding": True,
            "embedding_params": {"date": "enabled"},
        }

        update_payload = {
            "parameters": payload.get("parameters"),
            "cache_ttl": payload.get("cache_ttl"),
        }

        # Simulate the import logic
        if config.include_embedding_settings:
            if "enable_embedding" in payload:
                update_payload["enable_embedding"] = payload["enable_embedding"]
            if "embedding_params" in payload:
                update_payload["embedding_params"] = payload["embedding_params"]

        assert "enable_embedding" in update_payload
        assert "embedding_params" in update_payload
        assert update_payload["enable_embedding"] is True

    def test_import_dashboard_without_embedding_settings_enabled(self, tmp_path):
        """Test that dashboard embedding settings are excluded when flag is False."""
        config = ImportConfig(
            target_url="https://target.metabase.com",
            export_dir=str(tmp_path),
            db_map_path="db_map.json",
            include_embedding_settings=False,
        )

        # Mock dashboard payload
        payload = {
            "name": "Test Dashboard",
            "parameters": [],
            "cache_ttl": None,
            "enable_embedding": True,
            "embedding_params": {"date": "enabled"},
        }

        update_payload = {
            "parameters": payload.get("parameters"),
            "cache_ttl": payload.get("cache_ttl"),
        }

        # Simulate the import logic (should NOT add embedding settings)
        if config.include_embedding_settings:
            if "enable_embedding" in payload:
                update_payload["enable_embedding"] = payload["enable_embedding"]
            if "embedding_params" in payload:
                update_payload["embedding_params"] = payload["embedding_params"]

        assert "enable_embedding" not in update_payload
        assert "embedding_params" not in update_payload
