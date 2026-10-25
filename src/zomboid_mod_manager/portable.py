"""App-owned data paths for standard and portable distributions."""

from __future__ import annotations

import os
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


def app_data_directory() -> Path:
    """Return the app-owned data root for portable or standard installs."""
    portable_data = portable_data_directory()
    if portable_data is not None:
        return portable_data
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    elif os.name == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "ProjectZomboidModManager"
