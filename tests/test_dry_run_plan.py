"""
Unit tests for lib/services/dry_run.py

The dry run must reflect the state of the target instance: objects that already
exist have to be reported the way they would actually be handled, according to
the conflict strategy.
"""

from unittest.mock import Mock

import pytest

from lib.models_core import Card, Collection, Dashboard, Manifest, ManifestMeta
from lib.services.dry_run import DryRunPlanner


@pytest.fixture
def target_client():
    """A target instance holding no collections and no items."""
    client = Mock()
    client.get_collections_tree.return_value = []
    client.get_collection_items.return_value = {"data": []}
    return client


def make_manifest(collections=None, cards=None, dashboards=None):
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


def plan_actions(manifest, client, strategy="skip", include_archived=False):
    planner = DryRunPlanner(
        manifest=manifest,
        client=client,
        conflict_strategy=strategy,
        include_archived=include_archived,
    )
    return planner.build_plan().actions


def action_for(actions, name):
    return next(a for a in actions if a.name == name)


class TestEmptyTarget:
    """Everything is created when the target holds nothing."""

    def test_all_created(self, target_client):
        manifest = make_manifest(
            collections=[
                Collection(id=1, name="Reports", slug="reports", path="collections/Reports")
            ],
            cards=[Card(id=2, name="Revenue", collection_id=1)],
            dashboards=[Dashboard(id=3, name="Overview", collection_id=1)],
        )

        actions = plan_actions(manifest, target_client)

        assert [a.action for a in actions] == ["create", "create", "create"]

    def test_target_is_not_written_to(self, target_client):
        manifest = make_manifest(cards=[Card(id=1, name="Revenue")])

        plan_actions(manifest, target_client)

        target_client.create_card.assert_not_called()
        target_client.update_card.assert_not_called()
        target_client.create_collection.assert_not_called()
        target_client.create_dashboard.assert_not_called()


class TestExistingObjects:
    """Objects already present in the target follow the conflict strategy."""

    @staticmethod
    def _client_with_existing_dashboard():
        client = Mock()
        client.get_collections_tree.return_value = []
        client.get_collection_items.return_value = {
            "data": [{"id": 77, "name": "Overview", "model": "dashboard"}]
        }
        return client

    def test_existing_dashboard_is_skipped(self):
        manifest = make_manifest(dashboards=[Dashboard(id=3, name="Overview")])

        actions = plan_actions(manifest, self._client_with_existing_dashboard(), "skip")

        assert [a.action for a in actions] == ["skip"]

    def test_existing_dashboard_is_updated_with_overwrite(self):
        manifest = make_manifest(dashboards=[Dashboard(id=3, name="Overview")])

        actions = plan_actions(manifest, self._client_with_existing_dashboard(), "overwrite")

        assert [a.action for a in actions] == ["update"]

    def test_existing_dashboard_is_renamed_with_rename(self):
        manifest = make_manifest(dashboards=[Dashboard(id=3, name="Overview")])

        actions = plan_actions(manifest, self._client_with_existing_dashboard(), "rename")

        assert actions[0].action == "rename"
        assert actions[0].name == "Overview (1)"

    def test_existing_collection_is_reported_against_target_tree(self, target_client):
        target_client.get_collections_tree.return_value = [
            {"id": 5, "name": "Reports", "children": []}
        ]
        manifest = make_manifest(
            collections=[
                Collection(id=1, name="Reports", slug="reports", path="collections/Reports")
            ]
        )

        actions = plan_actions(manifest, target_client, "overwrite")

        assert [a.action for a in actions] == ["update"]

    def test_card_in_existing_collection_resolves_against_that_collection(self, target_client):
        target_client.get_collections_tree.return_value = [
            {"id": 5, "name": "Reports", "children": []}
        ]
        target_client.get_collection_items.return_value = {
            "data": [{"id": 9, "name": "Revenue", "model": "card"}]
        }
        manifest = make_manifest(
            collections=[
                Collection(id=1, name="Reports", slug="reports", path="collections/Reports")
            ],
            cards=[Card(id=2, name="Revenue", collection_id=1, card_type="question")],
        )

        actions = plan_actions(manifest, target_client, "overwrite")

        target_client.get_collection_items.assert_called_with(5)
        assert action_for(actions, "Revenue").action == "update"

    def test_card_in_new_collection_is_created(self, target_client):
        """A collection that does not exist yet cannot hold any conflicting card."""
        target_client.get_collection_items.return_value = {
            "data": [{"id": 9, "name": "Revenue", "model": "card"}]
        }
        manifest = make_manifest(
            collections=[Collection(id=1, name="New", slug="new", path="collections/New")],
            cards=[Card(id=2, name="Revenue", collection_id=1)],
        )

        actions = plan_actions(manifest, target_client, "overwrite")

        assert action_for(actions, "Revenue").action == "create"


