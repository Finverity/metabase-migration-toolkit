"""Tests for dashboard filter export and import functionality.

This module tests that dashboard filters (parameters) and their mappings
are correctly preserved during the export and import process.
"""

from unittest.mock import Mock, patch

import pytest

from export_metabase import MetabaseExporter
from import_metabase import MetabaseImporter
from lib.config import ExportConfig, ImportConfig
from lib.models import Dashboard, Manifest, ManifestMeta
from lib.utils import read_json_file, write_json_file
from tests.fixtures.sample_responses import SAMPLE_DASHBOARD_WITH_FILTERS


class TestDashboardFilterExport:
    """Test suite for exporting dashboards with filters."""

    def test_export_dashboard_preserves_parameters(self, tmp_path):
        """Test that dashboard parameters (filters) are exported."""
        config = ExportConfig(
            source_url="https://source.example.com",
            export_dir=str(tmp_path / "export"),
            include_dashboards=True,
            source_session_token="token",
        )

        with patch("lib.services.export_service.MetabaseClient") as mock_client_class:
            mock_client = Mock()
            mock_client.get_dashboard.return_value = SAMPLE_DASHBOARD_WITH_FILTERS
            # Mock get_card for cards referenced by the dashboard
            mock_client.get_card.side_effect = lambda card_id: {
                "id": card_id,
                "name": f"Card {card_id}",
                "collection_id": 1,
                "database_id": 1,
                "dataset_query": {"database": 1, "query": {"source-table": 1}},
            }
            mock_client_class.return_value = mock_client

            exporter = MetabaseExporter(config)
            exporter._collection_path_map = {1: "collections/test"}
            exporter._export_dashboard(201, "collections/test")

            # Verify dashboard was exported
            exported_files = list(
                (tmp_path / "export" / "collections" / "test" / "dashboards").glob("*.json")
            )
            assert len(exported_files) == 1

            # Read exported dashboard
            exported_data = read_json_file(exported_files[0])

            # Verify parameters are preserved
            assert "parameters" in exported_data
            assert len(exported_data["parameters"]) == 3

            # Verify parameter details
            date_param = next(p for p in exported_data["parameters"] if p["id"] == "date_filter")
            assert date_param["name"] == "Date Range"
            assert date_param["type"] == "date/range"

            category_param = next(
                p for p in exported_data["parameters"] if p["id"] == "category_filter"
            )
            assert category_param["name"] == "Product Category"
            assert category_param["type"] == "string/="
            assert category_param["default"] == "Electronics"
            assert "values_source_config" in category_param
            assert category_param["values_source_config"]["card_id"] == 100

    def test_export_dashboard_preserves_parameter_mappings(self, tmp_path):
        """Test that dashcard parameter mappings are exported."""
        config = ExportConfig(
            source_url="https://source.example.com",
            export_dir=str(tmp_path / "export"),
            include_dashboards=True,
            source_session_token="token",
        )

        with patch("lib.services.export_service.MetabaseClient") as mock_client_class:
            mock_client = Mock()
            mock_client.get_dashboard.return_value = SAMPLE_DASHBOARD_WITH_FILTERS
            # Mock get_card for cards referenced by the dashboard
            mock_client.get_card.side_effect = lambda card_id: {
                "id": card_id,
                "name": f"Card {card_id}",
                "collection_id": 1,
                "database_id": 1,
                "dataset_query": {"database": 1, "query": {"source-table": 1}},
            }
            mock_client_class.return_value = mock_client

            exporter = MetabaseExporter(config)
            exporter._collection_path_map = {1: "collections/test"}
            exporter._export_dashboard(201, "collections/test")

            # Read exported dashboard
            exported_files = list(
                (tmp_path / "export" / "collections" / "test" / "dashboards").glob("*.json")
            )
            exported_data = read_json_file(exported_files[0])

            # Verify dashcards have parameter_mappings
            assert "dashcards" in exported_data
            assert len(exported_data["dashcards"]) == 2

            # Check first dashcard mappings
            dashcard1 = exported_data["dashcards"][0]
            assert "parameter_mappings" in dashcard1
            assert len(dashcard1["parameter_mappings"]) == 2

            # Verify mapping structure
            date_mapping = next(
                m for m in dashcard1["parameter_mappings"] if m["parameter_id"] == "date_filter"
            )
            assert date_mapping["card_id"] == 100
            assert "target" in date_mapping

            # Check second dashcard mappings
            dashcard2 = exported_data["dashcards"][1]
            assert len(dashcard2["parameter_mappings"]) == 2

    def test_export_dashboard_exports_referenced_cards(self, tmp_path):
        """Test that cards referenced by dashboard parameters are exported."""
        config = ExportConfig(
            source_url="https://source.example.com",
            export_dir=str(tmp_path / "export"),
            include_dashboards=True,
            source_session_token="token",
        )

        with patch("lib.services.export_service.MetabaseClient") as mock_client_class:
            mock_client = Mock()
            mock_client.get_dashboard.return_value = SAMPLE_DASHBOARD_WITH_FILTERS
            # Mock get_card for cards referenced by the dashboard
            mock_client.get_card.side_effect = lambda card_id: {
                "id": card_id,
                "name": f"Card {card_id}",
                "collection_id": 1,
                "database_id": 1,
                "dataset_query": {"database": 1, "query": {"source-table": 1}},
            }
            mock_client_class.return_value = mock_client

            exporter = MetabaseExporter(config)
            exporter._collection_path_map = {1: "collections/test"}
            exporter._export_dashboard(201, "collections/test")

            # Verify that cards were exported
            card_files = list(
                (tmp_path / "export" / "collections" / "test" / "cards").glob("*.json")
            )
            assert len(card_files) == 2, "Expected 2 cards to be exported (100 and 101)"

            # Verify card IDs
            card_ids = set()
            for card_file in card_files:
                card_data = read_json_file(card_file)
                card_ids.add(card_data["id"])

            assert card_ids == {100, 101}, "Expected cards 100 and 101 to be exported"

            # Verify cards are in manifest
            assert len(exporter.manifest.cards) == 2
            manifest_card_ids = {card.id for card in exporter.manifest.cards}
            assert manifest_card_ids == {100, 101}


