"""Unit tests for the error, recursion and edge-case paths of lib/services/export_service.py.

tests/test_export.py covers the happy paths of the exporter. This module targets the
branches that only trigger on malformed data, API failures, circular dependencies,
archived content and database exclusion.
"""

from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from lib.client import MetabaseAPIError
from lib.config import ExportConfig
from lib.services.export_service import ExportService


@pytest.fixture
def make_service(tmp_path: Path):
    """Return a factory building an ExportService with a mocked MetabaseClient."""

    def _make(**config_overrides) -> ExportService:
        config_kwargs = {
            "source_url": "https://source.example.com",
            "export_dir": str(tmp_path / "export"),
            "source_username": "test@example.com",
            "source_password": "password123",  # pragma: allowlist secret
            "log_level": "INFO",
        }
        config_kwargs.update(config_overrides)
        config = ExportConfig(**config_kwargs)

        with patch("lib.services.export_service.MetabaseClient") as mock_client_cls:
            service = ExportService(config)
            service.client = mock_client_cls.return_value

        service.client.get_databases.return_value = []
        service.client.get_collections_tree.return_value = []
        service.client.get_collection_items.return_value = {"data": []}
        service.client.get_archived_cards.return_value = []
        return service

    return _make


def card_payload(card_id: int, **overrides) -> dict:
    """Build a minimal exportable card payload."""
    payload = {
        "id": card_id,
        "name": f"Card {card_id}",
        "collection_id": 1,
        "database_id": 1,
        "dataset_query": {"type": "query", "database": 1, "query": {"source-table": 1}},
    }
    payload.update(overrides)
    return payload


# ============================================================================
# run_export orchestration
# ============================================================================


class TestRunExport:
    """Tests for the run_export entry point."""

    def test_logs_excluded_databases(self, make_service, caplog):
        service = make_service(exclude_database_ids=[4, 24, 4])

        with caplog.at_level("INFO", logger="metabase_migration"):
            service.run_export()

        assert "Excluding cards from databases: [4, 24]" in caplog.text

    def test_warns_and_returns_when_no_collections(self, make_service, caplog):
        service = make_service()

        with caplog.at_level("WARNING", logger="metabase_migration"):
            service.run_export()

        assert "No collections found to export." in caplog.text
        assert not (service.export_dir / "manifest.json").exists()

    def test_filters_tree_to_root_collections(self, make_service):
        service = make_service(root_collection_ids=[2])
        service.client.get_collections_tree.return_value = [
            {"id": 1, "name": "Excluded"},
            {"id": 2, "name": "Included"},
        ]

        service.run_export()

        assert [c.id for c in service.manifest.collections] == [2]

    def test_summary_reports_excluded_card_count(self, make_service, caplog):
        service = make_service(exclude_database_ids=[9], include_permissions=True)
        service.client.get_collections_tree.return_value = [{"id": 1, "name": "C"}]
        service.client.get_collection_items.return_value = {"data": [{"id": 100, "model": "card"}]}
        service.client.get_card.return_value = card_payload(100, database_id=9)
        service.client.get_permission_groups.return_value = []
        service.client.get_permissions_graph.return_value = {}
        service.client.get_collection_permissions_graph.return_value = {}

        with caplog.at_level("INFO", logger="metabase_migration"):
            service.run_export()

        assert "Cards skipped (excluded databases): 1" in caplog.text
        assert "Permission Groups: 0" in caplog.text
        assert service.manifest.cards == []

    def test_exports_archived_cards_when_requested(self, make_service):
        service = make_service(include_archived=True)
        service.client.get_collections_tree.return_value = [{"id": 1, "name": "C"}]
        service.client.get_archived_cards.return_value = [
            {"id": 100, "name": "Old", "collection_id": 1}
        ]
        service.client.get_card.return_value = card_payload(100, archived=True)

        service.run_export()

        service.client.get_archived_cards.assert_called_once()
        assert [c.id for c in service.manifest.cards] == [100]

    def test_reraises_metabase_api_error(self, make_service, caplog):
        service = make_service()
        service.client.get_databases.side_effect = MetabaseAPIError("boom")

        with caplog.at_level("ERROR", logger="metabase_migration"):
            with pytest.raises(MetabaseAPIError):
                service.run_export()

        assert "A Metabase API error occurred" in caplog.text

    def test_reraises_unexpected_error(self, make_service, caplog):
        service = make_service()
        service.client.get_databases.side_effect = RuntimeError("kaboom")

        with caplog.at_level("ERROR", logger="metabase_migration"):
            with pytest.raises(RuntimeError):
                service.run_export()

        assert "An unexpected error occurred" in caplog.text


