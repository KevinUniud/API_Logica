"""Runtime configuration helpers (environment-driven) and logging setup.

Keep this module intentionally small: it exposes a few runtime defaults and
a convenience `configure_logging()` to initialize module loggers uniformly.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

from constants import DEFAULT_PROLOG_DIR


SWI_PROLOG_PATH: str = os.getenv("SWI_PROLOG_PATH", "swipl")
"""Path or executable name used to run SWI-Prolog."""

DEFAULT_TIMEOUT: int = int(os.getenv("DEFAULT_TIMEOUT", "10"))
"""Default timeout (seconds) used by bridge/run operations."""

PROLOG_DIR: Path = Path(os.getenv("PROLOG_DIR", str(DEFAULT_PROLOG_DIR))).resolve()
"""Directory containing Prolog sources used by the bridge."""


def configure_logging(level: int | str = logging.INFO) -> None:
    """Configure basic logging for the application when invoked.

    This is intentionally minimal; callers (e.g. server) can call this once on
    startup to enable module loggers.
    """
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
