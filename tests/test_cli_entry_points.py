"""
Unit tests for CLI entry points (export_metabase.py, import_metabase.py, sync_metabase.py).

Tests cover main() functions and exit code handling.
"""

from unittest.mock import Mock, patch

import pytest

from lib.client import MetabaseAPIError


class TestExportMetabaseMain:
    """Tests for export_metabase.main() function."""

    @patch("export_metabase.ExportService")
    @patch("export_metabase.setup_logging")
    @patch("export_metabase.get_export_args")
    def test_main_success(self, mock_get_args, mock_setup_logging, mock_export_service):
        """Test successful export execution."""
        from export_metabase import main

        mock_config = Mock()
        mock_config.log_level = "INFO"
        mock_get_args.return_value = mock_config

        mock_exporter = Mock()
        mock_export_service.return_value = mock_exporter

        main()

        mock_get_args.assert_called_once()
        mock_setup_logging.assert_called_once_with("INFO")
        mock_export_service.assert_called_once_with(mock_config)
        mock_exporter.run_export.assert_called_once()

    @patch("export_metabase.ExportService")
    @patch("export_metabase.setup_logging")
    @patch("export_metabase.get_export_args")
    def test_main_api_error_exit_code_1(
        self, mock_get_args, mock_setup_logging, mock_export_service
    ):
        """Test that MetabaseAPIError causes exit code 1."""
        from export_metabase import main

        mock_config = Mock()
        mock_config.log_level = "INFO"
        mock_get_args.return_value = mock_config

        mock_exporter = Mock()
        mock_exporter.run_export.side_effect = MetabaseAPIError("API Error")
        mock_export_service.return_value = mock_exporter

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 1

    @patch("export_metabase.ExportService")
    @patch("export_metabase.setup_logging")
    @patch("export_metabase.get_export_args")
    def test_main_generic_error_exit_code_2(
        self, mock_get_args, mock_setup_logging, mock_export_service
    ):
        """Test that generic exceptions cause exit code 2."""
        from export_metabase import main

        mock_config = Mock()
        mock_config.log_level = "INFO"
        mock_get_args.return_value = mock_config

        mock_exporter = Mock()
        mock_exporter.run_export.side_effect = ValueError("Some error")
        mock_export_service.return_value = mock_exporter

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 2


class TestImportMetabaseMain:
    """Tests for import_metabase.main() function."""

    @patch("import_metabase.ImportService")
    @patch("import_metabase.setup_logging")
    @patch("import_metabase.get_import_args")
    def test_main_success(self, mock_get_args, mock_setup_logging, mock_import_service):
        """Test successful import execution."""
        from import_metabase import main

        mock_config = Mock()
        mock_config.log_level = "DEBUG"
        mock_get_args.return_value = mock_config

        mock_importer = Mock()
        mock_import_service.return_value = mock_importer

        main()

        mock_get_args.assert_called_once()
        mock_setup_logging.assert_called_once_with("DEBUG")
        mock_import_service.assert_called_once_with(mock_config)
        mock_importer.run_import.assert_called_once()

    @patch("import_metabase.ImportService")
    @patch("import_metabase.setup_logging")
    @patch("import_metabase.get_import_args")
    def test_main_api_error_exit_code_1(
        self, mock_get_args, mock_setup_logging, mock_import_service
    ):
        """Test that MetabaseAPIError causes exit code 1."""
        from import_metabase import main

        mock_config = Mock()
        mock_config.log_level = "INFO"
        mock_get_args.return_value = mock_config

        mock_importer = Mock()
        mock_importer.run_import.side_effect = MetabaseAPIError("API Error")
        mock_import_service.return_value = mock_importer

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 1

    @patch("import_metabase.ImportService")
    @patch("import_metabase.setup_logging")
    @patch("import_metabase.get_import_args")
    def test_main_file_not_found_exit_code_2(
        self, mock_get_args, mock_setup_logging, mock_import_service
    ):
        """Test that FileNotFoundError causes exit code 2."""
        from import_metabase import main

        mock_config = Mock()
        mock_config.log_level = "INFO"
        mock_get_args.return_value = mock_config

        mock_importer = Mock()
        mock_importer.run_import.side_effect = FileNotFoundError("File not found")
        mock_import_service.return_value = mock_importer

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 2

    @patch("import_metabase.ImportService")
    @patch("import_metabase.setup_logging")
    @patch("import_metabase.get_import_args")
    def test_main_value_error_exit_code_2(
        self, mock_get_args, mock_setup_logging, mock_import_service
    ):
        """Test that ValueError causes exit code 2."""
        from import_metabase import main

        mock_config = Mock()
        mock_config.log_level = "INFO"
        mock_get_args.return_value = mock_config

        mock_importer = Mock()
        mock_importer.run_import.side_effect = ValueError("Invalid value")
        mock_import_service.return_value = mock_importer

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 2

    @patch("import_metabase.ImportService")
    @patch("import_metabase.setup_logging")
    @patch("import_metabase.get_import_args")
    def test_main_runtime_error_exit_code_4(
        self, mock_get_args, mock_setup_logging, mock_import_service
    ):
        """Test that RuntimeError causes exit code 4."""
        from import_metabase import main

        mock_config = Mock()
        mock_config.log_level = "INFO"
        mock_get_args.return_value = mock_config

        mock_importer = Mock()
        mock_importer.run_import.side_effect = RuntimeError("Runtime error")
        mock_import_service.return_value = mock_importer

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 4

    @patch("import_metabase.ImportService")
    @patch("import_metabase.setup_logging")
    @patch("import_metabase.get_import_args")
    def test_main_generic_error_exit_code_3(
        self, mock_get_args, mock_setup_logging, mock_import_service
    ):
        """Test that other exceptions cause exit code 3."""
        from import_metabase import main

        mock_config = Mock()
        mock_config.log_level = "INFO"
        mock_get_args.return_value = mock_config

        mock_importer = Mock()
        mock_importer.run_import.side_effect = KeyError("Some key error")
        mock_import_service.return_value = mock_importer

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 3


