"""Tests for native query card reference remapping functionality.

Tests SQL card reference remapping ({{#123-model-name}} format) and
template-tags card-id remapping for both v56 and v57 formats.
"""

import pytest

from lib.constants import MetabaseVersion
from lib.handlers.card import CardHandler
from lib.models import DatabaseMap, Manifest, ManifestMeta
from lib.remapping.id_mapper import IDMapper
from lib.remapping.query_remapper import QueryRemapper
from lib.version import V57Adapter, get_version_adapter


def create_test_id_mapper(
    db_mapping: dict[int, int] | None = None,
    card_mapping: dict[int, int] | None = None,
) -> IDMapper:
    """Create an IDMapper with test data.

    Args:
        db_mapping: Dict of source_db_id -> target_db_id mappings.
        card_mapping: Dict of source_card_id -> target_card_id mappings.

    Returns:
        Configured IDMapper for testing.
    """
    db_mapping = db_mapping or {}
    card_mapping = card_mapping or {}

    manifest = Manifest(
        meta=ManifestMeta(
            source_url="https://source.example.com",
            export_timestamp="2025-01-01T00:00:00",
            tool_version="1.0.0",
            cli_args={},
        ),
        databases={source_id: f"DB{source_id}" for source_id in db_mapping.keys()},
    )

    # Create db_map with string keys (JSON compatibility)
    db_map = DatabaseMap(by_id={str(k): v for k, v in db_mapping.items()})

    mapper = IDMapper(manifest, db_map)

    # Set up card mappings
    for source_id, target_id in card_mapping.items():
        mapper.set_card_mapping(source_id, target_id)

    return mapper


class TestNativeQueryDependencyExtraction:
    """Tests for extracting dependencies from native SQL queries."""

    def test_extract_single_sql_reference(self):
        """Test extracting single card reference from SQL."""
        card_data = {
            "dataset_query": {
                "type": "native",
                "native": {
                    "query": "SELECT * FROM {{#50-filtered-test-server-dataset}}",
                    "template-tags": {
                        "50-filtered-test-server-dataset": {
                            "type": "card",
                            "card-id": 50,
                            "name": "50-filtered-test-server-dataset",
                        }
                    },
                },
            }
        }
        deps = CardHandler._extract_card_dependencies(card_data)
        assert deps == {50}

    def test_extract_multiple_sql_references(self):
        """Test extracting multiple card references from SQL."""
        card_data = {
            "dataset_query": {
                "type": "native",
                "native": {
                    "query": """
                        SELECT a.*, b.value
                        FROM {{#50-model-a}} a
                        JOIN {{#60-model-b}} b ON a.id = b.a_id
                    """,
                    "template-tags": {
                        "50-model-a": {"type": "card", "card-id": 50},
                        "60-model-b": {"type": "card", "card-id": 60},
                    },
                },
            }
        }
        deps = CardHandler._extract_card_dependencies(card_data)
        assert deps == {50, 60}

    def test_extract_from_template_tags_only(self):
        """Test extracting dependencies from template-tags with type 'card'."""
        card_data = {
            "dataset_query": {
                "type": "native",
                "native": {
                    "query": "SELECT * FROM {{#123-my-model}}",
                    "template-tags": {
                        "123-my-model": {
                            "type": "card",
                            "card-id": 123,
                            "name": "123-my-model",
                            "display-name": "My Model",
                        }
                    },
                },
            }
        }
        deps = CardHandler._extract_card_dependencies(card_data)
        assert 123 in deps

    def test_extract_ignores_non_card_template_tags(self):
        """Test that non-card template tags are ignored."""
        card_data = {
            "dataset_query": {
                "type": "native",
                "native": {
                    "query": "SELECT * FROM table WHERE date > {{start_date}}",
                    "template-tags": {
                        "start_date": {
                            "type": "date",
                            "name": "start_date",
                        }
                    },
                },
            }
        }
        deps = CardHandler._extract_card_dependencies(card_data)
        assert deps == set()

    def test_extract_mixed_card_and_non_card_tags(self):
        """Test extracting with both card and non-card template tags."""
        card_data = {
            "dataset_query": {
                "type": "native",
                "native": {
                    "query": """
                        SELECT * FROM {{#50-model}}
                        WHERE date > {{start_date}}
                    """,
                    "template-tags": {
                        "50-model": {"type": "card", "card-id": 50},
                        "start_date": {"type": "date"},
                    },
                },
            }
        }
        deps = CardHandler._extract_card_dependencies(card_data)
        assert deps == {50}


class TestNativeQueryDependencyExtractionV57:
    """Tests for extracting dependencies from v57 (MBQL 5) native queries."""

    def test_extract_v57_native_query_reference(self):
        """Test extracting card reference from v57 native query format."""
        card_data = {
            "dataset_query": {
                "lib/type": "mbql/query",
                "stages": [
                    {
                        "lib/type": "mbql.stage/native",
                        "native": "SELECT * FROM {{#50-model-name}}",
                        "template-tags": {
                            "50-model-name": {
                                "type": "card",
                                "card-id": 50,
                            }
                        },
                    }
                ],
            }
        }
        deps = CardHandler._extract_card_dependencies(card_data)
        assert deps == {50}

    def test_extract_v57_multiple_stages(self):
        """Test extracting from v57 format with multiple stages."""
        card_data = {
            "dataset_query": {
                "lib/type": "mbql/query",
                "stages": [
                    {
                        "lib/type": "mbql.stage/native",
                        "native": "SELECT * FROM {{#50-model}}",
                        "template-tags": {
                            "50-model": {"type": "card", "card-id": 50},
                        },
                    },
                    {
                        "lib/type": "mbql.stage/mbql",
                        "source-table": "card__60",
                    },
                ],
            }
        }
        deps = CardHandler._extract_card_dependencies(card_data)
        assert deps == {50, 60}


class TestQueryRemapperNativeSQL:
    """Tests for QueryRemapper native SQL card reference remapping."""

    @pytest.fixture
    def id_mapper(self):
        """Create an ID mapper with card mappings."""
        return create_test_id_mapper(
            db_mapping={1: 100},
            card_mapping={50: 500, 60: 600},
        )

    @pytest.fixture
    def remapper(self, id_mapper):
        """Create a query remapper."""
        return QueryRemapper(id_mapper)

    def test_remap_sql_card_reference(self, remapper):
        """Test remapping card reference in SQL query string."""
        sql = "SELECT * FROM {{#50-filtered-test-server-dataset}}"
        result = remapper._remap_sql_card_references(sql)
        assert "{{#500-filtered-test-server-dataset}}" in result
        assert "{{#50-" not in result

    def test_remap_multiple_sql_references(self, remapper):
        """Test remapping multiple card references in SQL."""
        sql = """
            SELECT a.*, b.value
            FROM {{#50-model-a}} a
            JOIN {{#60-model-b}} b ON a.id = b.a_id
        """
        result = remapper._remap_sql_card_references(sql)
        assert "{{#500-model-a}}" in result
        assert "{{#600-model-b}}" in result
        assert "{{#50-" not in result
        assert "{{#60-" not in result

    def test_remap_sql_preserves_unmapped_references(self, remapper):
        """Test that unmapped card references are preserved."""
        sql = "SELECT * FROM {{#999-unknown-model}}"
        result = remapper._remap_sql_card_references(sql)
        assert "{{#999-unknown-model}}" in result

    def test_remap_sql_preserves_other_content(self, remapper):
        """Test that non-card content is preserved."""
        sql = """
            SELECT * FROM {{#50-model}}
            WHERE date > {{start_date}}
            AND status = 'active'
        """
        result = remapper._remap_sql_card_references(sql)
        assert "WHERE date > {{start_date}}" in result
        assert "AND status = 'active'" in result


