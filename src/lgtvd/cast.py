"""Strumieniowanie ekranu komputera na telewizor: Sunshine (tu) → Moonlight (tam).

O tym, czy strumień płynie, NIE rozstrzyga sam dziennik Sunshine'a: przy nagłym
zerwaniu (zamknięcie Moonlighta, mignięcie sieci) zostaje w nim osierocone
"CLIENT CONNECTED" i wygląda to na trwającą sesję, choć nikogo już nie ma.
Dlatego pytamy telewizor, co ma na wierzchu, i dopiero potem zaglądamy do
dziennika.
"""

from __future__ import annotations

import os
import re
import socket
import subprocess
import time
from collections.abc import Callable

from . import tv
from .config import Config
from .logs import log
from .ssh import SshError, Transport

#: Trzy zdarzenia, bo strumień może się urwać na dwa sposoby, a Sunshine tylko
#: jeden z nich zapisuje jako rozłączenie klienta. "PipeWire stream stopped"
#: oznacza, że padło źródło obrazu (np. wygaszenie ekranu zamyka sesję portalu)
#: — klient widzi przerwanie, a w dzienniku nie ma "CLIENT DISCONNECTED".
#:
#: Uwaga: "CLIENT DISCONNECTED" zawiera w sobie "CONNECTED", więc wzorzec musi
#: dopasowywać całe zdarzenie, nie podciąg.
_EVENTS = re.compile(r"CLIENT DISCONNECTED|CLIENT CONNECTED|PipeWire stream stopped")

_TAIL_BYTES = 256 * 1024   # ostatnie zdarzenia; dziennik potrafi urosnąć


class CastError(RuntimeError):
    pass


def _sunshine_up(cfg: Config) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(1.5)
        return sock.connect_ex(("127.0.0.1", cfg.sunshine_port)) == 0


def _tail(cfg: Config) -> str:
    """Ostatnie ``_TAIL_BYTES`` dziennika Sunshine'a; pusty łańcuch, gdy go nie ma.

    Czytamy od końca, bo dziennik rośnie bez ograniczeń, a interesują nas
    wyłącznie świeże zdarzenia. Dekodowanie z ``replace`` — ucięcie w połowie
    znaku wielobajtowego jest tu regułą, nie wyjątkiem.
    """
    try:
        with open(cfg.sunshine_log, "rb") as handle:
            handle.seek(0, os.SEEK_END)
            handle.seek(max(0, handle.tell() - _TAIL_BYTES), os.SEEK_SET)
            return handle.read().decode("utf-8", "replace")
    except OSError:
        return ""


def _last_event(cfg: Config) -> str:
    found = _EVENTS.findall(_tail(cfg))
    return found[-1] if found else ""


def state(transport: Transport, cfg: Config, tv_awake: bool) -> str:
    """streaming | ready | stopped"""
    if not cfg.cast_enabled:
        return "stopped"
    if not _sunshine_up(cfg):
        return "stopped"
    if not tv_awake:
        return "ready"
    try:
        if tv.foreground_app(transport) != cfg.moonlight_app_id:
            return "ready"
    except SshError:
        return "ready"
    return "streaming" if _last_event(cfg) == "CLIENT CONNECTED" else "ready"


