"""Basic logging configuration (R7.4)."""

from __future__ import annotations

import logging

_CONFIGURED = False


def configure_logging(level: int = logging.INFO) -> logging.Logger:
    """Configure root logging once and return the finalsay logger."""
    global _CONFIGURED
    if not _CONFIGURED:
        logging.basicConfig(
            level=level,
            format="%(asctime)s %(levelname)s %(name)s %(message)s",
        )
        _CONFIGURED = True
    return logging.getLogger("finalsay")