class TestQueryRemapperTemplateTags:
    """Tests for QueryRemapper template-tags remapping."""

    @pytest.fixture
    def id_mapper(self):
        """Create an ID mapper with card mappings."""
        return create_test_id_mapper(
            db_mapping={1: 100},
            card_mapping={50: 500},
        )

    @pytest.fixture
    def remapper(self, id_mapper):
        """Create a query remapper."""
        return QueryRemapper(id_mapper)

    def test_remap_template_tag_card_id(self, remapper):
        """Test remapping card-id in template tags."""
        template_tags = {
            "50-my-model": {
                "type": "card",
                "card-id": 50,
                "name": "50-my-model",
                "display-name": "50-my-model",
            }
        }
        result = remapper._remap_template_tags(template_tags)

        # Tag name should be remapped
        assert "500-my-model" in result
        assert "50-my-model" not in result

        # Card-id should be remapped
        assert result["500-my-model"]["card-id"] == 500

        # Name and display-name should be remapped
        assert result["500-my-model"]["name"] == "500-my-model"
        assert result["500-my-model"]["display-name"] == "500-my-model"

    def test_remap_template_tags_preserves_non_card_tags(self, remapper):
        """Test that non-card template tags are preserved."""
        template_tags = {
            "start_date": {
                "type": "date",
                "name": "start_date",
            },
            "50-model": {
                "type": "card",
                "card-id": 50,
            },
        }
        result = remapper._remap_template_tags(template_tags)

        # Non-card tag preserved
        assert "start_date" in result
        assert result["start_date"]["type"] == "date"

        # Card tag remapped
        assert "500-model" in result

    def test_remap_template_tags_preserves_unmapped_cards(self, remapper):
        """Test that unmapped card references are preserved."""
        template_tags = {
            "999-unknown": {
                "type": "card",
                "card-id": 999,
            }
        }
        result = remapper._remap_template_tags(template_tags)

        assert "999-unknown" in result
        assert result["999-unknown"]["card-id"] == 999


class TestQueryRemapperNativeQueryV56:
    """Tests for full native query remapping in v56 format."""

    @pytest.fixture
    def id_mapper(self):
        """Create an ID mapper with mappings."""
        return create_test_id_mapper(
            db_mapping={1: 100},
            card_mapping={50: 500},
        )

    @pytest.fixture
    def remapper(self, id_mapper):
        """Create a query remapper."""
        return QueryRemapper(id_mapper)

    def test_remap_native_query_v56(self, remapper):
        """Test full v56 native query remapping."""
        card_data = {
            "database_id": 1,
            "dataset_query": {
                "type": "native",
                "database": 1,
                "native": {
                    "query": "SELECT * FROM {{#50-my-model}}",
                    "template-tags": {
                        "50-my-model": {
                            "type": "card",
                            "card-id": 50,
                            "name": "50-my-model",
                        }
                    },
                },
            },
        }

        result, success = remapper.remap_card_data(card_data)

        assert success
        # Database remapped
        assert result["database_id"] == 100
        assert result["dataset_query"]["database"] == 100

        # SQL remapped
        native = result["dataset_query"]["native"]
        assert "{{#500-my-model}}" in native["query"]

        # Template tags remapped
        assert "500-my-model" in native["template-tags"]
        assert native["template-tags"]["500-my-model"]["card-id"] == 500


class TestQueryRemapperNativeQueryV57:
    """Tests for full native query remapping in v57 format."""

    @pytest.fixture
    def id_mapper(self):
        """Create an ID mapper with mappings."""
        return create_test_id_mapper(
            db_mapping={1: 100},
            card_mapping={50: 500},
        )

    @pytest.fixture
    def remapper(self, id_mapper):
        """Create a query remapper."""
        return QueryRemapper(id_mapper)

    def test_remap_native_query_v57(self, remapper):
        """Test full v57 native query remapping."""
        card_data = {
            "database_id": 1,
            "dataset_query": {
                "lib/type": "mbql/query",
                "database": 1,
                "stages": [
                    {
                        "lib/type": "mbql.stage/native",
                        "native": "SELECT * FROM {{#50-my-model}}",
                        "template-tags": {
                            "50-my-model": {
                                "type": "card",
                                "card-id": 50,
                                "name": "50-my-model",
                            }
                        },
                    }
                ],
            },
        }

        result, success = remapper.remap_card_data(card_data)

        assert success
        # Database remapped
        assert result["database_id"] == 100
        assert result["dataset_query"]["database"] == 100

        # SQL remapped in stage
        stage = result["dataset_query"]["stages"][0]
        assert "{{#500-my-model}}" in stage["native"]

        # Template tags remapped in stage
        assert "500-my-model" in stage["template-tags"]
        assert stage["template-tags"]["500-my-model"]["card-id"] == 500


class TestV57AdapterNativeDependencies:
    """Tests for V57Adapter extracting native query dependencies."""

    def test_v57_adapter_extract_native_dependencies(self):
        """Test V57Adapter extracts native query card dependencies."""
        adapter = get_version_adapter(MetabaseVersion.V57)
        assert isinstance(adapter, V57Adapter)

        card_data = {
            "dataset_query": {
                "lib/type": "mbql/query",
                "stages": [
                    {
                        "lib/type": "mbql.stage/native",
                        "native": "SELECT * FROM {{#50-model}}",
                        "template-tags": {
                            "50-model": {"type": "card", "card-id": 50},
                        },
                    }
                ],
            }
        }

        deps = adapter.extract_card_dependencies(card_data)
        assert 50 in deps

    def test_v57_adapter_extract_mixed_dependencies(self):
        """Test V57Adapter extracts both MBQL and native dependencies."""
        adapter = get_version_adapter(MetabaseVersion.V57)

        card_data = {
            "dataset_query": {
                "lib/type": "mbql/query",
                "stages": [
                    {
                        "lib/type": "mbql.stage/mbql",
                        "source-table": "card__100",
                        "joins": [{"source-table": "card__200"}],
                    },
                    {
                        "lib/type": "mbql.stage/native",
                        "native": "SELECT * FROM {{#300-model}}",
                        "template-tags": {
                            "300-model": {"type": "card", "card-id": 300},
                        },
                    },
                ],
            }
        }

        deps = adapter.extract_card_dependencies(card_data)
        assert deps == {100, 200, 300}


