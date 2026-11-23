"""
Unit tests for recognising dashboard questions on re-import (issue #84).

Metabase leaves dashboard questions out of /api/collection/:id/items unless
show_dashboard_questions=true is passed, so every lookup of existing target
objects has to request them.
"""

import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from lib.constants import COLLECTION_ITEMS_LOOKUP_PARAMS
from lib.handlers.base import ImportContext
from lib.handlers.card import CardHandler
from lib.models_core import Card, Collection, Manifest, ManifestMeta
from lib.remapping.id_mapper import IDMapper
from lib.services.dry_run import DryRunPlanner

DASHBOARD_QUESTION = {"id": 77, "name": "Revenue", "model": "card", "dashboard_id": 5}


@pytest.fixture
def client():
    """A target whose listing behaves like Metabase: questions need the parameter."""

    def get_items(collection_id, params=None):
        show = (params or {}).get("show_dashboard_questions") == "true"
        return {"data": [DASHBOARD_QUESTION] if show else []}

    mock = Mock()
    mock.get_collection_items.side_effect = get_items
    mock.get_collections_tree.return_value = [{"id": 10, "name": "Reports", "children": []}]
    return mock


@pytest.fixture
def manifest():
    return Manifest(
        meta=ManifestMeta(
            source_url="https://source.example.com",
            export_timestamp="2026-01-01T00:00:00",
            tool_version="1.0.0",
            cli_args={},
        ),
        databases={},
        collections=[Collection(id=1, name="Reports", slug="reports", path="collections/Reports")],
        cards=[
            Card(
                id=2,
                name="Revenue",
                collection_id=1,
                card_type="question",
                file_path="cards/card_2.json",
            )
        ],
        dashboards=[],
    )


def make_context(client, manifest):
    id_mapper = Mock(spec=IDMapper)
    id_mapper.resolve_collection_id.return_value = 10
    return ImportContext(
        config=Mock(),
        client=client,
        manifest=manifest,
        export_dir=Path("/tmp/export"),
        id_mapper=id_mapper,
        query_remapper=Mock(),
        report=Mock(),
    )


class TestLookupsRequestDashboardQuestions:
    def test_prefetch_finds_dashboard_question(self, client, manifest):
        context = make_context(client, manifest)
        context.prefetch_collection_items()

        assert context.find_existing_card("Revenue", 10, "question") == DASHBOARD_QUESTION

    def test_lazy_card_lookup_finds_dashboard_question(self, client, manifest):
        context = make_context(client, manifest)

        assert context.find_existing_card("Revenue", 10, "question") == DASHBOARD_QUESTION

    def test_lazy_dashboard_lookup_requests_dashboard_questions(self, client, manifest):
        context = make_context(client, manifest)
        context.find_existing_dashboard("Sales", 10)

        client.get_collection_items.assert_called_once_with(10, COLLECTION_ITEMS_LOOKUP_PARAMS)

    def test_dry_run_plans_update_for_dashboard_question(self, client, manifest):
        planner = DryRunPlanner(manifest, client, "overwrite")

        actions = planner.build_plan().actions
        assert [a.action for a in actions if a.entity_type == "card"] == ["update"]


class TestOverwriteKeepsDashboardLink:
    def import_card(self, client, manifest, tmp_path, card_data):
        (tmp_path / "cards").mkdir()
        (tmp_path / "cards" / "card_2.json").write_text(json.dumps(card_data))
        context = make_context(client, manifest)
        context.export_dir = tmp_path
        context.config.conflict_strategy = "overwrite"
        context.id_mapper.resolve_dashboard_id.return_value = None
        context.id_mapper.resolve_card_id.return_value = 77
        context.query_remapper.remap_card_data.side_effect = lambda data, _cards: (data, True)
        client.update_card.return_value = {"id": 77}
        CardHandler(context)._import_single_card(manifest.cards[0])
        return context

    def test_unresolved_parent_is_omitted_and_relink_queued(self, client, manifest, tmp_path):
        """The parent is imported later; sending null would detach the card."""
        context = self.import_card(
            client, manifest, tmp_path, {"name": "Revenue", "dashboard_id": 5, "database_id": 1}
        )

        assert "dashboard_id" not in client.update_card.call_args[0][1]
        context.id_mapper.register_pending_dashboard_question.assert_called_once_with(5, 77)

    def test_regular_card_keeps_explicit_null(self, client, manifest, tmp_path):
        """A card outside any dashboard on the source stays outside one on the target."""
        context = self.import_card(
            client, manifest, tmp_path, {"name": "Revenue", "dashboard_id": None, "database_id": 1}
        )

        assert client.update_card.call_args[0][1]["dashboard_id"] is None
        context.id_mapper.register_pending_dashboard_question.assert_not_called()
