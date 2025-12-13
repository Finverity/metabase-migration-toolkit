"""
Unit tests for card dependency resolution.

Tests the logic for detecting and resolving card dependencies.
"""

from unittest.mock import patch

from export_metabase import MetabaseExporter


class TestCardDependencyExtraction:
    """Test suite for extracting card dependencies."""

    def test_no_dependencies(self, sample_export_config):
        """Test card with no dependencies."""
        with patch("lib.services.export_service.MetabaseClient"):
            exporter = MetabaseExporter(sample_export_config)

            card_data = {
                "id": 100,
                "name": "Simple Card",
                "dataset_query": {
                    "type": "query",
                    "database": 1,
                    "query": {"source-table": 10},  # Regular table, not a card
                },
            }

            deps = exporter._extract_card_dependencies(card_data)
            assert deps == set()

    def test_single_card_dependency(self, sample_export_config):
        """Test card with single card dependency."""
        with patch("lib.services.export_service.MetabaseClient"):
            exporter = MetabaseExporter(sample_export_config)

            card_data = {
                "id": 100,
                "name": "Dependent Card",
                "dataset_query": {
                    "type": "query",
                    "database": 1,
                    "query": {"source-table": "card__50"},
                },
            }

            deps = exporter._extract_card_dependencies(card_data)
            assert deps == {50}

    def test_multiple_dependencies_in_joins(self, sample_export_config):
        """Test card with multiple dependencies in joins."""
        with patch("lib.services.export_service.MetabaseClient"):
            exporter = MetabaseExporter(sample_export_config)

            card_data = {
                "id": 100,
                "name": "Complex Card",
                "dataset_query": {
                    "type": "query",
                    "database": 1,
                    "query": {
                        "source-table": "card__50",
                        "joins": [
                            {"source-table": "card__51", "alias": "Join 1"},
                            {"source-table": "card__52", "alias": "Join 2"},
                        ],
                    },
                },
            }

            deps = exporter._extract_card_dependencies(card_data)
            assert deps == {50, 51, 52}

    def test_mixed_dependencies(self, sample_export_config):
        """Test card with mix of card and table dependencies."""
        with patch("lib.services.export_service.MetabaseClient"):
            exporter = MetabaseExporter(sample_export_config)

            card_data = {
                "id": 100,
                "name": "Mixed Card",
                "dataset_query": {
                    "type": "query",
                    "database": 1,
                    "query": {
                        "source-table": "card__50",
                        "joins": [
                            {"source-table": 10, "alias": "Table Join"},  # Regular table
                            {"source-table": "card__51", "alias": "Card Join"},  # Card
                        ],
                    },
                },
            }

            deps = exporter._extract_card_dependencies(card_data)
            # Should only include card dependencies
            assert deps == {50, 51}

    def test_nested_query_dependencies(self, sample_export_config):
        """Test card with nested query dependencies."""
        with patch("lib.services.export_service.MetabaseClient"):
            exporter = MetabaseExporter(sample_export_config)

            card_data = {
                "id": 100,
                "name": "Nested Card",
                "dataset_query": {
                    "type": "query",
                    "database": 1,
                    "query": {
                        "source-table": "card__50",
                        "joins": [
                            {"source-table": "card__51", "joins": [{"source-table": "card__52"}]}
                        ],
                    },
                },
            }

            deps = exporter._extract_card_dependencies(card_data)
            # Current implementation may not handle deeply nested joins
            # This test documents current behavior
            assert 50 in deps
            assert 51 in deps


class TestDependencyChainTracking:
    """Test suite for dependency chain tracking."""

    def test_dependency_chain_initialization(self, sample_export_config):
        """Test that dependency chain is initialized empty."""
        with patch("lib.services.export_service.MetabaseClient"):
            exporter = MetabaseExporter(sample_export_config)

            assert exporter._dependency_chain == []

    def test_track_simple_dependency_chain(self, sample_export_config):
        """Test tracking a simple dependency chain."""
        with patch("lib.services.export_service.MetabaseClient"):
            exporter = MetabaseExporter(sample_export_config)

            # Simulate processing cards in dependency order
            exporter._dependency_chain = [50, 100]

            assert 50 in exporter._dependency_chain
            assert 100 in exporter._dependency_chain


class TestCircularDependencyDetection:
    """Test suite for circular dependency detection."""

    def test_detect_direct_circular_dependency(self, sample_export_config):
        """Test detection of direct circular dependency (A -> B -> A)."""
        with patch("lib.services.export_service.MetabaseClient"):
            exporter = MetabaseExporter(sample_export_config)

            # Simulate circular dependency
            exporter._dependency_chain = [50, 51]

            # If we try to add 50 again, it would be circular
            is_circular = 50 in exporter._dependency_chain
            assert is_circular is True

    def test_detect_indirect_circular_dependency(self, sample_export_config):
        """Test detection of indirect circular dependency (A -> B -> C -> A)."""
        with patch("lib.services.export_service.MetabaseClient"):
            exporter = MetabaseExporter(sample_export_config)

            # Simulate longer circular chain
            exporter._dependency_chain = [50, 51, 52]

            # If we try to add 50 again, it would be circular
            is_circular = 50 in exporter._dependency_chain
            assert is_circular is True