class TestFetchAndStoreDatabases:
    """Tests for _fetch_and_store_databases response handling."""

    def test_paginated_response_shape(self, make_service):
        service = make_service()
        service.client.get_databases.return_value = {"data": [{"id": 1, "name": "DB"}]}
        service.client.get_database_metadata.return_value = {"tables": []}

        service._fetch_and_store_databases()

        assert service.manifest.databases == {1: "DB"}

    def test_unexpected_response_shape_logs_error(self, make_service, caplog):
        service = make_service()
        service.client.get_databases.return_value = "nonsense"

        with caplog.at_level("ERROR", logger="metabase_migration"):
            service._fetch_and_store_databases()

        assert "Unexpected databases response format" in caplog.text
        assert service.manifest.databases == {}

    def test_metadata_failure_does_not_abort(self, make_service, caplog):
        service = make_service()
        service.client.get_databases.return_value = [{"id": 1, "name": "A"}, {"id": 2, "name": "B"}]
        service.client.get_database_metadata.side_effect = [
            MetabaseAPIError("nope"),
            {"tables": [{"id": 5, "name": "t", "fields": [{"id": 6, "name": "f"}]}]},
        ]

        with caplog.at_level("WARNING", logger="metabase_migration"):
            service._fetch_and_store_databases()

        assert "Failed to fetch metadata for database 1" in caplog.text
        assert 1 not in service.manifest.database_metadata
        assert service.manifest.database_metadata[2]["tables"][0]["fields"] == [
            {"id": 6, "name": "f"}
        ]


# ============================================================================
# collection traversal
# ============================================================================


class TestTraverseCollections:
    """Tests for _traverse_collections."""

    def test_skips_personal_collections(self, make_service, caplog):
        service = make_service()

        with caplog.at_level("INFO", logger="metabase_migration"):
            service._traverse_collections([{"id": 1, "name": "Mine", "personal_owner_id": 3}])

        assert "Skipping personal collection 'Mine'" in caplog.text
        assert service.manifest.collections == []

    def test_includes_explicitly_requested_personal_collection(self, make_service):
        service = make_service(root_collection_ids=[1])

        service._traverse_collections([{"id": 1, "name": "Mine", "personal_owner_id": 3}])

        assert [c.id for c in service.manifest.collections] == [1]

    def test_root_collection_processed_by_id_string(self, make_service):
        service = make_service()

        service._traverse_collections([{"id": "root", "name": "Our analytics"}])

        service.client.get_collection_items.assert_called_once()
        assert service.client.get_collection_items.call_args[0][0] == "root"
        assert service.manifest.collections == []

    def test_already_processed_collection_skipped(self, make_service):
        service = make_service()
        service._processed_collections.add(1)

        service._traverse_collections([{"id": 1, "name": "C"}])

        assert service.manifest.collections == []

    def test_parent_id_derived_from_location(self, make_service):
        service = make_service()

        service._traverse_collections([{"id": 3, "name": "Child", "location": "/24/25/"}])

        assert service.manifest.collections[0].parent_id == 25

    def test_unparsable_location_leaves_parent_none(self, make_service):
        service = make_service()

        service._traverse_collections([{"id": 3, "name": "Child", "location": "/abc/"}])

        assert service.manifest.collections[0].parent_id is None

    def test_empty_location_leaves_parent_none(self, make_service):
        service = make_service()

        service._traverse_collections([{"id": 3, "name": "Child", "location": "/"}])

        assert service.manifest.collections[0].parent_id is None

    def test_recurses_into_children(self, make_service):
        service = make_service()

        service._traverse_collections(
            [{"id": 1, "name": "Parent", "children": [{"id": 2, "name": "Child"}]}]
        )

        assert [c.id for c in service.manifest.collections] == [1, 2]
        assert service._collection_path_map[2] == "Parent/Child"
        assert service.manifest.collections[1].parent_id == 1

    def test_empty_children_list_not_recursed(self, make_service):
        service = make_service()

        service._traverse_collections([{"id": 1, "name": "Parent", "children": []}])

        assert [c.id for c in service.manifest.collections] == [1]


