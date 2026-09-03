"""Helpers for extracting card dependencies from Metabase query structures."""

from collections.abc import Iterator
from typing import Any


def iter_template_tags(
    template_tags: Any,
) -> Iterator[tuple[str, dict[str, Any]]]:
    """Yield (name, tag_data) pairs from dict or list template-tags.

    Metabase historically stores template-tags as a dict keyed by name.
    From v0.63 onward (metabase#77133) they are serialized as a list of
    tag objects, each with a ``name`` field. Both shapes are accepted.
    """
    if isinstance(template_tags, dict):
        for tag_name, tag_data in template_tags.items():
            if isinstance(tag_data, dict):
                yield str(tag_name), tag_data
        return

    if isinstance(template_tags, list):
        for tag_data in template_tags:
            if isinstance(tag_data, dict):
                yield str(tag_data.get("name") or ""), tag_data


def extract_parameter_card_dependencies(card_data: dict[str, Any]) -> set[int]:
    """Extract card IDs referenced by parameter value sources.

    Native SQL and other cards can source filter dropdown values from another
    saved question/model via parameters[].values_source_config.card_id.
    """
    dependencies: set[int] = set()

    for param in card_data.get("parameters") or []:
        if not isinstance(param, dict):
            continue

        config = param.get("values_source_config")
        if not isinstance(config, dict):
            continue

        card_id = config.get("card_id")
        if isinstance(card_id, int):
            dependencies.add(card_id)

    return dependencies


def extract_metric_deps_from_clause(clause: Any, dependencies: set[int]) -> None:
    """Recursively extracts card IDs from pMBQL metric references in a clause.

    In v57 MBQL, saved metrics are referenced in aggregation clauses as:
      ["metric", {"lib/uuid": "...", "effective-type": "..."}, <card_id>]
    where the third element is the integer ID of a card of type "metric".
    Standard metric tuples have exactly 3 elements; elements beyond index 2
    are intentionally not recursed into.

    Args:
        clause: A single aggregation clause (list) or nested structure.
        dependencies: Set to add found card IDs to.
    """
    if not isinstance(clause, list) or len(clause) == 0:
        return
    if clause[0] == "metric" and len(clause) >= 3 and isinstance(clause[2], int):
        dependencies.add(clause[2])
    else:
        for item in clause:
            if isinstance(item, list):
                extract_metric_deps_from_clause(item, dependencies)