def _launch_sunshine(cfg: Config) -> None:
    """Uruchamia Sunshine'a JAKO OSOBNĄ USŁUGĘ, nie jako własne dziecko.

    To nie jest kosmetyka. Ograniczenia nałożone na tę usługę w unicie
    (seccomp z RestrictRealtime, MemoryDenyWriteExecute i reszty) dziedziczą się
    przez exec i przeżywają nawet to, że flatpak przenosi aplikację do własnej
    grupy kontrolnej. Sunshine uruchomiony jako nasze dziecko dostawał
    dziesięć filtrów seccomp zamiast jednego, a razem z nimi zakaz proszenia
    o priorytet czasu rzeczywistego — którego jego wątki przechwytu
    i kodowania używają do równego wypuszczania klatek. Efektem był gorszy
    obraz niż przy uruchomieniu z terminala.

    ``systemd-run --user`` zleca start menedżerowi sesji, więc proces rodzi się
    obok nas, z czystym środowiskiem sesji graficznej. Przy okazji przestaje
    ginąć razem z restartem demona.
    """
    launched_by_systemd = False
    try:
        result = subprocess.run(
            [
                "systemd-run", "--user", "--collect",
                "--unit", "lgtv-sunshine",
                "--description", "Sunshine, started by the LG TV remote",
                "flatpak", "run", "--user", cfg.sunshine_app_id,
            ],
            stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=15,
        )
        launched_by_systemd = result.returncode == 0
        if not launched_by_systemd:
            log.warning("systemd-run refused to start Sunshine: %s",
                        result.stderr.strip()[:200])
    except (OSError, subprocess.SubprocessError) as exc:
        log.warning("could not use systemd-run: %s", exc)

    if launched_by_systemd:
        return

    # Zapas na wypadek braku systemd-run. Działa, ale Sunshine dziedziczy wtedy
    # nasze ograniczenia i strumień bywa gorszej jakości.
    log.warning("falling back to starting Sunshine as a child of this service — "
                "the stream may be choppier than usual")
    subprocess.Popen(
        ["flatpak", "run", "--user", cfg.sunshine_app_id],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def _ensure_sunshine(cfg: Config) -> None:
    if _sunshine_up(cfg):
        return
    log.info("starting Sunshine")
    _launch_sunshine(cfg)
    for _ in range(30):
        if _sunshine_up(cfg):
            return
        time.sleep(1)
    raise CastError(
        f"Sunshine did not start. Run it by hand to see why: "
        f"flatpak run --user {cfg.sunshine_app_id}"
    )


def _count_connects(cfg: Config) -> int:
    # "CLIENT DISCONNECTED" nie jest tu zagrożeniem: między "CLIENT" a
    # "CONNECTED" stoi w nim "DIS", więc pełna fraza się nie dopasowuje.
    # (Pułapka z podciągiem dotyczy _EVENTS, gdzie wzorce są krótsze.)
    return len(re.findall(r"CLIENT CONNECTED", _tail(cfg)))


def start(transport: Transport, cfg: Config, cancelled: Callable[[], bool] | None = None) -> None:
    """Otwiera Moonlighta na telewizorze i czeka na POTWIERDZONE połączenie.

    Liczymy zdarzenia połączenia przed otwarciem aplikacji i czekamy na nowe.
    Bez tego wystarczyłby nieświeży wpis z poprzedniej sesji, żeby samo
    otwarcie aplikacji uznać za sukces.
    """
    _ensure_sunshine(cfg)
    if not transport.alive():
        raise CastError("the TV is not responding — switched off or off the network")

    before = _count_connects(cfg)
    tv.launch_app(transport, cfg.moonlight_app_id)

    started = time.monotonic()
    while True:
        if cancelled is not None and cancelled():
            raise CastError("cancelled")
        if _count_connects(cfg) > before:
            return
        if time.monotonic() - started >= cfg.cast_start_timeout:
            raise CastError(
                f"the stream did not start within {cfg.cast_start_timeout}s. "
                f"Moonlight is open on the TV — pick this computer in it and start Desktop."
            )
        time.sleep(2)


def stop(transport: Transport, cfg: Config, cancelled: Callable[[], bool] | None = None) -> None:
    """Zamyka Moonlighta na telewizorze; Sunshine zostaje gotowy na kolejną sesję."""
    tv.close_app(transport, cfg.moonlight_app_id)

    started = time.monotonic()
    while True:
        if cancelled is not None and cancelled():
            raise CastError("cancelled")
        if state(transport, cfg, tv_awake=True) != "streaming":
            return
        if time.monotonic() - started >= cfg.cast_stop_timeout:
            raise CastError(f"the session is still active after {cfg.cast_stop_timeout}s")
        time.sleep(2)