class TestProcessCollectionItems:
    """Tests for _process_collection_items."""

    def test_empty_items_returns_early(self, make_service):
        service = make_service()
        service.client.get_collection_items.return_value = {"data": []}

        service._process_collection_items(1, "path")

        service.client.get_card.assert_not_called()

    def test_dataset_and_metric_models_exported_as_cards(self, make_service):
        service = make_service()
        service.client.get_collection_items.return_value = {
            "data": [
                {"id": 100, "model": "dataset"},
                {"id": 101, "model": "metric"},
                {"id": 102, "model": "card", "type": "model"},
            ]
        }
        service.client.get_card.side_effect = lambda cid: card_payload(cid)

        service._process_collection_items(1, "path")

        exported = {c.id: c.dataset for c in service.manifest.cards}
        assert exported == {100: True, 101: False, 102: True}

    def test_dashboard_skipped_when_not_included(self, make_service):
        service = make_service(include_dashboards=False)
        service.client.get_collection_items.return_value = {
            "data": [{"id": 200, "model": "dashboard"}]
        }

        service._process_collection_items(1, "path")

        service.client.get_dashboard.assert_not_called()

    def test_dashboard_exported_when_included(self, make_service):
        service = make_service(include_dashboards=True)
        service.client.get_collection_items.return_value = {
            "data": [{"id": 200, "model": "dashboard"}]
        }
        service.client.get_dashboard.return_value = {
            "id": 200,
            "name": "Dash",
            "collection_id": 1,
            "dashcards": [],
        }

        service._process_collection_items(1, "path")

        assert [d.id for d in service.manifest.dashboards] == [200]

    def test_api_error_is_logged_not_raised(self, make_service, caplog):
        service = make_service()
        service.client.get_collection_items.side_effect = MetabaseAPIError("denied")

        with caplog.at_level("ERROR", logger="metabase_migration"):
            service._process_collection_items(1, "path")

        assert "Failed to process items for collection 1" in caplog.text


# ============================================================================
# archived cards
# ============================================================================


class TestExportArchivedCards:
    """Tests for _export_archived_cards."""

    def test_fetch_failure_is_logged(self, make_service, caplog):
        service = make_service()
        service.client.get_archived_cards.side_effect = MetabaseAPIError("nope")

        with caplog.at_level("ERROR", logger="metabase_migration"):
            service._export_archived_cards()

        assert "Failed to fetch archived cards" in caplog.text

    def test_card_without_id_skipped(self, make_service):
        service = make_service()
        service.client.get_archived_cards.return_value = [{"name": "No ID"}]

        service._export_archived_cards()

        service.client.get_card.assert_not_called()

    def test_card_in_processed_collection_exported(self, make_service):
        service = make_service()
        service._processed_collections.add(4)
        service._collection_path_map[4] = "Sales"
        service.client.get_archived_cards.return_value = [
            {"id": 100, "name": "Old", "collection_id": 4}
        ]
        service.client.get_card.return_value = card_payload(100, archived=True)

        service._export_archived_cards()

        assert service.manifest.cards[0].file_path.startswith("Sales/cards/")
        assert service.manifest.cards[0].archived is True

    def test_root_collection_card_skipped(self, make_service, caplog):
        service = make_service()
        service.client.get_archived_cards.return_value = [
            {"id": 100, "name": "Root card", "collection_id": None}
        ]

        with caplog.at_level("DEBUG", logger="metabase_migration"):
            service._export_archived_cards()

        assert "no collection_id (root collection)" in caplog.text
        service.client.get_card.assert_not_called()

    def test_card_outside_processed_collections_skipped(self, make_service):
        service = make_service()
        service.client.get_archived_cards.return_value = [
            {"id": 100, "name": "Elsewhere", "collection_id": 99}
        ]

        service._export_archived_cards()

        service.client.get_card.assert_not_called()


# ============================================================================
# dependency extraction
# ============================================================================


