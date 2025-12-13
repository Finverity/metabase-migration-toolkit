"""Logging configuration utilities."""

import logging
import sys


def setup_logging(name_or_level: str = "INFO", level: str | None = None) -> logging.Logger:
    """Configures and returns a structured logger.

    Args:
        name_or_level: Either a logger name (e.g., __name__) or a log level (e.g., "INFO").
                       If it looks like a log level, it's used as the level.
                       If it looks like a module name, it's used as the logger name.
        level: Optional explicit log level. If provided, overrides name_or_level interpretation.

    Returns:
        A configured logger instance.
    """
    # Determine if first argument is a log level or a logger name
    log_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}

    if level is not None:
        # Explicit level provided
        log_level_str = level
        logger_name = (
            name_or_level if name_or_level.upper() not in log_levels else "metabase_migration"
        )
    elif name_or_level.upper() in log_levels:
        # First argument is a log level
        log_level_str = name_or_level
        logger_name = "metabase_migration"
    else:
        # First argument is a logger name
        logger_name = name_or_level
        log_level_str = "INFO"

    log_level = getattr(logging, log_level_str.upper(), logging.INFO)

    # Configure the root logger to ensure all loggers inherit the level and handler
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    # Only add handler if root logger doesn't have handlers
    if not root_logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
        handler.setFormatter(formatter)
        root_logger.addHandler(handler)

    # Get the specific logger (it will inherit from root)
    logger = logging.getLogger(logger_name)
    # Ensure logger uses root handlers to avoid duplicate outputs
    logger.propagate = True
    logger.setLevel(log_level)

    return logger
