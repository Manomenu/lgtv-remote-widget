"""Odczyt i zmiana stanu telewizora."""

from __future__ import annotations

from .config import Config
from .luna import call, call_ok
from .ssh import SshError, Transport

POWER = "com.webos.service.tvpower"
AUDIO = "com.webos.service.audio/master"
APPS = "com.webos.applicationManager"
NOTIFY = "com.webos.notification"

# Stany zasilania w słowniku webOS-a -> nasze znaczniki.
#
# "Screen Saver" trafia się przy muzyce z wygaszonym obrazem — telewizor pracuje
# normalnie, więc traktujemy go jak włączony.
_POWER_STATES = {
    "Active": "active",
    "Screen Off": "screen-off",
    "Screen Saver": "screen-saver",
    "Active Standby": "standby",
    "Suspend": "standby",
    "Prepare Suspend": "standby",
}

#: Stany, w których telewizor faktycznie pracuje i da się nim sterować.
AWAKE = ("active", "screen-off", "screen-saver")


def power_state(transport: Transport) -> str:
    """Zwraca znacznik stanu: active/screen-off/screen-saver/standby/offline."""
    try:
        reply = call(transport, POWER, "power/getPowerState")
    except SshError:
        # SSH nie odpowiada albo szyna milczy. To drugie przy Szybkim
        # uruchamianiu+ wygląda dokładnie tak: sieć żyje, usługi już nie.
        # Nazywamy to czuwaniem tylko wtedy, gdy sam SSH działa.
        return "standby" if transport.alive() else "offline"

    raw = reply.get("state", "")
    if raw in _POWER_STATES:
        return _POWER_STATES[raw]
    # Nieznana nazwa stanu: skoro szyna odpowiada, telewizor pracuje.
    return "active"


def get_volume(transport: Transport) -> tuple[int, bool]:
    """Zwraca (głośność 0-100, wyciszony)."""
    reply = call_ok(transport, AUDIO, "getVolume")
    status = reply.get("volumeStatus") or {}
    return int(status.get("volume", -1)), bool(status.get("muteStatus", False))


def set_volume(transport: Transport, value: int) -> int:
    value = max(0, min(100, int(value)))
    call_ok(transport, AUDIO, "setVolume", {"volume": value})
    return value


def set_mute(transport: Transport, muted: bool) -> None:
    """Wycisza i odcisza.

    Metoda nazywa się ``muteVolume``, a jej parametr ``mute`` — nie
    ``setMuted``/``muted``, jak można by się spodziewać po tym, że odczyt
    zwraca pole ``muteStatus``. Sprawdzone na tym firmwarze: pozostałe nazwy
    odpowiadają „Unknown method”.

    To prawdziwe wyciszenie, nie zerowanie głośności: poziom zostaje
    zapamiętany i wraca przy odciszeniu.
    """
    call_ok(transport, AUDIO, "muteVolume", {"mute": bool(muted)})


def foreground_app(transport: Transport) -> str:
    reply = call(transport, APPS, "getForegroundAppInfo")
    return reply.get("appId") or ""


def launch_app(transport: Transport, app_id: str) -> None:
    call_ok(transport, APPS, "launch", {"id": app_id})


def close_app(transport: Transport, app_id: str) -> None:
    call_ok(transport, APPS, "closeByAppId", {"id": app_id})


def toast(transport: Transport, message: str) -> None:
    """Powiadomienie na ekranie telewizora.

    webOS nie pozwala ustawić czasu trwania ani zamknąć powiadomienia
    (``closeToast`` nie działa na tym firmwarze), więc pokazujemy je raz
    i zostawiamy telewizorowi decyzję, kiedy zniknie.
    """
    call_ok(transport, NOTIFY, "createToast", {"sourceId": "lgtv-remote", "message": message})


def power_off(transport: Transport) -> bool:
    """Wydaje polecenie wyłączenia. Zwraca, czy usługa je przyjęła.

    Polecenie jest jednoznaczne („wyłącz”, nie „przełącz”), więc bezpieczne do
    wielokrotnego ponawiania — w odróżnieniu od wstrzykniętego KEY_POWER.
    """
    try:
        reply = call(transport, POWER, "power/powerOff", {"reason": "remoteKey"})
    except SshError:
        return False
    return bool(reply.get("returnValue"))


def probe(transport: Transport, cfg: Config) -> dict:
    """Jedno odpytanie: stan zasilania, a przy działającym TV także głośność.

    Zwraca słownik z tym, co udało się ustalić. Nie rzuca — wołane z pollera,
    a chwilowa niedostępność telewizora to nie jest sytuacja wyjątkowa.
    """
    result: dict = {"power": power_state(transport)}
    if result["power"] not in AWAKE:
        return result
    try:
        volume, muted = get_volume(transport)
        result["volume"] = volume
        result["muted"] = muted
    except (SshError, ValueError):
        pass
    return result