class TestExtractCardDependencies:
    """Tests for the static _extract_card_dependencies helper."""

    def test_v56_source_table_card_reference(self):
        card = {"dataset_query": {"query": {"source-table": "card__12"}}}
        assert ExportService._extract_card_dependencies(card) == {12}

    def test_v56_invalid_source_table_reference(self, caplog):
        card = {"dataset_query": {"query": {"source-table": "card__oops"}}}

        with caplog.at_level("WARNING", logger="metabase_migration"):
            assert ExportService._extract_card_dependencies(card) == set()

        assert "Invalid card reference format: card__oops" in caplog.text

    def test_v57_stage_source_card(self):
        card = {"dataset_query": {"stages": [{"source-card": 12}]}}
        assert ExportService._extract_card_dependencies(card) == {12}

    def test_v57_stage_non_dict_ignored(self):
        card = {"dataset_query": {"stages": ["nope"]}}
        assert ExportService._extract_card_dependencies(card) == set()

    def test_v57_join_source_card(self):
        card = {"dataset_query": {"stages": [{"joins": [{"source-card": 13}]}]}}
        assert ExportService._extract_card_dependencies(card) == {13}

    def test_v56_join_source_table_reference(self):
        card = {"dataset_query": {"query": {"joins": [{"source-table": "card__14"}]}}}
        assert ExportService._extract_card_dependencies(card) == {14}

    def test_v56_join_invalid_reference(self, caplog):
        card = {"dataset_query": {"query": {"joins": [{"source-table": "card__bad"}]}}}

        with caplog.at_level("WARNING", logger="metabase_migration"):
            assert ExportService._extract_card_dependencies(card) == set()

        assert "Invalid card reference in join: card__bad" in caplog.text

    def test_v57_metric_aggregation_reference(self):
        card = {"dataset_query": {"stages": [{"aggregation": [["metric", {"lib/uuid": "u"}, 15]]}]}}
        assert ExportService._extract_card_dependencies(card) == {15}

    def test_parameter_card_dependency(self):
        card = {
            "dataset_query": {"query": {}},
            "parameters": [{"values_source_config": {"card_id": 16}}],
        }
        assert ExportService._extract_card_dependencies(card) == {16}

    def test_no_dependencies(self):
        assert ExportService._extract_card_dependencies({"dataset_query": {}}) == set()


# ============================================================================
# card export with dependencies
# ============================================================================


