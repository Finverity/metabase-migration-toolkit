"""
Sample API responses for testing.

This module contains realistic sample responses from the Metabase API
that can be used in tests.
"""

SAMPLE_COLLECTION = {
    "id": 1,
    "name": "Marketing Analytics",
    "slug": "marketing-analytics",
    "description": "Marketing team dashboards and reports",
    "archived": False,
    "parent_id": None,
    "location": "/",
    "personal_owner_id": None,
    "can_write": True,
    "created_at": "2025-01-01T00:00:00.000Z",
    "updated_at": "2025-01-15T10:30:00.000Z",
}

SAMPLE_CARD = {
    "id": 100,
    "name": "Monthly Revenue",
    "description": "Total revenue by month",
    "collection_id": 1,
    "database_id": 2,
    "dataset_query": {
        "type": "query",
        "database": 2,
        "query": {
            "source-table": 10,
            "aggregation": [["sum", ["field", 5, None]]],
            "breakout": [["field", 3, {"temporal-unit": "month"}]],
        },
    },
    "display": "line",
    "visualization_settings": {"graph.dimensions": ["created_at"], "graph.metrics": ["sum"]},
    "archived": False,
    "enable_embedding": False,
    "embedding_params": None,
    "cache_ttl": None,
    "result_metadata": [],
    "created_at": "2025-01-05T14:20:00.000Z",
    "updated_at": "2025-01-20T09:15:00.000Z",
    "creator_id": 1,
    "creator": {"id": 1, "email": "admin@example.com", "first_name": "Admin", "last_name": "User"},
}

SAMPLE_CARD_WITH_DEPENDENCY = {
    "id": 101,
    "name": "Revenue Analysis",
    "description": "Analysis based on Monthly Revenue card",
    "collection_id": 1,
    "database_id": 2,
    "dataset_query": {
        "type": "query",
        "database": 2,
        "query": {
            "source-table": "card__100",  # Depends on card 100
            "aggregation": [["avg", ["field", "sum", {"base-type": "type/Float"}]]],
            "breakout": [["field", "created_at", {"temporal-unit": "year"}]],
        },
    },
    "display": "bar",
    "visualization_settings": {},
    "archived": False,
    "created_at": "2025-01-10T11:00:00.000Z",
    "updated_at": "2025-01-22T16:45:00.000Z",
}

SAMPLE_MODEL = {
    "id": 102,
    "name": "Customer Base Model",
    "description": "Curated customer data model",
    "collection_id": 1,
    "database_id": 2,
    "type": "model",  # Card type for models in Metabase v56+
    "dataset": True,  # Legacy field that also marks it as a model
    "dataset_query": {
        "type": "query",
        "database": 2,
        "query": {
            "source-table": 15,
            "fields": [
                ["field", 20, None],  # customer_id
                ["field", 21, None],  # customer_name
                ["field", 22, None],  # email
                ["field", 23, None],  # created_at
            ],
        },
    },
    "display": "table",
    "visualization_settings": {},
    "archived": False,
    "result_metadata": [
        {"name": "customer_id", "display_name": "Customer ID", "base_type": "type/Integer"},
        {"name": "customer_name", "display_name": "Customer Name", "base_type": "type/Text"},
        {"name": "email", "display_name": "Email", "base_type": "type/Text"},
        {"name": "created_at", "display_name": "Created At", "base_type": "type/DateTime"},
    ],
    "created_at": "2025-01-08T09:00:00.000Z",
    "updated_at": "2025-01-20T14:30:00.000Z",
    "creator_id": 1,
    "creator": {"id": 1, "email": "admin@example.com", "first_name": "Admin", "last_name": "User"},
}

SAMPLE_QUESTION_BASED_ON_MODEL = {
    "id": 103,
    "name": "Active Customers",
    "description": "Question based on Customer Base Model",
    "collection_id": 1,
    "database_id": 2,
    "dataset_query": {
        "type": "query",
        "database": 2,
        "query": {
            "source-table": "card__102",  # Depends on model 102
            "filter": ["=", ["field", "status", {"base-type": "type/Text"}], "Active"],
        },
    },
    "display": "table",
    "visualization_settings": {},
    "archived": False,
    "created_at": "2025-01-15T10:00:00.000Z",
    "updated_at": "2025-01-22T11:00:00.000Z",
}

SAMPLE_DASHBOARD = {
    "id": 200,
    "name": "Marketing Overview",
    "description": "Key marketing metrics and KPIs",
    "collection_id": 1,
    "parameters": [
        {
            "id": "param1",
            "name": "Date Range",
            "slug": "date_range",
            "type": "date/range",
            "default": None,
        }
    ],
    "dashcards": [
        {
            "id": 1,
            "card_id": 100,
            "dashboard_id": 200,
            "size_x": 6,
            "size_y": 4,
            "row": 0,
            "col": 0,
            "parameter_mappings": [],
            "visualization_settings": {},
        },
        {
            "id": 2,
            "card_id": 101,
            "dashboard_id": 200,
            "size_x": 6,
            "size_y": 4,
            "row": 0,
            "col": 6,
            "parameter_mappings": [],
            "visualization_settings": {},
        },
    ],
    "archived": False,
    "enable_embedding": False,
    "embedding_params": None,
    "cache_ttl": None,
    "width": "fixed",
    "auto_apply_filters": True,
    "created_at": "2025-01-08T13:30:00.000Z",
    "updated_at": "2025-01-25T08:20:00.000Z",
    "creator_id": 1,
}

