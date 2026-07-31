"""Unit tests for remaining uncovered branches across small library modules.

Covers the HTTP error-logging paths in the client, multi-page pagination, the
custom JSON encoder, ImportReport's items/results synchronisation, version-config
lookup failures and parameter-dependency extraction edge cases.
"""

import dataclasses
import json
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
import requests
from pydantic import BaseModel

from lib.client import MetabaseAPIError, MetabaseClient
from lib.constants import MetabaseVersion
from lib.models_core import ImportReport, ImportReportItem
from lib.utils.file_io import CustomJsonEncoder, write_json_file
from lib.utils.query import extract_metric_deps_from_clause, extract_parameter_card_dependencies
from lib.version import get_version_config

# ============================================================================
# Client
# ============================================================================


def http_error(status_code: int, text: str, json_body=None) -> requests.exceptions.HTTPError:
    """Build an HTTPError carrying a mock response."""
    response = Mock()
    response.status_code = status_code
    response.text = text
    if json_body is None:
        response.json.side_effect = ValueError("not json")
    else:
        response.json.return_value = json_body
    return requests.exceptions.HTTPError(response=response)


@pytest.fixture
def client() -> MetabaseClient:
    """A client with authentication stubbed out."""
    with patch.object(MetabaseClient, "_authenticate"):
        return MetabaseClient(base_url="https://example.com", session_token="tok")


class TestRequestErrorLogging:
    """Tests for the HTTPError branch of MetabaseClient._request."""

    def test_logs_json_request_body_and_pretty_response(self, client, caplog):
        client._session = Mock()
        client._session.headers = {}
        client._session.request.return_value.raise_for_status.side_effect = http_error(
            400, '{"errors":{"name":"required"}}', {"errors": {"name": "required"}}
        )

        with caplog.at_level("ERROR", logger="metabase_migration"):
            with pytest.raises(MetabaseAPIError) as exc_info:
                client._request.__wrapped__(client, "post", "/card", json={"name": "X"})

        assert "Request body: {'name': 'X'}" in caplog.text
        assert json.dumps({"errors": {"name": "required"}}, indent=2) in caplog.text
        assert exc_info.value.status_code == 400

    def test_falls_back_to_raw_text_when_response_is_not_json(self, client, caplog):
        client._session = Mock()
        client._session.headers = {}
        client._session.request.return_value.raise_for_status.side_effect = http_error(
            500, "Internal Server Error"
        )

        with caplog.at_level("ERROR", logger="metabase_migration"):
            with pytest.raises(MetabaseAPIError):
                client._request.__wrapped__(client, "get", "/card/1")

        assert "Internal Server Error" in caplog.text
        assert "Request body:" not in caplog.text

    def test_logs_form_data_request_body(self, client, caplog):
        client._session = Mock()
        client._session.headers = {}
        client._session.request.return_value.raise_for_status.side_effect = http_error(
            422, "bad", {"message": "bad"}
        )

        with caplog.at_level("ERROR", logger="metabase_migration"):
            with pytest.raises(MetabaseAPIError):
                client._request.__wrapped__(client, "post", "/card", data="name=X")

        assert "Request body: name=X" in caplog.text


class TestPagination:
    """Tests for MetabaseClient._get_paginated."""

    def test_list_response_returns_immediately(self, client):
        with patch.object(client, "_request") as mock_request:
            mock_request.return_value.json.return_value = [{"id": 1}]

            assert client._get_paginated("/card") == [{"id": 1}]
            assert mock_request.call_count == 1

    def test_follows_multiple_pages_until_total_reached(self, client):
        pages = [
            {"data": [{"id": 1}], "total": 2, "limit": 1},
            {"data": [{"id": 2}], "total": 2, "limit": 1},
        ]
        with patch.object(client, "_request") as mock_request:
            mock_request.return_value.json.side_effect = pages

            assert client._get_paginated("/card") == [{"id": 1}, {"id": 2}]
            assert mock_request.call_count == 2

    def test_stops_when_total_is_absent(self, client):
        with patch.object(client, "_request") as mock_request:
            mock_request.return_value.json.return_value = {"data": [{"id": 1}]}

            assert client._get_paginated("/card") == [{"id": 1}]
            assert mock_request.call_count == 1

    def test_stops_when_limit_is_zero(self, client):
        with patch.object(client, "_request") as mock_request:
            mock_request.return_value.json.return_value = {
                "data": [{"id": 1}],
                "total": 9,
                "limit": 0,
            }

            assert client._get_paginated("/card") == [{"id": 1}]
            assert mock_request.call_count == 1

    def test_unexpected_shape_raises(self, client):
        with patch.object(client, "_request") as mock_request:
            mock_request.return_value.json.return_value = "nonsense"

            with pytest.raises(MetabaseAPIError, match="Unexpected pagination response format"):
                client._get_paginated("/card")


class TestArchivedCards:
    """Tests for MetabaseClient.get_archived_cards."""

    def test_returns_list_response(self, client):
        with patch.object(client, "_request") as mock_request:
            mock_request.return_value.json.return_value = [{"id": 1}]

            assert client.get_archived_cards() == [{"id": 1}]
            mock_request.assert_called_once_with("get", "/card", params={"f": "archived"})

    def test_non_list_response_becomes_empty_list(self, client):
        with patch.object(client, "_request") as mock_request:
            mock_request.return_value.json.return_value = {"data": []}

            assert client.get_archived_cards() == []


