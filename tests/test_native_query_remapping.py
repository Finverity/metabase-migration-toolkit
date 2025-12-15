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
