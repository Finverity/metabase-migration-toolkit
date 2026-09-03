"""Tests for card-level parameter and temporal-unit template-tag remapping."""

from lib.handlers.card import CardHandler
from lib.models import Card, DatabaseMap, Manifest, ManifestMeta
from lib.remapping.id_mapper import IDMapper
from lib.remapping.query_remapper import QueryRemapper
from lib.services.export_service import ExportService
from lib.utils.query import extract_parameter_card_dependencies


def _create_test_id_mapper(
    db_mapping: dict[int, int] | None = None,
    card_mapping: dict[int, int] | None = None,
) -> IDMapper:
    db_mapping = db_mapping or {}
    card_mapping = card_mapping or {}

    manifest = Manifest(
        meta=ManifestMeta(
            source_url="https://source.example.com",
            export_timestamp="2025-01-01T00:00:00",
            tool_version="1.0.0",
            cli_args={},
        ),
        databases={source_id: f"DB{source_id}" for source_id in db_mapping},
    )
    db_map = DatabaseMap(by_id={str(k): v for k, v in db_mapping.items()})
    mapper = IDMapper(manifest, db_map)

    for source_id, target_id in card_mapping.items():
        mapper.set_card_mapping(source_id, target_id)

    return mapper


class TestCardParameterDependencies:
    """Tests for extracting parameter card dependencies."""

    def test_extract_parameter_card_dependencies(self):
        card_data = {
            "parameters": [
                {
                    "name": "Client",
                    "values_source_type": "card",
                    "values_source_config": {"card_id": 232},
                }
            ]
        }

        assert extract_parameter_card_dependencies(card_data) == {232}

    def test_extract_parameter_card_dependencies_ignores_missing_config(self):
        card_data = {
            "parameters": [
                {"name": "Date", "type": "date/all-options"},
                {"name": "Client", "values_source_config": {}},
            ]
        }

        assert extract_parameter_card_dependencies(card_data) == set()

    def test_card_handler_includes_parameter_dependencies(self):
        card_data = {
            "dataset_query": {"type": "native", "native": {"query": "SELECT 1"}},
            "parameters": [
                {
                    "values_source_config": {"card_id": 232},
                }
            ],
        }

        deps = CardHandler._extract_card_dependencies(card_data)
        assert 232 in deps

    def test_export_service_includes_parameter_dependencies(self):
        card_data = {
            "dataset_query": {"query": {}},
            "parameters": [
                {
                    "values_source_config": {"card_id": 232},
                }
            ],
        }

        deps = ExportService._extract_card_dependencies(card_data)
        assert 232 in deps


class TestCardParameterRemapping:
    """Tests for remapping card parameter value sources on import."""

    def test_remap_card_data_remaps_parameter_card_id(self):
        id_mapper = _create_test_id_mapper(db_mapping={2: 2}, card_mapping={232: 501})

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
                        "value_field": ["field", "Client", {"base-type": "type/Text"}],
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
        client_param = remapped_data["parameters"][0]
        assert client_param["values_source_config"]["card_id"] == 501
        assert client_param["values_source_type"] == "card"

    def test_remap_card_data_removes_missing_parameter_card_reference(self):
        id_mapper = _create_test_id_mapper(db_mapping={2: 2})
        remapper = QueryRemapper(id_mapper)
        card_data = {
            "database_id": 2,
            "dataset_query": {
                "type": "native",
                "native": {"query": "SELECT 1"},
            },
            "parameters": [
                {
                    "name": "Client",
                    "values_source_type": "card",
                    "values_source_config": {"card_id": 232},
                }
            ],
        }

        remapped_data, success = remapper.remap_card_data(card_data, [])

        assert success is True
        client_param = remapped_data["parameters"][0]
        assert "values_source_config" not in client_param
        assert "values_source_type" not in client_param