class TestExportCardWithDependencies:
    """Tests for _export_card_with_dependencies."""

    def test_already_exported_card_skipped(self, make_service):
        service = make_service()
        service._exported_cards.add(100)

        service._export_card_with_dependencies(100, "path")

        service.client.get_card.assert_not_called()

    def test_already_excluded_card_skipped(self, make_service):
        service = make_service(exclude_database_ids=[9])
        service._excluded_cards.add(100)

        service._export_card_with_dependencies(100, "path")

        service.client.get_card.assert_not_called()

    def test_circular_dependency_breaks_cycle(self, make_service, caplog):
        service = make_service()

        with caplog.at_level("WARNING", logger="metabase_migration"):
            service._export_card_with_dependencies(100, "path", dependency_chain=[100, 101])

        assert "Circular dependency detected: 100 -> 101 -> 100" in caplog.text
        service.client.get_card.assert_not_called()

    def test_mutual_dependency_is_broken(self, make_service, caplog):
        """Two cards referencing each other must not recurse forever."""
        service = make_service()
        cards = {
            100: card_payload(
                100,
                dataset_query={
                    "type": "query",
                    "database": 1,
                    "query": {"source-table": "card__101"},
                },
            ),
            101: card_payload(
                101,
                dataset_query={
                    "type": "query",
                    "database": 1,
                    "query": {"source-table": "card__100"},
                },
            ),
        }
        service.client.get_card.side_effect = lambda cid: cards[cid]
        service._collection_path_map[1] = "Sales"

        with caplog.at_level("WARNING", logger="metabase_migration"):
            service._export_card_with_dependencies(100, "Sales")

        assert "Circular dependency detected" in caplog.text
        assert sorted(c.id for c in service.manifest.cards) == [100, 101]

    def test_excluded_card_skips_dependency_traversal(self, make_service):
        service = make_service(exclude_database_ids=[9])
        service.client.get_card.return_value = card_payload(
            100,
            database_id=9,
            dataset_query={"type": "query", "database": 9, "query": {"source-table": "card__101"}},
        )

        service._export_card_with_dependencies(100, "path")

        assert service._excluded_cards == {100}
        assert service.client.get_card.call_count == 1
        assert service.manifest.cards == []

    def test_dependency_placed_in_known_collection_path(self, make_service):
        service = make_service()
        service._collection_path_map[7] = "Shared"
        cards = {
            100: card_payload(
                100,
                dataset_query={
                    "type": "query",
                    "database": 1,
                    "query": {"source-table": "card__101"},
                },
            ),
            101: card_payload(101, collection_id=7),
        }
        service.client.get_card.side_effect = lambda cid: cards[cid]

        service._export_card_with_dependencies(100, "Main")

        paths = {c.id: c.file_path for c in service.manifest.cards}
        assert paths[101].startswith("Shared/cards/")
        assert paths[100].startswith("Main/cards/")

    def test_dependency_outside_scope_goes_to_dependencies_folder(self, make_service, caplog):
        service = make_service()
        cards = {
            100: card_payload(
                100,
                dataset_query={
                    "type": "query",
                    "database": 1,
                    "query": {"source-table": "card__101"},
                },
            ),
            101: card_payload(101, collection_id=None),
        }
        service.client.get_card.side_effect = lambda cid: cards[cid]

        with caplog.at_level("INFO", logger="metabase_migration"):
            service._export_card_with_dependencies(100, "Main")

        assert "is outside export scope" in caplog.text
        assert {c.id: c.file_path for c in service.manifest.cards}[101].startswith(
            "dependencies/cards/"
        )

    def test_archived_dependency_warns_when_flag_not_set(self, make_service, caplog):
        service = make_service(include_archived=False)
        cards = {
            100: card_payload(
                100,
                dataset_query={
                    "type": "query",
                    "database": 1,
                    "query": {"source-table": "card__101"},
                },
            ),
            101: card_payload(101, archived=True),
        }
        service.client.get_card.side_effect = lambda cid: cards[cid]

        with caplog.at_level("WARNING", logger="metabase_migration"):
            service._export_card_with_dependencies(100, "Main")

        assert "Exporting anyway due to dependency" in caplog.text

    def test_dependency_fetch_failure_is_logged(self, make_service, caplog):
        service = make_service()

        def get_card(cid):
            if cid == 101:
                raise MetabaseAPIError("gone")
            return card_payload(
                100,
                dataset_query={
                    "type": "query",
                    "database": 1,
                    "query": {"source-table": "card__101"},
                },
            )

        service.client.get_card.side_effect = get_card

        with caplog.at_level("WARNING", logger="metabase_migration"):
            service._export_card_with_dependencies(100, "Main")

        assert "Failed to fetch dependency card 101" in caplog.text
        assert "may fail to import due to missing dependency 101" in caplog.text
        assert [c.id for c in service.manifest.cards] == [100]

    def test_already_exported_dependency_not_refetched(self, make_service):
        service = make_service()
        service._exported_cards.add(101)
        service.client.get_card.return_value = card_payload(
            100,
            dataset_query={"type": "query", "database": 1, "query": {"source-table": "card__101"}},
        )

        service._export_card_with_dependencies(100, "Main")

        assert service.client.get_card.call_count == 1

    def test_card_fetch_failure_is_logged(self, make_service, caplog):
        service = make_service()
        service.client.get_card.side_effect = MetabaseAPIError("gone")

        with caplog.at_level("ERROR", logger="metabase_migration"):
            service._export_card_with_dependencies(100, "Main")

        assert "Failed to fetch card 100 for dependency analysis" in caplog.text


