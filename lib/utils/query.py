from typing import Any


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