class TestIsNativeQuery:
    """Tests for QueryRemapper._is_native_query method."""

    @pytest.fixture
    def remapper(self):
        """Create a query remapper with minimal mapper."""
        mapper = create_test_id_mapper(db_mapping={1: 100})
        return QueryRemapper(mapper)

    def test_is_native_query_v56(self, remapper):
        """Test detecting v56 native query."""
        dataset_query = {"type": "native", "native": {"query": "SELECT 1"}}
        assert remapper._is_native_query(dataset_query) is True

    def test_is_not_native_query_v56(self, remapper):
        """Test detecting v56 MBQL query."""
        dataset_query = {"type": "query", "query": {"source-table": 1}}
        assert remapper._is_native_query(dataset_query) is False

    def test_is_native_query_v57(self, remapper):
        """Test detecting v57 native query by stage type."""
        dataset_query = {
            "lib/type": "mbql/query",
            "stages": [{"lib/type": "mbql.stage/native", "native": "SELECT 1"}],
        }
        assert remapper._is_native_query(dataset_query) is True

    def test_is_native_query_v57_by_native_string(self, remapper):
        """Test detecting v57 native query by native string value."""
        dataset_query = {"stages": [{"native": "SELECT 1"}]}
        assert remapper._is_native_query(dataset_query) is True

    def test_is_not_native_query_v57(self, remapper):
        """Test detecting v57 MBQL query."""
        dataset_query = {
            "lib/type": "mbql/query",
            "stages": [{"lib/type": "mbql.stage/mbql", "source-table": 1}],
        }
        assert remapper._is_native_query(dataset_query) is False


class TestMBQLQueryRemappingV57:
    """Tests for MBQL query remapping in v57 format."""

    @pytest.fixture
    def id_mapper(self):
        """Create an ID mapper with mappings."""
        mapper = create_test_id_mapper(
            db_mapping={1: 100},
            card_mapping={50: 500},
        )
        return mapper

    @pytest.fixture
    def remapper(self, id_mapper):
        """Create a query remapper."""
        return QueryRemapper(id_mapper)

    def test_remap_mbql_v57_source_table(self, remapper):
        """Test remapping source-table in v57 MBQL stage."""
        card_data = {
            "database_id": 1,
            "dataset_query": {
                "lib/type": "mbql/query",
                "database": 1,
                "stages": [
                    {
                        "lib/type": "mbql.stage/mbql",
                        "source-table": "card__50",
                    }
                ],
            },
        }

        result, success = remapper.remap_card_data(card_data)

        assert success
        assert result["dataset_query"]["stages"][0]["source-table"] == "card__500"

    def test_remap_mbql_v57_joins(self, remapper):
        """Test remapping joins in v57 MBQL stage."""
        card_data = {
            "database_id": 1,
            "dataset_query": {
                "lib/type": "mbql/query",
                "database": 1,
                "stages": [
                    {
                        "lib/type": "mbql.stage/mbql",
                        "source-table": 10,
                        "joins": [{"source-table": "card__50"}],
                    }
                ],
            },
        }

        result, success = remapper.remap_card_data(card_data)

        assert success
        assert result["dataset_query"]["stages"][0]["joins"][0]["source-table"] == "card__500"


class TestV57TemplateTagHashPrefix:
    """Tests for v57 template tags with # prefix in key names.

    In v57, template tag keys can have a # prefix like "#50-model-name"
    instead of just "50-model-name". This tests that remapping handles both formats.
    """

    @pytest.fixture
    def id_mapper(self):
        """Create an ID mapper with card mappings."""
        return create_test_id_mapper(
            db_mapping={1: 100},
            card_mapping={50: 406},  # Real-world example mapping
        )

    @pytest.fixture
    def remapper(self, id_mapper):
        """Create a query remapper."""
        return QueryRemapper(id_mapper)

    def test_remap_tag_name_with_hash_prefix(self, remapper):
        """Test that _remap_tag_name handles # prefix in tag names."""
        # v57 format with # prefix
        result = remapper._remap_tag_name("#50-filtered-xxxx-server-dataset", 50, 406)
        assert result == "#406-filtered-xxxx-server-dataset"

        # v56 format without # prefix still works
        result = remapper._remap_tag_name("50-filtered-xxxx-server-dataset", 50, 406)
        assert result == "406-filtered-xxxx-server-dataset"

    def test_remap_template_tags_with_hash_prefix_key(self, remapper):
        """Test remapping template tags where the key has # prefix."""
        template_tags = {
            "#50-filtered-xxxx-server-dataset": {
                "type": "card",
                "card-id": 50,
                "name": "#50-filtered-xxxx-server-dataset",
                "display-name": "#50 Filtered XXXX Server Dataset",
                "id": "896131a3-6d4f-4399-83e8-7833dae83233",
            }
        }
        result = remapper._remap_template_tags(template_tags)

        # Key should be remapped with # preserved
        assert "#406-filtered-xxxx-server-dataset" in result
        assert "#50-filtered-xxxx-server-dataset" not in result

        tag_data = result["#406-filtered-xxxx-server-dataset"]

        # card-id should be remapped
        assert tag_data["card-id"] == 406

        # name should be remapped with # prefix preserved
        assert tag_data["name"] == "#406-filtered-xxxx-server-dataset"

        # display-name should be remapped with # prefix preserved
        assert tag_data["display-name"] == "#406 Filtered XXXX Server Dataset"

        # id should be preserved
        assert tag_data["id"] == "896131a3-6d4f-4399-83e8-7833dae83233"

    def test_remap_full_v57_native_query_with_hash_prefix(self, remapper):
        """Test full v57 native query with # prefix template tag key."""
        card_data = {
            "database_id": 1,
            "dataset_query": {
                "lib/type": "mbql/query",
                "database": 1,
                "stages": [
                    {
                        "lib/type": "mbql.stage/native",
                        "native": "SELECT * FROM {{#50-filtered-xxxx-server-dataset}}",
                        "template-tags": {
                            "#50-filtered-xxxx-server-dataset": {
                                "type": "card",
                                "card-id": 50,
                                "name": "#50-filtered-xxxx-server-dataset",
                                "display-name": "#50 Filtered XXXX Server Dataset",
                                "id": "896131a3-6d4f-4399-83e8-7833dae83233",
                            }
                        },
                    }
                ],
            },
        }

        result, success = remapper.remap_card_data(card_data)

        assert success

        # Database remapped
        assert result["database_id"] == 100
        assert result["dataset_query"]["database"] == 100

        # SQL remapped
        stage = result["dataset_query"]["stages"][0]
        assert "{{#406-filtered-xxxx-server-dataset}}" in stage["native"]
        assert "{{#50-" not in stage["native"]

        # Template tag key remapped with # prefix preserved
        assert "#406-filtered-xxxx-server-dataset" in stage["template-tags"]
        assert "#50-filtered-xxxx-server-dataset" not in stage["template-tags"]

        tag_data = stage["template-tags"]["#406-filtered-xxxx-server-dataset"]
        assert tag_data["card-id"] == 406
        assert tag_data["name"] == "#406-filtered-xxxx-server-dataset"
        assert tag_data["display-name"] == "#406 Filtered XXXX Server Dataset"


