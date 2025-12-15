"""
Unit tests for lib/utils/logging.py

Tests for the setup_logging function with various argument combinations.
"""

import logging
import sys

from lib.utils.logging import setup_logging


class TestSetupLoggingNameOrLevel:
    """Tests for setup_logging with different argument combinations."""

    def teardown_method(self):
        """Clean up logger handlers after each test."""
        # Clean up both the specific logger and root logger
        for name in ["metabase_migration", "myapp", "test.module", ""]:
            logger = logging.getLogger(name)
            logger.handlers.clear()
            logger.setLevel(logging.NOTSET)

    def test_explicit_level_with_logger_name(self):
        """Test setup_logging with explicit level parameter."""
        logger = setup_logging("myapp", level="DEBUG")

        assert logger.name == "myapp"
        assert logger.level == logging.DEBUG

    def test_explicit_level_with_log_level_as_name(self):
        """Test setup_logging with log level string as first arg but explicit level override."""
        # When first arg looks like a log level but explicit level is also provided
        logger = setup_logging("INFO", level="DEBUG")

        # Should use "metabase_migration" as name since INFO looks like a level
        assert logger.name == "metabase_migration"
        assert logger.level == logging.DEBUG

    def test_logger_name_as_first_arg(self):
        """Test setup_logging with a module name as first argument."""
        logger = setup_logging("test.module")

        assert logger.name == "test.module"
        assert logger.level == logging.INFO  # Default level

    def test_log_level_as_first_arg(self):
        """Test setup_logging with log level as first argument."""
        logger = setup_logging("WARNING")

        assert logger.name == "metabase_migration"
        assert logger.level == logging.WARNING

    def test_lowercase_log_level(self):
        """Test setup_logging with lowercase log level."""
        logger = setup_logging("debug")

        assert logger.name == "metabase_migration"
        assert logger.level == logging.DEBUG

    def test_critical_level(self):
        """Test setup_logging with CRITICAL level."""
        logger = setup_logging("CRITICAL")

        assert logger.level == logging.CRITICAL

    def test_handler_created_when_none_exist(self):
        """Test that handler is created when root logger has no handlers."""
        # Clear all handlers first
        root_logger = logging.getLogger()
        root_logger.handlers.clear()

        _ = setup_logging("INFO")

        # Should have created a handler on root logger
        assert len(root_logger.handlers) > 0
        assert isinstance(root_logger.handlers[0], logging.StreamHandler)

    def test_handler_not_duplicated(self):
        """Test that handlers are not duplicated on multiple calls."""
        root_logger = logging.getLogger()
        root_logger.handlers.clear()

        # First call creates handler
        setup_logging("INFO")
        handler_count = len(root_logger.handlers)

        # Second call should not add another handler
        setup_logging("DEBUG")

        assert len(root_logger.handlers) == handler_count

    def test_handler_formatter(self):
        """Test that handler has correct formatter."""
        root_logger = logging.getLogger()
        root_logger.handlers.clear()

        setup_logging("INFO")

        handler = root_logger.handlers[0]
        formatter = handler.formatter
        assert formatter is not None
        # Check formatter format includes expected parts
        assert "%(asctime)s" in formatter._fmt
        assert "%(name)s" in formatter._fmt
        assert "%(levelname)s" in formatter._fmt
        assert "%(message)s" in formatter._fmt

    def test_handler_stream_is_stdout(self):
        """Test that handler streams to stdout."""
        root_logger = logging.getLogger()
        root_logger.handlers.clear()

        setup_logging("INFO")

        handler = root_logger.handlers[0]
        assert handler.stream == sys.stdout

    def test_logger_propagate_is_true(self):
        """Test that logger propagate is set to True."""
        logger = setup_logging("myapp")

        assert logger.propagate is True

    def test_invalid_log_level_defaults_to_info(self):
        """Test that invalid log level defaults to INFO."""
        logger = setup_logging("INVALID_LEVEL")

        # "INVALID_LEVEL" is not in log_levels, so treated as logger name
        assert logger.name == "INVALID_LEVEL"
        assert logger.level == logging.INFO

    def test_explicit_invalid_level_defaults_to_info(self):
        """Test that explicit invalid level defaults to INFO."""
        logger = setup_logging("myapp", level="INVALID")

        assert logger.name == "myapp"
        assert logger.level == logging.INFO  # getattr returns default

    def test_root_logger_level_set(self):
        """Test that root logger level is also set."""
        root_logger = logging.getLogger()
        root_logger.handlers.clear()

        setup_logging("DEBUG")

        assert root_logger.level == logging.DEBUG

    def test_all_log_levels(self):
        """Test all valid log levels."""
        log_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        expected_levels = [
            logging.DEBUG,
            logging.INFO,
            logging.WARNING,
            logging.ERROR,
            logging.CRITICAL,
        ]

        for level_str, expected in zip(log_levels, expected_levels, strict=False):
            # Clean up for each iteration
            root_logger = logging.getLogger()
            root_logger.handlers.clear()

            logger = setup_logging(level_str)
            assert logger.level == expected, f"Failed for level {level_str}"
