"""Dwa dzienniki i konsola.

``actions.log`` to zapis tego, co widget zrobił — jedna linia na akcję, żeby
dało się przejrzeć okiem. ``errors.log`` zbiera wyłącznie problemy, z pełnym
tracebackiem. Oba rotowane, więc nie urosną w nieskończoność. Wszystko idzie
dodatkowo na stdout, czyli do dziennika systemd.
"""

from __future__ import annotations

import logging
import logging.handlers
import sys
import time

from .paths import STATE_DIR

ACTION_LOG = STATE_DIR / "actions.log"
ERROR_LOG = STATE_DIR / "errors.log"

_MAX_BYTES = 1 << 20   # 1 MiB
_BACKUPS = 3

actions = logging.getLogger("lgtvd.actions")
log = logging.getLogger("lgtvd")


class _Iso8601(logging.Formatter):
    """Znacznik czasu ze strefą, żeby wpisy dało się porównywać z journalctl."""

    def formatTime(self, record, datefmt=None):
        return time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(record.created))


def setup(level: str = "INFO") -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger("lgtvd")
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    root.handlers.clear()

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(_Iso8601("%(levelname)-7s %(name)s: %(message)s"))
    root.addHandler(console)

    errors = logging.handlers.RotatingFileHandler(
        ERROR_LOG, maxBytes=_MAX_BYTES, backupCount=_BACKUPS, encoding="utf-8"
    )
    errors.setLevel(logging.WARNING)
    errors.setFormatter(_Iso8601("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root.addHandler(errors)

    actions.handlers.clear()
    actions.propagate = False          # akcje mają własny plik, nie dublują się
    actions.setLevel(logging.INFO)
    action_file = logging.handlers.RotatingFileHandler(
        ACTION_LOG, maxBytes=_MAX_BYTES, backupCount=_BACKUPS, encoding="utf-8"
    )
    action_file.setFormatter(_Iso8601("%(asctime)s %(message)s"))
    actions.addHandler(action_file)
    console_actions = logging.StreamHandler(sys.stdout)
    console_actions.setFormatter(_Iso8601("ACTION  %(message)s"))
    actions.addHandler(console_actions)


def record(action: str, result: str, duration: float | None = None, **fields) -> None:
    """Jedna linia w actions.log, w formacie klucz=wartość.

    Format wybrany tak, żeby dał się czytać oczami i ciąć ``grep``-em bez
    parsowania JSON-a.
    """
    parts = [f"action={action}"]
    parts += [f"{k}={v}" for k, v in fields.items() if v is not None and v != ""]
    parts.append(f"result={result}")
    if duration is not None:
        parts.append(f"duration={duration:.1f}s")
    actions.info(" ".join(parts))