class TestQueryRemapperV57Advanced:
    """Advanced tests for v57 query remapping including stages and nested structures."""

    @pytest.fixture
    def id_mapper(self):
        """Create an ID mapper with mappings."""
        mapper = create_test_id_mapper(
            db_mapping={1: 100, 2: 200},
            card_mapping={50: 500, 60: 600, 70: 700},
        )
        # Add table and field mappings
        mapper._table_map[(1, 10)] = 1000
        mapper._field_map[(1, 101)] = 10100
        mapper._field_map[(1, 102)] = 10200
        return mapper

    @pytest.fixture
    def remapper(self, id_mapper):
        """Create a query remapper."""
        return QueryRemapper(id_mapper)

    def test_remap_v57_source_card_integer(self, remapper):
        """Test remapping source-card (integer) in v57 format."""
        card_data = {
            "database_id": 1,
            "dataset_query": {
                "lib/type": "mbql/query",
                "database": 1,
                "stages": [
                    {
                        "lib/type": "mbql.stage/mbql",
                        "source-card": 50,
                    }
                ],
            },
        }

        result, success = remapper.remap_card_data(card_data)

        assert success
        assert result["dataset_query"]["stages"][0]["source-card"] == 500

    def test_remap_v57_multiple_stages(self, remapper):
        """Test remapping multiple stages in v57 format."""
        card_data = {
            "database_id": 1,
            "dataset_query": {
                "lib/type": "mbql/query",
                "database": 1,
                "stages": [
                    {
                        "lib/type": "mbql.stage/mbql",
                        "source-card": 50,
                    },
                    {
                        "lib/type": "mbql.stage/mbql",
                        "joins": [{"source-card": 60}],
                    },
                ],
            },
        }

        result, success = remapper.remap_card_data(card_data)

        assert success
        assert result["dataset_query"]["stages"][0]["source-card"] == 500
        assert result["dataset_query"]["stages"][1]["joins"][0]["source-card"] == 600

    def test_remap_v57_filters_plural(self, remapper):
        """Test remapping filters (plural) in v57 format."""
        card_data = {
            "database_id": 1,
            "dataset_query": {
                "lib/type": "mbql/query",
                "database": 1,
                "stages": [
                    {
                        "lib/type": "mbql.stage/mbql",
                        "source-table": 10,
                        "filters": [
                            ["=", ["field", 101, {"base-type": "type/Integer"}], 1],
                        ],
                    }
                ],
            },
        }

        result, success = remapper.remap_card_data(card_data)

        assert success
        assert result["dataset_query"]["stages"][0]["filters"][0][1][1] == 10100

    def test_remap_v57_breakout(self, remapper):
        """Test remapping breakout fields in v57 format."""
        card_data = {
            "database_id": 1,
            "dataset_query": {
                "lib/type": "mbql/query",
                "database": 1,
                "stages": [
                    {
                        "lib/type": "mbql.stage/mbql",
                        "source-table": 10,
                        "breakout": [["field", 101, {"temporal-unit": "month"}]],
                    }
                ],
            },
        }

        result, success = remapper.remap_card_data(card_data)

        assert success
        assert result["dataset_query"]["stages"][0]["breakout"][0][1] == 10100

    def test_remap_v57_aggregation(self, remapper):
        """Test remapping aggregation fields in v57 format."""
        card_data = {
            "database_id": 1,
            "dataset_query": {
                "lib/type": "mbql/query",
                "database": 1,
                "stages": [
                    {
                        "lib/type": "mbql.stage/mbql",
                        "source-table": 10,
                        "aggregation": [["sum", ["field", 101, None]]],
                    }
                ],
            },
        }

        result, success = remapper.remap_card_data(card_data)

        assert success
        assert result["dataset_query"]["stages"][0]["aggregation"][0][1][1] == 10100

    def test_remap_v57_order_by(self, remapper):
        """Test remapping order-by fields in v57 format."""
        card_data = {
            "database_id": 1,
            "dataset_query": {
                "lib/type": "mbql/query",
                "database": 1,
                "stages": [
                    {
                        "lib/type": "mbql.stage/mbql",
                        "source-table": 10,
                        "order-by": [["asc", ["field", 101, None]]],
                    }
                ],
            },
        }

        result, success = remapper.remap_card_data(card_data)

        assert success
        assert result["dataset_query"]["stages"][0]["order-by"][0][1][1] == 10100

    def test_remap_v57_expressions(self, remapper):
        """Test remapping expressions in v57 format."""
        card_data = {
            "database_id": 1,
            "dataset_query": {
                "lib/type": "mbql/query",
                "database": 1,
                "stages": [
                    {
                        "lib/type": "mbql.stage/mbql",
                        "source-table": 10,
                        "expressions": [
                            [
                                "concat",
                                ["field", 101, None],
                                ["field", 102, None],
                            ]
                        ],
                    }
                ],
            },
        }

        result, success = remapper.remap_card_data(card_data)

        assert success
        assert result["dataset_query"]["stages"][0]["expressions"][0][1][1] == 10100
        assert result["dataset_query"]["stages"][0]["expressions"][0][2][1] == 10200


class TestQueryRemapperEdgeCases:
    """Tests for edge cases in query remapping."""

    @pytest.fixture
    def id_mapper(self):
        """Create an ID mapper with minimal mappings."""
        return create_test_id_mapper(
            db_mapping={1: 100},
            card_mapping={},
        )

    @pytest.fixture
    def remapper(self, id_mapper):
        """Create a query remapper."""
        return QueryRemapper(id_mapper)

    def test_remap_empty_dataset_query(self, remapper):
        """Test remapping card with empty dataset_query."""
        card_data = {
            "database_id": 1,
            "dataset_query": {},
        }

        result, success = remapper.remap_card_data(card_data)

        assert success
        assert result["database_id"] == 100

    def test_remap_no_dataset_query(self, remapper):
        """Test remapping card without dataset_query returns failure."""
        card_data = {"database_id": 1}

        result, success = remapper.remap_card_data(card_data)

        # Should still set database_id
        assert result["database_id"] == 100
        assert success

    def test_remap_unmapped_database(self):
        """Test remapping with unmapped database ID raises ValueError."""
        mapper = create_test_id_mapper(db_mapping={})  # No mappings

        remapper = QueryRemapper(mapper)

        card_data = {
            "database_id": 999,  # Not mapped
            "dataset_query": {
                "type": "query",
                "database": 999,
                "query": {},
            },
        }

        # Should raise ValueError when database is not mapped
        with pytest.raises(ValueError, match="Unmapped database ID"):
            remapper.remap_card_data(card_data)

    def test_remap_preserves_unknown_fields(self, remapper):
        """Test that unknown fields in card data are preserved."""
        card_data = {
            "database_id": 1,
            "dataset_query": {
                "type": "query",
                "database": 1,
                "query": {},
            },
            "custom_field": "preserved",
            "another_field": {"nested": "value"},
        }

        result, success = remapper.remap_card_data(card_data)

        assert success
        assert result["custom_field"] == "preserved"
        assert result["another_field"]["nested"] == "value"


