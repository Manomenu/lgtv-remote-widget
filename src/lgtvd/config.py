"""Wczytanie konfiguracji: wartości domyślne → plik systemowy → plik użytkownika
→ zmienne środowiskowe.

Kolejność jest celowa i rośnie od najsłabszego źródła do najmocniejszego, żeby
dało się podmienić jedną wartość na jeden strzał (``LGTV_HOST=... lgtvd``) bez
edytowania czegokolwiek.
"""

from __future__ import annotations

import configparser
import os
from dataclasses import dataclass, field
from pathlib import Path

from . import APP_ID
from .paths import CONFIG_FILE

SYSTEM_CONFIG = Path("/etc/xdg") / APP_ID / "config.ini"

#: Ustawienia, których wyzerowanie jest błędem, a nie prośbą o domyślne.
#:
#: Wzorzec konfiguracji przychodzi z wypełnionym ``host``, więc wykasowanie go
#: to świadome działanie. Ciche sięgnięcie po wartość domyślną oznaczałoby
#: rozmowę z INNYM telewizorem niż ten, o którym myśli użytkownik.
#: ``mac`` celowo nie jest tu wymieniony — jest pusty we wzorcu i pusty znaczy
#: tylko tyle, że nie da się telewizora włączyć.
_REQUIRED = {"host"}

# Klucz w pliku -> (sekcja, nazwa pola, zmienna środowiskowa, konwerter)
_SCHEMA: list[tuple[str, str, str, str, type]] = [
    ("tv", "host", "host", "LGTV_HOST", str),
    ("tv", "mac", "mac", "LGTV_MAC", str),
    ("tv", "broadcast", "broadcast", "LGTV_BROADCAST", str),
    ("tv", "connect_timeout", "connect_timeout", "LGTV_CONNECT_TIMEOUT", int),
    ("tv", "control_persist", "control_persist", "LGTV_CONTROL_PERSIST", int),
    ("power", "on_timeout", "on_timeout", "LGTV_ON_TIMEOUT", int),
    ("power", "off_timeout", "off_timeout", "LGTV_OFF_TIMEOUT", int),
    ("power", "retry_every", "retry_every", "LGTV_RETRY_EVERY", int),
    ("keys", "device", "key_device", "LGTV_KEY_DEVICE", str),
    ("keys", "device_name", "key_device_name", "LGTV_KEY_DEVICE_NAME", str),
    ("keys", "next", "key_next", "LGTV_KEY_NEXT", int),
    ("keys", "previous", "key_previous", "LGTV_KEY_PREVIOUS", int),
    ("cast", "enabled", "cast_enabled", "LGTV_CAST_ENABLED", bool),
    ("cast", "sunshine_app_id", "sunshine_app_id", "LGTV_SUNSHINE_APP_ID", str),
    ("cast", "sunshine_port", "sunshine_port", "LGTV_SUNSHINE_PORT", int),
    ("cast", "moonlight_app_id", "moonlight_app_id", "LGTV_MOONLIGHT_APP_ID", str),
    ("cast", "start_timeout", "cast_start_timeout", "LGTV_CAST_START_TIMEOUT", int),
    ("cast", "stop_timeout", "cast_stop_timeout", "LGTV_CAST_STOP_TIMEOUT", int),
    ("daemon", "poll_idle", "poll_idle", "LGTV_POLL_IDLE", int),
    ("daemon", "poll_active", "poll_active", "LGTV_POLL_ACTIVE", int),
    ("daemon", "volume_throttle_ms", "volume_throttle_ms", "LGTV_VOLUME_THROTTLE_MS", int),
    ("daemon", "log_level", "log_level", "LGTV_LOG_LEVEL", str),
]


