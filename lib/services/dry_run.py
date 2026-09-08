"""Builds a target-aware plan for an import, without writing anything.

The plan resolves every exported object against the target instance, so each one
is labelled the way the real run would handle it under the configured conflict
strategy. Objects the run would create are folded into the simulated target state,
which is what makes a second object with the same name show up as a conflict.
"""

import logging
from typing import Any, Literal

from lib.client import MetabaseClient
from lib.constants import (
    CARD_TYPE_TO_MODEL,
    CONFLICT_OVERWRITE,
    CONFLICT_RENAME,
    MODEL_TYPE_CARD,
    MODEL_TYPE_DASHBOARD,
    MODEL_TYPE_DATASET,
    ROOT_COLLECTION,
)
from lib.handlers.collection import flatten_collection_tree
from lib.models import Card, Dashboard, ImportAction, ImportPlan, Manifest

logger = logging.getLogger("metabase_migration")

# Models a card may match when the export does not record its type.
_ANY_CARD_MODEL = frozenset({MODEL_TYPE_CARD, MODEL_TYPE_DATASET, "metric"})

PlanAction = Literal["create", "update", "skip", "rename"]


class DryRunPlanner:
    """Produces an import plan by comparing the export against the target."""

    def __init__(
        self,
        manifest: Manifest,
        client: MetabaseClient,
        conflict_strategy: str,
        include_archived: bool = False,
    ) -> None:
        """Initialize the planner.

        Args:
            manifest: The parsed export manifest.
            client: Client connected to the target instance (read-only usage).
            conflict_strategy: The configured conflict strategy.
            include_archived: Whether archived objects are part of the import.
        """
        self.manifest = manifest
        self.client = client
        self.conflict_strategy = conflict_strategy
        self.include_archived = include_archived

        # Source collection ID -> target collection ID. Collections the run would
        # create get a negative placeholder: they hold nothing in the target yet.
        self._collection_targets: dict[int, int] = {}
        self._next_pending_id = -1

        # Simulated target state, keyed the same way the importer caches it.
        self._items: dict[int | str, list[dict[str, Any]]] = {}

    def build_plan(self) -> ImportPlan:
        """Builds the full plan.

        Returns:
            The plan, with one action per object that would be imported.
        """
        target_tree = flatten_collection_tree(self.client.get_collections_tree())

        actions: list[ImportAction] = []
        actions.extend(self._plan_collections(target_tree))
        actions.extend(self._plan_cards())
        actions.extend(self._plan_dashboards())
        return ImportPlan(actions=actions)

    # --- Collections ---------------------------------------------------------

    def _plan_collections(self, target_tree: list[dict[str, Any]]) -> list[ImportAction]:
        """Plans the collection tree, recording where each source collection lands.

        Args:
            target_tree: The flattened target collection tree. Collections the run
                would create are appended so their children resolve against them.

        Returns:
            One action per source collection.
        """
        actions = []
        for collection in sorted(self.manifest.collections, key=lambda c: c.path):
            parent_target_id = self._resolve_collection(collection.parent_id)
            existing = self._find_collection(target_tree, collection.name, parent_target_id)

            if existing is None:
                action: PlanAction = "create"
                target_id = self._reserve_pending_id()
                target_tree.append(
                    {"id": target_id, "name": collection.name, "parent_id": parent_target_id}
                )
            else:
                # The rename strategy reuses the existing collection as a container.
                action = "update" if self.conflict_strategy == CONFLICT_OVERWRITE else "skip"
                target_id = existing["id"]

            self._collection_targets[collection.id] = target_id
            actions.append(
                ImportAction(
                    entity_type="collection",
                    action=action,
                    source_id=collection.id,
                    name=collection.name,
                    target_path=self._collection_path(collection.parent_id),
                )
            )
        return actions

    @staticmethod
    def _find_collection(
        target_tree: list[dict[str, Any]], name: str, parent_id: int | None
    ) -> dict[str, Any] | None:
        """Finds a target collection by name and parent, as the importer does."""
        for candidate in target_tree:
            if candidate["name"] == name and candidate.get("parent_id") == parent_id:
                return candidate
        return None

    def _reserve_pending_id(self) -> int:
        """Returns a placeholder ID standing for a collection that does not exist yet."""
        pending_id = self._next_pending_id
        self._next_pending_id -= 1
        return pending_id

    def _resolve_collection(self, source_collection_id: int | None) -> int | None:
        """Resolves a source collection ID to its planned target ID."""
        if source_collection_id is None:
            return None
        return self._collection_targets.get(source_collection_id)

    # --- Cards and dashboards ------------------------------------------------

    def _plan_cards(self) -> list[ImportAction]:
        """Plans every card that would be imported."""
        actions = []
        for card in sorted(self.manifest.cards, key=lambda c: c.file_path):
            if card.archived and not self.include_archived:
                continue
            actions.append(self._plan_item("card", card, self._card_models(card)))
        return actions

    def _plan_dashboards(self) -> list[ImportAction]:
        """Plans every dashboard that would be imported."""
        actions = []
        for dashboard in sorted(self.manifest.dashboards, key=lambda d: d.file_path):
            if dashboard.archived and not self.include_archived:
                continue
            actions.append(self._plan_item("dashboard", dashboard, {MODEL_TYPE_DASHBOARD}))
        return actions

    def _plan_item(
        self,
        entity_type: Literal["card", "dashboard"],
        item: Card | Dashboard,
        models: set[str] | frozenset[str],
    ) -> ImportAction:
        """Plans a single card or dashboard against the simulated target state.

        Args:
            entity_type: The entity type being planned.
            item: The manifest entry.
            models: The target models this object may conflict with.

        Returns:
            The planned action.
        """
        target_collection_id = self._resolve_collection(item.collection_id)
        items = self._items_in(target_collection_id)
        existing = self._find_item(items, item.name, models)

        name = item.name
        if existing is None:
            action: PlanAction = "create"
        elif self.conflict_strategy == CONFLICT_OVERWRITE:
            action = "update"
        elif self.conflict_strategy == CONFLICT_RENAME:
            action = "rename"
            name = self._unique_name(items, item.name, models)
        else:
            action = "skip"

        if action in ("create", "rename"):
            # Mirror the importer's cache update so later objects see this one.
            items.append({"id": None, "name": name, "model": min(models)})

        return ImportAction(
            entity_type=entity_type,
            action=action,
            source_id=item.id,
            name=name,
            target_path=self._collection_path(item.collection_id),
        )

    @staticmethod
    def _card_models(card: Card) -> set[str] | frozenset[str]:
        """Returns the target models a card may conflict with.

        Exports predating the ``card_type`` field do not record the type, and the
        importer then matches any card-like model.
        """
        if card.card_type:
            return {CARD_TYPE_TO_MODEL.get(card.card_type, MODEL_TYPE_CARD)}
        if card.dataset:
            return {MODEL_TYPE_DATASET}
        return _ANY_CARD_MODEL

    @staticmethod
    def _find_item(
        items: list[dict[str, Any]], name: str, models: set[str] | frozenset[str]
    ) -> dict[str, Any] | None:
        """Finds an item by name among the given target models."""
        for candidate in items:
            if candidate.get("model") in models and candidate.get("name") == name:
                return candidate
        return None

    def _unique_name(
        self, items: list[dict[str, Any]], base_name: str, models: set[str] | frozenset[str]
    ) -> str:
        """Generates the name the rename strategy would pick."""
        counter = 1
        while True:
            candidate = f"{base_name} ({counter})"
            if self._find_item(items, candidate, models) is None:
                return candidate
            counter += 1

    def _items_in(self, target_collection_id: int | None) -> list[dict[str, Any]]:
        """Returns the simulated contents of a target collection.

        Collections the run would create are empty by definition and are never
        fetched from the target.
        """
        cache_key: int | str = (
            target_collection_id if target_collection_id is not None else ROOT_COLLECTION
        )
        if cache_key in self._items:
            return self._items[cache_key]

        if isinstance(cache_key, int) and cache_key < 0:
            self._items[cache_key] = []
            return self._items[cache_key]

        try:
            response = self.client.get_collection_items(cache_key)
            self._items[cache_key] = list(response.get("data", []))
        except Exception as e:
            logger.warning(
                f"Could not read items of target collection {cache_key}: {e}. "
                "Objects in it are reported as created."
            )
            self._items[cache_key] = []
        return self._items[cache_key]

    # --- Presentation --------------------------------------------------------

    def _collection_path(self, source_collection_id: int | None) -> str:
        """Returns a readable location for an object's collection."""
        if source_collection_id is None:
            return ROOT_COLLECTION
        for collection in self.manifest.collections:
            if collection.id == source_collection_id:
                return collection.path or collection.name
        return f"collection {source_collection_id}"


