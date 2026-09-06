"""Ścieżki zgodne z XDG Base Directory Specification.

Wszystko liczone ze zmiennych środowiskowych, nie z twardego ``~/.config`` —
inaczej program przestaje działać u kogoś, kto ma je poustawiane inaczej.
"""

from __future__ import annotations

import os
from pathlib import Path

from . import APP_ID


def _xdg(var: str, default: str) -> Path:
    value = os.environ.get(var, "").strip()
    return Path(value) if value else Path.home() / default


def config_home() -> Path:
    return _xdg("XDG_CONFIG_HOME", ".config")


def state_home() -> Path:
    return _xdg("XDG_STATE_HOME", ".local/state")


def cache_home() -> Path:
    return _xdg("XDG_CACHE_HOME", ".cache")


def runtime_dir() -> Path:
    """Katalog na gniazda i inne rzeczy krótkotrwałe.

    ``XDG_RUNTIME_DIR`` bywa nieustawiony (np. w sesji przez ``ssh``), więc
    cache jest sensownym zapasem — gniazdo ControlMaster przeżyje wtedy
    restart, ale ssh i tak wykryje, że jest martwe.
    """
    value = os.environ.get("XDG_RUNTIME_DIR", "").strip()
    return Path(value) / APP_ID if value else cache_home() / APP_ID


CONFIG_FILE = config_home() / APP_ID / "config.ini"
STATE_DIR = state_home() / APP_ID
CACHE_DIR = cache_home() / APP_ID