@dataclass(slots=True)
class Config:
    # --- telewizor -----------------------------------------------------------
    host: str = "lgtv-root"
    mac: str = ""
    broadcast: str = "255.255.255.255"
    connect_timeout: int = 5
    control_persist: int = 300

    # --- zasilanie -----------------------------------------------------------
    #
    # Zimny start telewizora bywa naprawdę powolny, a pakiety budzące bywają
    # gubione — stąd długi limit i ponawianie, tak samo jak w toggle.sh.
    on_timeout: int = 90
    off_timeout: int = 45
    retry_every: int = 5

    # --- klawisze ------------------------------------------------------------
    #
    # Zmierzone przez nasłuchiwanie wszystkich urządzeń wejściowych telewizora
    # w trakcie naciskania prawdziwego pilota (patrz docs/webos-notes.md).
    #
    # Urządzenie wyszukiwane jest po NAZWIE, bo numery się przesuwają: między
    # dwoma pomiarami tego samego dnia lista urosła z 7 do 11 pozycji. Ścieżka
    # niżej służy już tylko za zapas, gdyby nazwa się nie znalazła.
    key_device_name: str = "LGE M-RCU - Builtin [2]"
    key_device: str = "/dev/input/event4"
    key_next: int = 402       # rocker w górę (KEY_CHANNELUP)
    key_previous: int = 403   # rocker w dół  (KEY_CHANNELDOWN)

    # --- strumieniowanie -----------------------------------------------------
    cast_enabled: bool = True
    sunshine_app_id: str = "dev.lizardbyte.app.Sunshine"
    sunshine_port: int = 47990
    moonlight_app_id: str = "com.limelight.webos"
    cast_start_timeout: int = 90
    cast_stop_timeout: int = 20

    # --- demon ---------------------------------------------------------------
    #: Tempo odpytywania, gdy panel jest ZAMKNIĘTY. Zero (domyślnie) znaczy:
    #: wcale — nikt wtedy nie ogląda wyniku, a każde odpytanie budzi telewizor.
    poll_idle: int = 0
    #: Tempo, gdy panel jest otwarty albo trwa operacja.
    poll_active: int = 5
    #: Przyjmowane i ignorowane. Dławieniem zajmuje się samo zlepianie zgłoszeń
    #: w Daemon.set_volume, więc osobna pauza nie ma już czego chronić — a że
    #: klucz stoi w plikach, które ludzie mają u siebie, wywalenie go zrobiłoby
    #: tylko ostrzeżenie z setup.sh o „brakującym” ustawieniu.
    volume_throttle_ms: int = 120
    log_level: str = "INFO"

    sources: list[str] = field(default_factory=list)

    @property
    def sunshine_log(self) -> Path:
        return (
            Path.home()
            / ".var/app"
            / self.sunshine_app_id
            / "config/sunshine/sunshine.log"
        )


def _coerce(raw: str, kind: type) -> object:
    raw = raw.strip()
    if kind is bool:
        return raw.lower() in ("1", "true", "yes", "on")
    if kind is int:
        return int(raw, 0)
    return raw


def load(path: Path | None = None) -> Config:
    """Zwraca konfigurację złożoną ze wszystkich dostępnych źródeł."""
    cfg = Config()
    parser = configparser.ConfigParser()

    candidates = [SYSTEM_CONFIG, path or CONFIG_FILE]
    for candidate in candidates:
        if candidate.is_file():
            parser.read(candidate, encoding="utf-8")
            cfg.sources.append(str(candidate))

    for section, key, field_name, env, kind in _SCHEMA:
        raw = None
        if parser.has_option(section, key):
            raw = parser.get(section, key)
        env_value = os.environ.get(env)
        if env_value is not None and env_value.strip():
            raw = env_value
            if "environment" not in cfg.sources:
                cfg.sources.append("environment")
        if raw is None:
            continue
        if not raw.strip():
            if field_name in _REQUIRED:
                raise ValueError(f"{section}.{key} is empty — set it in {CONFIG_FILE}")
            continue
        try:
            setattr(cfg, field_name, _coerce(raw, kind))
        except ValueError as exc:
            raise ValueError(
                f"{section}.{key}: cannot read {raw!r} as {kind.__name__}"
            ) from exc

    return cfg
