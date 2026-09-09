"""Pre-flight detection of export objects that collapse into one target object.

The importer identifies target objects by name within a collection (and, for
cards, by model — a card, dataset or metric), so two exported objects sharing
that identity resolve to the same target: one of them is overwritten or
skipped, and which one survives depends on processing order. This module
surfaces the ambiguity from the manifest alone, before anything is written.
"""

import dataclasses

from lib.constants import CARD_TYPE_TO_MODEL, MODEL_TYPE_CARD, MODEL_TYPE_DATASET
from lib.models import Card, Manifest

# Order used when reporting groups, mirroring the order entities are imported in.
_ENTITY_ORDER = {"collection": 0, "card": 1, "dashboard": 2}


@dataclasses.dataclass(frozen=True)
class DuplicateGroup:
    """A set of exported objects that resolve to a single target object."""

    entity_type: str
    name: str
    collection_id: int | None
    source_ids: tuple[int, ...]

    def describe(self) -> str:
        """Returns a single-line, operator-facing description of the collision."""
        location = (
            "the root collection"
            if self.collection_id is None
            else (f"collection {self.collection_id}")
        )
        ids = ", ".join(str(source_id) for source_id in self.source_ids)
        return (
            f"{len(self.source_ids)} {self.entity_type}s named '{self.name}' in "
            f"{location} (source IDs: {ids})"
        )


def card_target_model(card: Card) -> str:
    """Returns the Metabase model a card is matched against in the target.

    Args:
        card: The manifest card entry.

    Returns:
        The model name used for conflict lookup ("card", "dataset" or "metric").
    """
    if card.card_type:
        return CARD_TYPE_TO_MODEL.get(card.card_type, MODEL_TYPE_CARD)
    # Exports predating the card_type field only record whether a card is a model.
    return MODEL_TYPE_DATASET if card.dataset else MODEL_TYPE_CARD


def find_duplicate_targets(
    manifest: Manifest, include_archived: bool = False
) -> list[DuplicateGroup]:
    """Finds exported objects that share a target identity.

    Args:
        manifest: The parsed export manifest.
        include_archived: Whether archived objects are part of the import.

    Returns:
        Duplicate groups ordered by entity type, then name.
    """
    groups: list[DuplicateGroup] = []

    groups.extend(
        _group_by_identity(
            # Collections are matched by name and parent, so the parent stands in
            # for the containing collection.
            "collection",
            [(c.parent_id, c.name, "collection", c.id) for c in manifest.collections],
        )
    )
    groups.extend(
        _group_by_identity(
            "card",
            [
                (c.collection_id, c.name, card_target_model(c), c.id)
                for c in manifest.cards
                if include_archived or not c.archived
            ],
        )
    )
    groups.extend(
        _group_by_identity(
            "dashboard",
            [
                (d.collection_id, d.name, "dashboard", d.id)
                for d in manifest.dashboards
                if include_archived or not d.archived
            ],
        )
    )

    return sorted(groups, key=lambda g: (_ENTITY_ORDER[g.entity_type], g.name))


def _group_by_identity(
    entity_type: str,
    entries: list[tuple[int | None, str, str, int]],
) -> list[DuplicateGroup]:
    """Groups entries that share a (collection, name, model) identity.

    Args:
        entity_type: The entity type being grouped.
        entries: Tuples of (collection_id, name, target_model, source_id).

    Returns:
        The groups holding more than one source object.
    """
    by_identity: dict[tuple[int | None, str, str], list[int]] = {}
    for collection_id, name, target_model, source_id in entries:
        by_identity.setdefault((collection_id, name, target_model), []).append(source_id)

    return [
        DuplicateGroup(
            entity_type=entity_type,
            name=name,
            collection_id=collection_id,
            source_ids=tuple(sorted(source_ids)),
        )
        for (collection_id, name, _model), source_ids in by_identity.items()
        if len(source_ids) > 1
    ]


def format_duplicate_report(groups: list[DuplicateGroup]) -> list[str]:
    """Formats duplicate groups as log lines explaining the consequence.

    Args:
        groups: The duplicate groups to report.

    Returns:
        A list of log lines.
    """
    lines = [
        "The export contains objects that resolve to the same target object.",
        "Only one of each group would reach the target; the others would be",
        "skipped or overwritten, depending on processing order.",
        "",
    ]
    lines.extend(f"  - {group.describe()}" for group in groups)
    return lines