class TestQueryRemapperResultMetadata:
    """Tests for result_metadata remapping."""

    @pytest.fixture
    def id_mapper(self):
        """Create an ID mapper with mappings."""
        mapper = create_test_id_mapper(
            db_mapping={1: 100},
            card_mapping={},
        )
        mapper._table_map[(1, 10)] = 1000
        mapper._field_map[(1, 101)] = 10100
        mapper._field_map[(1, 102)] = 10200
        return mapper

    @pytest.fixture
    def remapper(self, id_mapper):
        """Create a query remapper."""
        return QueryRemapper(id_mapper)

    def test_remap_result_metadata_fields(self, remapper):
        """Test remapping field IDs in result_metadata."""
        card_data = {
            "database_id": 1,
            "table_id": 10,
            "dataset_query": {
                "type": "query",
                "database": 1,
                "query": {"source-table": 10},
            },
            "result_metadata": [
                {
                    "id": 101,
                    "name": "field1",
                    "table_id": 10,
                    "field_ref": ["field", 101, None],
                },
                {
                    "id": 102,
                    "name": "field2",
                    "table_id": 10,
                    "field_ref": ["field", 102, {"base-type": "type/Text"}],
                },
            ],
        }

        result, success = remapper.remap_card_data(card_data)

        assert success
        assert result["result_metadata"][0]["id"] == 10100
        assert result["result_metadata"][0]["table_id"] == 1000
        assert result["result_metadata"][0]["field_ref"][1] == 10100
        assert result["result_metadata"][1]["id"] == 10200
        assert result["result_metadata"][1]["table_id"] == 1000
        assert result["result_metadata"][1]["field_ref"][1] == 10200

    def test_remap_result_metadata_expression_field(self, remapper):
        """Test that expression fields in result_metadata are preserved."""
        card_data = {
            "database_id": 1,
            "dataset_query": {
                "type": "query",
                "database": 1,
                "query": {"source-table": 10},
            },
            "result_metadata": [
                {
                    "name": "custom_expression",
                    "field_ref": ["expression", "custom_expression"],
                },
            ],
        }

        result, success = remapper.remap_card_data(card_data)

        assert success
        # Expression field refs should be preserved as-is
        assert result["result_metadata"][0]["field_ref"] == [
            "expression",
            "custom_expression",
        ]


class TestClickBehaviorRemapping:
    """Tests for click_behavior remapping in visualization settings."""

    @pytest.fixture
    def id_mapper(self):
        mapper = create_test_id_mapper(db_mapping={1: 100}, card_mapping={10: 110, 20: 220})
        mapper.set_dashboard_mapping(30, 330)
        return mapper

    @pytest.fixture
    def remapper(self, id_mapper):
        return QueryRemapper(id_mapper)

    def test_click_behavior_question_link(self, remapper):
        """Test remapping click_behavior with linkType=question."""
        viz = {
            "click_behavior": {
                "type": "link",
                "linkType": "question",
                "targetId": 10,
            }
        }
        result = remapper.remap_dashcard_visualization_settings(viz, None)
        assert result["click_behavior"]["targetId"] == 110

    def test_click_behavior_dashboard_link(self, remapper):
        """Test remapping click_behavior with linkType=dashboard."""
        viz = {
            "click_behavior": {
                "type": "link",
                "linkType": "dashboard",
                "targetId": 30,
            }
        }
        result = remapper.remap_dashcard_visualization_settings(viz, None)
        assert result["click_behavior"]["targetId"] == 330

    def test_click_behavior_unmapped_question(self, remapper):
        """Test click_behavior with unmapped question keeps original."""
        viz = {
            "click_behavior": {
                "type": "link",
                "linkType": "question",
                "targetId": 999,
            }
        }
        result = remapper.remap_dashcard_visualization_settings(viz, None)
        assert result["click_behavior"]["targetId"] == 999

    def test_click_behavior_unmapped_dashboard(self, remapper):
        """Test click_behavior with unmapped dashboard keeps original."""
        viz = {
            "click_behavior": {
                "type": "link",
                "linkType": "dashboard",
                "targetId": 999,
            }
        }
        result = remapper.remap_dashcard_visualization_settings(viz, None)
        assert result["click_behavior"]["targetId"] == 999

    def test_click_behavior_not_link_type(self, remapper):
        """Test click_behavior with non-link type is preserved."""
        viz = {"click_behavior": {"type": "crossfilter"}}
        result = remapper.remap_dashcard_visualization_settings(viz, None)
        assert result["click_behavior"]["type"] == "crossfilter"

    def test_click_behavior_not_dict(self, remapper):
        """Test _remap_click_behavior with non-dict input."""
        result = remapper._remap_click_behavior("not a dict")
        assert result == "not a dict"

    def test_column_settings_click_behavior(self, remapper):
        """Test remapping click_behavior in column_settings."""
        viz = {
            "column_settings": {
                '["ref",["field",1,null]]': {
                    "click_behavior": {
                        "type": "link",
                        "linkType": "question",
                        "targetId": 10,
                    }
                }
            }
        }
        result = remapper.remap_dashcard_visualization_settings(viz, None)
        col_key = '["ref",["field",1,null]]'
        assert result["column_settings"][col_key]["click_behavior"]["targetId"] == 110

    def test_empty_viz_settings(self, remapper):
        """Test empty viz settings returns as-is."""
        assert remapper.remap_dashcard_visualization_settings({}, None) == {}
        assert remapper.remap_dashcard_visualization_settings(None, None) is None


class TestVisualizerRemapping:
    """Tests for Visualizer columnValuesMapping remapping."""

    @pytest.fixture
    def id_mapper(self):
        mapper = create_test_id_mapper(db_mapping={1: 100}, card_mapping={10: 110, 20: 220})
        return mapper

    @pytest.fixture
    def remapper(self, id_mapper):
        return QueryRemapper(id_mapper)

    def test_remap_visualizer_column_values_mapping(self, remapper):
        """Test remapping sourceId in columnValuesMapping."""
        viz = {
            "visualization": {
                "columnValuesMapping": {
                    "col1": [{"sourceId": "card:10", "name": "col1", "originalName": "col1"}],
                }
            }
        }
        result = remapper.remap_dashcard_visualization_settings(viz, None)
        assert result["visualization"]["columnValuesMapping"]["col1"][0]["sourceId"] == "card:110"

    def test_remap_visualizer_unmapped_card(self, remapper):
        """Test Visualizer with unmapped card keeps original."""
        viz = {
            "visualization": {
                "columnValuesMapping": {
                    "col1": [{"sourceId": "card:999", "name": "col1"}],
                }
            }
        }
        result = remapper.remap_dashcard_visualization_settings(viz, None)
        assert result["visualization"]["columnValuesMapping"]["col1"][0]["sourceId"] == "card:999"

    def test_remap_data_source_name_ref(self, remapper):
        """Test remapping $_card:123_name format."""
        viz = {
            "visualization": {
                "columnValuesMapping": {
                    "col1": ["$_card:10_name"],
                }
            }
        }
        result = remapper.remap_dashcard_visualization_settings(viz, None)
        assert result["visualization"]["columnValuesMapping"]["col1"][0] == "$_card:110_name"

    def test_remap_data_source_name_ref_unmapped(self, remapper):
        """Test $_card:999_name with unmapped card keeps original."""
        result = remapper._remap_data_source_name_ref("$_card:999_name")
        assert result == "$_card:999_name"

    def test_remap_data_source_name_ref_no_match(self, remapper):
        """Test non-matching ref string returns as-is."""
        result = remapper._remap_data_source_name_ref("some_other_ref")
        assert result == "some_other_ref"

    def test_remap_visualizer_source_id_invalid(self, remapper):
        """Test invalid sourceId format."""
        item = {"sourceId": "card:not_a_number"}
        result = remapper._remap_visualizer_source_id(item)
        assert result["sourceId"] == "card:not_a_number"

    def test_remap_visualizer_definition_not_dict(self, remapper):
        """Test _remap_visualizer_definition with non-dict."""
        result = remapper._remap_visualizer_definition("not a dict")
        assert result == "not a dict"

    def test_column_values_mapping_non_list_value(self, remapper):
        """Test columnValuesMapping with non-list value."""
        mapping = {"col1": "string_value"}
        result = remapper._remap_column_values_mapping(mapping)
        assert result["col1"] == "string_value"

    def test_column_values_mapping_plain_items(self, remapper):
        """Test columnValuesMapping with items that are not dicts or card refs."""
        mapping = {"col1": [42, "plain_string"]}
        result = remapper._remap_column_values_mapping(mapping)
        assert result["col1"] == [42, "plain_string"]


