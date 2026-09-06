"""Włączanie i wyłączanie telewizora — z potwierdzeniem, nie „na wiarę”.

Obie drogi są niesymetryczne i to nie jest przypadek:
  * wyłączanie idzie przez SSH, bo telewizor działa i ma czym odpowiedzieć;
  * włączanie idzie pakietem budzącym Wake-on-LAN, bo wyłączony telewizor
    nie ma z czym rozmawiać.

Pakiety budzące bywają gubione, a wyłączanie nie zawsze łapie za pierwszym
razem — dlatego oba polecenia są ponawiane aż do skutku albo do wyczerpania
limitu czasu.
"""

from __future__ import annotations

import socket
import time
from collections.abc import Callable

from . import tv
from .config import Config
from .logs import log
from .ssh import Transport


class PowerError(RuntimeError):
    pass


def _magic_packet(mac: str) -> bytes:
    clean = mac.replace(":", "").replace("-", "").strip()
    if len(clean) != 12:
        raise PowerError(f"invalid MAC address: {mac!r}")
    return b"\xff" * 6 + bytes.fromhex(clean) * 16


def wake(cfg: Config) -> None:
    """Wysyła pakiet budzący. Strzelamy szeroko, bo to nic nie kosztuje.

    Dwa adresy (rozgłoszeniowy z konfiguracji i uniwersalny) na dwóch portach
    (9 i 7) — różne sieci i różne firmware'y słuchają w różnych miejscach.
    """
    packet = _magic_packet(cfg.mac)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        for target in {cfg.broadcast, "255.255.255.255"}:
            for port in (9, 7):
                try:
                    sock.sendto(packet, (target, port))
                except OSError as exc:
                    log.debug("magic packet to %s:%d failed: %s", target, port, exc)


def _wait_for(
    transport: Transport,
    want_awake: bool,
    limit: int,
    retry_every: int,
    resend: Callable[[], None],
    on_tick: Callable[[str], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> str:
    """Czeka na docelowy stan, ponawiając polecenie co ``retry_every`` sekund."""
    started = time.monotonic()
    last_resend = started

    while True:
        if cancelled is not None and cancelled():
            raise PowerError("cancelled")

        state = tv.power_state(transport)
        if on_tick is not None:
            on_tick(state)

        awake = state in tv.AWAKE
        if awake == want_awake:
            return state

        elapsed = time.monotonic() - started
        if elapsed >= limit:
            raise PowerError(
                f"the TV did not reach the requested state within {limit}s "
                f"(last seen: {state})"
            )
        if time.monotonic() - last_resend >= retry_every:
            resend()
            last_resend = time.monotonic()
        time.sleep(2)


def turn_on(transport: Transport, cfg: Config, **kwargs) -> str:
    if not cfg.mac:
        raise PowerError("no MAC address configured — set tv.mac to use Wake-on-LAN")
    wake(cfg)
    return _wait_for(
        transport,
        want_awake=True,
        limit=cfg.on_timeout,
        retry_every=cfg.retry_every,
        resend=lambda: wake(cfg),
        **kwargs,
    )


def turn_off(transport: Transport, cfg: Config, **kwargs) -> str:
    # Droga awaryjna — wstrzyknięcie KEY_POWER — jest PRZEŁĄCZNIKIEM, nie
    # wyłącznikiem: ponowiona po tym, jak telewizor zdążył zgasnąć, włączyłaby
    # go z powrotem. Dlatego wolno jej zadziałać najwyżej raz na wywołanie.
    fallback_used = False

    def send_off() -> None:
        nonlocal fallback_used
        if tv.power_off(transport):
            return
        if fallback_used:
            return
        fallback_used = True
        log.warning("powerOff was not acknowledged — falling back to the power key")
        from . import keys
        try:
            keys.tap(transport, cfg.key_device, 116)   # KEY_POWER
        except Exception as exc:
            log.warning("the power key fallback failed too: %s", exc)

    send_off()
    return _wait_for(
        transport,
        want_awake=False,
        limit=cfg.off_timeout,
        retry_every=cfg.retry_every,
        resend=send_off,
        **kwargs,
    )
