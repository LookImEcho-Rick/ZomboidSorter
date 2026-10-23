"""Portable-mode paths for the standalone Windows distribution."""

from __future__ import annotations

import sys
from pathlib import Path


def application_directory() -> Path:
    """Return the directory that contains the running application."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def portable_data_directory() -> Path | None:
    """Return the portable data folder when portable.flag is beside the app."""
    app_directory = application_directory()
    if not (app_directory / "portable.flag").is_file():
        return None
    return app_directory / "data"


def portable_settings_path() -> Path | None:
    """Return the INI settings file path in portable mode."""
    data_directory = portable_data_directory()
    if data_directory is None:
        return None
    return data_directory / "settings.ini"
