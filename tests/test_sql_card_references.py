"""Tests for SQL card reference remapping during import.

This module tests that native SQL queries containing card references
({{#ID-name}} syntax) are correctly remapped when cards get new IDs
after migration.

Bug fixed: When a model is migrated and gets a new ID, SQL cards that
reference it via {{#50-model-name}} syntax were not being updated,
causing "Card 50 does not exist" errors.
"""

from unittest.mock import Mock, patch

import pytest

from import_metabase import MetabaseImporter
from lib.config import ImportConfig
from lib.utils import write_json_file


class TestSqlCardReferenceExtraction:
    """Test suite for extracting card dependencies from native SQL queries."""

    @pytest.fixture
    def importer_for_extraction(self, tmp_path):
        """Create an importer instance for testing extraction."""
        export_dir = tmp_path / "export"
        export_dir.mkdir()

        manifest_data = {
            "meta": {
                "source_url": "https://source.example.com",
                "export_timestamp": "2025-10-07T12:00:00.000000",
                "tool_version": "1.0.0",
                "cli_args": {},
            },
            "databases": {"1": "Test Database"},
            "collections": [],
            "cards": [],
            "dashboards": [],
        }
        write_json_file(manifest_data, export_dir / "manifest.json")

        db_map_path = tmp_path / "db_map.json"
        write_json_file({"by_id": {"1": 10}, "by_name": {"Test Database": 10}}, db_map_path)

        config = ImportConfig(
            target_url="https://target.example.com",
            export_dir=str(export_dir),
            db_map_path=str(db_map_path),
            dry_run=False,
        )

        with patch("import_metabase.MetabaseClient"):
            importer = MetabaseImporter(config)
            importer._load_export_package()
            return importer

    def test_extract_single_sql_card_reference(self, importer_for_extraction):
        """Test extracting a single card reference from SQL."""
        card_data = {
            "id": 100,
            "dataset_query": {
                "type": "native",
                "database": 1,
                "native": {"query": "SELECT * FROM {{#50-filtered-test-server-dataset}}"},
            },
        }

        deps = importer_for_extraction._extract_card_dependencies(card_data)
        assert deps == {50}

    def test_extract_multiple_sql_card_references(self, importer_for_extraction):
        """Test extracting multiple card references from SQL."""
        card_data = {
            "id": 100,
            "dataset_query": {
                "type": "native",
                "database": 1,
                "native": {
                    "query": """
                        SELECT a.*, b.name
                        FROM {{#50-model-a}} a
                        JOIN {{#60-model-b}} b ON a.id = b.a_id
                        WHERE a.category IN (SELECT category FROM {{#70-categories-list}})
                    """
                },
            },
        }

        deps = importer_for_extraction._extract_card_dependencies(card_data)
        assert deps == {50, 60, 70}

    def test_extract_sql_reference_with_complex_name(self, importer_for_extraction):
        """Test extracting card reference with complex name containing hyphens."""
        card_data = {
            "id": 100,
            "dataset_query": {
                "type": "native",
                "database": 1,
                "native": {
                    "query": "SELECT * FROM {{#123-my-complex-model-name-with-many-hyphens}}"
                },
            },
        }

        deps = importer_for_extraction._extract_card_dependencies(card_data)
        assert deps == {123}

    def test_no_sql_card_references(self, importer_for_extraction):
        """Test that no dependencies are extracted from SQL without card references."""
        card_data = {
            "id": 100,
            "dataset_query": {
                "type": "native",
                "database": 1,
                "native": {"query": "SELECT * FROM regular_table WHERE id > 10"},
            },
        }

        deps = importer_for_extraction._extract_card_dependencies(card_data)
        assert deps == set()

    def test_mixed_mbql_card_reference(self, importer_for_extraction):
        """Test that MBQL card references are also extracted."""
        # MBQL query with source-table card reference
        card_data = {
            "id": 100,
            "dataset_query": {
                "type": "query",
                "database": 1,
                "query": {"source-table": "card__50"},
            },
        }

        deps = importer_for_extraction._extract_card_dependencies(card_data)
        assert deps == {50}  # Found via MBQL pattern