class TestCardModelMatching:
    """Cards only conflict with target objects of the same model."""

    @staticmethod
    def _client_with_model_named(model):
        client = Mock()
        client.get_collections_tree.return_value = []
        client.get_collection_items.return_value = {
            "data": [{"id": 9, "name": "Revenue", "model": model}]
        }
        return client

    def test_question_matches_card_model(self):
        manifest = make_manifest(cards=[Card(id=1, name="Revenue", card_type="question")])

        actions = plan_actions(manifest, self._client_with_model_named("card"))

        assert actions[0].action == "skip"

    def test_question_does_not_match_dataset_model(self):
        manifest = make_manifest(cards=[Card(id=1, name="Revenue", card_type="question")])

        actions = plan_actions(manifest, self._client_with_model_named("dataset"))

        assert actions[0].action == "create"

    def test_legacy_model_without_card_type_matches_dataset(self):
        """Exports predating card_type only record the model flag."""
        manifest = make_manifest(cards=[Card(id=1, name="Revenue", dataset=True)])

        actions = plan_actions(manifest, self._client_with_model_named("dataset"))

        assert actions[0].action == "skip"

    def test_model_matches_dataset(self):
        manifest = make_manifest(
            cards=[Card(id=1, name="Revenue", card_type="model", dataset=True)]
        )

        actions = plan_actions(manifest, self._client_with_model_named("dataset"))

        assert actions[0].action == "skip"


class TestObjectsCreatedEarlierInTheRun:
    """The plan accounts for objects the same run would have just created."""

    def test_second_object_with_the_same_name_conflicts(self, target_client):
        manifest = make_manifest(
            dashboards=[Dashboard(id=1, name="Overview"), Dashboard(id=2, name="Overview")]
        )

        actions = plan_actions(manifest, target_client, "skip")

        assert [a.action for a in actions] == ["create", "skip"]


class TestUnreadableCollection:
    """A collection the target refuses to list must not abort the plan."""

    def test_items_that_cannot_be_read_are_reported_as_create(self, target_client):
        target_client.get_collection_items.side_effect = Exception("403 Forbidden")
        manifest = make_manifest(dashboards=[Dashboard(id=1, name="Overview")])

        actions = plan_actions(manifest, target_client)

        assert [a.action for a in actions] == ["create"]


class TestRenameNumbering:
    """The rename strategy picks the first free suffix, as the importer does."""

    def test_skips_names_already_taken(self):
        client = Mock()
        client.get_collections_tree.return_value = []
        client.get_collection_items.return_value = {
            "data": [
                {"id": 1, "name": "Overview", "model": "dashboard"},
                {"id": 2, "name": "Overview (1)", "model": "dashboard"},
                {"id": 3, "name": "Overview (2)", "model": "dashboard"},
            ]
        }
        manifest = make_manifest(dashboards=[Dashboard(id=9, name="Overview")])

        actions = plan_actions(manifest, client, "rename")

        assert actions[0].name == "Overview (3)"


class TestArchivedFiltering:
    """Archived objects only appear when they are part of the import."""

    def test_archived_excluded_by_default(self, target_client):
        manifest = make_manifest(
            cards=[Card(id=1, name="Old", archived=True)],
            dashboards=[Dashboard(id=2, name="Old Dash", archived=True)],
        )

        assert plan_actions(manifest, target_client) == []

    def test_archived_included_when_requested(self, target_client):
        manifest = make_manifest(cards=[Card(id=1, name="Old", archived=True)])

        assert len(plan_actions(manifest, target_client, include_archived=True)) == 1


