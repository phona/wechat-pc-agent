"""Portable path resolution for frozen (PyInstaller) and development modes."""

import sys
from pathlib import Path


def app_dir() -> Path:
    """Return the directory containing the exe (frozen) or project root (dev)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


def data_dir() -> Path:
    """Return the data directory (auto-created on first access)."""
    d = app_dir() / "data"
    d.mkdir(parents=True, exist_ok=True)
    return d


def config_dir() -> Path:
    """Return the config directory — same as app_dir() for portable installs."""
    return app_dir()
