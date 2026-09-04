"""Unit tests for lib/remapping/query_remapper.py.

Covers the QueryRemapper paths that the feature-oriented suites
(test_native_query_remapping.py, test_card_parameter_remapping.py,
test_dashboard_filters.py) do not exercise: warning/fallback branches,
malformed input handling, Visualizer settings, click behaviors and link cards.
"""

import pytest

from lib.models import Card, DatabaseMap, Manifest, ManifestMeta
from lib.remapping.id_mapper import IDMapper
from lib.remapping.query_remapper import QueryRemapper


def build_mapper(
    db_mapping: dict[int, int] | None = None,
    card_mapping: dict[int, int] | None = None,
    dashboard_mapping: dict[int, int] | None = None,
    table_mapping: dict[tuple[int, int], int] | None = None,
    field_mapping: dict[tuple[int, int], int] | None = None,
) -> IDMapper:
    """Build an IDMapper pre-populated with the given mappings."""
    db_mapping = db_mapping or {1: 10}

    manifest = Manifest(
        meta=ManifestMeta(
            source_url="https://source.example.com",
            export_timestamp="2025-01-01T00:00:00",
            tool_version="1.0.0",
            cli_args={},
        ),
        databases={source_id: f"DB{source_id}" for source_id in db_mapping},
    )
    mapper = IDMapper(manifest, DatabaseMap(by_id={str(k): v for k, v in db_mapping.items()}))

    for source_id, target_id in (card_mapping or {}).items():
        mapper.set_card_mapping(source_id, target_id)
    for source_id, target_id in (dashboard_mapping or {}).items():
        mapper.set_dashboard_mapping(source_id, target_id)
    mapper.table_map.update(table_mapping or {})
    mapper.field_map.update(field_mapping or {})

    return mapper


@pytest.fixture
def remapper() -> QueryRemapper:
    """A QueryRemapper with db 1->10, card 5->50, dashboard 7->70, table/field maps."""
    return QueryRemapper(
        build_mapper(
            db_mapping={1: 10},
            card_mapping={5: 50},
            dashboard_mapping={7: 70},
            table_mapping={(1, 100): 1000},
            field_mapping={(1, 200): 2000},
        )
    )


# ============================================================================
# remap_card_data
# ============================================================================


class TestRemapCardData:
    """Tests for the top-level remap_card_data entry point."""

    def test_returns_false_when_no_database_reference(self, remapper):
        """A card with neither database_id nor dataset_query.database is not remappable."""
        data, success = remapper.remap_card_data({"name": "No DB", "dataset_query": {}})

        assert success is False
        assert data["name"] == "No DB"

    def test_raises_on_unmapped_database(self, remapper):
        """An unmapped source database is a fatal error at import time."""
        with pytest.raises(ValueError, match="Unmapped database ID 99"):
            remapper.remap_card_data({"database_id": 99, "dataset_query": {"database": 99}})

    def test_sets_query_database_without_top_level_database_id(self, remapper):
        """When database_id is absent, only dataset_query.database is rewritten."""
        card = {"name": "Card", "dataset_query": {"database": 1, "type": "query", "query": {}}}

        data, success = remapper.remap_card_data(card)

        assert success is True
        assert data["dataset_query"]["database"] == 10
        assert "database_id" not in data

    def test_does_not_mutate_input(self, remapper):
        """remap_card_data works on a deep copy of the input."""
        card = {"database_id": 1, "dataset_query": {"database": 1, "type": "query", "query": {}}}

        remapper.remap_card_data(card)

        assert card["database_id"] == 1
        assert card["dataset_query"]["database"] == 1

    def test_remaps_card_level_table_id(self, remapper):
        """table_id at the card level is remapped through the table map."""
        card = {
            "database_id": 1,
            "table_id": 100,
            "dataset_query": {"database": 1, "type": "query", "query": {}},
        }

        data, _ = remapper.remap_card_data(card)

        assert data["table_id"] == 1000

    def test_keeps_unmapped_card_level_table_id(self, remapper, caplog):
        """An unmapped table_id is kept as-is and logged as a warning."""
        card = {
            "database_id": 1,
            "table_id": 999,
            "dataset_query": {"database": 1, "type": "query", "query": {}},
        }

        with caplog.at_level("WARNING", logger="metabase_migration"):
            data, _ = remapper.remap_card_data(card)

        assert data["table_id"] == 999
        assert "No table ID mapping found for source table 999" in caplog.text

    def test_ignores_non_integer_table_id(self, remapper):
        """A non-integer table_id (e.g. a card ref) is left untouched."""
        card = {
            "database_id": 1,
            "table_id": "card__5",
            "dataset_query": {"database": 1, "type": "query", "query": {}},
        }

        data, _ = remapper.remap_card_data(card)

        assert data["table_id"] == "card__5"

    def test_remaps_result_metadata_and_visualization_settings(self, remapper):
        """result_metadata and visualization_settings are remapped when present."""
        card = {
            "database_id": 1,
            "dataset_query": {"database": 1, "type": "query", "query": {}},
            "result_metadata": [{"id": 200, "table_id": 100, "field_ref": ["field", 200, None]}],
            "visualization_settings": {"graph.dimensions": [["field", 200, None]]},
        }

        data, _ = remapper.remap_card_data(card)

        meta = data["result_metadata"][0]
        assert meta["id"] == 2000
        assert meta["table_id"] == 1000
        assert meta["field_ref"] == ["field", 2000, None]
        assert data["visualization_settings"]["graph.dimensions"] == [["field", 2000, None]]

    def test_remaps_card_level_parameters(self, remapper):
        """Card-level filter parameters sourcing values from another card are remapped."""
        card = {
            "database_id": 1,
            "dataset_query": {"database": 1, "type": "query", "query": {}},
            "parameters": [
                {
                    "name": "Category",
                    "values_source_type": "card",
                    "values_source_config": {"card_id": 5},
                }
            ],
        }

        data, _ = remapper.remap_card_data(card)

        assert data["parameters"][0]["values_source_config"]["card_id"] == 50

    def test_dispatches_native_v57_stage_with_string_native(self, remapper):
        """A v57 stage whose 'native' key holds a string is treated as a native query."""
        card = {
            "database_id": 1,
            "dataset_query": {
                "database": 1,
                "stages": [{"native": "SELECT * FROM {{#5-orders}}"}],
            },
        }

        data, _ = remapper.remap_card_data(card)

        assert data["dataset_query"]["stages"][0]["native"] == "SELECT * FROM {{#50-orders}}"