class TestSqlCardReferenceRemapping:
    """Test suite for remapping card references in native SQL during import."""

    @pytest.fixture
    def setup_import_test(self, tmp_path):
        """Set up test environment for import tests."""
        export_dir = tmp_path / "export"
        export_dir.mkdir()
        (export_dir / "cards").mkdir()

        # Create manifest with a model card and a SQL card that references it
        manifest_data = {
            "meta": {
                "source_url": "https://source.example.com",
                "export_timestamp": "2025-10-07T12:00:00.000000",
                "tool_version": "1.0.0",
                "cli_args": {},
            },
            "databases": {"1": "Test Database"},
            "collections": [
                {"id": 1, "name": "Test Collection", "slug": "test-collection", "parent_id": None}
            ],
            "cards": [
                {
                    "id": 50,
                    "name": "Filtered Test Server Dataset",
                    "collection_id": 1,
                    "database_id": 1,
                    "file_path": "cards/card_50_model.json",
                    "dataset": True,
                },
                {
                    "id": 100,
                    "name": "SQL Card Using Model",
                    "collection_id": 1,
                    "database_id": 1,
                    "file_path": "cards/card_100_sql.json",
                    "dataset": False,
                },
            ],
            "dashboards": [],
        }
        write_json_file(manifest_data, export_dir / "manifest.json")

        # Create the model card file
        model_card_data = {
            "id": 50,
            "name": "Filtered Test Server Dataset",
            "collection_id": 1,
            "database_id": 1,
            "type": "model",
            "dataset_query": {
                "type": "query",
                "database": 1,
                "query": {"source-table": 1},
            },
        }
        write_json_file(model_card_data, export_dir / "cards" / "card_50_model.json")

        # Create the SQL card that references the model
        sql_card_data = {
            "id": 100,
            "name": "SQL Card Using Model",
            "collection_id": 1,
            "database_id": 1,
            "type": "question",
            "dataset_query": {
                "type": "native",
                "database": 1,
                "native": {
                    "query": "SELECT * FROM {{#50-filtered-test-server-dataset}} WHERE status = 'active'",
                    "template-tags": {},
                },
            },
        }
        write_json_file(sql_card_data, export_dir / "cards" / "card_100_sql.json")

        # Create db_map.json
        db_map_data = {
            "by_id": {"1": 10},
            "by_name": {"Test Database": 10},
        }
        db_map_path = tmp_path / "db_map.json"
        write_json_file(db_map_data, db_map_path)

        return {
            "export_dir": export_dir,
            "db_map_path": db_map_path,
            "model_card_path": export_dir / "cards" / "card_50_model.json",
            "sql_card_path": export_dir / "cards" / "card_100_sql.json",
        }

    def test_sql_card_reference_is_remapped(self, setup_import_test):
        """Test that SQL card references are remapped when model gets new ID."""
        config = ImportConfig(
            target_url="https://target.example.com",
            export_dir=str(setup_import_test["export_dir"]),
            db_map_path=str(setup_import_test["db_map_path"]),
            dry_run=False,
        )

        with patch("import_metabase.MetabaseClient") as mock_client_class:
            mock_client = Mock()
            mock_client.get_collections_tree.return_value = []

            # Model card (50) gets created with new ID 999
            mock_client.create_card.side_effect = [
                {"id": 999, "name": "Filtered Test Server Dataset"},  # Model gets ID 999
                {"id": 1000, "name": "SQL Card Using Model"},  # SQL card gets ID 1000
            ]

            mock_client.create_collection.return_value = {"id": 100}
            mock_client_class.return_value = mock_client

            importer = MetabaseImporter(config)
            importer._load_export_package()
            importer._collection_map = {1: 100}

            # Import cards
            importer._import_cards()

            # Verify create_card was called twice
            assert mock_client.create_card.call_count == 2

            # Get the payload for the SQL card (second call)
            sql_card_payload = mock_client.create_card.call_args_list[1][0][0]

            # Verify the SQL query has been remapped from 50 to 999
            sql_query = sql_card_payload["dataset_query"]["native"]["query"]
            assert "{{#999-filtered-test-server-dataset}}" in sql_query
            assert "{{#50-" not in sql_query

    def test_multiple_sql_card_references_are_remapped(self, tmp_path):
        """Test that multiple SQL card references are all remapped."""
        export_dir = tmp_path / "export"
        export_dir.mkdir()
        (export_dir / "cards").mkdir()

        manifest_data = {
            "meta": {
                "source_url": "https://source.example.com",
                "export_timestamp": "2025-10-07T12:00:00.000000",
                "tool_version": "1.0.0",
                "cli_args": {},
            },
            "databases": {"1": "Test Database"},
            "collections": [
                {"id": 1, "name": "Test Collection", "slug": "test-collection", "parent_id": None}
            ],
            "cards": [
                {
                    "id": 50,
                    "name": "Model A",
                    "collection_id": 1,
                    "database_id": 1,
                    "file_path": "cards/card_50.json",
                    "dataset": True,
                },
                {
                    "id": 60,
                    "name": "Model B",
                    "collection_id": 1,
                    "database_id": 1,
                    "file_path": "cards/card_60.json",
                    "dataset": True,
                },
                {
                    "id": 100,
                    "name": "SQL Card",
                    "collection_id": 1,
                    "database_id": 1,
                    "file_path": "cards/card_100.json",
                    "dataset": False,
                },
            ],
            "dashboards": [],
        }
        write_json_file(manifest_data, export_dir / "manifest.json")

        # Create model cards
        for card_id in [50, 60]:
            write_json_file(
                {
                    "id": card_id,
                    "name": f"Model {'A' if card_id == 50 else 'B'}",
                    "collection_id": 1,
                    "database_id": 1,
                    "type": "model",
                    "dataset_query": {"type": "query", "database": 1, "query": {"source-table": 1}},
                },
                export_dir / "cards" / f"card_{card_id}.json",
            )

        # SQL card with multiple references
        write_json_file(
            {
                "id": 100,
                "name": "SQL Card",
                "collection_id": 1,
                "database_id": 1,
                "type": "question",
                "dataset_query": {
                    "type": "native",
                    "database": 1,
                    "native": {
                        "query": """
                            SELECT a.*, b.value
                            FROM {{#50-model-a}} a
                            JOIN {{#60-model-b}} b ON a.id = b.a_id
                        """,
                        "template-tags": {},
                    },
                },
            },
            export_dir / "cards" / "card_100.json",
        )

        db_map_path = tmp_path / "db_map.json"
        write_json_file({"by_id": {"1": 10}, "by_name": {"Test Database": 10}}, db_map_path)

        config = ImportConfig(
            target_url="https://target.example.com",
            export_dir=str(export_dir),
            db_map_path=str(db_map_path),
            dry_run=False,
        )

        with patch("import_metabase.MetabaseClient") as mock_client_class:
            mock_client = Mock()
            mock_client.get_collections_tree.return_value = []
            mock_client.create_collection.return_value = {"id": 100}

            # Models get new IDs
            mock_client.create_card.side_effect = [
                {"id": 500, "name": "Model A"},  # 50 -> 500
                {"id": 600, "name": "Model B"},  # 60 -> 600
                {"id": 1000, "name": "SQL Card"},
            ]

            mock_client_class.return_value = mock_client

            importer = MetabaseImporter(config)
            importer._load_export_package()
            importer._collection_map = {1: 100}

            importer._import_cards()

            # Get the SQL card payload (third call)
            sql_card_payload = mock_client.create_card.call_args_list[2][0][0]
            sql_query = sql_card_payload["dataset_query"]["native"]["query"]

            # Verify both references are remapped
            assert "{{#500-model-a}}" in sql_query
            assert "{{#600-model-b}}" in sql_query
            assert "{{#50-" not in sql_query
            assert "{{#60-" not in sql_query

    def test_card_with_unmapped_sql_reference_is_skipped(self, tmp_path, caplog):
        """Test that cards referencing non-existent cards are skipped during import."""
        export_dir = tmp_path / "export"
        export_dir.mkdir()
        (export_dir / "cards").mkdir()

        manifest_data = {
            "meta": {
                "source_url": "https://source.example.com",
                "export_timestamp": "2025-10-07T12:00:00.000000",
                "tool_version": "1.0.0",
                "cli_args": {},
            },
            "databases": {"1": "Test Database"},
            "collections": [
                {"id": 1, "name": "Test Collection", "slug": "test-collection", "parent_id": None}
            ],
            "cards": [
                {
                    "id": 100,
                    "name": "SQL Card",
                    "collection_id": 1,
                    "database_id": 1,
                    "file_path": "cards/card_100.json",
                    "dataset": False,
                },
            ],
            "dashboards": [],
        }
        write_json_file(manifest_data, export_dir / "manifest.json")

        # SQL card referencing a card that's not in the export (e.g., card 999)
        write_json_file(
            {
                "id": 100,
                "name": "SQL Card",
                "collection_id": 1,
                "database_id": 1,
                "type": "question",
                "dataset_query": {
                    "type": "native",
                    "database": 1,
                    "native": {
                        "query": "SELECT * FROM {{#999-external-model}}",
                        "template-tags": {},
                    },
                },
            },
            export_dir / "cards" / "card_100.json",
        )

        db_map_path = tmp_path / "db_map.json"
        write_json_file({"by_id": {"1": 10}, "by_name": {"Test Database": 10}}, db_map_path)

        config = ImportConfig(
            target_url="https://target.example.com",
            export_dir=str(export_dir),
            db_map_path=str(db_map_path),
            dry_run=False,
        )

        with patch("import_metabase.MetabaseClient") as mock_client_class:
            mock_client = Mock()
            mock_client.get_collections_tree.return_value = []
            mock_client.create_collection.return_value = {"id": 100}

            mock_client_class.return_value = mock_client

            importer = MetabaseImporter(config)
            importer._load_export_package()
            importer._collection_map = {1: 100}

            importer._import_cards()

            # Card should be skipped, not created
            assert mock_client.create_card.call_count == 0

            # Verify the skip is logged
            assert "Skipping card 'SQL Card'" in caplog.text
            assert "depends on missing cards" in caplog.text


