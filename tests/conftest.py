"""
Pytest configuration and shared fixtures for all tests.

This module provides common fixtures that can be used across all test files.
"""

import json
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import pytest

# ============================================================================
# Directory and File Fixtures
# ============================================================================


@pytest.fixture
def temp_dir(tmp_path: Path) -> Path:
    """Create a temporary directory for test files."""
    return tmp_path


@pytest.fixture
def export_dir(tmp_path: Path) -> Path:
    """Create a temporary export directory structure."""
    export_dir = tmp_path / "metabase_export"
    export_dir.mkdir()

    # Create subdirectories
    (export_dir / "dependencies").mkdir()
    (export_dir / "collections").mkdir()

    return export_dir


@pytest.fixture
def sample_manifest_data() -> dict[str, Any]:
    """Return sample manifest data for testing."""
    return {
        "meta": {
            "source_url": "https://source.example.com",
            "export_timestamp": "2025-10-07T12:00:00.000000",
            "tool_version": "1.0.0",
            "cli_args": {
                "source_url": "https://source.example.com",
                "export_dir": "./metabase_export",
                "include_dashboards": True,
                "include_archived": False,
            },
        },
        "databases": {"1": "Sample Database", "2": "Production DB", "3": "Analytics DB"},
        "collections": [
            {"id": 1, "name": "Test Collection", "slug": "test-collection", "parent_id": None}
        ],
        "cards": [
            {
                "id": 100,
                "name": "Test Card",
                "collection_id": 1,
                "database_id": 1,
                "dataset_query": {"type": "query", "database": 1, "query": {"source-table": 1}},
            }
        ],
        "dashboards": [],
    }


@pytest.fixture
def manifest_file(export_dir: Path, sample_manifest_data: dict[str, Any]) -> Path:
    """Create a manifest.json file in the export directory."""
    manifest_path = export_dir / "manifest.json"
    with open(manifest_path, "w") as f:
        json.dump(sample_manifest_data, f, indent=2)
    return manifest_path


@pytest.fixture
def sample_db_map() -> dict[str, Any]:
    """Return sample database mapping data."""
    return {
        "by_id": {"1": 10, "2": 20, "3": 30},
        "by_name": {"Sample Database": 10, "Production DB": 20, "Analytics DB": 30},
    }


@pytest.fixture
def db_map_file(tmp_path: Path, sample_db_map: dict[str, Any]) -> Path:
    """Create a db_map.json file."""
    db_map_path = tmp_path / "db_map.json"
    with open(db_map_path, "w") as f:
        json.dump(sample_db_map, f, indent=2)
    return db_map_path


# ============================================================================
# Mock API Response Fixtures
# ============================================================================


@pytest.fixture
def mock_collection_response() -> dict[str, Any]:
    """Return a mock collection API response."""
    return {
        "id": 1,
        "name": "Test Collection",
        "slug": "test-collection",
        "description": "A test collection",
        "archived": False,
        "parent_id": None,
        "location": "/",
        "personal_owner_id": None,
    }


@pytest.fixture
def mock_card_response() -> dict[str, Any]:
    """Return a mock card (question) API response."""
    return {
        "id": 100,
        "name": "Test Question",
        "description": "A test question",
        "collection_id": 1,
        "database_id": 1,
        "dataset_query": {
            "type": "query",
            "database": 1,
            "query": {
                "source-table": 1,
                "aggregation": [["count"]],
                "breakout": [[["field", 1, None]]],
            },
        },
        "display": "table",
        "visualization_settings": {},
        "archived": False,
        "created_at": "2025-01-01T00:00:00.000Z",
        "updated_at": "2025-01-01T00:00:00.000Z",
    }


@pytest.fixture
def mock_dashboard_response() -> dict[str, Any]:
    """Return a mock dashboard API response."""
    return {
        "id": 200,
        "name": "Test Dashboard",
        "description": "A test dashboard",
        "collection_id": 1,
        "parameters": [],
        "dashcards": [
            {
                "id": 1,
                "card_id": 100,
                "dashboard_id": 200,
                "size_x": 4,
                "size_y": 4,
                "row": 0,
                "col": 0,
            }
        ],
        "archived": False,
        "created_at": "2025-01-01T00:00:00.000Z",
        "updated_at": "2025-01-01T00:00:00.000Z",
    }


@pytest.fixture
def mock_collections_tree() -> list:
    """Return a mock collections tree API response."""
    return [
        {
            "id": "root",
            "name": "Our analytics",
            "children": [
                {"id": 1, "name": "Test Collection", "children": []},
                {
                    "id": 2,
                    "name": "Another Collection",
                    "children": [{"id": 3, "name": "Nested Collection", "children": []}],
                },
            ],
        }
    ]


# ============================================================================
# Mock Client Fixtures
# ============================================================================


@pytest.fixture
def mock_metabase_client():
    """Create a mock MetabaseClient for testing."""
    client = Mock()
    client.base_url = "https://example.com"
    client.api_url = "https://example.com/api"
    client._session_token = "test-token"
    return client


@pytest.fixture
def mock_requests_session():
    """Create a mock requests.Session for testing."""
    session = Mock()
    session.headers = {}
    return session


# ============================================================================
# Configuration Fixtures
# ============================================================================


@pytest.fixture
def sample_export_config():
    """Return a sample ExportConfig for testing."""
    from lib.config import ExportConfig

    return ExportConfig(
        source_url="https://source.example.com",
        export_dir="./test_export",
        source_username="test@example.com",
        source_password="password123",  # pragma: allowlist secret
        include_dashboards=True,
        include_archived=False,
        root_collection_ids=None,
        log_level="INFO",
    )


@pytest.fixture
def sample_import_config(tmp_path: Path):
    """Return a sample ImportConfig for testing."""
    from lib.config import ImportConfig

    return ImportConfig(
        target_url="https://target.example.com",
        export_dir=str(tmp_path / "metabase_export"),
        db_map_path=str(tmp_path / "db_map.json"),
        target_username="test@example.com",
        target_password="password123",  # pragma: allowlist secret
        conflict_strategy="skip",
        dry_run=False,
        log_level="INFO",
    )


# ============================================================================
# Pytest Configuration
# ============================================================================


def pytest_configure(config):
    """Configure pytest with custom markers."""
    config.addinivalue_line("markers", "integration: mark test as an integration test")
    config.addinivalue_line("markers", "slow: mark test as slow running")
    config.addinivalue_line("markers", "requires_api: mark test as requiring API access")