class TestLinkCardRemapping:
    """Tests for link card entity remapping."""

    @pytest.fixture
    def id_mapper(self):
        mapper = create_test_id_mapper(db_mapping={1: 100}, card_mapping={10: 110})
        mapper.set_dashboard_mapping(30, 330)
        return mapper

    @pytest.fixture
    def remapper(self, id_mapper):
        return QueryRemapper(id_mapper)

    def test_link_card_question(self, remapper):
        """Test remapping link card with model=card."""
        viz = {"link": {"entity": {"id": 10, "model": "card"}}}
        result = remapper.remap_dashcard_visualization_settings(viz, None)
        assert result["link"]["entity"]["id"] == 110

    def test_link_card_question_model(self, remapper):
        """Test remapping link card with model=question."""
        viz = {"link": {"entity": {"id": 10, "model": "question"}}}
        result = remapper.remap_dashcard_visualization_settings(viz, None)
        assert result["link"]["entity"]["id"] == 110

    def test_link_card_model_type(self, remapper):
        """Test remapping link card with model=model."""
        viz = {"link": {"entity": {"id": 10, "model": "model"}}}
        result = remapper.remap_dashcard_visualization_settings(viz, None)
        assert result["link"]["entity"]["id"] == 110

    def test_link_card_metric_type(self, remapper):
        """Test remapping link card with model=metric."""
        viz = {"link": {"entity": {"id": 10, "model": "metric"}}}
        result = remapper.remap_dashcard_visualization_settings(viz, None)
        assert result["link"]["entity"]["id"] == 110

    def test_link_card_dashboard(self, remapper):
        """Test remapping link card with model=dashboard."""
        viz = {"link": {"entity": {"id": 30, "model": "dashboard"}}}
        result = remapper.remap_dashcard_visualization_settings(viz, None)
        assert result["link"]["entity"]["id"] == 330

    def test_link_card_unmapped_card(self, remapper):
        """Test link card with unmapped card keeps original."""
        viz = {"link": {"entity": {"id": 999, "model": "card"}}}
        result = remapper.remap_dashcard_visualization_settings(viz, None)
        assert result["link"]["entity"]["id"] == 999

    def test_link_card_unmapped_dashboard(self, remapper):
        """Test link card with unmapped dashboard keeps original."""
        viz = {"link": {"entity": {"id": 999, "model": "dashboard"}}}
        result = remapper.remap_dashcard_visualization_settings(viz, None)
        assert result["link"]["entity"]["id"] == 999

    def test_link_card_restricted_entity(self, remapper):
        """Test link card with restricted entity is preserved."""
        viz = {"link": {"entity": {"restricted": True}}}
        result = remapper.remap_dashcard_visualization_settings(viz, None)
        assert result["link"]["entity"]["restricted"] is True

    def test_link_card_no_entity(self, remapper):
        """Test link card without entity is preserved."""
        viz = {"link": {"url": "https://example.com"}}
        result = remapper.remap_dashcard_visualization_settings(viz, None)
        assert result["link"]["url"] == "https://example.com"

    def test_link_card_non_int_id(self, remapper):
        """Test link card with non-int entity id is preserved."""
        viz = {"link": {"entity": {"id": "string_id", "model": "card"}}}
        result = remapper.remap_dashcard_visualization_settings(viz, None)
        assert result["link"]["entity"]["id"] == "string_id"

    def test_link_card_not_dict(self, remapper):
        """Test _remap_link_card_settings with non-dict."""
        result = remapper._remap_link_card_settings("not a dict")
        assert result == "not a dict"


class TestV57JoinsRemapping:
    """Tests for v57 join remapping with nested stages."""

    @pytest.fixture
    def id_mapper(self):
        mapper = create_test_id_mapper(db_mapping={1: 100}, card_mapping={10: 110, 20: 220})
        mapper._table_map[(1, 50)] = 5000
        mapper._field_map[(1, 101)] = 10100
        return mapper

    @pytest.fixture
    def remapper(self, id_mapper):
        return QueryRemapper(id_mapper)

    def test_v57_join_with_nested_stages(self, remapper):
        """Test v57 join with nested stages array."""
        card_data = {
            "database_id": 1,
            "dataset_query": {
                "type": "query",
                "database": 1,
                "query": {
                    "source-table": 50,
                    "joins": [
                        {
                            "stages": [{"source-table": 50, "source-card": 10}],
                            "condition": ["=", ["field", 101, None], ["field", 101, None]],
                        }
                    ],
                },
            },
        }
        result, success = remapper.remap_card_data(card_data)
        assert success
        join = result["dataset_query"]["query"]["joins"][0]
        assert join["stages"][0]["source-table"] == 5000
        assert join["stages"][0]["source-card"] == 110

    def test_v56_join_card_reference(self, remapper):
        """Test v56 join with card__XX reference."""
        card_data = {
            "database_id": 1,
            "dataset_query": {
                "type": "query",
                "database": 1,
                "query": {
                    "source-table": 50,
                    "joins": [
                        {
                            "source-table": "card__10",
                            "condition": ["=", ["field", 101, None], 1],
                        }
                    ],
                },
            },
        }
        result, success = remapper.remap_card_data(card_data)
        assert success
        assert result["dataset_query"]["query"]["joins"][0]["source-table"] == "card__110"

    def test_v56_join_table_id(self, remapper):
        """Test v56 join with integer table ID."""
        card_data = {
            "database_id": 1,
            "dataset_query": {
                "type": "query",
                "database": 1,
                "query": {
                    "source-table": 50,
                    "joins": [
                        {
                            "source-table": 50,
                            "condition": ["=", 1, 1],
                        }
                    ],
                },
            },
        }
        result, success = remapper.remap_card_data(card_data)
        assert success
        assert result["dataset_query"]["query"]["joins"][0]["source-table"] == 5000

    def test_v57_join_source_card(self, remapper):
        """Test v57 join with source-card integer."""
        card_data = {
            "database_id": 1,
            "dataset_query": {
                "type": "query",
                "database": 1,
                "query": {
                    "source-table": 50,
                    "joins": [{"source-card": 10}],
                },
            },
        }
        result, success = remapper.remap_card_data(card_data)
        assert success
        assert result["dataset_query"]["query"]["joins"][0]["source-card"] == 110