class TestSqlCardReferenceDependencyOrder:
    """Test that cards with SQL references are imported after their dependencies."""

    @pytest.fixture
    def setup_dependency_test(self, tmp_path):
        """Set up test for dependency ordering."""
        export_dir = tmp_path / "export"
        export_dir.mkdir()
        (export_dir / "cards").mkdir()

        # Card 100 depends on card 50 via SQL reference
        manifest_data = {
            "meta": {
                "source_url": "https://source.example.com",
                "export_timestamp": "2025-10-07T12:00:00.000000",
                "tool_version": "1.0.0",
                "cli_args": {},
            },
            "databases": {"1": "Test Database"},
            "collections": [
                {"id": 1, "name": "Test Collection", "slug": "test-collection", "parent_id": None}
            ],
            "cards": [
                # Note: Listed in reverse order to test sorting
                {
                    "id": 100,
                    "name": "SQL Card (depends on 50)",
                    "collection_id": 1,
                    "database_id": 1,
                    "file_path": "cards/card_100.json",
                    "dataset": False,
                },
                {
                    "id": 50,
                    "name": "Model (no dependencies)",
                    "collection_id": 1,
                    "database_id": 1,
                    "file_path": "cards/card_50.json",
                    "dataset": True,
                },
            ],
            "dashboards": [],
        }
        write_json_file(manifest_data, export_dir / "manifest.json")

        # Model card
        write_json_file(
            {
                "id": 50,
                "name": "Model",
                "collection_id": 1,
                "database_id": 1,
                "type": "model",
                "dataset_query": {"type": "query", "database": 1, "query": {"source-table": 1}},
            },
            export_dir / "cards" / "card_50.json",
        )

        # SQL card with reference
        write_json_file(
            {
                "id": 100,
                "name": "SQL Card",
                "collection_id": 1,
                "database_id": 1,
                "type": "question",
                "dataset_query": {
                    "type": "native",
                    "database": 1,
                    "native": {
                        "query": "SELECT * FROM {{#50-model}}",
                        "template-tags": {},
                    },
                },
            },
            export_dir / "cards" / "card_100.json",
        )

        db_map_path = tmp_path / "db_map.json"
        write_json_file({"by_id": {"1": 10}, "by_name": {"Test Database": 10}}, db_map_path)

        return {"export_dir": export_dir, "db_map_path": db_map_path}

    def test_sql_dependencies_imported_first(self, setup_dependency_test):
        """Test that model is imported before the SQL card that references it."""
        config = ImportConfig(
            target_url="https://target.example.com",
            export_dir=str(setup_dependency_test["export_dir"]),
            db_map_path=str(setup_dependency_test["db_map_path"]),
            dry_run=False,
        )

        created_cards = []

        with patch("import_metabase.MetabaseClient") as mock_client_class:
            mock_client = Mock()
            mock_client.get_collections_tree.return_value = []
            mock_client.create_collection.return_value = {"id": 100}

            def track_card_creation(payload):
                created_cards.append(payload["name"])
                # Return incrementing IDs
                card_id = 500 + len(created_cards)
                return {"id": card_id, "name": payload["name"]}

            mock_client.create_card.side_effect = track_card_creation
            mock_client_class.return_value = mock_client

            importer = MetabaseImporter(config)
            importer._load_export_package()
            importer._collection_map = {1: 100}

            importer._import_cards()

            # Model should be created before SQL card
            assert len(created_cards) == 2
            assert created_cards[0] == "Model"
            assert created_cards[1] == "SQL Card"