# ============================================================================
# _is_native_query
# ============================================================================


class TestIsNativeQuery:
    """Tests for native-query detection across v56 and v57 formats."""

    def test_v56_native(self, remapper):
        assert remapper._is_native_query({"type": "native"}) is True

    def test_v56_mbql(self, remapper):
        assert remapper._is_native_query({"type": "query"}) is False

    def test_v57_native_stage_type(self, remapper):
        query = {"stages": [{"lib/type": "mbql.stage/native"}]}
        assert remapper._is_native_query(query) is True

    def test_v57_mbql_stage_type(self, remapper):
        query = {"stages": [{"lib/type": "mbql.stage/mbql", "source-table": 1}]}
        assert remapper._is_native_query(query) is False

    def test_v57_non_dict_stage_ignored(self, remapper):
        assert remapper._is_native_query({"stages": ["not-a-dict"]}) is False

    def test_stages_not_a_list(self, remapper):
        assert remapper._is_native_query({"stages": "nope"}) is False


# ============================================================================
# source-table / source-card
# ============================================================================


class TestSourceTableRemapping:
    """Tests for _remap_source_table across v56 and v57 shapes."""

    def test_v57_source_card_remapped(self, remapper):
        query = {"source-card": 5}
        remapper._remap_source_table(query, 1)
        assert query["source-card"] == 50

    def test_v57_source_card_unmapped_kept(self, remapper, caplog):
        query = {"source-card": 404}

        with caplog.at_level("WARNING", logger="metabase_migration"):
            remapper._remap_source_table(query, 1)

        assert query["source-card"] == 404
        assert "No card mapping found for v57 source-card 404" in caplog.text

    def test_no_source_table_key_is_noop(self, remapper):
        query = {"aggregation": [["count"]]}
        remapper._remap_source_table(query, 1)
        assert query == {"aggregation": [["count"]]}

    def test_v56_card_reference_remapped(self, remapper):
        query = {"source-table": "card__5"}
        remapper._remap_source_table(query, 1)
        assert query["source-table"] == "card__50"

    def test_table_id_unmapped_kept(self, remapper, caplog):
        query = {"source-table": 777}

        with caplog.at_level("WARNING", logger="metabase_migration"):
            remapper._remap_source_table(query, 1)

        assert query["source-table"] == 777
        assert "No table ID mapping found for source table 777" in caplog.text

    def test_non_card_string_source_table_untouched(self, remapper):
        """A string source-table that is not a card ref falls through unchanged."""
        query = {"source-table": "public.orders"}
        remapper._remap_source_table(query, 1)
        assert query["source-table"] == "public.orders"

    def test_invalid_card_reference_logs_warning(self, remapper, caplog):
        """A malformed 'card__' reference is reported and left alone."""
        query = {"source-table": "card__abc"}

        with caplog.at_level("WARNING", logger="metabase_migration"):
            remapper._remap_source_table(query, 1)

        assert query["source-table"] == "card__abc"
        assert "Invalid card reference format: card__abc" in caplog.text

    def test_unmapped_card_reference_kept(self, remapper):
        """An unmapped card ref keeps its original value."""
        query = {"source-table": "card__404"}
        remapper._remap_source_table(query, 1)
        assert query["source-table"] == "card__404"


# ============================================================================
# joins
# ============================================================================


