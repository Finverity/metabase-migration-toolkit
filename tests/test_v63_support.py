"""
Tests for Metabase v63 support.

Covers the v63 version adapter, "table" template-tag remapping (Table
Variables), list-form template-tag edge cases, measure clause remapping and
measure migration, parameter label_field remapping, dashcard
inline_parameters preservation, document detection during export, the
--include-library flag, and explicit "none" collection-permission filling.
"""

import os
from unittest.mock import Mock, patch

import pytest

from lib.config import ExportConfig, ImportConfig
from lib.constants import SUPPORTED_METABASE_VERSIONS, MetabaseVersion
from lib.handlers.base import ImportContext
from lib.handlers.dashboard import DashboardHandler
from lib.handlers.permissions import PermissionsHandler
from lib.models import Card, DatabaseMap, ImportReport, Manifest, ManifestMeta, PermissionGroup
from lib.remapping.id_mapper import IDMapper
from lib.remapping.query_remapper import QueryRemapper
from lib.services.export_service import ExportService
from lib.services.import_service import ImportService
from lib.version import V63Adapter, get_version_adapter, get_version_config


def _make_manifest(databases: dict[int, str] | None = None) -> Manifest:
    return Manifest(
        meta=ManifestMeta(
            source_url="https://source.example.com",
            export_timestamp="2026-01-01T00:00:00",
            tool_version="1.0.0",
            cli_args={},
        ),
        databases=databases or {},
    )


def _make_id_mapper(
    db_mapping: dict[int, int] | None = None,
    card_mapping: dict[int, int] | None = None,
) -> IDMapper:
    db_mapping = db_mapping or {}
    card_mapping = card_mapping or {}
    manifest = _make_manifest({source_id: f"DB{source_id}" for source_id in db_mapping})
    db_map = DatabaseMap(by_id={str(k): v for k, v in db_mapping.items()})
    mapper = IDMapper(manifest, db_map)
    for source_id, target_id in card_mapping.items():
        mapper.set_card_mapping(source_id, target_id)
    return mapper


def _make_export_config(**overrides) -> ExportConfig:
    defaults = {
        "source_url": "https://source.example.com",
        "export_dir": "./test_export",
        "source_username": "test@example.com",
        "source_password": "password123",  # pragma: allowlist secret
        "metabase_version": MetabaseVersion.V63,
    }
    defaults.update(overrides)
    return ExportConfig(**defaults)


class TestV63VersionSupport:
    """Tests for the v63 version enum and adapter."""

    def test_v63_in_supported_versions(self):
        assert "v63" in SUPPORTED_METABASE_VERSIONS

    def test_get_version_adapter_returns_v63_adapter(self):
        adapter = get_version_adapter(MetabaseVersion.V63)
        assert isinstance(adapter, V63Adapter)
        assert adapter.version == MetabaseVersion.V63

    def test_v63_uses_stages(self):
        config = get_version_config(MetabaseVersion.V63)
        assert config.mbql_config.uses_stages is True

    def test_v63_dependency_extraction_matches_v58(self):
        """v63 inherits v58 dependency extraction (stages, card tags, list form)."""
        card_data = {
            "dataset_query": {
                "lib/type": "mbql/query",
                "stages": [
                    {
                        "lib/type": "mbql.stage/native",
                        "native": "SELECT * FROM {{#50-model}}",
                        "template-tags": [{"type": "card", "name": "50-model", "card-id": 50}],
                    },
                    {"lib/type": "mbql.stage/mbql", "source-table": "card__60"},
                ],
            }
        }
        v58 = get_version_adapter(MetabaseVersion.V58)
        v63 = get_version_adapter(MetabaseVersion.V63)
        assert v63.extract_card_dependencies(card_data) == {50, 60}
        assert v63.extract_card_dependencies(card_data) == v58.extract_card_dependencies(card_data)