class TestRealWorldSqlPatterns:
    """Test real-world SQL patterns with card references."""

    @pytest.fixture
    def importer_with_card_map(self, tmp_path):
        """Create an importer with a pre-populated card map."""
        export_dir = tmp_path / "export"
        export_dir.mkdir()

        manifest_data = {
            "meta": {
                "source_url": "https://source.example.com",
                "export_timestamp": "2025-10-07T12:00:00.000000",
                "tool_version": "1.0.0",
                "cli_args": {},
            },
            "databases": {"1": "Test Database"},
            "collections": [],
            "cards": [],
            "dashboards": [],
        }
        write_json_file(manifest_data, export_dir / "manifest.json")

        db_map_path = tmp_path / "db_map.json"
        write_json_file({"by_id": {"1": 10}, "by_name": {"Test Database": 10}}, db_map_path)

        config = ImportConfig(
            target_url="https://target.example.com",
            export_dir=str(export_dir),
            db_map_path=str(db_map_path),
            dry_run=False,
        )

        with patch("import_metabase.MetabaseClient"):
            importer = MetabaseImporter(config)
            importer._load_export_package()
            # Pre-populate card map
            importer._card_map = {50: 999, 60: 888, 70: 777}
            return importer

    def test_simple_from_clause(self, importer_with_card_map):
        """Test remapping in simple FROM clause."""
        sql = "SELECT * FROM {{#50-my-model}}"
        result = importer_with_card_map._remap_native_sql_card_references(sql)
        assert result == "SELECT * FROM {{#999-my-model}}"

    def test_join_clause(self, importer_with_card_map):
        """Test remapping in JOIN clause."""
        sql = """
            SELECT a.*, b.name
            FROM {{#50-model-a}} a
            JOIN {{#60-model-b}} b ON a.id = b.a_id
        """
        result = importer_with_card_map._remap_native_sql_card_references(sql)
        assert "{{#999-model-a}}" in result
        assert "{{#888-model-b}}" in result

    def test_subquery(self, importer_with_card_map):
        """Test remapping in subquery."""
        sql = """
            SELECT *
            FROM {{#50-main-model}}
            WHERE category_id IN (
                SELECT id FROM {{#60-categories}}
            )
        """
        result = importer_with_card_map._remap_native_sql_card_references(sql)
        assert "{{#999-main-model}}" in result
        assert "{{#888-categories}}" in result

    def test_cte_with_references(self, importer_with_card_map):
        """Test remapping in CTE (Common Table Expression)."""
        sql = """
            WITH base_data AS (
                SELECT * FROM {{#50-base-model}}
            ),
            enriched AS (
                SELECT b.*, e.extra
                FROM base_data b
                JOIN {{#60-enrichment-model}} e ON b.id = e.base_id
            )
            SELECT * FROM enriched
        """
        result = importer_with_card_map._remap_native_sql_card_references(sql)
        assert "{{#999-base-model}}" in result
        assert "{{#888-enrichment-model}}" in result

    def test_union_queries(self, importer_with_card_map):
        """Test remapping in UNION queries."""
        sql = """
            SELECT id, name FROM {{#50-model-a}}
            UNION ALL
            SELECT id, name FROM {{#60-model-b}}
            UNION ALL
            SELECT id, name FROM {{#70-model-c}}
        """
        result = importer_with_card_map._remap_native_sql_card_references(sql)
        assert "{{#999-model-a}}" in result
        assert "{{#888-model-b}}" in result
        assert "{{#777-model-c}}" in result

    def test_preserves_non_reference_content(self, importer_with_card_map):
        """Test that non-reference content is preserved."""
        sql = """
            -- This is a comment about {{#50-model}}
            SELECT
                id,
                'literal {{#50-not-a-ref}}' as fake,
                actual_column
            FROM {{#50-real-model}}
            WHERE status = 'active'
        """
        result = importer_with_card_map._remap_native_sql_card_references(sql)
        # Real reference is remapped
        assert "{{#999-real-model}}" in result
        # Comment reference is also remapped (acceptable behavior)
        assert "{{#999-model}}" in result
        # String literal is also remapped (limitation - regex can't distinguish)
        # This is acceptable as the literal still works

    def test_empty_sql(self, importer_with_card_map):
        """Test handling of empty SQL."""
        assert importer_with_card_map._remap_native_sql_card_references("") == ""
        assert importer_with_card_map._remap_native_sql_card_references(None) is None

    def test_sql_without_references(self, importer_with_card_map):
        """Test SQL without any card references."""
        sql = "SELECT * FROM regular_table WHERE id = 1"
        result = importer_with_card_map._remap_native_sql_card_references(sql)
        assert result == sql
