"""Dashboard handler for Metabase migration."""

import logging
from typing import Any, Literal, cast

from tqdm import tqdm

from lib.constants import (
    CONFLICT_OVERWRITE,
    CONFLICT_RENAME,
    CONFLICT_SKIP,
    DASHCARD_EXCLUDED_FIELDS,
    DASHCARD_POSITION_FIELDS,
)
from lib.handlers.base import BaseHandler, ImportContext
from lib.models import Dashboard
from lib.utils import clean_for_create, read_json_file

logger = logging.getLogger("metabase_migration")


class DashboardHandler(BaseHandler):
    """Handles import of dashboards."""

    def __init__(self, context: ImportContext) -> None:
        """Initialize the dashboard handler."""
        super().__init__(context)

    def import_dashboards(self, dashboards: list[Dashboard]) -> None:
        """Imports all dashboards.

        Args:
            dashboards: List of dashboards to import.
        """
        sorted_dashboards = sorted(dashboards, key=lambda d: d.file_path)

        for dash in tqdm(sorted_dashboards, desc="Importing Dashboards"):
            if dash.archived and not self.context.should_include_archived():
                continue
            self._import_single_dashboard(dash)

    def _import_single_dashboard(self, dash: Dashboard) -> None:
        """Imports a single dashboard.

        Args:
            dash: The dashboard to import.
        """
        try:
            dash_data = read_json_file(self.context.export_dir / dash.file_path)

            # Remap collection
            target_collection_id = self.id_mapper.resolve_collection_id(dash.collection_id)
            dash_data["collection_id"] = target_collection_id

            # Clean and remap parameters
            payload = clean_for_create(dash_data)
            remapped_parameters = self.query_remapper.remap_dashboard_parameters(
                payload.get("parameters", []),
                self.context.manifest.cards,
            )

            # Check for existing dashboard using cached collection items lookup
            existing_dashboard = self.context.find_existing_dashboard(
                dash.name, target_collection_id
            )

            dashboard_name = dash.name
            dashboard_id = None
            action_taken: str = "created"

            if existing_dashboard:
                result = self._handle_existing_dashboard(
                    dash, existing_dashboard, target_collection_id
                )
                if result is None:
                    return  # Skipped
                dashboard_id, dashboard_name, action_taken = result

            # Create or update dashboard
            if dashboard_id is None:
                create_payload = {
                    "name": dashboard_name,
                    "collection_id": target_collection_id,
                    "description": payload.get("description"),
                    "parameters": remapped_parameters,
                }
                new_dash = self.client.create_dashboard(create_payload)
                dashboard_id = new_dash["id"]
                logger.debug(f"Created dashboard '{dashboard_name}' (ID: {dashboard_id})")

            # Handle tabs: In v57, tabs must be created together with dashcards
            # Build tabs with negative IDs and create a mapping for dashcard tab remapping
            source_tabs = dash_data.get("tabs", [])
            tabs_to_create, tab_mapping = self._prepare_tabs_for_import(source_tabs)

            # Prepare dashcards with tab ID remapping
            dashcards_to_import = self._prepare_dashcards(
                dash_data.get("dashcards", []), tab_mapping
            )

            # Update with tabs and dashcards together (required for v57)
            update_payload = self._build_update_payload(
                dashboard_name, payload, remapped_parameters, dashcards_to_import, tabs_to_create
            )
            updated_dash = self.client.update_dashboard(dashboard_id, update_payload)

            self._add_report_item(
                "dashboard",
                cast(
                    Literal["created", "updated", "skipped", "failed"],
                    action_taken,
                ),
                dash.id,
                updated_dash["id"],
                dashboard_name,
            )

            # Store dashboard ID mapping for click_behavior remapping
            self.id_mapper.set_dashboard_mapping(dash.id, updated_dash["id"])

            # Add to collection cache to keep it up-to-date for conflict detection
            if action_taken == "created":
                self.context.add_to_collection_cache(
                    target_collection_id,
                    {
                        "id": updated_dash["id"],
                        "name": dashboard_name,
                        "model": "dashboard",
                    },
                )

            logger.debug(
                f"Successfully {action_taken} dashboard '{dashboard_name}' "
                f"(ID: {updated_dash['id']})"
            )

        except Exception as e:
            logger.error(
                f"Failed to import dashboard '{dash.name}' (ID: {dash.id}): {e}",
                exc_info=True,
            )
            self._add_report_item("dashboard", "failed", dash.id, None, dash.name, str(e))

    def _handle_existing_dashboard(
        self,
        dash: Dashboard,
        existing_dashboard: dict[str, Any],
        target_collection_id: int | None,
    ) -> tuple[int | None, str, str] | None:
        """Handles conflict when dashboard already exists.

        Args:
            dash: The source dashboard.
            existing_dashboard: The existing target dashboard.
            target_collection_id: The target collection ID.

        Returns:
            Tuple of (dashboard_id, name, action) or None if skipped.
        """
        strategy = self.context.get_conflict_strategy()

        if strategy == CONFLICT_SKIP:
            self._add_report_item(
                "dashboard",
                "skipped",
                dash.id,
                existing_dashboard["id"],
                dash.name,
                "Already exists (skipped)",
            )
            logger.debug(
                f"Skipped dashboard '{dash.name}' - already exists "
                f"with ID {existing_dashboard['id']}"
            )
            return None

        elif strategy == CONFLICT_OVERWRITE:
            logger.debug(
                f"Will overwrite existing dashboard '{dash.name}' "
                f"(ID: {existing_dashboard['id']})"
            )
            return (existing_dashboard["id"], dash.name, "updated")

        elif strategy == CONFLICT_RENAME:
            new_name = self._generate_unique_dashboard_name(dash.name, target_collection_id)
            logger.info(f"Renamed dashboard '{dash.name}' to '{new_name}' to avoid conflict")
            return (None, new_name, "created")

        return None

    def _generate_unique_dashboard_name(self, base_name: str, collection_id: int | None) -> str:
        """Generates a unique dashboard name by appending a number.

        Uses cached collection items for O(1) lookup.

        Args:
            base_name: The original name.
            collection_id: The collection ID.

        Returns:
            A unique name.
        """
        counter = 1
        while True:
            new_name = f"{base_name} ({counter})"
            if not self.context.find_existing_dashboard(new_name, collection_id):
                return new_name
            counter += 1

    def _prepare_tabs_for_import(
        self,
        source_tabs: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], dict[int, int]]:
        """Prepares tabs for import with negative IDs and builds the tab mapping.

        In Metabase v57, tabs must be created together with dashcards in a single
        PUT request. This method prepares tabs with negative IDs that Metabase will
        replace with real IDs, and builds a mapping from source tab IDs to these
        negative IDs for use in dashcard tab_id remapping.

        Args:
            source_tabs: List of source tab definitions.

        Returns:
            Tuple of (tabs_to_create, tab_mapping):
            - tabs_to_create: List of tabs with negative IDs for the PUT request
            - tab_mapping: Mapping of source_tab_id -> negative_temp_tab_id
        """
        tabs_to_create: list[dict[str, Any]] = []
        tab_mapping: dict[int, int] = {}

        if not source_tabs:
            return tabs_to_create, tab_mapping

        # Build tabs with negative IDs (Metabase will assign real IDs)
        for idx, tab in enumerate(source_tabs):
            source_tab_id = tab.get("id")
            temp_tab_id = -(idx + 1)  # Negative IDs: -1, -2, -3, ...

            tabs_to_create.append(
                {
                    "id": temp_tab_id,
                    "name": tab.get("name", "Tab"),
                    "position": tab.get("position", idx),
                }
            )

            # Map source tab ID to the temporary negative ID
            if source_tab_id is not None:
                tab_mapping[source_tab_id] = temp_tab_id
                logger.debug(
                    f"Tab '{tab.get('name')}': source_id={source_tab_id} -> temp_id={temp_tab_id}"
                )

        logger.debug(f"Prepared {len(tabs_to_create)} tabs for import")

        return tabs_to_create, tab_mapping

    def _prepare_dashcards(
        self,
        dashcards: list[dict[str, Any]],
        tab_mapping: dict[int, int] | None = None,
    ) -> list[dict[str, Any]]:
        """Prepares dashcards for import by remapping IDs.

        Args:
            dashcards: The source dashcards.
            tab_mapping: Optional mapping of source_tab_id -> target_tab_id.

        Returns:
            List of prepared dashcards.
        """
        prepared_dashcards = []
        next_temp_id = -1

        for dashcard in dashcards:
            clean_dashcard = self._prepare_single_dashcard(dashcard, next_temp_id, tab_mapping)
            if clean_dashcard is not None:
                prepared_dashcards.append(clean_dashcard)
                next_temp_id -= 1

        return prepared_dashcards

    def _prepare_single_dashcard(
        self,
        dashcard: dict[str, Any],
        temp_id: int,
        tab_mapping: dict[int, int] | None = None,
    ) -> dict[str, Any] | None:
        """Prepares a single dashcard for import.

        Args:
            dashcard: The source dashcard.
            temp_id: The temporary ID to assign.
            tab_mapping: Optional mapping of source_tab_id -> target_tab_id.

        Returns:
            The prepared dashcard or None if skipped.
        """
        clean_dashcard: dict[str, Any] = {}

        # Copy positioning fields
        for field in DASHCARD_POSITION_FIELDS:
            if field in dashcard and dashcard[field] is not None:
                clean_dashcard[field] = dashcard[field]

        # Set unique negative ID
        clean_dashcard["id"] = temp_id

        # Remap dashboard_tab_id if present and we have a tab mapping
        source_tab_id = dashcard.get("dashboard_tab_id")
        if source_tab_id is not None:
            if tab_mapping and source_tab_id in tab_mapping:
                clean_dashcard["dashboard_tab_id"] = tab_mapping[source_tab_id]
                logger.debug(
                    f"Remapped dashboard_tab_id: {source_tab_id} -> "
                    f"{tab_mapping[source_tab_id]}"
                )
            else:
                # Keep original tab ID - may work if tabs were already created
                # with matching IDs, or will be null for single-tab dashboards
                if tab_mapping:
                    logger.warning(f"No tab mapping found for dashboard_tab_id {source_tab_id}")
                clean_dashcard["dashboard_tab_id"] = source_tab_id

        # Get source database ID for field remapping
        source_db_id = self._get_dashcard_database_id(dashcard)

        # Remap visualization_settings (card IDs, dashboard IDs, field IDs)
        if "visualization_settings" in dashcard:
            clean_dashcard["visualization_settings"] = (
                self.query_remapper.remap_dashcard_visualization_settings(
                    dashcard["visualization_settings"], source_db_id
                )
            )

        # Remap parameter_mappings
        if dashcard.get("parameter_mappings"):
            source_db_id = self._get_dashcard_database_id(dashcard)
            clean_dashcard["parameter_mappings"] = (
                self.query_remapper.remap_dashcard_parameter_mappings(
                    dashcard["parameter_mappings"], source_db_id
                )
            )

        # Remap series
        if dashcard.get("series"):
            clean_dashcard["series"] = self._remap_series(dashcard["series"])

        # Remap card_id
        source_card_id = dashcard.get("card_id")
        if source_card_id:
            target_card_id = self.id_mapper.resolve_card_id(source_card_id)
            if target_card_id:
                clean_dashcard["card_id"] = target_card_id
            else:
                logger.warning(f"Skipping dashcard with unmapped card_id: {source_card_id}")
                return None

        # Handle embedded card object (used by "Visualize another way" feature)
        # The card field contains visualization overrides and needs ID remapping
        if dashcard.get("card"):
            remapped_card = self._remap_embedded_card(dashcard["card"], source_db_id)
            if remapped_card:
                clean_dashcard["card"] = remapped_card

        # Remove excluded fields (but NOT 'card' since we handle it explicitly above)
        for field in DASHCARD_EXCLUDED_FIELDS:
            # Skip 'card' - we handle it specially for "Visualize another way"
            if field == "card":
                continue
            if field in clean_dashcard:
                del clean_dashcard[field]

        return clean_dashcard

    def _remap_embedded_card(
        self, card: dict[str, Any], source_db_id: int | None
    ) -> dict[str, Any] | None:
        """Remaps IDs in an embedded card object (for 'Visualize another way').

        When a dashcard uses 'Visualize another way', it stores an embedded card
        object with custom visualization settings. This card object contains
        references to the original card ID, database ID, and potentially field IDs
        that need to be remapped.

        Args:
            card: The embedded card object from the dashcard.
            source_db_id: The source database ID for field lookups.

        Returns:
            The remapped card object, or None if remapping fails.
        """
        import copy

        remapped_card = copy.deepcopy(card)

        # Remap card.id (reference to the source card)
        source_card_id = card.get("id")
        if source_card_id and isinstance(source_card_id, int):
            target_card_id = self.id_mapper.resolve_card_id(source_card_id)
            if target_card_id:
                remapped_card["id"] = target_card_id
                logger.debug(f"Remapped embedded card.id from {source_card_id} to {target_card_id}")
            else:
                logger.warning(
                    f"No mapping found for embedded card.id {source_card_id}. " f"Keeping original."
                )

        # Remap database_id if present
        if "database_id" in card and card["database_id"]:
            target_db_id = self.id_mapper.resolve_db_id(card["database_id"])
            if target_db_id:
                remapped_card["database_id"] = target_db_id
                logger.debug(
                    f"Remapped embedded card.database_id from {card['database_id']} "
                    f"to {target_db_id}"
                )

        # Remap dataset_query if present (for query-based visualizations)
        # Use remap_card_data to handle full card remapping including query
        if "dataset_query" in card and card["dataset_query"]:
            try:
                # Create a minimal card structure for remapping
                card_for_remap = {
                    "database_id": card.get("database_id"),
                    "dataset_query": card["dataset_query"],
                }
                remapped_data, success = self.query_remapper.remap_card_data(card_for_remap)
                if success:
                    remapped_card["dataset_query"] = remapped_data["dataset_query"]
            except Exception as e:
                logger.warning(f"Failed to remap embedded card dataset_query: {e}")

        # Remap visualization_settings if present
        if "visualization_settings" in card and card["visualization_settings"]:
            remapped_card["visualization_settings"] = (
                self.query_remapper.remap_dashcard_visualization_settings(
                    card["visualization_settings"], source_db_id
                )
            )

        # Remove immutable fields that shouldn't be sent on import
        immutable_fields = [
            "creator_id",
            "creator",
            "created_at",
            "updated_at",
            "made_public_by_id",
            "public_uuid",
            "moderation_reviews",
            "can_write",
            "entity_id",
        ]
        for field in immutable_fields:
            remapped_card.pop(field, None)

        return remapped_card

    def _get_dashcard_database_id(self, dashcard: dict[str, Any]) -> int | None:
        """Gets the database ID for a dashcard's card.

        Tries to get the database ID from:
        1. The manifest cards lookup using card_id
        2. The embedded card object (for 'Visualize another way' dashcards)
        3. The embedded card's dataset_query.database

        Args:
            dashcard: The dashcard.

        Returns:
            The database ID or None.
        """
        # First try to get from card_id via manifest
        source_card_id = dashcard.get("card_id")
        if source_card_id:
            for card in self.context.manifest.cards:
                if card.id == source_card_id:
                    return card.database_id

        # Fall back to embedded card object (for "Visualize another way")
        embedded_card = dashcard.get("card")
        if embedded_card:
            # Try database_id field
            db_id = embedded_card.get("database_id")
            if db_id and isinstance(db_id, int):
                return int(db_id)
            # Try dataset_query.database
            dataset_query = embedded_card.get("dataset_query")
            if dataset_query:
                query_db = dataset_query.get("database")
                if query_db and isinstance(query_db, int):
                    return int(query_db)
            # Try to lookup by embedded card.id in manifest
            embedded_card_id = embedded_card.get("id")
            if embedded_card_id:
                for card in self.context.manifest.cards:
                    if card.id == embedded_card_id:
                        return card.database_id

        return None

    def _remap_series(self, series: list[Any]) -> list[dict[str, int]]:
        """Remaps series card references.

        Args:
            series: The source series list.

        Returns:
            List of remapped series.
        """
        remapped_series = []
        for series_card in series:
            if isinstance(series_card, dict) and "id" in series_card:
                series_card_id = series_card["id"]
                target_id = self.id_mapper.resolve_card_id(series_card_id)
                if target_id:
                    remapped_series.append({"id": target_id})
                else:
                    logger.warning(f"Skipping series card with unmapped id: {series_card_id}")
        return remapped_series

    def _build_update_payload(
        self,
        name: str,
        payload: dict[str, Any],
        parameters: list[dict[str, Any]],
        dashcards: list[dict[str, Any]],
        tabs: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Builds the dashboard update payload.

        Args:
            name: Dashboard name.
            payload: The original payload.
            parameters: Remapped parameters.
            dashcards: Prepared dashcards.
            tabs: Tabs to create (with negative IDs for v57).

        Returns:
            The update payload.
        """
        update_payload: dict[str, Any] = {
            "name": name,
            "description": payload.get("description"),
            "parameters": parameters,
            "cache_ttl": payload.get("cache_ttl"),
        }

        # Include display settings
        if "width" in payload:
            update_payload["width"] = payload["width"]
        if "auto_apply_filters" in payload:
            update_payload["auto_apply_filters"] = payload["auto_apply_filters"]

        # Add tabs if any (must be sent together with dashcards in v57)
        if tabs:
            update_payload["tabs"] = tabs
            logger.debug(f"Including {len(tabs)} tabs in dashboard update")

        # Add dashcards if any
        if dashcards:
            update_payload["dashcards"] = dashcards
            logger.debug(f"Updating dashboard with {len(dashcards)} dashcards")

        # Remove None values
        return {k: v for k, v in update_payload.items() if v is not None}