class TestTableTemplateTagRemapping:
    """Tests for v63 "table" template tags (Table Variables)."""

    @pytest.fixture
    def remapper(self):
        id_mapper = _make_id_mapper(db_mapping={1: 100}, card_mapping={50: 500})
        id_mapper._table_map[(1, 27)] = 42
        id_mapper._field_map[(1, 159)] = 301
        return QueryRemapper(id_mapper)

    def test_remap_table_tag_dict_form(self, remapper):
        tags = {
            "invoices": {
                "type": "table",
                "name": "invoices",
                "display-name": "Invoices",
                "table-id": 27,
                "alias": "inv",
                "source-filters": [{"field-id": 159, "op": "=", "value": "open"}],
            }
        }
        result = remapper._remap_template_tags(tags, source_db_id=1)

        assert result["invoices"]["table-id"] == 42
        assert result["invoices"]["source-filters"][0]["field-id"] == 301
        assert result["invoices"]["alias"] == "inv"
        # The original tag must not be mutated
        assert tags["invoices"]["table-id"] == 27
        assert tags["invoices"]["source-filters"][0]["field-id"] == 159

    def test_remap_table_tag_list_form(self, remapper):
        tags = [
            {
                "type": "table",
                "name": "invoices",
                "table-id": 27,
                "source-filters": [{"field-id": 159, "op": "=", "value": "open"}],
            },
            {"type": "text", "name": "client"},
        ]
        result = remapper._remap_template_tags(tags, source_db_id=1)

        assert isinstance(result, list)
        assert result[0]["table-id"] == 42
        assert result[0]["source-filters"][0]["field-id"] == 301
        assert result[1] == {"type": "text", "name": "client"}

    def test_remap_table_tag_unmapped_ids_kept(self, remapper):
        tags = {
            "orders": {
                "type": "table",
                "name": "orders",
                "table-id": 999,
                "source-filters": [{"field-id": 888, "op": "=", "value": "x"}],
            }
        }
        result = remapper._remap_template_tags(tags, source_db_id=1)

        assert result["orders"]["table-id"] == 999
        assert result["orders"]["source-filters"][0]["field-id"] == 888

    def test_remap_table_tag_in_card_data(self, remapper):
        """End-to-end: a v63 stages-form card with a table tag remaps cleanly."""
        card_data = {
            "database_id": 1,
            "dataset_query": {
                "lib/type": "mbql/query",
                "database": 1,
                "stages": [
                    {
                        "lib/type": "mbql.stage/native",
                        "native": "SELECT * FROM {{invoices}}",
                        "template-tags": [{"type": "table", "name": "invoices", "table-id": 27}],
                    }
                ],
            },
        }
        result, success = remapper.remap_card_data(card_data)

        assert success is True
        tags = result["dataset_query"]["stages"][0]["template-tags"]
        assert tags[0]["table-id"] == 42


class TestListFormTemplateTagEdgeCases:
    """Edge cases for list-form template-tags not covered by the base tests."""

    @pytest.fixture
    def remapper(self):
        return QueryRemapper(_make_id_mapper(db_mapping={1: 100}, card_mapping={50: 500}))

    def test_non_dict_entries_pass_through(self, remapper):
        tags = ["garbage", {"type": "text", "name": "client"}, 42]
        result = remapper._remap_template_tags(tags, source_db_id=1)

        assert result == ["garbage", {"type": "text", "name": "client"}, 42]

    def test_unmapped_card_tag_kept(self, remapper):
        tags = [{"type": "card", "name": "99-missing", "card-id": 99}]
        result = remapper._remap_template_tags(tags, source_db_id=1)

        assert result[0]["card-id"] == 99
        assert result[0]["name"] == "99-missing"

    def test_duplicate_names_preserved(self, remapper):
        tags = [
            {"type": "text", "name": "dup", "id": "a"},
            {"type": "text", "name": "dup", "id": "b"},
        ]
        result = remapper._remap_template_tags(tags, source_db_id=1)

        assert len(result) == 2
        assert {tag["id"] for tag in result} == {"a", "b"}


class TestMeasureClauseRemapping:
    """Tests for v63 ["measure", {...}, id] clause remapping."""

    def test_remap_measure_clause(self):
        id_mapper = _make_id_mapper(db_mapping={1: 100})
        id_mapper.set_measure_mapping(5, 77)
        remapper = QueryRemapper(id_mapper)

        clause = ["measure", {"lib/uuid": "x"}, 5]
        result = remapper.remap_field_ids_recursively(clause, 1)

        assert result == ["measure", {"lib/uuid": "x"}, 77]

    def test_unmapped_measure_clause_kept(self):
        remapper = QueryRemapper(_make_id_mapper(db_mapping={1: 100}))

        clause = ["measure", {"lib/uuid": "x"}, 5]
        result = remapper.remap_field_ids_recursively(clause, 1)

        assert result[2] == 5