class TestTemporalUnitTemplateTagRemapping:
    """Tests for remapping temporal-unit template-tag field references."""

    def test_remap_card_data_remaps_temporal_unit_template_tag(self):
        id_mapper = _create_test_id_mapper(db_mapping={2: 2})
        id_mapper._field_map[(2, 159)] = 301

        remapper = QueryRemapper(id_mapper)
        card_data = {
            "database_id": 2,
            "dataset_query": {
                "lib/type": "mbql/query",
                "database": 2,
                "stages": [
                    {
                        "lib/type": "mbql.stage/native",
                        "native": 'SELECT {{date_grouping}} AS "Date" GROUP BY {{date_grouping}}',
                        "template-tags": {
                            "date_grouping": {
                                "type": "temporal-unit",
                                "name": "date_grouping",
                                "display-name": "Date Grouping",
                                "default": "day",
                                "dimension": ["field", {"lib/uuid": "abc"}, 159],
                            }
                        },
                    }
                ],
            },
        }

        remapped_data, success = remapper.remap_card_data(card_data)

        assert success is True
        tag_dimension = remapped_data["dataset_query"]["stages"][0]["template-tags"][
            "date_grouping"
        ]["dimension"]
        assert tag_dimension[2] == 301

    def test_remap_card_data_remaps_list_form_date_range_dimension(self):
        """v0.63+ exports template-tags as a list; date_range field IDs must remap.

        Without this, source DimDate.Date (field 159) keeps its staging ID and
        resolves to an unrelated target field (e.g. MonthDate).
        """
        id_mapper = _create_test_id_mapper(db_mapping={2: 2})
        id_mapper._field_map[(2, 159)] = 301

        remapper = QueryRemapper(id_mapper)
        card_data = {
            "database_id": 2,
            "dataset_query": {
                "lib/type": "mbql/query",
                "database": 2,
                "stages": [
                    {
                        "lib/type": "mbql.stage/native",
                        "native": "SELECT 1 WHERE {{date_range}}",
                        "template-tags": [
                            {
                                "widget-type": "date/all-options",
                                "default": "past7days",
                                "name": "date_range",
                                "type": "dimension",
                                "id": "213629bc-f979-4e6e-a2e1-5670baf79855",
                                "dimension": [
                                    "field",
                                    {"lib/uuid": "1156aab8-566e-45d0-8e19-cd181d67590c"},
                                    159,
                                ],
                                "display-name": "Date Range",
                                "required": True,
                            },
                            {
                                "name": "client",
                                "type": "text",
                                "id": "a9de63f6-4ea2-496c-84a7-098ca0769b91",
                                "display-name": "Client",
                            },
                        ],
                    }
                ],
            },
        }

        remapped_data, success = remapper.remap_card_data(card_data)

        assert success is True
        tags = remapped_data["dataset_query"]["stages"][0]["template-tags"]
        assert isinstance(tags, list)
        date_range = next(tag for tag in tags if tag["name"] == "date_range")
        assert date_range["dimension"][2] == 301
        # Non-dimension tags stay in the list unchanged
        assert any(tag.get("name") == "client" for tag in tags)

    def test_remap_card_data_remaps_list_form_temporal_unit_tag(self):
        id_mapper = _create_test_id_mapper(db_mapping={2: 2})
        id_mapper._field_map[(2, 159)] = 301

        remapper = QueryRemapper(id_mapper)
        card_data = {
            "database_id": 2,
            "dataset_query": {
                "lib/type": "mbql/query",
                "database": 2,
                "stages": [
                    {
                        "lib/type": "mbql.stage/native",
                        "native": 'SELECT {{date_grouping}} AS "Date"',
                        "template-tags": [
                            {
                                "type": "temporal-unit",
                                "name": "date_grouping",
                                "display-name": "Date Grouping",
                                "default": "day",
                                "dimension": ["field", {"lib/uuid": "abc"}, 159],
                            }
                        ],
                    }
                ],
            },
        }

        remapped_data, success = remapper.remap_card_data(card_data)

        assert success is True
        tags = remapped_data["dataset_query"]["stages"][0]["template-tags"]
        assert isinstance(tags, list)
        assert tags[0]["dimension"][2] == 301
