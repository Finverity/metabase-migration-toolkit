"""Dashboard import logic.

This module handles importing dashboards from the export manifest to the
target Metabase instance, including dashcards, parameters, and filters.
"""

import logging
from pathlib import Path
from typing import Any, Literal, cast

from tqdm import tqdm

from lib.client import MetabaseClient
from lib.conflict_resolution import ConflictResolver
from lib.id_remapping import IDRemapper
from lib.models import Dashboard, ImportReport, ImportReportItem, Manifest
from lib.utils import clean_for_create, read_json_file

logger = logging.getLogger("metabase_migration")


class DashboardImporter:
    """Handles importing dashboards to a target Metabase instance."""

    def __init__(
        self,
        client: MetabaseClient,
        manifest: Manifest,
        id_remapper: IDRemapper,
        conflict_resolver: ConflictResolver,
        report: ImportReport,
        export_dir: Path,
        collection_map: dict[int, int],
        card_map: dict[int, int],
        include_archived: bool = False,
    ) -> None:
        """Initialize the dashboard importer.

        Args:
            client: Metabase API client for the target instance
            manifest: Export manifest containing dashboards
            id_remapper: ID remapper for field IDs
            conflict_resolver: Conflict resolution handler
            report: Import report for tracking results
            export_dir: Directory containing exported files
            collection_map: Mapping of source to target collection IDs
            card_map: Mapping of source to target card IDs
            include_archived: Whether to include archived dashboards
        """
        self.client = client
        self.manifest = manifest
        self.id_remapper = id_remapper
        self.conflict_resolver = conflict_resolver
        self.report = report
        self.export_dir = export_dir
        self.collection_map = collection_map
        self.card_map = card_map
        self.include_archived = include_archived

    def import_dashboards(self) -> None:
        """Import all dashboards from the manifest."""
        for dash in tqdm(
            sorted(self.manifest.dashboards, key=lambda d: d.file_path), desc="Importing Dashboards"
        ):
            if dash.archived and not self.include_archived:
                continue

            try:
                self._import_single_dashboard(dash)
            except Exception as e:
                logger.error(
                    f"Failed to import dashboard '{dash.name}' (ID: {dash.id}): {e}", exc_info=True
                )
                self.report.add(
                    ImportReportItem("dashboard", "failed", dash.id, None, dash.name, str(e))
                )

    def _import_single_dashboard(self, dash: Dashboard) -> None:
        """Import a single dashboard.

        Args:
            dash: Dashboard to import
        """
        dash_data = read_json_file(self.export_dir / dash.file_path)

        # Remap collection
        target_collection_id = (
            self.collection_map.get(dash.collection_id) if dash.collection_id else None
        )
        dash_data["collection_id"] = target_collection_id

        # Prepare dashcards for import
        dashcards_to_import = self._prepare_dashcards(dash_data)

        # Clean dashboard data and remap card IDs and field IDs in parameters
        payload = clean_for_create(dash_data)
        remapped_parameters = self._remap_parameters(payload.get("parameters", []))

        # Check for existing dashboard and handle conflicts
        existing_dashboard = self.conflict_resolver.find_existing_dashboard_in_collection(
            dash.name, target_collection_id
        )

        dashboard_name = dash.name
        dashboard_id = None
        action_taken: str = "created"

        if existing_dashboard:
            dashboard_id, action_taken = self._handle_existing_dashboard(
                dash, existing_dashboard, target_collection_id
            )
            if action_taken == "skipped":
                return
            dashboard_name = dash.name if action_taken == "updated" else dashboard_name

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

        # Update dashboard with dashcards and other settings
        self._update_dashboard_with_dashcards(
            dashboard_id, dashboard_name, payload, remapped_parameters, dashcards_to_import
        )

        self.report.add(
            ImportReportItem(
                "dashboard",
                cast(
                    Literal["created", "updated", "skipped", "failed", "success", "error"],
                    action_taken,
                ),
                dash.id,
                dashboard_id,
                dashboard_name,
            )
        )
        logger.debug(
            f"Successfully {action_taken} dashboard '{dashboard_name}' (ID: {dashboard_id})"
        )

    def _prepare_dashcards(self, dash_data: dict) -> list[dict]:
        """Prepare dashcards for import by remapping IDs and cleaning fields.

        Args:
            dash_data: Dashboard data dictionary

        Returns:
            List of cleaned dashcards ready for import
        """
        dashcards_to_import: list[dict[str, Any]] = []
        if "dashcards" not in dash_data:
            return dashcards_to_import

        next_temp_id = -1

        for dashcard in dash_data["dashcards"]:
            clean_dashcard = self._clean_dashcard(dashcard, next_temp_id)
            next_temp_id -= 1

            # Remap card_id to target (if it's a regular card, not a text/heading)
            source_card_id = dashcard.get("card_id")
            if source_card_id:
                if source_card_id in self.card_map:
                    clean_dashcard["card_id"] = self.card_map[source_card_id]
                else:
                    logger.warning(f"Skipping dashcard with unmapped card_id: {source_card_id}")
                    continue

            dashcards_to_import.append(clean_dashcard)

        return dashcards_to_import

    def _clean_dashcard(self, dashcard: dict, temp_id: int) -> dict:
        """Clean a dashcard by removing auto-generated fields and remapping IDs.

        Args:
            dashcard: Source dashcard
            temp_id: Temporary ID for the dashcard

        Returns:
            Cleaned dashcard dictionary
        """
        clean_dashcard = {}

        # Fields to explicitly exclude
        excluded_fields = {
            "dashboard_id",
            "created_at",
            "updated_at",
            "entity_id",
            "card",
            "action_id",
            "collection_authority_level",
            "dashboard_tab_id",
        }

        # Copy only essential positioning and display fields
        for field in ["col", "row", "size_x", "size_y"]:
            if field in dashcard and dashcard[field] is not None:
                clean_dashcard[field] = dashcard[field]

        # Set unique negative ID for this dashcard
        clean_dashcard["id"] = temp_id

        # Copy visualization_settings if present
        if "visualization_settings" in dashcard:
            clean_dashcard["visualization_settings"] = dashcard["visualization_settings"]

        # Copy and remap parameter_mappings if present
        if "parameter_mappings" in dashcard and dashcard["parameter_mappings"]:
            clean_dashcard["parameter_mappings"] = self._remap_parameter_mappings(
                dashcard["parameter_mappings"], dashcard.get("card_id")
            )

        # Copy and remap series if present (for combo charts)
        if "series" in dashcard and dashcard["series"]:
            clean_dashcard["series"] = self._remap_series(dashcard["series"])

        # Final safety check: ensure no excluded fields made it through
        for excluded_field in excluded_fields:
            if excluded_field in clean_dashcard:
                del clean_dashcard[excluded_field]
                logger.debug(f"Removed excluded field '{excluded_field}' from dashcard")

        return clean_dashcard

    def _remap_parameter_mappings(
        self, parameter_mappings: list[dict], source_card_id: int | None
    ) -> list[dict]:
        """Remap parameter mappings with card and field IDs.

        Args:
            parameter_mappings: List of parameter mappings
            source_card_id: Source card ID for field remapping

        Returns:
            List of remapped parameter mappings
        """
        remapped_mappings = []

        # Get the database ID for this dashcard's card (for field remapping)
        dashcard_db_id = None
        if source_card_id:
            for manifest_card in self.manifest.cards:
                if manifest_card.id == source_card_id:
                    dashcard_db_id = manifest_card.database_id
                    break

        for param_mapping in parameter_mappings:
            clean_param = param_mapping.copy()

            # Remap card_id in parameter_mappings
            if "card_id" in clean_param:
                source_param_card_id = clean_param["card_id"]
                if source_param_card_id in self.card_map:
                    clean_param["card_id"] = self.card_map[source_param_card_id]

            # Remap field IDs in parameter mapping target
            if "target" in clean_param and dashcard_db_id:
                clean_param["target"] = self.id_remapper.remap_field_ids_recursively(
                    clean_param["target"], dashcard_db_id
                )

            remapped_mappings.append(clean_param)

        return remapped_mappings

    def _remap_series(self, series: list[dict]) -> list[dict]:
        """Remap series card IDs.

        Args:
            series: List of series cards

        Returns:
            List of remapped series cards
        """
        remapped_series = []
        for series_card in series:
            if isinstance(series_card, dict) and "id" in series_card:
                series_card_id = series_card["id"]
                if series_card_id in self.card_map:
                    remapped_series.append({"id": self.card_map[series_card_id]})
                else:
                    logger.warning(f"Skipping series card with unmapped id: {series_card_id}")
        return remapped_series

    def _remap_parameters(self, parameters: list[dict]) -> list[dict]:
        """Remap field IDs in dashboard parameters.

        Args:
            parameters: List of dashboard parameters

        Returns:
            List of remapped parameters
        """
        remapped_params = []
        for param in parameters:
            clean_param = param.copy()

            # Remap field IDs in values_source_config if present
            if "values_source_config" in clean_param:
                values_config = clean_param["values_source_config"]

                # Remap card_id if present
                if "card_id" in values_config:
                    source_card_id = values_config["card_id"]
                    if source_card_id in self.card_map:
                        values_config["card_id"] = self.card_map[source_card_id]

                # Remap value_field if present
                if "value_field" in values_config:
                    # Find the database ID for this card
                    source_card_id = values_config.get("card_id")
                    if source_card_id:
                        # Look up the original card ID before remapping
                        original_card_id = None
                        for src_id, tgt_id in self.card_map.items():
                            if tgt_id == values_config["card_id"]:
                                original_card_id = src_id
                                break

                        if original_card_id:
                            # Find the database ID for this card
                            for manifest_card in self.manifest.cards:
                                if manifest_card.id == original_card_id:
                                    db_id = manifest_card.database_id
                                    values_config["value_field"] = (
                                        self.id_remapper.remap_field_ids_recursively(
                                            values_config["value_field"], db_id
                                        )
                                    )
                                    break

            remapped_params.append(clean_param)

        return remapped_params

    def _handle_existing_dashboard(
        self, dash: Dashboard, existing_dashboard: dict, target_collection_id: int | None
    ) -> tuple[int | None, str]:
        """Handle an existing dashboard based on conflict strategy.

        Args:
            dash: Source dashboard
            existing_dashboard: Existing target dashboard
            target_collection_id: Target collection ID

        Returns:
            Tuple of (dashboard_id, action_taken)
        """
        if self.conflict_resolver.should_skip(existing_dashboard):
            self.report.add(
                ImportReportItem(
                    "dashboard",
                    "skipped",
                    dash.id,
                    existing_dashboard["id"],
                    dash.name,
                    "Already exists (skipped)",
                )
            )
            logger.debug(
                f"Skipped dashboard '{dash.name}' - already exists with ID {existing_dashboard['id']}"
            )
            return existing_dashboard["id"], "skipped"

        elif self.conflict_resolver.should_overwrite(existing_dashboard):
            return existing_dashboard["id"], "updated"

        elif self.conflict_resolver.should_rename(existing_dashboard):
            new_name = self.conflict_resolver.generate_unique_name(
                dash.name, target_collection_id, "dashboard"
            )
            logger.info(f"Renamed dashboard '{dash.name}' to '{new_name}' to avoid conflict")
            return None, "created"

        return None, "created"

    def _update_dashboard_with_dashcards(
        self,
        dashboard_id: int,
        dashboard_name: str,
        payload: dict,
        remapped_parameters: list[dict],
        dashcards_to_import: list[dict],
    ) -> None:
        """Update dashboard with dashcards and other settings.

        Args:
            dashboard_id: Target dashboard ID
            dashboard_name: Dashboard name
            payload: Dashboard payload
            remapped_parameters: Remapped parameters
            dashcards_to_import: List of dashcards to import
        """
        update_payload = {
            "name": dashboard_name,
            "description": payload.get("description"),
            "parameters": remapped_parameters,
            "dashcards": dashcards_to_import,
        }

        # Add optional fields if present
        if "enable_embedding" in payload:
            update_payload["enable_embedding"] = payload["enable_embedding"]
        if "embedding_params" in payload:
            update_payload["embedding_params"] = payload["embedding_params"]
        if "cache_ttl" in payload:
            update_payload["cache_ttl"] = payload["cache_ttl"]
        if "auto_apply_filters" in payload:
            update_payload["auto_apply_filters"] = payload["auto_apply_filters"]

        self.client.update_dashboard(dashboard_id, update_payload)