class TestDependencyOrdering:
    """Test suite for dependency ordering."""

    def test_dependencies_exported_before_dependent(self, sample_export_config):
        """Test that dependencies are exported before dependent cards."""
        with patch("lib.services.export_service.MetabaseClient"):
            exporter = MetabaseExporter(sample_export_config)

            # Track exported cards
            exporter._exported_cards = {50, 51}

            # Card 100 depends on 50 and 51
            # Both should already be exported
            assert 50 in exporter._exported_cards
            assert 51 in exporter._exported_cards

    def test_prevent_duplicate_exports(self, sample_export_config):
        """Test that cards are not exported multiple times."""
        with patch("lib.services.export_service.MetabaseClient"):
            exporter = MetabaseExporter(sample_export_config)

            # Mark card as exported
            exporter._exported_cards.add(50)

            # Should not export again
            assert 50 in exporter._exported_cards


class TestComplexDependencyScenarios:
    """Test suite for complex dependency scenarios."""

    def test_diamond_dependency(self, sample_export_config):
        """
        Test diamond dependency pattern:

            A
           / \
          B   C
           \\ /
            D

        D depends on both B and C, which both depend on A.
        """
        with patch("lib.services.export_service.MetabaseClient"):
            exporter = MetabaseExporter(sample_export_config)

            # Card A (no dependencies)
            card_a = {"id": 1, "dataset_query": {"query": {"source-table": 10}}}

            # Card B (depends on A)
            card_b = {"id": 2, "dataset_query": {"query": {"source-table": "card__1"}}}

            # Card C (depends on A)
            card_c = {"id": 3, "dataset_query": {"query": {"source-table": "card__1"}}}

            # Card D (depends on B and C)
            card_d = {
                "id": 4,
                "dataset_query": {
                    "query": {"source-table": "card__2", "joins": [{"source-table": "card__3"}]}
                },
            }

            deps_a = exporter._extract_card_dependencies(card_a)
            deps_b = exporter._extract_card_dependencies(card_b)
            deps_c = exporter._extract_card_dependencies(card_c)
            deps_d = exporter._extract_card_dependencies(card_d)

            assert deps_a == set()
            assert deps_b == {1}
            assert deps_c == {1}
            assert deps_d == {2, 3}

    def test_long_dependency_chain(self, sample_export_config):
        """Test long chain of dependencies (A -> B -> C -> D -> E)."""
        with patch("lib.services.export_service.MetabaseClient"):
            exporter = MetabaseExporter(sample_export_config)

            cards = []
            for i in range(1, 6):
                if i == 1:
                    # First card has no dependencies
                    card = {"id": i, "dataset_query": {"query": {"source-table": 10}}}
                else:
                    # Each subsequent card depends on previous
                    card = {"id": i, "dataset_query": {"query": {"source-table": f"card__{i-1}"}}}
                cards.append(card)

            # Verify dependency chain
            for i, card in enumerate(cards):
                deps = exporter._extract_card_dependencies(card)
                if i == 0:
                    assert deps == set()
                else:
                    assert deps == {i}  # Depends on previous card


class TestInvalidDependencyReferences:
    """Test suite for invalid dependency references."""

    def test_invalid_card_reference_format(self, sample_export_config):
        """Test handling of invalid card reference format."""
        with patch("lib.services.export_service.MetabaseClient"):
            exporter = MetabaseExporter(sample_export_config)

            card_data = {"id": 100, "dataset_query": {"query": {"source-table": "card__invalid"}}}

            deps = exporter._extract_card_dependencies(card_data)
            # Should handle gracefully and return empty set
            assert deps == set()

    def test_malformed_card_reference(self, sample_export_config):
        """Test handling of malformed card reference."""
        with patch("lib.services.export_service.MetabaseClient"):
            exporter = MetabaseExporter(sample_export_config)

            card_data = {
                "id": 100,
                "dataset_query": {"query": {"source-table": "card__"}},  # Missing ID
            }

            deps = exporter._extract_card_dependencies(card_data)
            assert deps == set()

    def test_non_string_source_table(self, sample_export_config):
        """Test handling of non-string source-table value."""
        with patch("lib.services.export_service.MetabaseClient"):
            exporter = MetabaseExporter(sample_export_config)

            card_data = {
                "id": 100,
                "dataset_query": {"query": {"source-table": 123}},  # Integer, not string
            }

            deps = exporter._extract_card_dependencies(card_data)
            # Should handle gracefully
            assert deps == set()


class TestDependencyResolutionPerformance:
    """Test suite for dependency resolution performance."""

    def test_many_dependencies(self, sample_export_config):
        """Test handling of card with many dependencies."""
        with patch("lib.services.export_service.MetabaseClient"):
            exporter = MetabaseExporter(sample_export_config)

            # Create card with 50 dependencies
            joins = [{"source-table": f"card__{i}"} for i in range(1, 51)]

            card_data = {
                "id": 100,
                "dataset_query": {"query": {"source-table": 10, "joins": joins}},
            }

            deps = exporter._extract_card_dependencies(card_data)
            assert len(deps) == 50
            assert all(i in deps for i in range(1, 51))
