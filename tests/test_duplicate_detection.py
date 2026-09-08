"""
Unit tests for lib/services/duplicate_check.py

Objects sharing a name inside the same collection resolve to the same target
object, so one of them is silently dropped on import. These tests cover the
pre-flight detection that surfaces the ambiguity before anything is written.
"""

import pytest

from lib.models_core import Card, Collection, Dashboard, Manifest, ManifestMeta
from lib.services.duplicate_check import DuplicateGroup, find_duplicate_targets


def make_manifest(collections=None, cards=None, dashboards=None):
    """Builds a minimal manifest around the given entities."""
    return Manifest(
        meta=ManifestMeta(
            source_url="http://src",
            export_timestamp="2026-01-01T00:00:00Z",
            tool_version="test",
            cli_args={},
        ),
        collections=collections or [],
        cards=cards or [],
        dashboards=dashboards or [],
    )


def card(card_id, name, collection_id=10, **kwargs):
    return Card(id=card_id, name=name, collection_id=collection_id, **kwargs)


def dashboard(dash_id, name, collection_id=10, **kwargs):
    return Dashboard(id=dash_id, name=name, collection_id=collection_id, **kwargs)


def collection(coll_id, name, parent_id=None):
    return Collection(id=coll_id, name=name, slug=name.lower(), parent_id=parent_id)


class TestNoDuplicates:
    """Exports without ambiguity must pass cleanly."""

    def test_empty_manifest(self):
        assert find_duplicate_targets(make_manifest()) == []

    def test_distinct_names(self):
        manifest = make_manifest(
            cards=[card(1, "Alpha"), card(2, "Beta")],
            dashboards=[dashboard(3, "Alpha")],
        )
        assert find_duplicate_targets(manifest) == []

    def test_same_name_in_different_collections(self):
        manifest = make_manifest(
            dashboards=[dashboard(1, "Sales", collection_id=10), dashboard(2, "Sales", 11)]
        )
        assert find_duplicate_targets(manifest) == []

    def test_card_and_dashboard_sharing_a_name(self):
        """Cards and dashboards live in separate namespaces on lookup."""
        manifest = make_manifest(cards=[card(1, "Sales")], dashboards=[dashboard(2, "Sales")])
        assert find_duplicate_targets(manifest) == []

    def test_question_and_model_sharing_a_name(self):
        """A question and a model are matched by distinct target models."""
        manifest = make_manifest(
            cards=[
                card(1, "Sales", card_type="question"),
                card(2, "Sales", card_type="model", dataset=True),
            ]
        )
        assert find_duplicate_targets(manifest) == []


class TestDuplicateDashboards:
    """The case reported in issue #80."""

    def test_detects_duplicate_dashboards(self):
        manifest = make_manifest(
            dashboards=[
                dashboard(233, "Dashboard Assistenza"),
                dashboard(234, "Dashboard Assistenza"),
            ]
        )

        groups = find_duplicate_targets(manifest)

        assert len(groups) == 1
        group = groups[0]
        assert group.entity_type == "dashboard"
        assert group.name == "Dashboard Assistenza"
        assert group.collection_id == 10
        assert group.source_ids == (233, 234)

    def test_source_ids_are_sorted(self):
        manifest = make_manifest(
            dashboards=[dashboard(9, "D"), dashboard(2, "D"), dashboard(5, "D")]
        )

        assert find_duplicate_targets(manifest)[0].source_ids == (2, 5, 9)

    def test_duplicates_in_root_collection(self):
        manifest = make_manifest(
            dashboards=[dashboard(1, "D", collection_id=None), dashboard(2, "D", None)]
        )

        groups = find_duplicate_targets(manifest)

        assert len(groups) == 1
        assert groups[0].collection_id is None


class TestDuplicateCards:
    """Cards collide on name, collection and target model."""

    def test_detects_duplicate_questions(self):
        manifest = make_manifest(
            cards=[
                card(1, "Revenue", card_type="question"),
                card(2, "Revenue", card_type="question"),
            ]
        )

        groups = find_duplicate_targets(manifest)

        assert [(g.entity_type, g.source_ids) for g in groups] == [("card", (1, 2))]

    def test_detects_duplicate_models(self):
        manifest = make_manifest(
            cards=[card(1, "Base", dataset=True), card(2, "Base", dataset=True)]
        )

        assert len(find_duplicate_targets(manifest)) == 1

    def test_legacy_export_without_card_type(self):
        """Manifests predating the card_type field still group by name and model."""
        manifest = make_manifest(cards=[card(1, "Revenue"), card(2, "Revenue")])

        assert len(find_duplicate_targets(manifest)) == 1


