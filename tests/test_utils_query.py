"""
Unit tests for lib/utils/query.py

Tests for extract_metric_deps_from_clause.
"""

from lib.utils.query import extract_metric_deps_from_clause


class TestExtractMetricDepsFromClause:
    """Tests for extract_metric_deps_from_clause from lib.utils.query."""

    def test_simple_metric_reference(self):
        """A well-formed metric clause extracts the integer ID."""
        deps = set()
        extract_metric_deps_from_clause(["metric", {"lib/uuid": "abc"}, 70], deps)
        assert deps == {70}

    def test_nested_metrics_in_expression(self):
        """Metric IDs in nested clauses are all collected."""
        deps = set()
        extract_metric_deps_from_clause(
            ["/", {}, ["metric", {}, 70], ["metric", {}, 71]], deps
        )
        assert deps == {70, 71}

    def test_empty_list(self):
        """An empty list does not crash and yields no dependencies."""
        deps = set()
        extract_metric_deps_from_clause([], deps)
        assert deps == set()

    def test_non_list_input_string(self):
        """A string input does not crash and yields no dependencies."""
        deps = set()
        extract_metric_deps_from_clause("not_a_list", deps)
        assert deps == set()

    def test_non_list_input_int(self):
        """An integer input does not crash and yields no dependencies."""
        deps = set()
        extract_metric_deps_from_clause(42, deps)
        assert deps == set()

    def test_non_list_input_none(self):
        """None input does not crash and yields no dependencies."""
        deps = set()
        extract_metric_deps_from_clause(None, deps)
        assert deps == set()

    def test_metric_with_non_int_third_element(self):
        """A metric clause whose third element is not an int is ignored."""
        deps = set()
        extract_metric_deps_from_clause(["metric", {}, "not-an-int"], deps)
        assert deps == set()

    def test_metric_with_fewer_than_three_elements(self):
        """A metric clause with fewer than 3 elements is ignored."""
        deps = set()
        extract_metric_deps_from_clause(["metric", {}], deps)
        assert deps == set()

    def test_deeply_nested_metric(self):
        """A metric clause nested several levels deep is still found."""
        deps = set()
        extract_metric_deps_from_clause(
            ["+", {}, ["/", {}, ["metric", {}, 42]]], deps
        )
        assert deps == {42}

    def test_metric_clause_does_not_recurse_into_extra_elements(self):
        # Standard metric tuples are ["metric", {metadata}, card_id] — exactly 3 elements.
        # If a hypothetical 4th+ element contained nested structures, they are NOT recursed
        # into (the if-branch returns without recursing). This is intentional.
        deps = set()
        extract_metric_deps_from_clause(
            ["metric", {"lib/uuid": "abc"}, 70, ["metric", {}, 99]],
            deps,
        )
        assert deps == {70}  # only the direct card_id at index 2; 99 is intentionally ignored