class TestParameterLabelFieldRemapping:
    """Tests for v63 values_source_config.label_field remapping."""

    def test_label_field_remapped_alongside_value_field(self):
        id_mapper = _make_id_mapper(db_mapping={2: 2}, card_mapping={232: 501})
        id_mapper._field_map[(2, 159)] = 301
        id_mapper._field_map[(2, 160)] = 302
        remapper = QueryRemapper(id_mapper)

        card_data = {
            "database_id": 2,
            "dataset_query": {
                "type": "native",
                "native": {"query": "SELECT 1 WHERE client = {{client}}"},
            },
            "parameters": [
                {
                    "name": "Client",
                    "values_source_type": "card",
                    "values_source_config": {
                        "card_id": 232,
                        "value_field": ["field", {"lib/uuid": "v"}, 159],
                        "label_field": ["field", {"lib/uuid": "l"}, 160],
                    },
                }
            ],
        }
        manifest_cards = [
            Card(
                id=232,
                name="Client list",
                collection_id=20,
                database_id=2,
                file_path="cards/card_232.json",
                checksum="abc",
            )
        ]

        remapped_data, success = remapper.remap_card_data(card_data, manifest_cards)

        assert success is True
        config = remapped_data["parameters"][0]["values_source_config"]
        assert config["card_id"] == 501
        assert config["value_field"][2] == 301
        assert config["label_field"][2] == 302


class TestInlineParametersPreserved:
    """Tests for v63 dashcard inline_parameters (filter-widget placement)."""

    @pytest.fixture
    def import_context(self, tmp_path):
        id_mapper = Mock(spec=IDMapper)
        id_mapper.resolve_card_id.return_value = 999
        query_remapper = Mock(spec=QueryRemapper)
        query_remapper.remap_dashcard_visualization_settings.side_effect = lambda x, _: x
        manifest = Mock(spec=Manifest)
        manifest.cards = []
        config = Mock(spec=ImportConfig)
        config.conflict_strategy = "skip"
        return ImportContext(
            config=config,
            client=Mock(),
            manifest=manifest,
            export_dir=tmp_path,
            id_mapper=id_mapper,
            query_remapper=query_remapper,
            report=Mock(spec=ImportReport),
            target_collections=[],
        )

    def test_inline_parameters_copied(self, import_context):
        dashcard = {
            "id": 1,
            "card_id": 1,
            "row": 0,
            "col": 0,
            "size_x": 6,
            "size_y": 4,
            "inline_parameters": ["abc-123", "def-456"],
        }
        handler = DashboardHandler(import_context)
        result = handler._prepare_single_dashcard(dashcard, temp_id=-1)

        assert result["inline_parameters"] == ["abc-123", "def-456"]

    def test_inline_parameters_absent(self, import_context):
        dashcard = {"id": 1, "card_id": 1, "row": 0, "col": 0, "size_x": 6, "size_y": 4}
        handler = DashboardHandler(import_context)
        result = handler._prepare_single_dashcard(dashcard, temp_id=-1)

        assert "inline_parameters" not in result

    def test_inline_parameters_null_dropped(self, import_context):
        dashcard = {
            "id": 1,
            "card_id": 1,
            "row": 0,
            "col": 0,
            "size_x": 6,
            "size_y": 4,
            "inline_parameters": None,
        }
        handler = DashboardHandler(import_context)
        result = handler._prepare_single_dashcard(dashcard, temp_id=-1)

        assert "inline_parameters" not in result