class TestJoinRemapping:
    """Tests for _remap_joins across v56 and v57 shapes."""

    def test_v57_join_with_nested_stages(self, remapper):
        """A join carrying its own stages remaps source tables, clauses and condition."""
        query = {
            "joins": [
                {
                    "stages": [{"source-table": 100, "filters": [["=", ["field", 200, None], 1]]}],
                    "condition": ["=", ["field", 200, None], ["field", 200, None]],
                }
            ]
        }

        remapper._remap_joins(query, 1)

        stage = query["joins"][0]["stages"][0]
        assert stage["source-table"] == 1000
        assert stage["filters"] == [["=", ["field", 2000, None], 1]]
        assert query["joins"][0]["condition"] == [
            "=",
            ["field", 2000, None],
            ["field", 2000, None],
        ]

    def test_v57_join_stages_skips_non_dict_entries(self, remapper):
        query = {"joins": [{"stages": ["not-a-dict"]}]}
        remapper._remap_joins(query, 1)
        assert query["joins"][0]["stages"] == ["not-a-dict"]

    def test_v57_join_stages_without_condition(self, remapper):
        query = {"joins": [{"stages": [{"source-table": 100}]}]}
        remapper._remap_joins(query, 1)
        assert query["joins"][0]["stages"][0]["source-table"] == 1000

    def test_v57_join_source_card(self, remapper):
        query = {"joins": [{"source-card": 5}]}
        remapper._remap_joins(query, 1)
        assert query["joins"][0]["source-card"] == 50

    def test_v57_join_source_card_unmapped_kept(self, remapper):
        query = {"joins": [{"source-card": 404}]}
        remapper._remap_joins(query, 1)
        assert query["joins"][0]["source-card"] == 404

    def test_v56_join_source_table_int(self, remapper):
        query = {"joins": [{"source-table": 100}]}
        remapper._remap_joins(query, 1)
        assert query["joins"][0]["source-table"] == 1000

    def test_v56_join_source_table_int_unmapped_kept(self, remapper):
        query = {"joins": [{"source-table": 555}]}
        remapper._remap_joins(query, 1)
        assert query["joins"][0]["source-table"] == 555

    def test_v56_join_card_reference(self, remapper):
        query = {"joins": [{"source-table": "card__5"}]}
        remapper._remap_joins(query, 1)
        assert query["joins"][0]["source-table"] == "card__50"

    def test_join_condition_field_ids_remapped(self, remapper):
        query = {"joins": [{"source-table": 100, "condition": ["=", ["field", 200, None], 5]}]}
        remapper._remap_joins(query, 1)
        assert query["joins"][0]["condition"] == ["=", ["field", 2000, None], 5]

    def test_join_without_source_table_or_card(self, remapper):
        query = {"joins": [{"alias": "j0"}]}
        remapper._remap_joins(query, 1)
        assert query["joins"][0] == {"alias": "j0"}

    def test_no_joins_key_is_noop(self, remapper):
        query = {"source-table": 100}
        remapper._remap_joins(query, 1)
        assert query == {"source-table": 100}


# ============================================================================
# query clauses / MBQL dispatch
# ============================================================================


class TestQueryClauseRemapping:
    """Tests for _remap_query_clauses and _remap_mbql_query dispatch."""

    def test_v56_clauses_remapped(self, remapper):
        query = {
            "filter": ["=", ["field", 200, None], 1],
            "aggregation": [["sum", ["field", 200, None]]],
            "breakout": [["field", 200, None]],
            "order-by": [["asc", ["field", 200, None]]],
            "fields": [["field", 200, None]],
            "expressions": {"double": ["*", ["field", 200, None], 2]},
        }

        remapper._remap_query_clauses(query, 1)

        assert query["filter"] == ["=", ["field", 2000, None], 1]
        assert query["aggregation"] == [["sum", ["field", 2000, None]]]
        assert query["breakout"] == [["field", 2000, None]]
        assert query["order-by"] == [["asc", ["field", 2000, None]]]
        assert query["fields"] == [["field", 2000, None]]
        assert query["expressions"] == {"double": ["*", ["field", 2000, None], 2]}

    def test_v57_filters_plural_remapped(self, remapper):
        query = {"filters": [["=", ["field", 200, None], 1]]}
        remapper._remap_query_clauses(query, 1)
        assert query["filters"] == [["=", ["field", 2000, None], 1]]

    def test_mbql_dispatch_v57_stages(self, remapper):
        dataset_query = {"stages": [{"source-table": 100, "filters": [["field", 200, None]]}]}
        remapper._remap_mbql_query(dataset_query, 1)
        assert dataset_query["stages"][0]["source-table"] == 1000
        assert dataset_query["stages"][0]["filters"] == [["field", 2000, None]]

    def test_mbql_dispatch_v57_skips_non_dict_stage(self, remapper):
        dataset_query = {"stages": ["not-a-dict"]}
        remapper._remap_mbql_query(dataset_query, 1)
        assert dataset_query["stages"] == ["not-a-dict"]

    def test_mbql_dispatch_v56_inner_query(self, remapper):
        dataset_query = {"query": {"source-table": 100}}
        remapper._remap_mbql_query(dataset_query, 1)
        assert dataset_query["query"]["source-table"] == 1000

    def test_mbql_dispatch_v56_empty_query_is_noop(self, remapper):
        dataset_query = {"query": {}}
        remapper._remap_mbql_query(dataset_query, 1)
        assert dataset_query == {"query": {}}


# ============================================================================
# result_metadata
# ============================================================================