class TestSyncMetabaseMain:
    """Tests for sync_metabase.main() function."""

    @patch("sync_metabase.ImportService")
    @patch("sync_metabase.ExportService")
    @patch("sync_metabase.setup_logging")
    @patch("sync_metabase.get_sync_args")
    def test_main_success(
        self, mock_get_args, mock_setup_logging, mock_export_service, mock_import_service
    ):
        """Test successful sync execution."""
        from sync_metabase import main

        mock_config = Mock()
        mock_config.log_level = "INFO"
        mock_config.source_url = "https://source.example.com"
        mock_config.target_url = "https://target.example.com"
        mock_config.export_dir = "/tmp/export"
        mock_config.to_export_config.return_value = Mock()
        mock_config.to_import_config.return_value = Mock()
        mock_get_args.return_value = mock_config

        mock_exporter = Mock()
        mock_export_service.return_value = mock_exporter

        mock_importer = Mock()
        mock_import_service.return_value = mock_importer

        main()

        mock_get_args.assert_called_once()
        mock_setup_logging.assert_called_once_with("INFO")
        mock_exporter.run_export.assert_called_once()
        mock_importer.run_import.assert_called_once()

    @patch("sync_metabase.ImportService")
    @patch("sync_metabase.ExportService")
    @patch("sync_metabase.setup_logging")
    @patch("sync_metabase.get_sync_args")
    def test_main_export_api_error_exit_code_1(
        self, mock_get_args, mock_setup_logging, mock_export_service, mock_import_service
    ):
        """Test that MetabaseAPIError during export causes exit code 1."""
        from sync_metabase import main

        mock_config = Mock()
        mock_config.log_level = "INFO"
        mock_config.source_url = "https://source.example.com"
        mock_config.target_url = "https://target.example.com"
        mock_config.export_dir = "/tmp/export"
        mock_config.to_export_config.return_value = Mock()
        mock_get_args.return_value = mock_config

        mock_exporter = Mock()
        mock_exporter.run_export.side_effect = MetabaseAPIError("API Error")
        mock_export_service.return_value = mock_exporter

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 1

    @patch("sync_metabase.ImportService")
    @patch("sync_metabase.ExportService")
    @patch("sync_metabase.setup_logging")
    @patch("sync_metabase.get_sync_args")
    def test_main_export_generic_error_exit_code_2(
        self, mock_get_args, mock_setup_logging, mock_export_service, mock_import_service
    ):
        """Test that generic exception during export causes exit code 2."""
        from sync_metabase import main

        mock_config = Mock()
        mock_config.log_level = "INFO"
        mock_config.source_url = "https://source.example.com"
        mock_config.target_url = "https://target.example.com"
        mock_config.export_dir = "/tmp/export"
        mock_config.to_export_config.return_value = Mock()
        mock_get_args.return_value = mock_config

        mock_exporter = Mock()
        mock_exporter.run_export.side_effect = ValueError("Some error")
        mock_export_service.return_value = mock_exporter

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 2

    @patch("sync_metabase.ImportService")
    @patch("sync_metabase.ExportService")
    @patch("sync_metabase.setup_logging")
    @patch("sync_metabase.get_sync_args")
    def test_main_import_api_error_exit_code_3(
        self, mock_get_args, mock_setup_logging, mock_export_service, mock_import_service
    ):
        """Test that MetabaseAPIError during import causes exit code 3."""
        from sync_metabase import main

        mock_config = Mock()
        mock_config.log_level = "INFO"
        mock_config.source_url = "https://source.example.com"
        mock_config.target_url = "https://target.example.com"
        mock_config.export_dir = "/tmp/export"
        mock_config.to_export_config.return_value = Mock()
        mock_config.to_import_config.return_value = Mock()
        mock_get_args.return_value = mock_config

        mock_exporter = Mock()
        mock_export_service.return_value = mock_exporter

        mock_importer = Mock()
        mock_importer.run_import.side_effect = MetabaseAPIError("API Error")
        mock_import_service.return_value = mock_importer

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 3

    @patch("sync_metabase.ImportService")
    @patch("sync_metabase.ExportService")
    @patch("sync_metabase.setup_logging")
    @patch("sync_metabase.get_sync_args")
    def test_main_import_file_not_found_exit_code_4(
        self, mock_get_args, mock_setup_logging, mock_export_service, mock_import_service
    ):
        """Test that FileNotFoundError during import causes exit code 4."""
        from sync_metabase import main

        mock_config = Mock()
        mock_config.log_level = "INFO"
        mock_config.source_url = "https://source.example.com"
        mock_config.target_url = "https://target.example.com"
        mock_config.export_dir = "/tmp/export"
        mock_config.to_export_config.return_value = Mock()
        mock_config.to_import_config.return_value = Mock()
        mock_get_args.return_value = mock_config

        mock_exporter = Mock()
        mock_export_service.return_value = mock_exporter

        mock_importer = Mock()
        mock_importer.run_import.side_effect = FileNotFoundError("File not found")
        mock_import_service.return_value = mock_importer

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 4

    @patch("sync_metabase.ImportService")
    @patch("sync_metabase.ExportService")
    @patch("sync_metabase.setup_logging")
    @patch("sync_metabase.get_sync_args")
    def test_main_import_runtime_error_exit_code_5(
        self, mock_get_args, mock_setup_logging, mock_export_service, mock_import_service
    ):
        """Test that RuntimeError during import causes exit code 5."""
        from sync_metabase import main

        mock_config = Mock()
        mock_config.log_level = "INFO"
        mock_config.source_url = "https://source.example.com"
        mock_config.target_url = "https://target.example.com"
        mock_config.export_dir = "/tmp/export"
        mock_config.to_export_config.return_value = Mock()
        mock_config.to_import_config.return_value = Mock()
        mock_get_args.return_value = mock_config

        mock_exporter = Mock()
        mock_export_service.return_value = mock_exporter

        mock_importer = Mock()
        mock_importer.run_import.side_effect = RuntimeError("Runtime error")
        mock_import_service.return_value = mock_importer

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 5

    @patch("sync_metabase.ImportService")
    @patch("sync_metabase.ExportService")
    @patch("sync_metabase.setup_logging")
    @patch("sync_metabase.get_sync_args")
    def test_main_import_generic_error_exit_code_6(
        self, mock_get_args, mock_setup_logging, mock_export_service, mock_import_service
    ):
        """Test that other exceptions during import cause exit code 6."""
        from sync_metabase import main

        mock_config = Mock()
        mock_config.log_level = "INFO"
        mock_config.source_url = "https://source.example.com"
        mock_config.target_url = "https://target.example.com"
        mock_config.export_dir = "/tmp/export"
        mock_config.to_export_config.return_value = Mock()
        mock_config.to_import_config.return_value = Mock()
        mock_get_args.return_value = mock_config

        mock_exporter = Mock()
        mock_export_service.return_value = mock_exporter

        mock_importer = Mock()
        mock_importer.run_import.side_effect = KeyError("Some key error")
        mock_import_service.return_value = mock_importer

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 6


class TestBackwardCompatibilityAliases:
    """Tests for backward compatibility aliases."""

    def test_export_metabase_alias(self):
        """Test MetabaseExporter alias exists."""
        from export_metabase import MetabaseExporter
        from lib.services import ExportService

        assert MetabaseExporter is ExportService

    def test_import_metabase_alias(self):
        """Test MetabaseImporter alias exists."""
        from import_metabase import MetabaseImporter
        from lib.services import ImportService

        assert MetabaseImporter is ImportService

    def test_export_imports_client_classes(self):
        """Test that export_metabase exports client classes for backward compat."""
        from export_metabase import MetabaseAPIError, MetabaseClient
        from lib.client import MetabaseAPIError as OriginalError
        from lib.client import MetabaseClient as OriginalClient

        assert MetabaseClient is OriginalClient
        assert MetabaseAPIError is OriginalError

    def test_import_imports_client_classes(self):
        """Test that import_metabase exports client classes for backward compat."""
        from import_metabase import MetabaseAPIError, MetabaseClient
        from lib.client import MetabaseAPIError as OriginalError
        from lib.client import MetabaseClient as OriginalClient

        assert MetabaseClient is OriginalClient
        assert MetabaseAPIError is OriginalError
