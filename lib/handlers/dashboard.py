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

            # Prepare dashcards
            dashcards_to_import = self._prepare_dashcards(dash_data.get("dashcards", []))

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

            # Update with dashcards and settings
            update_payload = self._build_update_payload(
                dashboard_name, payload, remapped_parameters, dashcards_to_import
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

    def _prepare_dashcards(self, dashcards: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Prepares dashcards for import by remapping IDs.

        Args:
            dashcards: The source dashcards.

        Returns:
            List of prepared dashcards.
        """
        prepared_dashcards = []
        next_temp_id = -1

        for dashcard in dashcards:
            clean_dashcard = self._prepare_single_dashcard(dashcard, next_temp_id)
            if clean_dashcard is not None:
                prepared_dashcards.append(clean_dashcard)
                next_temp_id -= 1

        return prepared_dashcards

    def _prepare_single_dashcard(
        self, dashcard: dict[str, Any], temp_id: int
    ) -> dict[str, Any] | None:
        """Prepares a single dashcard for import.

        Args:
            dashcard: The source dashcard.
            temp_id: The temporary ID to assign.

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

        # Copy visualization_settings
        if "visualization_settings" in dashcard:
          vis_settings = dashcard["visualization_settings"]

          # Remap columnValuesMapping if present
          if isinstance(vis_settings, dict):
              # Check nested visualization.columnValuesMapping
              if "visualization" in vis_settings and isinstance(vis_settings["visualization"], dict):
                  viz_config = vis_settings["visualization"]
                  if "columnValuesMapping" in viz_config:
                      viz_config["columnValuesMapping"] = self.query_remapper._remap_column_values_mapping(
                          viz_config["columnValuesMapping"]
                      )

              # Check top-level columnValuesMapping
              if "columnValuesMapping" in vis_settings:
                  vis_settings["columnValuesMapping"] = self.query_remapper._remap_column_values_mapping(
                      vis_settings["columnValuesMapping"]
                  )

          clean_dashcard["visualization_settings"] = vis_settings

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

        # Remove excluded fields
        for field in DASHCARD_EXCLUDED_FIELDS:
            if field in clean_dashcard:
                del clean_dashcard[field]

        return clean_dashcard

    def _get_dashcard_database_id(self, dashcard: dict[str, Any]) -> int | None:
        """Gets the database ID for a dashcard's card.

        Args:
            dashcard: The dashcard.

        Returns:
            The database ID or None.
        """
        source_card_id = dashcard.get("card_id")
        if not source_card_id:
            return None

        for card in self.context.manifest.cards:
            if card.id == source_card_id:
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
    ) -> dict[str, Any]:
        """Builds the dashboard update payload.

        Args:
            name: Dashboard name.
            payload: The original payload.
            parameters: Remapped parameters.
            dashcards: Prepared dashcards.

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

        # Add dashcards if any
        if dashcards:
            update_payload["dashcards"] = dashcards
            logger.debug(f"Updating dashboard with {len(dashcards)} dashcards")

        # Remove None values
        return {k: v for k, v in update_payload.items() if v is not None}