class TestResultMetadataRemapping:
    """Tests for _remap_result_metadata."""

    def test_non_list_returned_unchanged(self, remapper):
        assert remapper._remap_result_metadata({"not": "a list"}, 1) == {"not": "a list"}

    def test_non_dict_items_preserved(self, remapper):
        result = remapper._remap_result_metadata(["string", 42, None], 1)
        assert result == ["string", 42, None]

    def test_unmapped_ids_kept(self, remapper):
        result = remapper._remap_result_metadata([{"id": 999, "table_id": 888}], 1)
        assert result == [{"id": 999, "table_id": 888}]

    def test_non_integer_ids_ignored(self, remapper):
        result = remapper._remap_result_metadata([{"id": "abc", "table_id": None}], 1)
        assert result == [{"id": "abc", "table_id": None}]

    def test_original_items_not_mutated(self, remapper):
        metadata = [{"id": 200}]
        remapper._remap_result_metadata(metadata, 1)
        assert metadata == [{"id": 200}]


# ============================================================================
# recursive field remapping
# ============================================================================


class TestRecursiveFieldRemapping:
    """Tests for remap_field_ids_recursively and _remap_list."""

    def test_none_passes_through(self, remapper):
        assert remapper.remap_field_ids_recursively(None, 1) is None

    def test_primitives_pass_through(self, remapper):
        assert remapper.remap_field_ids_recursively("text", 1) == "text"
        assert remapper.remap_field_ids_recursively(42, 1) == 42

    def test_empty_list_returned_as_is(self, remapper):
        assert remapper.remap_field_ids_recursively([], 1) == []

    def test_nested_dict_remapped(self, remapper):
        data = {"outer": {"inner": ["field", 200, None]}}
        assert remapper.remap_field_ids_recursively(data, 1) == {
            "outer": {"inner": ["field", 2000, None]}
        }

    def test_field_id_alias_type(self, remapper):
        assert remapper.remap_field_ids_recursively(["field-id", 200], 1) == ["field-id", 2000]

    def test_unmapped_field_id_kept_with_warning(self, remapper, caplog):
        with caplog.at_level("WARNING", logger="metabase_migration"):
            result = remapper.remap_field_ids_recursively(["field", 909, None], 1)

        assert result == ["field", 909, None]
        assert "No field ID mapping found for source field 909" in caplog.text

    def test_string_field_name_untouched(self, remapper):
        """Native-query field refs use a string name and must not be remapped."""
        assert remapper.remap_field_ids_recursively(["field", "TOTAL", None], 1) == [
            "field",
            "TOTAL",
            None,
        ]

    def test_v57_field_metadata_first(self, remapper):
        data = ["field", {"lib/uuid": "abc", "base-type": "type/Integer"}, 200]
        assert remapper.remap_field_ids_recursively(data, 1) == [
            "field",
            {"lib/uuid": "abc", "base-type": "type/Integer"},
            2000,
        ]

    def test_v57_field_metadata_first_unmapped(self, remapper, caplog):
        data = ["field", {"lib/uuid": "abc"}, 909]

        with caplog.at_level("WARNING", logger="metabase_migration"):
            result = remapper.remap_field_ids_recursively(data, 1)

        assert result == data
        assert "No field ID mapping found for v57 source field 909" in caplog.text

    def test_v57_metric_reference_remapped(self, remapper):
        data = ["metric", {"lib/uuid": "abc"}, 5]
        assert remapper.remap_field_ids_recursively(data, 1) == [
            "metric",
            {"lib/uuid": "abc"},
            50,
        ]

    def test_v57_metric_reference_unmapped_kept(self, remapper, caplog):
        data = ["metric", {"lib/uuid": "abc"}, 404]

        with caplog.at_level("WARNING", logger="metabase_migration"):
            result = remapper.remap_field_ids_recursively(data, 1)

        assert result == data
        assert "No card ID mapping found for metric source card 404" in caplog.text

    def test_metric_without_metadata_dict_recurses(self, remapper):
        """A ["metric", ...] clause that is not the v57 3-tuple shape recurses normally."""
        data = ["metric", ["field", 200, None]]
        assert remapper.remap_field_ids_recursively(data, 1) == ["metric", ["field", 2000, None]]

    def test_single_element_list_recurses(self, remapper):
        assert remapper.remap_field_ids_recursively([["field", 200, None]], 1) == [
            ["field", 2000, None]
        ]


# ============================================================================
# parameters
# ============================================================================