class TestExportCard:
    """Tests for _export_card."""

    def test_already_exported_returns_early(self, make_service):
        service = make_service()
        service._exported_cards.add(100)

        service._export_card(100, "path")

        service.client.get_card.assert_not_called()

    def test_fetches_card_when_not_provided(self, make_service):
        service = make_service()
        service.client.get_card.return_value = card_payload(100)

        service._export_card(100, "path")

        service.client.get_card.assert_called_once_with(100)
        assert [c.id for c in service.manifest.cards] == [100]

    def test_excluded_database_card_not_written(self, make_service, caplog):
        service = make_service(exclude_database_ids=[9])

        with caplog.at_level("INFO", logger="metabase_migration"):
            service._export_card(100, "path", card_payload(100, database_id=9))

        assert "database 9 is excluded" in caplog.text
        assert service.manifest.cards == []
        assert service._excluded_cards == {100}

    def test_database_id_resolved_from_dataset_query(self, make_service):
        """Cards without a top-level database_id fall back to dataset_query.database."""
        service = make_service()
        card = card_payload(100)
        del card["database_id"]

        service._export_card(100, "path", card)

        assert service.manifest.cards[0].database_id == 1

    def test_card_without_dataset_query_skipped(self, make_service, caplog):
        service = make_service()

        with caplog.at_level("WARNING", logger="metabase_migration"):
            service._export_card(100, "path", {"id": 100, "name": "Empty", "dataset_query": None})

        assert "has no dataset_query" in caplog.text
        assert service.manifest.cards == []

    def test_card_without_database_id_skipped(self, make_service, caplog):
        service = make_service()
        card = {"id": 100, "name": "No DB", "dataset_query": {"type": "native"}}

        with caplog.at_level("WARNING", logger="metabase_migration"):
            service._export_card(100, "path", card)

        assert "has no database ID" in caplog.text
        assert service.manifest.cards == []

    def test_legacy_dataset_flag_marks_model(self, make_service):
        service = make_service()

        service._export_card(100, "path", card_payload(100, dataset=True))

        assert service.manifest.cards[0].dataset is True

    def test_api_error_is_logged(self, make_service, caplog):
        service = make_service()
        service.client.get_card.side_effect = MetabaseAPIError("denied")

        with caplog.at_level("ERROR", logger="metabase_migration"):
            service._export_card(100, "path")

        assert "Failed to export card ID 100" in caplog.text

    def test_unexpected_error_is_logged(self, make_service, caplog):
        service = make_service()

        with patch("lib.services.export_service.write_json_file", side_effect=OSError("disk full")):
            with caplog.at_level("ERROR", logger="metabase_migration"):
                service._export_card(100, "path", card_payload(100))

        assert "An unexpected error occurred while exporting card ID 100" in caplog.text
        assert service.manifest.cards == []


# ============================================================================
# dashboards
# ============================================================================