class TestDashcardParameterMappings:
    """Tests for dashcard parameter_mappings remapping."""

    @pytest.fixture
    def id_mapper(self):
        mapper = create_test_id_mapper(db_mapping={1: 100}, card_mapping={10: 110})
        mapper._field_map[(1, 201)] = 20100
        return mapper

    @pytest.fixture
    def remapper(self, id_mapper):
        return QueryRemapper(id_mapper)

    def test_remap_card_id_in_parameter_mapping(self, remapper):
        """Test remapping card_id in parameter mappings."""
        mappings = [{"card_id": 10, "target": ["dimension", ["field", 201, None]]}]
        result = remapper.remap_dashcard_parameter_mappings(mappings, 1)
        assert result[0]["card_id"] == 110
        assert result[0]["target"][1][1] == 20100

    def test_remap_parameter_mapping_no_card_id(self, remapper):
        """Test parameter mapping without card_id."""
        mappings = [{"target": ["dimension", ["field", 201, None]]}]
        result = remapper.remap_dashcard_parameter_mappings(mappings, 1)
        assert "card_id" not in result[0]
        assert result[0]["target"][1][1] == 20100

    def test_remap_parameter_mapping_no_source_db(self, remapper):
        """Test parameter mapping without source_db_id skips field remapping."""
        mappings = [{"card_id": 10, "target": ["dimension", ["field", 201, None]]}]
        result = remapper.remap_dashcard_parameter_mappings(mappings, None)
        assert result[0]["card_id"] == 110
        assert result[0]["target"][1][1] == 201  # Not remapped


class TestParameterSourceConfig:
    """Tests for dashboard parameter values_source_config remapping."""

    @pytest.fixture
    def id_mapper(self):
        mapper = create_test_id_mapper(db_mapping={1: 100}, card_mapping={10: 110})
        mapper._field_map[(1, 201)] = 20100
        return mapper

    @pytest.fixture
    def remapper(self, id_mapper):
        return QueryRemapper(id_mapper)

    def test_remap_parameter_source_config_card_id(self, remapper):
        """Test remapping card_id in values_source_config."""
        from unittest.mock import MagicMock

        manifest_card = MagicMock()
        manifest_card.id = 10
        manifest_card.database_id = 1

        params = [
            {
                "name": "test_param",
                "values_source_config": {
                    "card_id": 10,
                    "value_field": ["field", 201, None],
                },
            }
        ]
        result = remapper.remap_dashboard_parameters(params, [manifest_card])
        assert result[0]["values_source_config"]["card_id"] == 110
        assert result[0]["values_source_config"]["value_field"][1] == 20100

    def test_remap_parameter_source_config_no_card_id(self, remapper):
        """Test parameter with empty card_id in values_source_config."""
        params = [{"name": "test", "values_source_config": {"card_id": None}}]
        result = remapper.remap_dashboard_parameters(params, [])
        assert result[0]["values_source_config"]["card_id"] is None

    def test_remap_parameter_source_config_unmapped_card(self, remapper):
        """Test parameter with unmapped card removes values_source_config."""
        params = [
            {
                "name": "test_param",
                "values_source_type": "card",
                "values_source_config": {"card_id": 999},
            }
        ]
        result = remapper.remap_dashboard_parameters(params, [])
        assert "values_source_config" not in result[0]
        assert "values_source_type" not in result[0]

    def test_remap_parameter_source_config_no_db_for_card(self, remapper):
        """Test parameter with card not in manifest (no db_id found)."""
        params = [
            {
                "name": "test",
                "values_source_config": {
                    "card_id": 10,
                    "value_field": ["field", 201, None],
                },
            }
        ]
        # Empty manifest_cards means _find_card_database_id returns None
        result = remapper.remap_dashboard_parameters(params, [])
        assert result[0]["values_source_config"]["card_id"] == 110
        # value_field not remapped because db_id not found
        assert result[0]["values_source_config"]["value_field"][1] == 201


class TestNativeQueryV57Remapping:
    """Tests for v57 native query remapping."""

    @pytest.fixture
    def id_mapper(self):
        return create_test_id_mapper(db_mapping={1: 100}, card_mapping={50: 550, 60: 660})

    @pytest.fixture
    def remapper(self, id_mapper):
        return QueryRemapper(id_mapper)

    def test_remap_native_query_v57_stages(self, remapper):
        """Test v57 native query with stages."""
        card_data = {
            "dataset_query": {
                "lib/type": "mbql/query",
                "stages": [
                    {
                        "lib/type": "mbql.stage/native",
                        "native": "SELECT * FROM {{#50-model}}",
                        "template-tags": {
                            "#50-model": {
                                "type": "card",
                                "card-id": 50,
                                "name": "#50-model",
                                "display-name": "#50 Model",
                            }
                        },
                    }
                ],
            }
        }
        result = remapper.remap_native_query(card_data)
        stage = result["dataset_query"]["stages"][0]
        assert "550" in stage["native"]
        assert stage["template-tags"]["#550-model"]["card-id"] == 550
        assert stage["template-tags"]["#550-model"]["name"] == "#550-model"
        assert stage["template-tags"]["#550-model"]["display-name"] == "#550 Model"

    def test_remap_native_query_v57_non_list_stages(self, remapper):
        """Test v57 native query with non-list stages."""
        card_data = {
            "dataset_query": {
                "lib/type": "mbql/query",
                "stages": "not a list",
            }
        }
        result = remapper.remap_native_query(card_data)
        assert result["dataset_query"]["stages"] == "not a list"

    def test_remap_native_query_v57_non_dict_stage(self, remapper):
        """Test v57 native query with non-dict stage."""
        card_data = {
            "dataset_query": {
                "lib/type": "mbql/query",
                "stages": ["not a dict"],
            }
        }
        result = remapper.remap_native_query(card_data)
        assert result["dataset_query"]["stages"] == ["not a dict"]

    def test_remap_native_query_v56_no_native(self, remapper):
        """Test v56 native query with no native key."""
        card_data = {"dataset_query": {"type": "native"}}
        result = remapper.remap_native_query(card_data)
        assert result["dataset_query"] == {"type": "native"}