class TestParameterRemapping:
    """Tests for remap_dashboard_parameters and its helpers."""

    def test_parameter_without_source_config_untouched(self, remapper):
        params = [{"name": "Plain", "type": "category"}]
        assert remapper.remap_dashboard_parameters(params, []) == params

    def test_non_dict_source_config_untouched(self, remapper):
        params = [{"name": "P", "values_source_config": "not-a-dict"}]
        assert remapper.remap_dashboard_parameters(params, []) == params

    def test_source_config_without_card_id_untouched(self, remapper):
        params = [{"name": "P", "values_source_config": {"values": ["a", "b"]}}]
        assert remapper.remap_dashboard_parameters(params, []) == params

    def test_card_id_remapped_without_value_field(self, remapper):
        params = [{"name": "P", "values_source_config": {"card_id": 5}}]
        result = remapper.remap_dashboard_parameters(params, [])
        assert result[0]["values_source_config"]["card_id"] == 50

    def test_value_field_remapped_using_manifest_card(self, remapper):
        params = [
            {
                "name": "P",
                "values_source_config": {"card_id": 5, "value_field": ["field", 200, None]},
            }
        ]
        manifest_cards = [
            Card(id=9, name="Other", database_id=2),
            Card(id=5, name="Src", database_id=1),
        ]

        result = remapper.remap_dashboard_parameters(params, manifest_cards)

        assert result[0]["values_source_config"]["value_field"] == ["field", 2000, None]

    def test_value_field_kept_when_card_not_in_manifest(self, remapper, caplog):
        params = [
            {
                "name": "P",
                "values_source_config": {"card_id": 5, "value_field": ["field", 200, None]},
            }
        ]

        with caplog.at_level("WARNING", logger="metabase_migration"):
            result = remapper.remap_dashboard_parameters(params, [])

        assert result[0]["values_source_config"]["value_field"] == ["field", 200, None]
        assert "Could not determine database ID for card 5" in caplog.text

    def test_unmapped_card_strips_source_config(self, remapper, caplog):
        params = [
            {
                "name": "Broken",
                "values_source_type": "card",
                "values_source_config": {"card_id": 404},
            }
        ]

        with caplog.at_level("WARNING", logger="metabase_migration"):
            result = remapper.remap_dashboard_parameters(params, [])

        assert "values_source_config" not in result[0]
        assert "values_source_type" not in result[0]
        assert "references missing card 404" in caplog.text

    def test_unmapped_card_without_source_type_key(self, remapper):
        params = [{"name": "Broken", "values_source_config": {"card_id": 404}}]
        result = remapper.remap_dashboard_parameters(params, [])
        assert "values_source_config" not in result[0]


class TestDashcardParameterMappings:
    """Tests for remap_dashcard_parameter_mappings."""

    def test_card_and_target_remapped(self, remapper):
        mappings = [{"card_id": 5, "target": ["dimension", ["field", 200, None]]}]

        result = remapper.remap_dashcard_parameter_mappings(mappings, 1)

        assert result[0]["card_id"] == 50
        assert result[0]["target"] == ["dimension", ["field", 2000, None]]

    def test_unmapped_card_id_kept(self, remapper):
        result = remapper.remap_dashcard_parameter_mappings([{"card_id": 404}], 1)
        assert result[0]["card_id"] == 404

    def test_mapping_without_card_id(self, remapper):
        result = remapper.remap_dashcard_parameter_mappings(
            [{"target": ["dimension", ["field", 200, None]]}], 1
        )
        assert result[0]["target"] == ["dimension", ["field", 2000, None]]

    def test_target_not_remapped_without_source_db(self, remapper):
        result = remapper.remap_dashcard_parameter_mappings(
            [{"target": ["dimension", ["field", 200, None]]}], None
        )
        assert result[0]["target"] == ["dimension", ["field", 200, None]]

    def test_original_mappings_not_mutated(self, remapper):
        mappings = [{"card_id": 5}]
        remapper.remap_dashcard_parameter_mappings(mappings, 1)
        assert mappings[0]["card_id"] == 5


# ============================================================================
# native queries
# ============================================================================