class TestActionContent:
    """Actions carry enough context to be read as a plan."""

    def test_action_fields(self, target_client):
        manifest = make_manifest(
            collections=[
                Collection(id=1, name="Reports", slug="reports", path="collections/Reports")
            ],
            cards=[Card(id=2, name="Revenue", collection_id=1)],
        )

        actions = plan_actions(manifest, target_client)
        card_action = action_for(actions, "Revenue")

        assert card_action.entity_type == "card"
        assert card_action.source_id == 2
        assert "Reports" in card_action.target_path

    def test_root_level_object_path(self, target_client):
        manifest = make_manifest(dashboards=[Dashboard(id=1, name="Overview")])

        assert plan_actions(manifest, target_client)[0].target_path == "root"


class TestFormatPlan:
    """The rendered plan must state the real action for every object."""

    def test_labels_reflect_actions(self, target_client):
        from lib.services.dry_run import format_plan

        manifest = make_manifest(
            dashboards=[Dashboard(id=1, name="Overview"), Dashboard(id=2, name="Overview")]
        )
        planner = DryRunPlanner(manifest, target_client, "skip")

        text = "\n".join(format_plan(planner.build_plan(), "skip"))

        assert "[CREATE] Dashboard 'Overview'" in text
        assert "[SKIP] Dashboard 'Overview'" in text
        assert "Conflict Strategy: SKIP" in text

    def test_summary_counts_actions(self, target_client):
        from lib.services.dry_run import summarize_plan

        manifest = make_manifest(dashboards=[Dashboard(id=1, name="A"), Dashboard(id=2, name="A")])
        plan = DryRunPlanner(manifest, target_client, "skip").build_plan()

        assert summarize_plan(plan) == "Planned: 1 to create, 1 to skip."


class TestImportServiceDryRun:
    """The service-level dry run consults the target and writes nothing."""

    @staticmethod
    def _run(tmp_path, existing_items, strategy="skip"):
        import json
        from unittest.mock import patch

        from lib.config import ImportConfig
        from lib.services.import_service import ImportService

        (tmp_path / "manifest.json").write_text(
            json.dumps(
                {
                    "meta": {
                        "source_url": "http://src",
                        "export_timestamp": "2026-01-01T00:00:00Z",
                        "tool_version": "test",
                        "cli_args": {},
                    },
                    "databases": {"1": "Sample"},
                    "collections": [],
                    "cards": [],
                    "dashboards": [
                        {"id": 3, "name": "Overview", "collection_id": None, "file_path": "d.json"}
                    ],
                }
            )
        )
        (tmp_path / "db_map.json").write_text(json.dumps({"by_id": {"1": 10}}))

        config = ImportConfig(
            target_url="https://target.example.com",
            export_dir=str(tmp_path),
            db_map_path=str(tmp_path / "db_map.json"),
            target_session_token="token",  # pragma: allowlist secret
            conflict_strategy=strategy,
            dry_run=True,
        )
        with patch("lib.services.import_service.MetabaseClient") as client_class:
            client = client_class.return_value
            client.get_databases.return_value = [{"id": 10, "name": "Target"}]
            client.get_collections_tree.return_value = []
            client.get_collection_items.return_value = {"data": existing_items}
            service = ImportService(config)
            service.run_import()
        return service, client

    def test_existing_dashboard_reported_as_skip(self, tmp_path):
        service, _ = self._run(
            tmp_path, [{"id": 7, "name": "Overview", "model": "dashboard"}], "skip"
        )

        assert [a.action for a in service.plan.actions] == ["skip"]

    def test_existing_dashboard_reported_as_update_with_overwrite(self, tmp_path):
        service, _ = self._run(
            tmp_path, [{"id": 7, "name": "Overview", "model": "dashboard"}], "overwrite"
        )

        assert [a.action for a in service.plan.actions] == ["update"]

    def test_missing_dashboard_reported_as_create(self, tmp_path):
        service, _ = self._run(tmp_path, [])

        assert [a.action for a in service.plan.actions] == ["create"]

    def test_nothing_is_written(self, tmp_path):
        _, client = self._run(tmp_path, [{"id": 7, "name": "Overview", "model": "dashboard"}])

        client.create_dashboard.assert_not_called()
        client.update_dashboard.assert_not_called()
        client.create_collection.assert_not_called()
        client.create_card.assert_not_called()


if __name__ == "__main__":
    pytest.main([__file__])
