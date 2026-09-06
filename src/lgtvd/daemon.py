"""Model stanu telewizora i orkiestracja poleceń.

Ten moduł nie wie nic o D-Bus ani o GNOME — wystawia stan i metody, a o tym,
komu je pokazać, decyduje warstwa wyżej. Dzięki temu wszystko da się przetestować
z terminala, zanim powstanie pierwszy kafelek.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable

from . import cast, keys, power, tv
from .config import Config
from .logs import log
from .ssh import Transport
from .worker import Worker

#: Stany zasilania widoczne na zewnątrz.
POWER_STATES = (
    "active", "screen-off", "screen-saver", "standby", "offline",
    "turning-on", "turning-off",
)

#: Stany strumieniowania widoczne na zewnątrz.
CAST_STATES = ("streaming", "ready", "stopped", "starting", "stopping")


class Daemon:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.transport = Transport(cfg)
        self.worker = Worker()

        self._lock = threading.Lock()
        self._state: dict[str, object] = {
            "PowerState": "offline",
            "Volume": -1,
            "Muted": False,
            "CastState": "stopped",
            # Stałe przez całe życie procesu, ale wystawione jak reszta: widget
            # nie ma innego sposobu, żeby dowiedzieć się, że kafelka nie ma po
            # co rysować. Bez tego jedynym objawem wyłączonego strumieniowania
            # był kafelek, który nie robi nic.
            "CastEnabled": cfg.cast_enabled,
            "LastError": "",
        }
        #: Wołane po każdej zmianie stanu, ze słownikiem samych zmian.
        #: Warstwa D-Bus podpina tu emisję PropertiesChanged.
        self.on_change: Callable[[dict], None] | None = None

        self._target_volume: int | None = None
        self._volume_queued = False
        self._busy_until_idle = False
        self._active_until = 0.0

    # -- stan ------------------------------------------------------------------

    def snapshot(self) -> dict:
        with self._lock:
            return dict(self._state)

    def get(self, key: str) -> object:
        with self._lock:
            return self._state[key]

    def _update(self, **changes) -> None:
        """Zapisuje zmiany i powiadamia obserwatora tylko o tym, co naprawdę się zmieniło."""
        real: dict[str, object] = {}
        with self._lock:
            for key, value in changes.items():
                if key not in self._state:
                    raise KeyError(key)
                if self._state[key] != value:
                    self._state[key] = value
                    real[key] = value
        if real and self.on_change is not None:
            self.on_change(real)

    def _fail(self, message: str) -> None:
        log.warning("%s", message)
        self._update(LastError=message)

    @property
    def awake(self) -> bool:
        return self.get("PowerState") in tv.AWAKE

    # -- odpytywanie -----------------------------------------------------------

    def poll_interval(self) -> int:
        """Szybciej, gdy panel jest otwarty albo trwa operacja; inaczej rzadko."""
        if self.get("PowerState") in ("turning-on", "turning-off"):
            return self.cfg.poll_active
        if time.monotonic() < self._active_until:
            return self.cfg.poll_active
        return self.cfg.poll_idle

    def poll(self) -> None:
        """Jedno odpytanie telewizora. Nigdy nie rzuca — to pętla tła."""
        if self.get("PowerState") in ("turning-on", "turning-off"):
            return   # operacja w toku sama pilnuje stanu
        try:
            reading = tv.probe(self.transport, self.cfg)
        except Exception as exc:
            log.debug("poll failed: %s", exc)
            self._update(PowerState="offline")
            return

        changes: dict[str, object] = {"PowerState": reading["power"]}
        if "volume" in reading and not self._volume_queued:
            changes["Volume"] = reading["volume"]
            changes["Muted"] = reading["muted"]
        elif reading["power"] not in tv.AWAKE:
            changes["Volume"] = -1

        if self.cfg.cast_enabled:
            try:
                changes["CastState"] = cast.state(
                    self.transport, self.cfg, tv_awake=reading["power"] in tv.AWAKE
                )
            except Exception as exc:
                log.debug("cast probe failed: %s", exc)

        self._update(**changes)

    def request_poll_soon(self) -> None:
        """Odpytaj teraz i przez chwilę odpytuj częściej — wołane przy otwarciu panelu."""
        self._active_until = time.monotonic() + 60
        self.worker.submit("poll", self.poll, log_action=False)

    # -- polecenia -------------------------------------------------------------

    def set_power(self, on: bool) -> None:
        if on and self.awake:
            return
        if not on and self.get("PowerState") in ("offline", "standby"):
            return

        target = "turning-on" if on else "turning-off"
        self._update(PowerState=target, LastError="")

        # Numer epoki wypełnia się przy zgłoszeniu zadania, a zadanie ruszy
        # dopiero po nim — dzięki temu nie musimy zgadywać go z góry.
        token: dict[str, int] = {}

        def job() -> None:
            def tick(seen: str) -> None:
                log.debug("waiting for the TV: %s", seen)

            action = power.turn_on if on else power.turn_off
            try:
                final = action(
                    self.transport,
                    self.cfg,
                    on_tick=tick,
                    cancelled=lambda: self.worker.superseded(token["epoch"]),
                )
            except power.PowerError as exc:
                if str(exc) == "cancelled":
                    return
                self._fail(str(exc))
                self.poll()
                raise
            self._update(PowerState=final)

        token["epoch"] = self.worker.submit(
            "set_power", job, supersedes=True, fields={"arg": "on" if on else "off"})

    def set_volume(self, value: int) -> None:
        """Ustawia głośność, dławiąc lawinę zdarzeń z suwaka.

        Suwak potrafi wysłać kilkadziesiąt wartości na sekundę. Zamiast kolejkować
        je wszystkie, zapamiętujemy OSTATNIĄ i wysyłamy ją jednym poleceniem —
        telewizor i tak nie nadążyłby z resztą, a użytkownika interesuje tylko
        wartość, na której puścił uchwyt.
        """
        value = max(0, min(100, int(value)))
        with self._lock:
            self._target_volume = value
            already_queued = self._volume_queued
            self._volume_queued = True
        self._update(Volume=value)   # UI reaguje natychmiast, nie czeka na TV

        if already_queued:
            return

        # Zadanie głośności NIE może być unieważnialne: gdyby zostało odrzucone,
        # flaga _volume_queued zostałaby zapalona na zawsze i suwak przestałby
        # cokolwiek wysyłać do końca życia procesu.
        #
        # Nie ma tu pauzy i to jest celowe. Dławienie robi już samo zlepianie
        # zgłoszeń: dopóki to zadanie stoi w kolejce, kolejne ruchy suwaka
        # tylko podmieniają wartość docelową, więc na całą serię przypada
        # jedno polecenie do telewizora. Wcześniejszy time.sleep() nie dokładał
        # do tego nic poza zablokowaniem JEDYNEGO wątku roboczego: naciśnięcie
        # „dalej” w trakcie kręcenia głośnością czekało do 120 ms na koniec
        # cudzej pauzy. Odłożenie zadania z powrotem do kolejki zamiast pauzy
        # też odpada — przy pustej kolejce robi się z tego pętla jałowa.

        def job() -> None:
            with self._lock:
                target = self._target_volume
                self._volume_queued = False
            if target is None:
                return
            tv.set_volume(self.transport, target)

        self.worker.submit("set_volume", job, fields={"value": value})

    def set_mute(self, muted: bool) -> None:
        self._update(Muted=muted)
        self.worker.submit("set_mute", lambda: tv.set_mute(self.transport, muted))

    def media_key(self, name: str) -> None:
        codes = {"next": self.cfg.key_next, "previous": self.cfg.key_previous}
        if name not in codes:
            raise ValueError(f"unknown media key {name!r} — expected 'next' or 'previous'")
        code = codes[name]

        def job() -> None:
            keys.tap(self.transport, self.cfg.key_device, code)

        self.worker.submit("media_key", job, fields={"key": name, "code": code})

    def set_cast(self, on: bool) -> None:
        if not self.cfg.cast_enabled:
            raise RuntimeError("screencast support is disabled in the configuration")
        current = self.get("CastState")
        if on and current in ("streaming", "starting"):
            return
        if not on and current in ("stopped", "stopping"):
            return

        self._update(CastState="starting" if on else "stopping", LastError="")
        token: dict[str, int] = {}

        def job() -> None:
            action = cast.start if on else cast.stop
            try:
                action(self.transport, self.cfg,
                       cancelled=lambda: self.worker.superseded(token["epoch"]))
            except cast.CastError as exc:
                if str(exc) == "cancelled":
                    return
                self._fail(str(exc))
                self.poll()
                raise
            self._update(CastState="streaming" if on else "ready")

        token["epoch"] = self.worker.submit(
            "set_cast", job, supersedes=True, fields={"arg": "on" if on else "off"})

    # -- cykl życia ------------------------------------------------------------

    def start(self) -> None:
        self.worker.start()
        self.worker.submit("poll", self.poll, log_action=False)

    def stop(self) -> None:
        self.worker.stop()
        self.transport.close()