class TestRemapNativeQuery:
    """Tests for the standalone remap_native_query entry point."""

    def test_v56_sql_and_template_tags(self, remapper):
        card = {
            "database_id": 1,
            "dataset_query": {
                "type": "native",
                "database": 1,
                "native": {
                    "query": "SELECT * FROM {{#5-orders}}",
                    "template-tags": {
                        "5-orders": {"type": "card", "card-id": 5, "name": "5-orders"}
                    },
                },
            },
        }

        result = remapper.remap_native_query(card)

        native = result["dataset_query"]["native"]
        assert native["query"] == "SELECT * FROM {{#50-orders}}"
        assert "50-orders" in native["template-tags"]
        assert native["template-tags"]["50-orders"]["card-id"] == 50

    def test_v57_dispatch_via_lib_type(self, remapper):
        card = {
            "database_id": 1,
            "dataset_query": {
                "lib/type": "mbql/query",
                "database": 1,
                "stages": [
                    {"lib/type": "mbql.stage/native", "native": "SELECT * FROM {{#5-orders}}"}
                ],
            },
        }

        result = remapper.remap_native_query(card)

        assert result["dataset_query"]["stages"][0]["native"] == "SELECT * FROM {{#50-orders}}"

    def test_missing_database_defaults_to_zero(self, remapper):
        """A card with no resolvable database still remaps card references."""
        card = {"dataset_query": {"type": "native", "native": {"query": "{{#5-orders}}"}}}

        result = remapper.remap_native_query(card)

        assert result["dataset_query"]["native"]["query"] == "{{#50-orders}}"

    def test_does_not_mutate_input(self, remapper):
        card = {
            "database_id": 1,
            "dataset_query": {"type": "native", "native": {"query": "{{#5-orders}}"}},
        }

        remapper.remap_native_query(card)

        assert card["dataset_query"]["native"]["query"] == "{{#5-orders}}"

    def test_v56_native_not_a_dict_is_noop(self, remapper):
        query = {"type": "native", "native": "raw string"}
        remapper._remap_native_query_v56(query, 1)
        assert query["native"] == "raw string"

    def test_v56_native_without_query_string(self, remapper):
        query = {"type": "native", "native": {"collection": "orders"}}
        remapper._remap_native_query_v56(query, 1)
        assert query["native"] == {"collection": "orders"}

    def test_v56_template_tags_not_a_dict(self, remapper):
        query = {"type": "native", "native": {"query": "x", "template-tags": []}}
        remapper._remap_native_query_v56(query, 1)
        assert query["native"]["template-tags"] == []

    def test_v57_stages_not_a_list_is_noop(self, remapper):
        query = {"lib/type": "mbql/query", "stages": "nope"}
        remapper._remap_native_query_v57(query, 1)
        assert query["stages"] == "nope"

    def test_v57_skips_non_dict_stages(self, remapper):
        query = {"lib/type": "mbql/query", "stages": ["not-a-dict"]}
        remapper._remap_native_query_v57(query, 1)
        assert query["stages"] == ["not-a-dict"]

    def test_v57_stage_without_string_native(self, remapper):
        query = {"lib/type": "mbql/query", "stages": [{"native": {"query": "x"}}]}
        remapper._remap_native_query_v57(query, 1)
        assert query["stages"][0]["native"] == {"query": "x"}

    def test_v57_stage_without_template_tags(self, remapper):
        query = {"lib/type": "mbql/query", "stages": [{"native": "{{#5-orders}}"}]}
        remapper._remap_native_query_v57(query, 1)
        assert query["stages"][0]["native"] == "{{#50-orders}}"

    def test_unmapped_sql_reference_kept(self, remapper, caplog):
        with caplog.at_level("WARNING", logger="metabase_migration"):
            result = remapper._remap_sql_card_references("SELECT * FROM {{#404-missing}}")

        assert result == "SELECT * FROM {{#404-missing}}"
        assert "No card mapping found for card reference" in caplog.text


class TestTemplateTags:
    """Tests for _remap_template_tags and _remap_tag_name."""

    def test_non_dict_tag_data_preserved(self, remapper):
        result = remapper._remap_template_tags({"tag": "not-a-dict"}, 1)
        assert result == {"tag": "not-a-dict"}

    def test_card_tag_without_card_id_preserved(self, remapper):
        tags = {"tag": {"type": "card"}}
        assert remapper._remap_template_tags(tags, 1) == tags

    def test_card_tag_unmapped_kept(self, remapper, caplog):
        tags = {"404-x": {"type": "card", "card-id": 404}}

        with caplog.at_level("WARNING", logger="metabase_migration"):
            result = remapper._remap_template_tags(tags, 1)

        assert result == tags
        assert "No card mapping found for template tag '404-x'" in caplog.text

    def test_card_tag_renames_name_and_display_name(self, remapper):
        tags = {
            "#5-orders": {
                "type": "card",
                "card-id": 5,
                "name": "#5-orders",
                "display-name": "#5 Orders",
            }
        }

        result = remapper._remap_template_tags(tags, 1)

        assert "#50-orders" in result
        assert result["#50-orders"]["name"] == "#50-orders"
        assert result["#50-orders"]["display-name"] == "#50 Orders"

    def test_dimension_tag_field_remapped(self, remapper):
        tags = {"cat": {"type": "dimension", "dimension": ["field", 200, None]}}

        result = remapper._remap_template_tags(tags, 1)

        assert result["cat"]["dimension"] == ["field", 2000, None]

    def test_temporal_unit_tag_field_remapped(self, remapper):
        tags = {"unit": {"type": "temporal-unit", "dimension": ["field", 200, None]}}

        result = remapper._remap_template_tags(tags, 1)

        assert result["unit"]["dimension"] == ["field", 2000, None]

    def test_dimension_tag_without_list_dimension_preserved(self, remapper):
        tags = {"cat": {"type": "dimension", "dimension": None}}
        assert remapper._remap_template_tags(tags, 1) == tags

    def test_plain_text_tag_preserved(self, remapper):
        tags = {"x": {"type": "text", "name": "x"}}
        assert remapper._remap_template_tags(tags, 1) == tags

    def test_tag_name_without_card_id_prefix_unchanged(self, remapper):
        assert remapper._remap_tag_name("orders-summary", 5, 50) == "orders-summary"

    def test_tag_name_partial_id_not_replaced(self, remapper):
        """'55-x' must not match a source card ID of 5."""
        assert remapper._remap_tag_name("55-x", 5, 50) == "55-x"


# ============================================================================
# dashcard visualization settings
# ============================================================================


