"""Payload cleaning utilities for API requests."""

from typing import Any

from lib.constants import IMMUTABLE_FIELDS

# Card type values for Metabase API
CARD_TYPE_QUESTION = "question"
CARD_TYPE_MODEL = "model"
CARD_TYPE_METRIC = "metric"


def clean_for_create(payload: dict[str, Any]) -> dict[str, Any]:
    """Removes immutable or server-generated fields before creating a new item.

    For card payloads, also ensures the 'type' field is set correctly based on
    the 'dataset' field (models have dataset=True and type='model').

    Args:
        payload: The original payload dictionary.

    Returns:
        A cleaned payload with immutable fields removed.
    """
    cleaned = {k: v for k, v in payload.items() if k not in IMMUTABLE_FIELDS}

    # Set table_id to null - it's instance-specific and will be auto-populated by Metabase
    # based on the query's source-table
    if "table_id" in cleaned:
        cleaned["table_id"] = None

    # Ensure 'type' field is set correctly for cards based on 'dataset' field
    # In Metabase v56+, cards with dataset=True must have type='model'
    # This is critical for models to be properly recognized after import
    if "dataset_query" in cleaned:  # This is a card payload
        is_model = cleaned.get("dataset", False)
        if is_model:
            cleaned["type"] = CARD_TYPE_MODEL
        elif "type" not in cleaned:
            # Default to 'question' if type is not set and it's not a model
            cleaned["type"] = CARD_TYPE_QUESTION

    return cleaned


def clean_dashboard_for_update(payload: dict[str, Any]) -> dict[str, Any]:
    """Removes fields that should not be sent on a dashboard update.

    Args:
        payload: The original dashboard payload.

    Returns:
        A cleaned payload suitable for dashboard updates.
    """
    cleaned = clean_for_create(payload)
    # Dashcards are updated via their own field, not at the top level
    if "dashcards" in cleaned:
        del cleaned["dashcards"]
    # Dash tabs are also updated via their own field
    if "tabs" in cleaned:
        del cleaned["tabs"]
    return cleaned