# ============================================================================
# JSON encoding
# ============================================================================


class SampleModel(BaseModel):
    """Minimal Pydantic model for encoder tests."""

    name: str


@dataclasses.dataclass
class SampleDataclass:
    """Minimal dataclass for encoder tests."""

    value: int


class TestCustomJsonEncoder:
    """Tests for CustomJsonEncoder.default."""

    def test_encodes_pydantic_model(self):
        assert json.dumps(SampleModel(name="x"), cls=CustomJsonEncoder) == '{"name": "x"}'

    def test_encodes_dataclass(self):
        assert json.dumps(SampleDataclass(value=3), cls=CustomJsonEncoder) == '{"value": 3}'

    def test_encodes_set_as_list(self):
        assert json.loads(json.dumps({"ids": {1}}, cls=CustomJsonEncoder)) == {"ids": [1]}

    def test_unsupported_type_raises(self):
        with pytest.raises(TypeError):
            json.dumps(object(), cls=CustomJsonEncoder)

    def test_dataclass_type_is_not_treated_as_instance(self):
        """A dataclass *class* (not an instance) is not serialisable."""
        with pytest.raises(TypeError):
            json.dumps(SampleDataclass, cls=CustomJsonEncoder)

    def test_write_json_file_creates_parent_directories(self, tmp_path: Path):
        target = tmp_path / "nested" / "deep" / "out.json"

        write_json_file({"ids": {1, 2}}, target)

        assert sorted(json.loads(target.read_text())["ids"]) == [1, 2]


# ============================================================================
# ImportReport
# ============================================================================


class TestImportReport:
    """Tests for ImportReport's items/results synchronisation."""

    def item(self, status: str = "created") -> ImportReportItem:
        return ImportReportItem(
            entity_type="card", status=status, source_id=1, target_id=10, name="X"
        )

    def test_empty_report_shares_one_list(self):
        report = ImportReport()
        report.add(self.item())

        assert report.items is report.results
        assert len(report.items) == 1
        assert report.summary["cards"]["created"] == 1

    def test_items_seeds_results(self):
        seeded = [self.item()]
        report = ImportReport(items=seeded)

        assert report.results is seeded

    def test_results_seeds_items(self):
        seeded = [self.item()]
        report = ImportReport(results=seeded)

        assert report.items is seeded

    def test_distinct_lists_are_both_appended_to(self):
        results = [self.item()]
        items: list[ImportReportItem] = [self.item("skipped")]
        report = ImportReport(results=results, items=items)

        assert report.results is not report.items
        report.add(self.item("updated"))

        assert len(report.results) == 2
        assert len(report.items) == 2

    def test_unknown_entity_type_does_not_update_summary(self):
        report = ImportReport()
        report.add(
            ImportReportItem(
                entity_type="widget", status="created", source_id=1, target_id=None, name="X"
            )
        )

        assert report.summary["cards"]["created"] == 0
        assert len(report.results) == 1


# ============================================================================
# Version configuration
# ============================================================================


class TestVersionConfig:
    """Tests for get_version_config."""

    @pytest.mark.parametrize("version", list(MetabaseVersion))
    def test_supported_versions_return_config(self, version):
        assert get_version_config(version) is not None

    def test_unsupported_version_raises(self):
        with pytest.raises(ValueError, match="Unsupported Metabase version"):
            get_version_config("v99")  # type: ignore[arg-type]


# ============================================================================
# Query dependency helpers
# ============================================================================


class TestParameterDependencies:
    """Tests for extract_parameter_card_dependencies."""

    def test_no_parameters_key(self):
        assert extract_parameter_card_dependencies({}) == set()

    def test_null_parameters(self):
        assert extract_parameter_card_dependencies({"parameters": None}) == set()

    def test_non_dict_parameter_skipped(self):
        assert extract_parameter_card_dependencies({"parameters": ["nope", 42]}) == set()

    def test_non_dict_source_config_skipped(self):
        card = {"parameters": [{"values_source_config": "nope"}]}
        assert extract_parameter_card_dependencies(card) == set()

    def test_non_integer_card_id_skipped(self):
        card = {"parameters": [{"values_source_config": {"card_id": "12"}}]}
        assert extract_parameter_card_dependencies(card) == set()

    def test_collects_integer_card_ids(self):
        card = {
            "parameters": [
                {"values_source_config": {"card_id": 12}},
                {"values_source_config": {"card_id": 13}},
            ]
        }
        assert extract_parameter_card_dependencies(card) == {12, 13}


class TestMetricDependencies:
    """Tests for extract_metric_deps_from_clause."""

    def test_direct_metric_tuple(self):
        deps: set[int] = set()
        extract_metric_deps_from_clause(["metric", {"lib/uuid": "u"}, 15], deps)
        assert deps == {15}

    def test_nested_metric_tuple(self):
        deps: set[int] = set()
        extract_metric_deps_from_clause(["+", ["metric", {"lib/uuid": "u"}, 15], 1], deps)
        assert deps == {15}

    def test_non_list_clause_ignored(self):
        deps: set[int] = set()
        extract_metric_deps_from_clause("count", deps)
        assert deps == set()

    def test_metric_without_metadata_dict_ignored(self):
        deps: set[int] = set()
        extract_metric_deps_from_clause(["metric", 15], deps)
        assert deps == set()