# Dashboard with comprehensive filter examples
SAMPLE_DASHBOARD_WITH_FILTERS = {
    "id": 201,
    "name": "Sales Dashboard with Filters",
    "description": "Dashboard demonstrating various filter types and mappings",
    "collection_id": 1,
    "parameters": [
        {
            "id": "date_filter",
            "name": "Date Range",
            "slug": "date_range",
            "type": "date/range",
            "default": None,
        },
        {
            "id": "category_filter",
            "name": "Product Category",
            "slug": "category",
            "type": "string/=",
            "default": "Electronics",
            "values_source_type": "card",
            "values_source_config": {
                "card_id": 100,
                "value_field": ["field", 10, None],
            },
        },
        {
            "id": "region_filter",
            "name": "Region",
            "slug": "region",
            "type": "string/=",
            "default": None,
        },
    ],
    "dashcards": [
        {
            "id": 10,
            "card_id": 100,
            "dashboard_id": 201,
            "size_x": 8,
            "size_y": 6,
            "row": 0,
            "col": 0,
            "parameter_mappings": [
                {
                    "parameter_id": "date_filter",
                    "card_id": 100,
                    "target": ["dimension", ["field", 3, {"temporal-unit": "month"}]],
                },
                {
                    "parameter_id": "category_filter",
                    "card_id": 100,
                    "target": ["dimension", ["field", 10, None]],
                },
            ],
            "visualization_settings": {
                "graph.dimensions": ["created_at"],
                "graph.metrics": ["sum"],
            },
        },
        {
            "id": 11,
            "card_id": 101,
            "dashboard_id": 201,
            "size_x": 8,
            "size_y": 6,
            "row": 0,
            "col": 8,
            "parameter_mappings": [
                {
                    "parameter_id": "date_filter",
                    "card_id": 101,
                    "target": [
                        "dimension",
                        ["field", "created_at", {"base-type": "type/DateTime"}],
                    ],
                },
                {
                    "parameter_id": "region_filter",
                    "card_id": 101,
                    "target": ["dimension", ["field", 15, None]],
                },
            ],
            "visualization_settings": {},
        },
    ],
    "archived": False,
    "enable_embedding": False,
    "embedding_params": None,
    "cache_ttl": None,
    "width": "fixed",
    "auto_apply_filters": True,
    "created_at": "2025-01-10T10:00:00.000Z",
    "updated_at": "2025-01-26T14:30:00.000Z",
    "creator_id": 1,
}

SAMPLE_COLLECTIONS_TREE = [
    {
        "id": "root",
        "name": "Our analytics",
        "children": [
            {
                "id": 1,
                "name": "Marketing Analytics",
                "children": [{"id": 3, "name": "Campaign Reports", "children": []}],
            },
            {"id": 2, "name": "Sales Analytics", "children": []},
        ],
    }
]

SAMPLE_DATABASE = {
    "id": 2,
    "name": "Production Database",
    "engine": "postgres",
    "details": {"host": "db.example.com", "port": 5432, "dbname": "production", "user": "metabase"},
    "is_sample": False,
    "is_full_sync": True,
    "is_on_demand": False,
    "created_at": "2024-12-01T00:00:00.000Z",
    "updated_at": "2025-01-01T00:00:00.000Z",
}

SAMPLE_DATABASES_LIST = [
    {"id": 1, "name": "Sample Database", "engine": "h2", "is_sample": True},
    {"id": 2, "name": "Production Database", "engine": "postgres", "is_sample": False},
    {"id": 3, "name": "Analytics Warehouse", "engine": "bigquery", "is_sample": False},
]

SAMPLE_MANIFEST = {
    "meta": {
        "source_url": "https://source.metabase.example.com",
        "export_timestamp": "2025-10-07T12:00:00.000000",
        "tool_version": "1.0.0",
        "cli_args": {
            "source_url": "https://source.metabase.example.com",
            "export_dir": "./metabase_export",
            "include_dashboards": True,
            "include_archived": False,
            "root_collection_ids": [1, 2],
            "log_level": "INFO",
        },
    },
    "databases": {"1": "Sample Database", "2": "Production Database", "3": "Analytics Warehouse"},
    "collections": [
        {"id": 1, "name": "Marketing Analytics", "slug": "marketing-analytics", "parent_id": None},
        {"id": 2, "name": "Sales Analytics", "slug": "sales-analytics", "parent_id": None},
        {"id": 3, "name": "Campaign Reports", "slug": "campaign-reports", "parent_id": 1},
    ],
    "cards": [
        {"id": 100, "name": "Monthly Revenue", "collection_id": 1, "database_id": 2},
        {"id": 101, "name": "Revenue Analysis", "collection_id": 1, "database_id": 2},
    ],
    "dashboards": [{"id": 200, "name": "Marketing Overview", "collection_id": 1}],
}

SAMPLE_DB_MAP = {
    "by_id": {"1": 10, "2": 20, "3": 30},
    "by_name": {"Sample Database": 10, "Production Database": 20, "Analytics Warehouse": 30},
}
