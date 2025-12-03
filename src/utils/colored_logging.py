"""
Colored logging formatter for console output.
Colors log messages based on their level for better visibility.
"""

import logging


class ColoredFormatter(logging.Formatter):
    """Custom formatter that adds colors to log levels."""

    # ANSI color codes
    COLORS = {
        "DEBUG": "\033[36m",  # Cyan
        "INFO": "\033[32m",  # Green
        "WARNING": "\033[33m",  # Yellow
        "ERROR": "\033[31m",  # Red
        "CRITICAL": "\033[41m",  # Red background
    }
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"

    def format(self, record: logging.LogRecord) -> str:
        # Get color for this level
        color = self.COLORS.get(record.levelname, "")

        # Format the timestamp in dim
        original_msg = super().format(record)

        # Apply color to levelname
        if color:
            # Colorize the level name part
            colored_level = f"{self.BOLD}{color}{record.levelname}{self.RESET}"
            original_msg = original_msg.replace(record.levelname, colored_level, 1)

        return original_msg


def setup_colored_logging(level: int = logging.INFO) -> None:
    """
    Setup colored logging for the application.

    Args:
        level: Logging level (default: INFO)
    """
    # Create handler with colored formatter
    handler = logging.StreamHandler()
    handler.setLevel(level)

    # Format: timestamp (dim) | LEVEL (colored) | logger name | message
    fmt = "%(asctime)s %(levelname)s %(name)s: %(message)s"
    handler.setFormatter(ColoredFormatter(fmt))

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # Remove existing handlers to avoid duplicates
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