def format_plan(plan: ImportPlan, conflict_strategy: str) -> list[str]:
    """Formats a plan as log lines.

    Args:
        plan: The plan to format.
        conflict_strategy: The strategy the plan was built with.

    Returns:
        A list of log lines.
    """
    lines = ["", "--- Import Plan ---", f"Conflict Strategy: {conflict_strategy.upper()}"]

    for entity_type, heading in (
        ("collection", "Collections"),
        ("card", "Cards"),
        ("dashboard", "Dashboards"),
    ):
        actions = [a for a in plan.actions if a.entity_type == entity_type]
        if not actions:
            continue
        lines.append("")
        lines.append(f"{heading}:")
        lines.extend(
            f"  [{a.action.upper()}] {entity_type.capitalize()} '{a.name}' in '{a.target_path}'"
            for a in actions
        )

    lines.append("")
    lines.append(summarize_plan(plan))
    return lines


def summarize_plan(plan: ImportPlan) -> str:
    """Returns a one-line count of the planned actions."""
    counts: dict[str, int] = {}
    for action in plan.actions:
        counts[action.action] = counts.get(action.action, 0) + 1
    if not counts:
        return "Nothing to import."
    breakdown = ", ".join(f"{count} to {name}" for name, count in sorted(counts.items()))
    return f"Planned: {breakdown}."