class TestV57FieldFormat:
    """Tests for v57 field format remapping: ['field', {metadata}, field_id]."""

    @pytest.fixture
    def id_mapper(self):
        mapper = create_test_id_mapper(db_mapping={1: 100}, card_mapping={})
        mapper._field_map[(1, 201)] = 20100
        return mapper

    @pytest.fixture
    def remapper(self, id_mapper):
        return QueryRemapper(id_mapper)

    def test_v57_field_format_with_lib_uuid(self, remapper):
        """Test v57 field format with lib/uuid metadata."""
        data = ["field", {"lib/uuid": "abc-123", "base-type": "type/Integer"}, 201]
        result = remapper.remap_field_ids_recursively(data, 1)
        assert result[2] == 20100

    def test_v57_field_format_with_base_type(self, remapper):
        """Test v57 field format with base-type metadata."""
        data = ["field", {"base-type": "type/Text"}, 201]
        result = remapper.remap_field_ids_recursively(data, 1)
        assert result[2] == 20100

    def test_v57_field_format_unmapped(self, remapper):
        """Test v57 field format with unmapped field keeps original."""
        data = ["field", {"lib/uuid": "abc-123", "base-type": "type/Integer"}, 999]
        result = remapper.remap_field_ids_recursively(data, 1)
        assert result[2] == 999

    def test_v56_field_format_unmapped(self, remapper):
        """Test v56 field format with unmapped field keeps original."""
        data = ["field", 999, None]
        result = remapper.remap_field_ids_recursively(data, 1)
        assert result[1] == 999


class TestTemplateTagNameRemapping:
    """Tests for template tag name/display-name remapping."""

    @pytest.fixture
    def id_mapper(self):
        return create_test_id_mapper(db_mapping={1: 100}, card_mapping={50: 550})

    @pytest.fixture
    def remapper(self, id_mapper):
        return QueryRemapper(id_mapper)

    def test_remap_tag_name_v56_format(self, remapper):
        """Test v56 tag name format: 50-model-name."""
        result = remapper._remap_tag_name("50-model-name", 50, 550)
        assert result == "550-model-name"

    def test_remap_tag_name_v57_format(self, remapper):
        """Test v57 tag name format: #50-model-name."""
        result = remapper._remap_tag_name("#50-model-name", 50, 550)
        assert result == "#550-model-name"

    def test_remap_tag_name_display_name_format(self, remapper):
        """Test display-name format: #50 Model Name."""
        result = remapper._remap_tag_name("#50 Model Name", 50, 550)
        assert result == "#550 Model Name"

    def test_remap_tag_name_no_match(self, remapper):
        """Test tag name that doesn't match pattern."""
        result = remapper._remap_tag_name("custom_tag", 50, 550)
        assert result == "custom_tag"

    def test_template_tags_non_dict_tag_data(self, remapper):
        """Test template tags with non-dict tag data."""
        tags = {"tag1": "not a dict"}
        result = remapper._remap_template_tags(tags)
        assert result["tag1"] == "not a dict"

    def test_template_tags_non_card_type(self, remapper):
        """Test template tags with non-card type are preserved."""
        tags = {"tag1": {"type": "text", "name": "tag1"}}
        result = remapper._remap_template_tags(tags)
        assert result["tag1"]["type"] == "text"

    def test_template_tags_card_type_no_card_id(self, remapper):
        """Test card-type template tag without card-id."""
        tags = {"tag1": {"type": "card"}}
        result = remapper._remap_template_tags(tags)
        assert result["tag1"]["type"] == "card"


class TestMiscQueryRemapperPaths:
    """Tests for miscellaneous uncovered paths in QueryRemapper."""

    @pytest.fixture
    def id_mapper(self):
        mapper = create_test_id_mapper(db_mapping={1: 100}, card_mapping={10: 110})
        mapper._table_map[(1, 50)] = 5000
        return mapper

    @pytest.fixture
    def remapper(self, id_mapper):
        return QueryRemapper(id_mapper)

    def test_card_reference_invalid_format(self, remapper):
        """Test invalid card reference format (ValueError path)."""
        card_data = {
            "database_id": 1,
            "dataset_query": {
                "type": "query",
                "database": 1,
                "query": {"source-table": "card__not_a_number"},
            },
        }
        result, success = remapper.remap_card_data(card_data)
        assert success
        assert result["dataset_query"]["query"]["source-table"] == "card__not_a_number"

    def test_is_native_query_v57_stages(self, remapper):
        """Test _is_native_query with v57 stages format."""
        query = {"stages": [{"lib/type": "mbql.stage/native", "native": "SELECT 1"}]}
        assert remapper._is_native_query(query) is True

    def test_is_native_query_v57_native_string(self, remapper):
        """Test _is_native_query with v57 native string in stage."""
        query = {"stages": [{"native": "SELECT 1"}]}
        assert remapper._is_native_query(query) is True

    def test_is_native_query_v57_non_native_stage(self, remapper):
        """Test _is_native_query with v57 non-native stage."""
        query = {"stages": [{"lib/type": "mbql.stage/mbql", "source-table": 1}]}
        assert remapper._is_native_query(query) is False

    def test_remap_card_table_id_warning(self, remapper):
        """Test table_id remapping warning when no mapping found."""
        card_data = {
            "database_id": 1,
            "table_id": 999,
            "dataset_query": {
                "type": "query",
                "database": 1,
                "query": {"source-table": 50},
            },
        }
        result, success = remapper.remap_card_data(card_data)
        assert success
        assert result["table_id"] == 999  # Kept original

    def test_source_card_warning_unmapped(self, remapper):
        """Test v57 source-card warning when unmapped."""
        card_data = {
            "database_id": 1,
            "dataset_query": {
                "type": "query",
                "database": 1,
                "query": {"source-card": 999},
            },
        }
        result, success = remapper.remap_card_data(card_data)
        assert success
        assert result["dataset_query"]["query"]["source-card"] == 999

    def test_v57_mbql_stages_remapping(self, remapper):
        """Test v57 MBQL query with stages array."""
        card_data = {
            "database_id": 1,
            "dataset_query": {
                "type": "query",
                "database": 1,
                "stages": [{"source-table": 50}],
            },
        }
        result, success = remapper.remap_card_data(card_data)
        assert success
        assert result["dataset_query"]["stages"][0]["source-table"] == 5000

    def test_remap_native_query_in_place_v57(self, remapper):
        """Test _remap_native_query_in_place with v57 format."""
        card_data = {
            "database_id": 1,
            "dataset_query": {
                "type": "native",
                "database": 1,
                "lib/type": "mbql/query",
                "stages": [
                    {
                        "lib/type": "mbql.stage/native",
                        "native": "SELECT * FROM {{#10-model}}",
                        "template-tags": {
                            "#10-model": {"type": "card", "card-id": 10, "name": "#10-model"}
                        },
                    }
                ],
            },
        }
        result, success = remapper.remap_card_data(card_data)
        assert success
        stage = result["dataset_query"]["stages"][0]
        assert "110" in stage["native"]

    def test_viz_settings_with_field_remapping(self, remapper):
        """Test viz settings with source_db_id triggers field remapping."""
        remapper.id_mapper._field_map[(1, 201)] = 20100
        viz = {"column_settings": {"key": {"some_field": ["field", 201, None]}}}
        result = remapper.remap_dashcard_visualization_settings(viz, 1)
        assert result["column_settings"]["key"]["some_field"][1] == 20100
