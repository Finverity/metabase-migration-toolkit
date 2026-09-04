"""Unit tests for lib/remapping/id_mapper.py.

Covers ID resolution, the property accessors and build_table_and_field_mappings,
including the paths taken when metadata is missing, unmapped or unfetchable.
"""

from unittest.mock import Mock

import pytest

from lib.client import MetabaseAPIError
from lib.models import DatabaseMap, Manifest, ManifestMeta
from lib.remapping.id_mapper import IDMapper


def make_manifest(
    databases: dict[int, str] | None = None,
    database_metadata: dict | None = None,
) -> Manifest:
    """Build a manifest with the given databases and metadata."""
    manifest = Manifest(
        meta=ManifestMeta(
            source_url="https://source.example.com",
            export_timestamp="2025-01-01T00:00:00",
            tool_version="1.0.0",
            cli_args={},
        ),
        databases=databases or {},
    )
    manifest.database_metadata = database_metadata or {}
    return manifest


@pytest.fixture
def mapper() -> IDMapper:
    """An IDMapper with db 1 mapped by id and db 2 mapped by name."""
    manifest = make_manifest({1: "Sales", 2: "Analytics"})
    db_map = DatabaseMap(by_id={"1": 10}, by_name={"Analytics": 20})
    return IDMapper(manifest, db_map)


class TestDatabaseResolution:
    """Tests for resolve_db_id."""

    def test_by_id_takes_precedence(self):
        manifest = make_manifest({1: "Sales"})
        mapper = IDMapper(manifest, DatabaseMap(by_id={"1": 10}, by_name={"Sales": 99}))
        assert mapper.resolve_db_id(1) == 10

    def test_falls_back_to_name(self, mapper):
        assert mapper.resolve_db_id(2) == 20

    def test_unmapped_returns_none(self, mapper):
        assert mapper.resolve_db_id(3) is None

    def test_known_database_with_unmapped_name_returns_none(self):
        manifest = make_manifest({1: "Sales"})
        mapper = IDMapper(manifest, DatabaseMap(by_id={}, by_name={"Other": 20}))
        assert mapper.resolve_db_id(1) is None


class TestIdResolution:
    """Tests for the simple map-backed resolvers and their setters."""

    def test_collection_mapping(self, mapper):
        mapper.set_collection_mapping(1, 100)
        assert mapper.resolve_collection_id(1) == 100
        assert mapper.collection_map == {1: 100}

    def test_collection_none_returns_none(self, mapper):
        assert mapper.resolve_collection_id(None) is None

    def test_collection_unmapped_returns_none(self, mapper):
        assert mapper.resolve_collection_id(42) is None

    def test_card_mapping(self, mapper):
        mapper.set_card_mapping(5, 50)
        assert mapper.resolve_card_id(5) == 50
        assert mapper.card_map == {5: 50}

    def test_card_unmapped_returns_none(self, mapper):
        assert mapper.resolve_card_id(5) is None

    def test_dashboard_mapping(self, mapper):
        mapper.set_dashboard_mapping(7, 70)
        assert mapper.resolve_dashboard_id(7) == 70
        assert mapper.dashboard_map == {7: 70}

    def test_dashboard_unmapped_returns_none(self, mapper):
        assert mapper.resolve_dashboard_id(7) is None

    def test_group_mapping(self, mapper):
        mapper.set_group_mapping(3, 30)
        assert mapper.group_map == {3: 30}

    def test_table_and_field_resolution(self, mapper):
        mapper.table_map[(1, 100)] = 1000
        mapper.field_map[(1, 200)] = 2000

        assert mapper.resolve_table_id(1, 100) == 1000
        assert mapper.resolve_field_id(1, 200) == 2000

    def test_table_and_field_unmapped_return_none(self, mapper):
        assert mapper.resolve_table_id(1, 100) is None
        assert mapper.resolve_field_id(1, 200) is None

    def test_table_lookup_is_scoped_by_database(self, mapper):
        mapper.table_map[(1, 100)] = 1000
        assert mapper.resolve_table_id(2, 100) is None