class TestDashcardVisualizationSettings:
    """Tests for remap_dashcard_visualization_settings and its helpers."""

    def test_empty_settings_returned_as_is(self, remapper):
        assert remapper.remap_dashcard_visualization_settings({}, 1) == {}
        assert remapper.remap_dashcard_visualization_settings(None, 1) is None

    def test_click_behavior_question_target(self, remapper):
        settings = {"click_behavior": {"type": "link", "linkType": "question", "targetId": 5}}

        result = remapper.remap_dashcard_visualization_settings(settings, None)

        assert result["click_behavior"]["targetId"] == 50

    def test_click_behavior_dashboard_target(self, remapper):
        settings = {"click_behavior": {"type": "link", "linkType": "dashboard", "targetId": 7}}

        result = remapper.remap_dashcard_visualization_settings(settings, None)

        assert result["click_behavior"]["targetId"] == 70

    def test_click_behavior_unmapped_question_kept(self, remapper, caplog):
        settings = {"click_behavior": {"type": "link", "linkType": "question", "targetId": 404}}

        with caplog.at_level("WARNING", logger="metabase_migration"):
            result = remapper.remap_dashcard_visualization_settings(settings, None)

        assert result["click_behavior"]["targetId"] == 404
        assert "No card mapping found for click_behavior targetId 404" in caplog.text

    def test_click_behavior_unmapped_dashboard_kept(self, remapper, caplog):
        settings = {"click_behavior": {"type": "link", "linkType": "dashboard", "targetId": 404}}

        with caplog.at_level("WARNING", logger="metabase_migration"):
            result = remapper.remap_dashcard_visualization_settings(settings, None)

        assert result["click_behavior"]["targetId"] == 404
        assert "No dashboard mapping found for click_behavior targetId 404" in caplog.text

    def test_click_behavior_non_link_type_untouched(self, remapper):
        settings = {"click_behavior": {"type": "crossfilter", "targetId": 5}}
        result = remapper.remap_dashcard_visualization_settings(settings, None)
        assert result["click_behavior"]["targetId"] == 5

    def test_click_behavior_non_integer_target_untouched(self, remapper):
        settings = {"click_behavior": {"type": "link", "linkType": "question", "targetId": "abc"}}
        result = remapper.remap_dashcard_visualization_settings(settings, None)
        assert result["click_behavior"]["targetId"] == "abc"

    def test_click_behavior_non_dict_returned_as_is(self, remapper):
        assert remapper._remap_click_behavior("not-a-dict") == "not-a-dict"

    def test_column_settings_click_behavior_remapped(self, remapper):
        settings = {
            "column_settings": {
                '["name","ID"]': {
                    "click_behavior": {"type": "link", "linkType": "question", "targetId": 5}
                },
                '["name","Other"]': {"column_title": "Other"},
            }
        }

        result = remapper.remap_dashcard_visualization_settings(settings, None)

        assert result["column_settings"]['["name","ID"]']["click_behavior"]["targetId"] == 50
        assert result["column_settings"]['["name","Other"]'] == {"column_title": "Other"}

    def test_column_settings_non_dict_entry_ignored(self, remapper):
        settings = {"column_settings": {"col": "not-a-dict"}}
        result = remapper.remap_dashcard_visualization_settings(settings, None)
        assert result["column_settings"]["col"] == "not-a-dict"

    def test_column_settings_not_a_dict_ignored(self, remapper):
        settings = {"column_settings": []}
        result = remapper.remap_dashcard_visualization_settings(settings, None)
        assert result["column_settings"] == []

    def test_field_ids_remapped_when_source_db_given(self, remapper):
        settings = {"graph.dimensions": [["field", 200, None]]}
        result = remapper.remap_dashcard_visualization_settings(settings, 1)
        assert result["graph.dimensions"] == [["field", 2000, None]]

    def test_input_not_mutated(self, remapper):
        settings = {"click_behavior": {"type": "link", "linkType": "question", "targetId": 5}}
        remapper.remap_dashcard_visualization_settings(settings, None)
        assert settings["click_behavior"]["targetId"] == 5


