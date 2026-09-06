"""Wywoływanie usług webOS przez ``luna-send``.

Dwie pułapki, obie wykryte doświadczalnie przy skryptach w ~/scripts/lgtv
i obie konieczne do obejścia przy KAŻDYM wywołaniu:

1. ``luna-send`` gubi odpowiedź, gdy jego wyjście jest potokiem — a przez SSH
   zawsze jest. Dlatego piszemy na telewizorze do pliku i dopiero go czytamy.

2. ``luna-send`` obserwuje standardowe wejście i kończy pracę na jego końcu,
   zanim zdąży odebrać odpowiedź z szyny. Bez ``< /dev/null`` odpowiedź
   przychodzi raz na kilka prób, co wygląda jak awarie telewizora, a jest
   wyłącznie tym.
"""

from __future__ import annotations

import json
import shlex

from .ssh import SshError, Transport

# Osobny plik na odpowiedź dla każdego wywołania nie jest potrzebny — polecenia
# do telewizora idą jednym wątkiem, po kolei.
_OUT = "/tmp/.lgtvd-luna"


class LunaError(RuntimeError):
    """Usługa odpowiedziała, ale odmówiła wykonania."""


def call(
    transport: Transport,
    service: str,
    method: str,
    payload: dict | None = None,
    timeout: int | None = None,
) -> dict:
    """Woła ``luna://<service>/<method>`` i zwraca odpowiedź jako słownik."""
    body = json.dumps(payload or {}, separators=(",", ":"))
    uri = f"luna://{service}/{method}"
    command = (
        f"luna-send -n 1 -f {shlex.quote(uri)} {shlex.quote(body)} "
        f"< /dev/null > {_OUT} 2>&1; cat {_OUT}"
    )
    raw = transport.check(command, timeout=timeout)
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        # Szyna milczy albo odpowiedziała śmieciem. Przy czuwaniu z Szybkim
        # uruchamianiem+ to normalny stan: sieć żyje, system usług już nie.
        raise SshError(f"{uri}: unreadable reply {raw.strip()[:200]!r}") from exc


def call_ok(transport: Transport, service: str, method: str, payload=None, timeout=None) -> dict:
    """Jak ``call``, ale wymaga ``returnValue: true``."""
    reply = call(transport, service, method, payload, timeout)
    if not reply.get("returnValue"):
        raise LunaError(reply.get("errorText") or f"{service}/{method} refused the request")
    return reply