class TestExportDashboard:
    """Tests for _export_dashboard."""

    def test_archived_dashboard_404_is_skipped(self, make_service, caplog):
        service = make_service()
        service.client.get_dashboard.side_effect = MetabaseAPIError(
            "Dashboard is archived", status_code=404
        )

        with caplog.at_level("WARNING", logger="metabase_migration"):
            service._export_dashboard(200, "path")

        assert "Skipping archived dashboard ID 200" in caplog.text
        assert service.manifest.dashboards == []

    def test_other_api_errors_are_reraised(self, make_service):
        service = make_service()
        service.client.get_dashboard.side_effect = MetabaseAPIError("denied", status_code=403)

        with pytest.raises(MetabaseAPIError):
            service._export_dashboard(200, "path")

    def test_non_404_not_found_message_reraised(self, make_service):
        service = make_service()
        service.client.get_dashboard.side_effect = MetabaseAPIError("not found", status_code=404)

        with pytest.raises(MetabaseAPIError):
            service._export_dashboard(200, "path")

    def test_dashcards_without_card_id_ignored(self, make_service):
        service = make_service()
        service.client.get_dashboard.return_value = {
            "id": 200,
            "name": "Dash",
            "collection_id": 1,
            "dashcards": [{"id": 1, "card_id": None}, {"id": 2}],
        }

        service._export_dashboard(200, "path")

        assert service.manifest.dashboards[0].ordered_cards == []

    def test_parameter_source_card_added_as_dependency(self, make_service, caplog):
        service = make_service()
        service.client.get_dashboard.return_value = {
            "id": 200,
            "name": "Dash",
            "collection_id": 1,
            "dashcards": [],
            "parameters": [
                {"name": "Category", "values_source_config": {"card_id": 100}},
                {"name": "Static", "values_source_config": {"values": []}},
                {"name": "NoConfig"},
            ],
        }
        service.client.get_card.return_value = card_payload(100)

        with caplog.at_level("INFO", logger="metabase_migration"):
            service._export_dashboard(200, "path")

        assert "references card 100 - will be exported as dependency" in caplog.text
        assert service.manifest.dashboards[0].ordered_cards == [100]

    def test_duplicate_parameter_card_not_added_twice(self, make_service):
        service = make_service()
        service.client.get_dashboard.return_value = {
            "id": 200,
            "name": "Dash",
            "collection_id": 1,
            "dashcards": [{"id": 1, "card_id": 100}],
            "parameters": [{"name": "P", "values_source_config": {"card_id": 100}}],
        }
        service.client.get_card.return_value = card_payload(100)

        service._export_dashboard(200, "path")

        assert service.manifest.dashboards[0].ordered_cards == [100]

    def test_card_in_known_collection_uses_its_path(self, make_service):
        service = make_service()
        service._collection_path_map[7] = "Shared"
        service.client.get_dashboard.return_value = {
            "id": 200,
            "name": "Dash",
            "collection_id": 1,
            "dashcards": [{"id": 1, "card_id": 100}],
        }
        service.client.get_card.return_value = card_payload(100, collection_id=7)

        service._export_dashboard(200, "path")

        assert service.manifest.cards[0].file_path.startswith("Shared/cards/")

    def test_card_outside_scope_uses_dependencies_folder(self, make_service, caplog):
        service = make_service()
        service.client.get_dashboard.return_value = {
            "id": 200,
            "name": "Dash",
            "collection_id": 1,
            "dashcards": [{"id": 1, "card_id": 100}],
        }
        service.client.get_card.return_value = card_payload(100, collection_id=None)

        with caplog.at_level("INFO", logger="metabase_migration"):
            service._export_dashboard(200, "path")

        assert "is outside export scope" in caplog.text
        assert service.manifest.cards[0].file_path.startswith("dependencies/cards/")

    def test_already_exported_card_not_refetched(self, make_service):
        service = make_service()
        service._exported_cards.add(100)
        service.client.get_dashboard.return_value = {
            "id": 200,
            "name": "Dash",
            "collection_id": 1,
            "dashcards": [{"id": 1, "card_id": 100}],
        }

        service._export_dashboard(200, "path")

        service.client.get_card.assert_not_called()
        assert service.manifest.dashboards[0].ordered_cards == [100]

    def test_excluded_card_not_fetched(self, make_service):
        service = make_service(exclude_database_ids=[9])
        service._excluded_cards.add(100)
        service.client.get_dashboard.return_value = {
            "id": 200,
            "name": "Dash",
            "collection_id": 1,
            "dashcards": [{"id": 1, "card_id": 100}],
        }

        service._export_dashboard(200, "path")

        service.client.get_card.assert_not_called()
        assert service.manifest.dashboards[0].ordered_cards == [100]

    def test_card_fetch_failure_is_logged(self, make_service, caplog):
        service = make_service()
        service.client.get_dashboard.return_value = {
            "id": 200,
            "name": "Dash",
            "collection_id": 1,
            "dashcards": [{"id": 1, "card_id": 100}],
        }
        service.client.get_card.side_effect = MetabaseAPIError("gone")

        with caplog.at_level("WARNING", logger="metabase_migration"):
            service._export_dashboard(200, "path")

        assert "Failed to export card 100" in caplog.text
        assert "may fail to import due to missing card 100" in caplog.text
        assert [d.id for d in service.manifest.dashboards] == [200]

    def test_unexpected_error_is_logged(self, make_service, caplog):
        service = make_service()
        service.client.get_dashboard.return_value = {
            "id": 200,
            "name": "Dash",
            "collection_id": 1,
            "dashcards": [],
        }

        with patch("lib.services.export_service.write_json_file", side_effect=OSError("disk full")):
            with caplog.at_level("ERROR", logger="metabase_migration"):
                service._export_dashboard(200, "path")

        assert "An unexpected error occurred while exporting dashboard ID 200" in caplog.text
        assert service.manifest.dashboards == []

    def test_api_error_during_export_is_logged(self, make_service, caplog):
        service = make_service()
        service.client.get_dashboard.return_value = {
            "id": 200,
            "name": "Dash",
            "collection_id": 1,
            "dashcards": [],
        }

        with patch(
            "lib.services.export_service.calculate_checksum",
            side_effect=MetabaseAPIError("boom"),
        ):
            with caplog.at_level("ERROR", logger="metabase_migration"):
                service._export_dashboard(200, "path")

        assert "Failed to export dashboard ID 200" in caplog.text