class TestCollectionPermissionsNoneFill:
    """Tests for explicit "none" filling in the collection permissions graph."""

    @pytest.fixture
    def import_context(self, tmp_path):
        manifest = Mock(spec=Manifest)
        manifest.permission_groups = [
            PermissionGroup(id=2, name="Administrators", member_count=1),
            PermissionGroup(id=3, name="Analysts", member_count=5),
            PermissionGroup(id=4, name="Viewers", member_count=10),
        ]
        manifest.collection_permissions_graph = {
            "revision": 1,
            "groups": {
                "3": {"10": "write", "20": "read"},
                "4": {"10": "read", "root": "none"},
            },
        }
        id_mapper = Mock(spec=IDMapper)
        id_mapper.group_map = {}
        id_mapper.collection_map = {}
        client = Mock()
        client.get_collection_permissions_graph.return_value = {"revision": 3}
        return ImportContext(
            config=Mock(spec=ImportConfig),
            client=client,
            manifest=manifest,
            export_dir=tmp_path,
            id_mapper=id_mapper,
            query_remapper=Mock(spec=QueryRemapper),
            report=Mock(spec=ImportReport),
            target_collections=[],
        )

    def test_absent_pairs_filled_with_none(self, import_context):
        id_mapper = import_context.id_mapper
        id_mapper.group_map = {3: 100, 4: 101}
        id_mapper.collection_map = {10: 1010, 20: 1020}
        id_mapper.resolve_collection_id.side_effect = lambda x: {10: 1010, 20: 1020}.get(x)

        handler = PermissionsHandler(import_context)
        result = handler._remap_collection_permissions_graph(
            import_context.manifest.collection_permissions_graph
        )

        assert result["groups"]["100"] == {"1010": "write", "1020": "read"}
        # Group 4 had no entry for collection 20 -> explicit "none"
        assert result["groups"]["101"]["1010"] == "read"
        assert result["groups"]["101"]["1020"] == "none"
        # Root pass-through is untouched and never synthesized
        assert result["groups"]["101"]["root"] == "none"
        assert "root" not in result["groups"]["100"]

    def test_group_absent_from_graph_gets_all_none(self, import_context):
        id_mapper = import_context.id_mapper
        id_mapper.group_map = {3: 100, 5: 105}  # group 5 has no graph entries
        id_mapper.collection_map = {10: 1010}
        id_mapper.resolve_collection_id.side_effect = lambda x: {10: 1010, 20: None}.get(x)
        import_context.manifest.permission_groups.append(
            PermissionGroup(id=5, name="Auditors", member_count=2)
        )

        handler = PermissionsHandler(import_context)
        result = handler._remap_collection_permissions_graph(
            import_context.manifest.collection_permissions_graph
        )

        assert result["groups"]["105"] == {"1010": "none"}

    def test_administrators_not_filled(self, import_context):
        id_mapper = import_context.id_mapper
        id_mapper.group_map = {2: 999}  # only the Administrators group is mapped
        id_mapper.collection_map = {10: 1010}
        id_mapper.resolve_collection_id.return_value = None

        handler = PermissionsHandler(import_context)
        result = handler._remap_collection_permissions_graph(
            import_context.manifest.collection_permissions_graph
        )

        assert result == {}


class TestV63DocumentDetection:
    """Tests for detecting (and reporting) v63 documents during export."""

    def test_documents_requested_and_skipped_for_v63(self):
        with patch("lib.services.export_service.MetabaseClient") as mock_client_class:
            mock_client = Mock()
            mock_client.get_collection_items.return_value = {
                "data": [
                    {"id": 7, "model": "document", "name": "Q3 Report"},
                    {"id": 100, "model": "card"},
                ]
            }
            mock_client_class.return_value = mock_client

            exporter = ExportService(_make_export_config())
            with patch.object(exporter, "_export_card_with_dependencies") as mock_export:
                exporter._process_collection_items(1, "test-path")

            params = mock_client.get_collection_items.call_args[0][1]
            assert "document" in params["models"]
            assert exporter._skipped_documents == ["Q3 Report"]
            assert mock_export.call_count == 1  # the card is still exported

    def test_documents_not_requested_before_v63(self):
        with patch("lib.services.export_service.MetabaseClient") as mock_client_class:
            mock_client = Mock()
            mock_client.get_collection_items.return_value = {"data": []}
            mock_client_class.return_value = mock_client

            exporter = ExportService(_make_export_config(metabase_version=MetabaseVersion.V56))
            exporter._process_collection_items(1, "test-path")

            params = mock_client.get_collection_items.call_args[0][1]
            assert "document" not in params["models"]


class TestV63MeasureExport:
    """Tests for exporting v63 measures into the manifest."""

    def test_export_measures_filters_by_known_tables(self):
        with patch("lib.services.export_service.MetabaseClient") as mock_client_class:
            mock_client = Mock()
            mock_client.get_measures.return_value = [
                {"id": 5, "name": "Total", "table_id": 27, "definition": {"aggregation": []}},
                {"id": 6, "name": "Foreign", "table_id": 99, "definition": {}},
                {"id": 7, "name": "Old", "table_id": 27, "definition": {}, "archived": True},
            ]
            mock_client_class.return_value = mock_client

            exporter = ExportService(_make_export_config())
            exporter.manifest.database_metadata = {
                1: {"tables": [{"id": 27, "name": "orders", "fields": []}]}
            }
            exporter._export_measures()

            assert len(exporter.manifest.measures) == 1
            assert exporter.manifest.measures[0]["id"] == 5
            assert exporter.manifest.measures[0]["table_id"] == 27