class TestBuildTableAndFieldMappings:
    """Tests for build_table_and_field_mappings."""

    def source_metadata(self) -> dict:
        return {
            1: {
                "tables": [
                    {
                        "id": 100,
                        "name": "orders",
                        "fields": [{"id": 200, "name": "total"}, {"id": 201, "name": "gone"}],
                    },
                    {"id": 101, "name": "missing_table", "fields": []},
                ]
            }
        }

    def target_metadata(self) -> dict:
        return {
            "tables": [{"id": 1000, "name": "orders", "fields": [{"id": 2000, "name": "total"}]}]
        }

    def test_no_client_logs_warning(self, mapper, caplog):
        with caplog.at_level("WARNING", logger="metabase_migration"):
            mapper.build_table_and_field_mappings()

        assert "No MetabaseClient set" in caplog.text
        assert mapper.table_map == {}

    def test_maps_matching_tables_and_fields(self, caplog):
        manifest = make_manifest({1: "Sales"}, self.source_metadata())
        client = Mock()
        client.get_database_metadata.return_value = self.target_metadata()
        mapper = IDMapper(manifest, DatabaseMap(by_id={"1": 10}), client)

        with caplog.at_level("WARNING", logger="metabase_migration"):
            mapper.build_table_and_field_mappings()

        assert mapper.resolve_table_id(1, 100) == 1000
        assert mapper.resolve_field_id(1, 200) == 2000
        # Unmatched table and field are skipped, the table with a warning
        assert mapper.resolve_table_id(1, 101) is None
        assert mapper.resolve_field_id(1, 201) is None
        assert "Table 'missing_table' (ID: 101) not found in target database 10" in caplog.text

    def test_unmapped_database_is_skipped(self):
        manifest = make_manifest({1: "Sales"}, self.source_metadata())
        client = Mock()
        mapper = IDMapper(manifest, DatabaseMap(by_id={}), client)

        mapper.build_table_and_field_mappings()

        client.get_database_metadata.assert_not_called()

    def test_database_without_source_metadata_is_skipped(self):
        manifest = make_manifest({1: "Sales"}, {})
        client = Mock()
        mapper = IDMapper(manifest, DatabaseMap(by_id={"1": 10}), client)

        mapper.build_table_and_field_mappings()

        client.get_database_metadata.assert_not_called()

    def test_empty_source_table_list_is_skipped(self):
        manifest = make_manifest({1: "Sales"}, {1: {"tables": []}})
        client = Mock()
        mapper = IDMapper(manifest, DatabaseMap(by_id={"1": 10}), client)

        mapper.build_table_and_field_mappings()

        client.get_database_metadata.assert_not_called()

    def test_target_metadata_fetch_failure_is_logged(self, caplog):
        manifest = make_manifest({1: "Sales"}, self.source_metadata())
        client = Mock()
        client.get_database_metadata.side_effect = MetabaseAPIError("denied")
        mapper = IDMapper(manifest, DatabaseMap(by_id={"1": 10}), client)

        with caplog.at_level("WARNING", logger="metabase_migration"):
            mapper.build_table_and_field_mappings()

        assert "Failed to fetch metadata for target database 10" in caplog.text
        assert mapper.table_map == {}

    def test_target_metadata_is_fetched_once_per_database(self):
        """Two source databases mapped to the same target reuse the cached metadata."""
        manifest = make_manifest(
            {1: "Sales", 2: "Sales Copy"},
            {
                1: {"tables": [{"id": 100, "name": "orders", "fields": []}]},
                2: {"tables": [{"id": 300, "name": "orders", "fields": []}]},
            },
        )
        client = Mock()
        client.get_database_metadata.return_value = self.target_metadata()
        mapper = IDMapper(manifest, DatabaseMap(by_id={"1": 10, "2": 10}), client)

        mapper.build_table_and_field_mappings()

        assert client.get_database_metadata.call_count == 1
        assert mapper.resolve_table_id(1, 100) == 1000
        assert mapper.resolve_table_id(2, 300) == 1000

    def test_target_table_without_fields_key(self):
        manifest = make_manifest(
            {1: "Sales"},
            {1: {"tables": [{"id": 100, "name": "orders", "fields": [{"id": 200, "name": "x"}]}]}},
        )
        client = Mock()
        client.get_database_metadata.return_value = {"tables": [{"id": 1000, "name": "orders"}]}
        mapper = IDMapper(manifest, DatabaseMap(by_id={"1": 10}), client)

        mapper.build_table_and_field_mappings()

        assert mapper.resolve_table_id(1, 100) == 1000
        assert mapper.resolve_field_id(1, 200) is None

    def test_source_table_without_fields_key(self):
        manifest = make_manifest({1: "Sales"}, {1: {"tables": [{"id": 100, "name": "orders"}]}})
        client = Mock()
        client.get_database_metadata.return_value = self.target_metadata()
        mapper = IDMapper(manifest, DatabaseMap(by_id={"1": 10}), client)

        mapper.build_table_and_field_mappings()

        assert mapper.resolve_table_id(1, 100) == 1000
        assert mapper.field_map == {}