# ============================================================================
# permissions
# ============================================================================


class TestExportPermissions:
    """Tests for _export_permissions."""

    def test_exports_groups_and_graphs(self, make_service):
        service = make_service()
        service.client.get_permission_groups.return_value = [
            {"id": 1, "name": "All Users", "member_count": 5}
        ]
        service.client.get_permissions_graph.return_value = {"revision": 1}
        service.client.get_collection_permissions_graph.return_value = {"revision": 2}

        service._export_permissions()

        assert service.manifest.permission_groups[0].member_count == 5
        assert service.manifest.permissions_graph == {"revision": 1}
        assert service.manifest.collection_permissions_graph == {"revision": 2}

    def test_api_error_does_not_abort_export(self, make_service, caplog):
        service = make_service()
        service.client.get_permission_groups.side_effect = MetabaseAPIError("denied")

        with caplog.at_level("WARNING", logger="metabase_migration"):
            service._export_permissions()

        assert "Failed to export permissions" in caplog.text
        assert "The export will continue without permissions data." in caplog.text

    def test_unexpected_error_does_not_abort_export(self, make_service, caplog):
        service = make_service()
        service.client.get_permission_groups.side_effect = RuntimeError("kaboom")

        with caplog.at_level("WARNING", logger="metabase_migration"):
            service._export_permissions()

        assert "An unexpected error occurred while exporting permissions" in caplog.text


# ============================================================================
# exclusion helpers
# ============================================================================


class TestExclusionHelpers:
    """Tests for _resolve_card_database_id and _is_card_excluded."""

    def test_resolve_prefers_top_level_database_id(self):
        assert (
            ExportService._resolve_card_database_id(
                {"database_id": 3, "dataset_query": {"database": 4}}
            )
            == 3
        )

    def test_resolve_falls_back_to_dataset_query(self):
        assert ExportService._resolve_card_database_id({"dataset_query": {"database": 4}}) == 4

    def test_resolve_handles_missing_dataset_query(self):
        assert ExportService._resolve_card_database_id({"name": "x"}) is None

    def test_resolve_handles_null_dataset_query(self):
        assert ExportService._resolve_card_database_id({"dataset_query": None}) is None

    def test_not_excluded_without_configuration(self, make_service):
        service = make_service()
        assert service._is_card_excluded(1, {"database_id": 9}) is False
        assert service._excluded_cards == set()

    def test_not_excluded_when_database_not_listed(self, make_service):
        service = make_service(exclude_database_ids=[9])
        assert service._is_card_excluded(1, {"database_id": 1}) is False
        assert service._excluded_cards == set()

    def test_excluded_card_is_tracked(self, make_service):
        service = make_service(exclude_database_ids=[9])
        assert service._is_card_excluded(1, {"database_id": 9}) is True
        assert service._excluded_cards == {1}


def test_manifest_metadata_omits_version_when_absent(tmp_path):
    """_initialize_manifest tolerates a config dump without metabase_version."""
    config = ExportConfig(
        source_url="https://source.example.com",
        export_dir=str(tmp_path / "export"),
        source_session_token="tok",
    )
    with patch("lib.services.export_service.MetabaseClient"):
        with patch.object(
            ExportConfig, "model_dump", return_value={"source_url": config.source_url}
        ):
            service = ExportService(config)

    assert "metabase_version" not in service.manifest.meta.cli_args
    assert service.manifest.meta.metabase_version == "v56"


def test_client_constructed_from_config(tmp_path):
    """The service wires every credential from the config into the client."""
    config = ExportConfig(
        source_url="https://source.example.com",
        export_dir=str(tmp_path / "export"),
        source_personal_token="pat",
    )
    with patch("lib.services.export_service.MetabaseClient") as mock_client_cls:
        ExportService(config)

    mock_client_cls.assert_called_once_with(
        base_url="https://source.example.com",
        username=None,
        password=None,
        session_token=None,
        personal_token="pat",
    )
    assert isinstance(mock_client_cls.return_value, Mock)