class TestVisualizerSettings:
    """Tests for the Visualizer columnValuesMapping remapping."""

    def test_source_id_remapped(self, remapper):
        settings = {
            "visualization": {
                "columnValuesMapping": {
                    "COLUMN_1": [{"sourceId": "card:5", "name": "c", "originalName": "c"}]
                }
            }
        }

        result = remapper.remap_dashcard_visualization_settings(settings, None)

        mapping = result["visualization"]["columnValuesMapping"]["COLUMN_1"]
        assert mapping[0]["sourceId"] == "card:50"

    def test_source_id_unmapped_kept(self, remapper, caplog):
        settings = {"visualization": {"columnValuesMapping": {"C": [{"sourceId": "card:404"}]}}}

        with caplog.at_level("WARNING", logger="metabase_migration"):
            result = remapper.remap_dashcard_visualization_settings(settings, None)

        assert result["visualization"]["columnValuesMapping"]["C"][0]["sourceId"] == "card:404"
        assert "No card mapping found for Visualizer sourceId card:404" in caplog.text

    def test_invalid_source_id_logged(self, remapper, caplog):
        with caplog.at_level("WARNING", logger="metabase_migration"):
            result = remapper._remap_visualizer_source_id({"sourceId": "card:abc"})

        assert result["sourceId"] == "card:abc"
        assert "Invalid Visualizer sourceId format: card:abc" in caplog.text

    def test_non_card_source_id_untouched(self, remapper):
        assert remapper._remap_visualizer_source_id({"sourceId": "table:5"}) == {
            "sourceId": "table:5"
        }

    def test_non_string_source_id_untouched(self, remapper):
        assert remapper._remap_visualizer_source_id({"sourceId": 5}) == {"sourceId": 5}

    def test_data_source_name_reference_remapped(self, remapper):
        settings = {"visualization": {"columnValuesMapping": {"C": ["$_card:5_name"]}}}

        result = remapper.remap_dashcard_visualization_settings(settings, None)

        assert result["visualization"]["columnValuesMapping"]["C"] == ["$_card:50_name"]

    def test_data_source_name_reference_unmapped_kept(self, remapper, caplog):
        with caplog.at_level("WARNING", logger="metabase_migration"):
            result = remapper._remap_data_source_name_ref("$_card:404_name")

        assert result == "$_card:404_name"
        assert "No card mapping found for data source name ref" in caplog.text

    def test_data_source_name_reference_bad_format_kept(self, remapper):
        assert remapper._remap_data_source_name_ref("$_card:x_name") == "$_card:x_name"

    def test_other_list_items_preserved(self, remapper):
        settings = {"visualization": {"columnValuesMapping": {"C": [42, {"name": "no-source"}]}}}

        result = remapper.remap_dashcard_visualization_settings(settings, None)

        assert result["visualization"]["columnValuesMapping"]["C"] == [42, {"name": "no-source"}]

    def test_non_list_mapping_values_preserved(self, remapper):
        settings = {"visualization": {"columnValuesMapping": {"C": "scalar"}}}
        result = remapper.remap_dashcard_visualization_settings(settings, None)
        assert result["visualization"]["columnValuesMapping"]["C"] == "scalar"

    def test_visualization_without_column_values_mapping(self, remapper):
        settings = {"visualization": {"display": "bar"}}
        result = remapper.remap_dashcard_visualization_settings(settings, None)
        assert result["visualization"] == {"display": "bar"}

    def test_visualization_not_a_dict_ignored(self, remapper):
        settings = {"visualization": "bar"}
        result = remapper.remap_dashcard_visualization_settings(settings, None)
        assert result["visualization"] == "bar"

    def test_remap_visualizer_definition_non_dict(self, remapper):
        assert remapper._remap_visualizer_definition("nope") == "nope"


class TestLinkCardSettings:
    """Tests for _remap_link_card_settings."""

    @pytest.mark.parametrize("model", ["card", "question", "model", "metric"])
    def test_card_like_entities_remapped(self, remapper, model):
        settings = {"link": {"entity": {"id": 5, "model": model}}}

        result = remapper.remap_dashcard_visualization_settings(settings, None)

        assert result["link"]["entity"]["id"] == 50

    def test_dashboard_entity_remapped(self, remapper):
        settings = {"link": {"entity": {"id": 7, "model": "dashboard"}}}

        result = remapper.remap_dashcard_visualization_settings(settings, None)

        assert result["link"]["entity"]["id"] == 70

    def test_unmapped_card_entity_kept(self, remapper, caplog):
        with caplog.at_level("WARNING", logger="metabase_migration"):
            result = remapper._remap_link_card_settings({"entity": {"id": 404, "model": "card"}})

        assert result["entity"]["id"] == 404
        assert "No card mapping found for link card entity id 404" in caplog.text

    def test_unmapped_dashboard_entity_kept(self, remapper, caplog):
        with caplog.at_level("WARNING", logger="metabase_migration"):
            result = remapper._remap_link_card_settings(
                {"entity": {"id": 404, "model": "dashboard"}}
            )

        assert result["entity"]["id"] == 404
        assert "No dashboard mapping found for link card entity id 404" in caplog.text

    def test_restricted_entity_untouched(self, remapper):
        link = {"entity": {"id": 5, "model": "card", "restricted": True}}
        assert remapper._remap_link_card_settings(link)["entity"]["id"] == 5

    def test_entity_not_a_dict_untouched(self, remapper):
        link = {"entity": "nope"}
        assert remapper._remap_link_card_settings(link) == link

    def test_non_integer_entity_id_untouched(self, remapper):
        link = {"entity": {"id": "abc", "model": "card"}}
        assert remapper._remap_link_card_settings(link)["entity"]["id"] == "abc"

    def test_unknown_model_untouched(self, remapper):
        link = {"entity": {"id": 5, "model": "collection"}}
        assert remapper._remap_link_card_settings(link)["entity"]["id"] == 5

    def test_url_link_without_entity(self, remapper):
        settings = {"link": {"url": "https://example.com"}}
        result = remapper.remap_dashcard_visualization_settings(settings, None)
        assert result["link"] == {"url": "https://example.com"}

    def test_link_not_a_dict_ignored(self, remapper):
        settings = {"link": "https://example.com"}
        result = remapper.remap_dashcard_visualization_settings(settings, None)
        assert result["link"] == "https://example.com"

    def test_remap_link_card_settings_non_dict(self, remapper):
        assert remapper._remap_link_card_settings("nope") == "nope"