class TestDuplicateCollections:
    """Sibling collections with one name merge into a single target collection."""

    def test_detects_duplicate_sibling_collections(self):
        manifest = make_manifest(
            collections=[collection(1, "Reports", parent_id=5), collection(2, "Reports", 5)]
        )

        groups = find_duplicate_targets(manifest)

        assert len(groups) == 1
        assert groups[0].entity_type == "collection"
        assert groups[0].collection_id == 5

    def test_same_name_under_different_parents(self):
        manifest = make_manifest(
            collections=[collection(1, "Reports", parent_id=5), collection(2, "Reports", 6)]
        )

        assert find_duplicate_targets(manifest) == []


class TestArchivedHandling:
    """Archived objects only count when they are part of the import."""

    def test_archived_duplicates_ignored_by_default(self):
        manifest = make_manifest(
            dashboards=[dashboard(1, "D"), dashboard(2, "D", archived=True)],
            cards=[card(3, "C"), card(4, "C", archived=True)],
        )

        assert find_duplicate_targets(manifest) == []

    def test_archived_duplicates_counted_when_included(self):
        manifest = make_manifest(dashboards=[dashboard(1, "D"), dashboard(2, "D", archived=True)])

        assert len(find_duplicate_targets(manifest, include_archived=True)) == 1


class TestReporting:
    """The groups must be describable for the operator."""

    def test_describe_mentions_ids_and_location(self):
        group = DuplicateGroup(
            entity_type="dashboard", name="Sales", collection_id=10, source_ids=(1, 2)
        )

        description = group.describe()

        assert "dashboard" in description
        assert "Sales" in description
        assert "1" in description and "2" in description
        assert "10" in description

    def test_describe_root_collection(self):
        group = DuplicateGroup(
            entity_type="dashboard", name="Sales", collection_id=None, source_ids=(1, 2)
        )

        assert "root" in group.describe().lower()

    def test_groups_are_ordered_by_type_then_name(self):
        manifest = make_manifest(
            collections=[collection(1, "Z", parent_id=5), collection(2, "Z", 5)],
            cards=[card(3, "B"), card(4, "B")],
            dashboards=[dashboard(5, "A"), dashboard(6, "A")],
        )

        assert [g.entity_type for g in find_duplicate_targets(manifest)] == [
            "collection",
            "card",
            "dashboard",
        ]


class TestImportServiceGuard:
    """The importer must refuse to write an ambiguous export by default."""

    @staticmethod
    def _service(tmp_path, manifest, allow_duplicate_names=False):
        from unittest.mock import patch

        from lib.config import ImportConfig
        from lib.services.import_service import ImportService

        config = ImportConfig(
            target_url="https://target.example.com",
            export_dir=str(tmp_path),
            db_map_path=str(tmp_path / "db_map.json"),
            target_session_token="token",  # pragma: allowlist secret
            allow_duplicate_names=allow_duplicate_names,
        )
        with patch("lib.services.import_service.MetabaseClient"):
            service = ImportService(config)
        service.manifest = manifest
        return service

    def test_raises_on_duplicates(self, tmp_path):
        manifest = make_manifest(dashboards=[dashboard(1, "D"), dashboard(2, "D")])
        service = self._service(tmp_path, manifest)

        with pytest.raises(ValueError, match="same target object"):
            service._check_for_duplicate_targets()

    def test_error_names_the_opt_out_flag(self, tmp_path):
        manifest = make_manifest(dashboards=[dashboard(1, "D"), dashboard(2, "D")])
        service = self._service(tmp_path, manifest)

        with pytest.raises(ValueError, match="--allow-duplicate-names"):
            service._check_for_duplicate_targets()

    def test_allows_duplicates_when_opted_in(self, tmp_path, caplog):
        manifest = make_manifest(dashboards=[dashboard(1, "D"), dashboard(2, "D")])
        service = self._service(tmp_path, manifest, allow_duplicate_names=True)

        service._check_for_duplicate_targets()

        assert "D" in caplog.text

    def test_passes_without_duplicates(self, tmp_path):
        manifest = make_manifest(dashboards=[dashboard(1, "A"), dashboard(2, "B")])
        service = self._service(tmp_path, manifest)

        service._check_for_duplicate_targets()


if __name__ == "__main__":
    pytest.main([__file__])