class TestIncludeLibraryParam:
    """Tests for the --include-library export flag."""

    def _run_export_with(self, config) -> Mock:
        with patch("lib.services.export_service.MetabaseClient") as mock_client_class:
            mock_client = Mock()
            mock_client.get_databases.return_value = []
            mock_client.get_collections_tree.return_value = []
            mock_client_class.return_value = mock_client

            exporter = ExportService(config)
            exporter.run_export()  # returns early: no collections
            return mock_client

    def test_include_library_passed_for_v63(self, tmp_path):
        config = _make_export_config(export_dir=str(tmp_path), include_library=True)
        client = self._run_export_with(config)

        client.get_collections_tree.assert_called_with(params={"include-library": "true"})

    def test_include_library_ignored_before_v63(self, tmp_path):
        config = _make_export_config(
            export_dir=str(tmp_path),
            include_library=True,
            metabase_version=MetabaseVersion.V58,
        )
        client = self._run_export_with(config)

        client.get_collections_tree.assert_called_with()

    @patch.dict(os.environ, {}, clear=True)
    @patch(
        "sys.argv",
        [
            "export_metabase.py",
            "--source-url",
            "https://cli.example.com",
            "--source-username",
            "cli_user@example.com",
            "--source-password",
            "cli_password",
            "--export-dir",
            "./cli_export",
            "--include-library",
        ],
    )
    def test_include_library_cli_flag(self):
        from lib.config import get_export_args

        config = get_export_args()
        assert config.include_library is True


class TestImportMeasures:
    """Tests for measure creation and mapping during import."""

    def _make_service(self, tmp_path):
        config = ImportConfig(
            target_url="https://target.example.com",
            export_dir=str(tmp_path),
            db_map_path="./db_map.json",
            target_username="test@example.com",
            target_password="password123",  # pragma: allowlist secret
            metabase_version=MetabaseVersion.V63,
        )
        with patch("lib.services.import_service.MetabaseClient"):
            service = ImportService(config)

        manifest = _make_manifest({1: "DB1"})
        manifest.database_metadata = {1: {"tables": [{"id": 27, "name": "orders", "fields": []}]}}
        manifest.measures = [
            {
                "id": 5,
                "name": "Total",
                "description": "Sum of totals",
                "table_id": 27,
                "definition": {"aggregation": [["sum", ["field", {"lib/uuid": "u"}, 159]]]},
            }
        ]
        service.manifest = manifest

        id_mapper = IDMapper(manifest, DatabaseMap(by_id={"1": 100}))
        id_mapper._table_map[(1, 27)] = 42
        id_mapper._field_map[(1, 159)] = 301
        service._id_mapper = id_mapper
        service._query_remapper = QueryRemapper(id_mapper)
        service.client = Mock()
        return service

    def test_creates_measure_with_remapped_ids(self, tmp_path):
        service = self._make_service(tmp_path)
        service.client.get_measures.return_value = []
        service.client.create_measure.return_value = {"id": 77}

        service._import_measures()

        payload = service.client.create_measure.call_args[0][0]
        assert payload["name"] == "Total"
        assert payload["table_id"] == 42
        assert payload["description"] == "Sum of totals"
        assert payload["definition"]["aggregation"][0][1][2] == 301
        assert service._id_mapper.resolve_measure_id(5) == 77

    def test_reuses_existing_target_measure(self, tmp_path):
        service = self._make_service(tmp_path)
        service.client.get_measures.return_value = [{"id": 88, "table_id": 42, "name": "Total"}]

        service._import_measures()

        service.client.create_measure.assert_not_called()
        assert service._id_mapper.resolve_measure_id(5) == 88

    def test_skips_measure_with_unmapped_table(self, tmp_path):
        service = self._make_service(tmp_path)
        service._id_mapper._table_map.clear()
        service.client.get_measures.return_value = []

        service._import_measures()

        service.client.create_measure.assert_not_called()
        assert service._id_mapper.resolve_measure_id(5) is None

    def test_no_measures_is_a_no_op(self, tmp_path):
        service = self._make_service(tmp_path)
        service.manifest.measures = []

        service._import_measures()

        service.client.get_measures.assert_not_called()