class TestDashboardFilterImport:
    """Test suite for importing dashboards with filters."""

    @pytest.fixture
    def setup_import_test(self, tmp_path):
        """Set up test environment for import tests."""
        export_dir = tmp_path / "export"
        export_dir.mkdir()

        # Create manifest
        manifest = Manifest(
            meta=ManifestMeta(
                source_url="https://source.example.com",
                export_timestamp="2025-10-21T12:00:00.000000",
                tool_version="1.0.0",
                cli_args={},
            ),
            databases={2: "Production Database"},
            collections=[],
            cards=[],
            dashboards=[
                Dashboard(
                    id=201,
                    name="Sales Dashboard with Filters",
                    collection_id=1,
                    ordered_cards=[100, 101],
                    file_path="collections/test/dashboards/dash_201_sales.json",
                    checksum="abc123",
                )
            ],
        )

        # Write manifest
        write_json_file(manifest, export_dir / "manifest.json")

        # Write dashboard file
        dash_dir = export_dir / "collections" / "test" / "dashboards"
        dash_dir.mkdir(parents=True)
        write_json_file(SAMPLE_DASHBOARD_WITH_FILTERS, dash_dir / "dash_201_sales.json")

        # Create db_map
        db_map = {"by_id": {"2": 20}, "by_name": {"Production Database": 20}}
        db_map_path = tmp_path / "db_map.json"
        write_json_file(db_map, db_map_path)

        return {
            "export_dir": export_dir,
            "db_map_path": db_map_path,
            "tmp_path": tmp_path,
        }

    def test_import_dashboard_preserves_parameters(self, setup_import_test):
        """Test that dashboard parameters are preserved during import."""
        from lib.handlers.base import ImportContext

        config = ImportConfig(
            target_url="https://target.example.com",
            export_dir=str(setup_import_test["export_dir"]),
            db_map_path=str(setup_import_test["db_map_path"]),
            dry_run=False,
            target_session_token="token",
        )

        with patch("lib.services.import_service.MetabaseClient") as mock_client_class:
            mock_client = Mock()
            mock_client.get_collections_tree.return_value = []
            mock_client.get_collection_items.return_value = {"data": []}

            # Mock create_dashboard to capture the payload
            created_dashboard = {"id": 301, "name": "Sales Dashboard with Filters"}
            mock_client.create_dashboard.return_value = created_dashboard
            mock_client.update_dashboard.return_value = created_dashboard

            mock_client_class.return_value = mock_client

            importer = MetabaseImporter(config)
            # Load manifest
            importer._load_export_package()

            # Set up the context (normally done in _perform_import)
            importer._context = ImportContext(
                config=importer.config,
                client=importer.client,
                manifest=importer.manifest,
                export_dir=importer.export_dir,
                id_mapper=importer._id_mapper,
                query_remapper=importer._query_remapper,
                report=importer.report,
                target_collections=[],
            )

            # Set up the mappings on the id_mapper
            importer._id_mapper.set_collection_mapping(1, 10)
            importer._id_mapper.set_card_mapping(100, 200)
            importer._id_mapper.set_card_mapping(101, 201)

            # Import dashboards
            importer._import_dashboards()

            # Verify create_dashboard was called with parameters
            assert mock_client.create_dashboard.called
            create_payload = mock_client.create_dashboard.call_args[0][0]

            assert "parameters" in create_payload
            assert len(create_payload["parameters"]) == 3

            # Verify date filter
            date_param = next(p for p in create_payload["parameters"] if p["id"] == "date_filter")
            assert date_param["name"] == "Date Range"
            assert date_param["type"] == "date/range"

            # Verify category filter with remapped card_id
            category_param = next(
                p for p in create_payload["parameters"] if p["id"] == "category_filter"
            )
            assert category_param["values_source_config"]["card_id"] == 200  # Remapped from 100

    def test_import_dashboard_remaps_parameter_mapping_card_ids(self, setup_import_test):
        """Test that card IDs in parameter mappings are remapped during import."""
        from lib.handlers.base import ImportContext

        config = ImportConfig(
            target_url="https://target.example.com",
            export_dir=str(setup_import_test["export_dir"]),
            db_map_path=str(setup_import_test["db_map_path"]),
            dry_run=False,
            target_session_token="token",
        )

        with patch("lib.services.import_service.MetabaseClient") as mock_client_class:
            mock_client = Mock()
            mock_client.get_collections_tree.return_value = []
            mock_client.get_collection_items.return_value = {"data": []}

            created_dashboard = {"id": 301, "name": "Sales Dashboard with Filters"}
            mock_client.create_dashboard.return_value = created_dashboard
            mock_client.update_dashboard.return_value = created_dashboard

            mock_client_class.return_value = mock_client

            importer = MetabaseImporter(config)
            importer._load_export_package()

            # Set up the context (normally done in _perform_import)
            importer._context = ImportContext(
                config=importer.config,
                client=importer.client,
                manifest=importer.manifest,
                export_dir=importer.export_dir,
                id_mapper=importer._id_mapper,
                query_remapper=importer._query_remapper,
                report=importer.report,
                target_collections=[],
            )

            # Set up the mappings on the id_mapper
            importer._id_mapper.set_collection_mapping(1, 10)
            importer._id_mapper.set_card_mapping(100, 200)
            importer._id_mapper.set_card_mapping(101, 201)

            # Import dashboards
            importer._import_dashboards()

            # Verify update_dashboard was called with remapped parameter_mappings
            assert mock_client.update_dashboard.called
            update_payload = mock_client.update_dashboard.call_args[0][1]

            assert "dashcards" in update_payload
            dashcards = update_payload["dashcards"]
            assert len(dashcards) == 2

            # Check first dashcard - card_id should be remapped
            dashcard1 = dashcards[0]
            assert dashcard1["card_id"] == 200  # Remapped from 100

            # Check parameter_mappings in first dashcard
            assert "parameter_mappings" in dashcard1
            mappings1 = dashcard1["parameter_mappings"]
            assert len(mappings1) == 2

            # Verify card_id in parameter_mappings is remapped
            for mapping in mappings1:
                assert mapping["card_id"] == 200  # All should be remapped to 200

            # Check second dashcard
            dashcard2 = dashcards[1]
            assert dashcard2["card_id"] == 201  # Remapped from 101

            mappings2 = dashcard2["parameter_mappings"]
            for mapping in mappings2:
                assert mapping["card_id"] == 201  # All should be remapped to 201

    def test_import_dashboard_preserves_filter_dependencies(self, setup_import_test):
        """Test that filter dependencies and relationships are maintained."""
        from lib.handlers.base import ImportContext

        config = ImportConfig(
            target_url="https://target.example.com",
            export_dir=str(setup_import_test["export_dir"]),
            db_map_path=str(setup_import_test["db_map_path"]),
            dry_run=False,
            target_session_token="token",
        )

        with patch("lib.services.import_service.MetabaseClient") as mock_client_class:
            mock_client = Mock()
            mock_client.get_collections_tree.return_value = []
            mock_client.get_collection_items.return_value = {"data": []}

            created_dashboard = {"id": 301, "name": "Sales Dashboard with Filters"}
            mock_client.create_dashboard.return_value = created_dashboard
            mock_client.update_dashboard.return_value = created_dashboard

            mock_client_class.return_value = mock_client

            importer = MetabaseImporter(config)
            importer._load_export_package()

            # Set up the context (normally done in _perform_import)
            importer._context = ImportContext(
                config=importer.config,
                client=importer.client,
                manifest=importer.manifest,
                export_dir=importer.export_dir,
                id_mapper=importer._id_mapper,
                query_remapper=importer._query_remapper,
                report=importer.report,
                target_collections=[],
            )

            # Set up the mappings on the id_mapper
            importer._id_mapper.set_collection_mapping(1, 10)
            importer._id_mapper.set_card_mapping(100, 200)
            importer._id_mapper.set_card_mapping(101, 201)

            # Import dashboards
            importer._import_dashboards()

            # Verify parameter relationships are preserved
            update_payload = mock_client.update_dashboard.call_args[0][1]
            dashcards = update_payload["dashcards"]

            # Verify that parameter_id references match between parameters and mappings
            create_payload = mock_client.create_dashboard.call_args[0][0]
            parameter_ids = {p["id"] for p in create_payload["parameters"]}

            for dashcard in dashcards:
                for mapping in dashcard.get("parameter_mappings", []):
                    # Each mapping should reference a valid parameter
                    assert mapping["parameter_id"] in parameter_ids
                    # Target field structure should be preserved
                    assert "target" in mapping
                    assert isinstance(mapping["target"], list)

    def test_import_dashboard_with_missing_parameter_card(self, setup_import_test):
        """Test that parameters are still imported even if referenced card is missing."""
        from lib.handlers.base import ImportContext

        config = ImportConfig(
            target_url="https://target.example.com",
            export_dir=str(setup_import_test["export_dir"]),
            db_map_path=str(setup_import_test["db_map_path"]),
            dry_run=False,
            target_session_token="token",
        )

        with patch("lib.services.import_service.MetabaseClient") as mock_client_class:
            mock_client = Mock()
            mock_client.get_collections_tree.return_value = []
            mock_client.get_collection_items.return_value = {"data": []}

            created_dashboard = {"id": 301, "name": "Sales Dashboard with Filters"}
            mock_client.create_dashboard.return_value = created_dashboard
            mock_client.update_dashboard.return_value = created_dashboard

            mock_client_class.return_value = mock_client

            importer = MetabaseImporter(config)
            importer._load_export_package()

            # Set up the context (normally done in _perform_import)
            importer._context = ImportContext(
                config=importer.config,
                client=importer.client,
                manifest=importer.manifest,
                export_dir=importer.export_dir,
                id_mapper=importer._id_mapper,
                query_remapper=importer._query_remapper,
                report=importer.report,
                target_collections=[],
            )

            # Set up the mappings on the id_mapper
            importer._id_mapper.set_collection_mapping(1, 10)
            # Card 100 is NOT in the map (simulating missing card)
            importer._id_mapper.set_card_mapping(101, 201)

            # Import dashboards
            importer._import_dashboards()

            # Verify create_dashboard was called
            create_payload = mock_client.create_dashboard.call_args[0][0]
            assert "parameters" in create_payload

            # The category parameter should still be imported, but without values_source_config
            category_param = next(
                (p for p in create_payload["parameters"] if p["id"] == "category_filter"), None
            )
            assert (
                category_param is not None
            ), "Parameter should be imported even if card is missing"
            assert (
                "values_source_config" not in category_param
            ), "values_source_config should be removed"
            assert (
                "values_source_type" not in category_param
            ), "values_source_type should be removed"

            # Other parameters without dependencies should still be there
            date_param = next(
                (p for p in create_payload["parameters"] if p["id"] == "date_filter"), None
            )
            assert date_param is not None

    def test_import_dashboard_preserves_display_settings(self, setup_import_test):
        """Test that dashboard display settings (width, auto_apply_filters) are preserved during import."""
        from lib.handlers.base import ImportContext

        config = ImportConfig(
            target_url="https://target.example.com",
            export_dir=str(setup_import_test["export_dir"]),
            db_map_path=str(setup_import_test["db_map_path"]),
            dry_run=False,
            target_session_token="token",
        )

        with patch("lib.services.import_service.MetabaseClient") as mock_client_class:
            mock_client = Mock()
            mock_client.get_collections_tree.return_value = []
            mock_client.get_collection_items.return_value = {"data": []}

            created_dashboard = {"id": 301, "name": "Sales Dashboard with Filters"}
            mock_client.create_dashboard.return_value = created_dashboard
            mock_client.update_dashboard.return_value = created_dashboard

            mock_client_class.return_value = mock_client

            importer = MetabaseImporter(config)
            importer._load_export_package()

            # Set up the context (normally done in _perform_import)
            importer._context = ImportContext(
                config=importer.config,
                client=importer.client,
                manifest=importer.manifest,
                export_dir=importer.export_dir,
                id_mapper=importer._id_mapper,
                query_remapper=importer._query_remapper,
                report=importer.report,
                target_collections=[],
            )

            # Set up the mappings on the id_mapper
            importer._id_mapper.set_collection_mapping(1, 10)
            importer._id_mapper.set_card_mapping(100, 200)
            importer._id_mapper.set_card_mapping(101, 201)

            # Import dashboards
            importer._import_dashboards()

            # Verify update_dashboard was called with display settings
            assert mock_client.update_dashboard.called
            update_payload = mock_client.update_dashboard.call_args[0][1]

            # Verify width setting is preserved
            assert "width" in update_payload
            assert update_payload["width"] == "fixed"

            # Verify auto_apply_filters setting is preserved
            assert "auto_apply_filters" in update_payload
            assert update_payload["auto_apply_filters"] is True
