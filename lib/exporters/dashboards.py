"""Dashboard export logic.

This module handles exporting dashboards from the source Metabase instance.
"""

import logging
from pathlib import Path

from lib.client import MetabaseAPIError, MetabaseClient
from lib.exporters.cards import CardExporter
from lib.models import Dashboard, Manifest
from lib.utils import calculate_checksum, sanitize_filename, write_json_file

logger = logging.getLogger("metabase_migration")


class DashboardExporter:
    """Handles exporting dashboards."""

    def __init__(
        self,
        client: MetabaseClient,
        manifest: Manifest,
        export_dir: Path,
        card_exporter: CardExporter,
        collection_path_map: dict[int, str],
    ):
        """Initialize the DashboardExporter.

        Args:
            client: Metabase API client
            manifest: Manifest object to populate with dashboard data
            export_dir: Base directory for exports
            card_exporter: CardExporter instance for exporting card dependencies
            collection_path_map: Mapping of collection IDs to their paths
        """
        self.client = client
        self.manifest = manifest
        self.export_dir = export_dir
        self.card_exporter = card_exporter
        self.collection_path_map = collection_path_map

    def export_dashboard(self, dashboard_id: int, base_path: str) -> None:
        """Export a single dashboard.

        Args:
            dashboard_id: The ID of the dashboard to export
            base_path: The base path for the export
        """
        try:
            logger.debug(f"Exporting dashboard ID {dashboard_id}")
            dashboard_data = self.client.get_dashboard(dashboard_id)

            dash_slug = sanitize_filename(dashboard_data["name"])
            file_path_str = f"{base_path}/dashboards/dash_{dashboard_id}_{dash_slug}.json"
            file_path = self.export_dir / file_path_str

            write_json_file(dashboard_data, file_path)
            checksum = calculate_checksum(file_path)

            # Extract card IDs from dashcards
            card_ids = []
            if dashboard_data.get("dashcards"):
                for dashcard in dashboard_data["dashcards"]:
                    if dashcard.get("card_id"):
                        card_ids.append(dashcard["card_id"])

            # Extract card IDs from dashboard parameters (filters with values from cards)
            if dashboard_data.get("parameters"):
                for param in dashboard_data["parameters"]:
                    if "values_source_config" in param and isinstance(
                        param["values_source_config"], dict
                    ):
                        source_card_id = param["values_source_config"].get("card_id")
                        if source_card_id and source_card_id not in card_ids:
                            card_ids.append(source_card_id)
                            logger.info(
                                f"     Dashboard parameter '{param.get('name')}' references card {source_card_id} - will be exported as dependency"
                            )

            # Export all card dependencies
            for card_id in card_ids:
                if card_id not in self.card_exporter.exported_cards:
                    logger.info(
                        f"     Exporting card {card_id} (required by dashboard {dashboard_id})"
                    )
                    try:
                        # Fetch the card to determine its collection
                        card_data = self.client.get_card(card_id)
                        card_collection_id = card_data.get("collection_id")

                        # Determine the base path for the card
                        if card_collection_id and card_collection_id in self.collection_path_map:
                            card_base_path = self.collection_path_map[card_collection_id]
                        else:
                            # Use a special "dependencies" folder for cards outside the export scope
                            card_base_path = "dependencies"
                            logger.info(
                                f"        Card {card_id} is outside export scope, placing in '{card_base_path}' folder"
                            )

                        # Export the card with its dependencies
                        self.card_exporter.export_card_with_dependencies(card_id, card_base_path)

                    except MetabaseAPIError as e:
                        logger.error(f"        Failed to export card {card_id}: {e}")
                        logger.warning(
                            f"        Dashboard {dashboard_id} may fail to import due to missing card {card_id}"
                        )

            dashboard_obj = Dashboard(
                id=dashboard_id,
                name=dashboard_data["name"],
                collection_id=dashboard_data.get("collection_id"),
                ordered_cards=card_ids,
                file_path=file_path_str,
                checksum=checksum,
                archived=dashboard_data.get("archived", False),
            )
            self.manifest.dashboards.append(dashboard_obj)
            logger.info(f"  -> Exported Dashboard: '{dashboard_data['name']}' (ID: {dashboard_id})")

        except MetabaseAPIError as e:
            logger.error(f"Failed to export dashboard ID {dashboard_id}: {e}")
        except Exception as e:
            logger.error(
                f"An unexpected error occurred while exporting dashboard ID {dashboard_id}: {e}"
            )
