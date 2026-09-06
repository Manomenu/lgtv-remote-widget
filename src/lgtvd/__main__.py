"""Punkt wejścia demona: konfiguracja, dzienniki, szyna, pętla główna."""

from __future__ import annotations

import argparse
import signal
import sys

import gi

gi.require_version("Gio", "2.0")
from gi.repository import GLib  # noqa: E402

from . import __version__, config, logs  # noqa: E402
from .daemon import Daemon  # noqa: E402
from .dbus import BUS_NAME as dbus_name  # noqa: E402
from .dbus import Service  # noqa: E402
from .paths import CONFIG_FILE  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="lgtvd",
        description="Background service that drives an LG webOS TV over SSH.",
    )
    parser.add_argument("--config", metavar="FILE", help="use this configuration file")
    parser.add_argument("--log-level", metavar="LEVEL", help="DEBUG, INFO, WARNING or ERROR")
    parser.add_argument("--version", action="version", version=f"lgtvd {__version__}")
    args = parser.parse_args(argv)

    try:
        cfg = config.load(args.config)
    except (ValueError, OSError) as exc:
        print(f"lgtvd: {exc}", file=sys.stderr)
        print(f"lgtvd: expected configuration at {CONFIG_FILE}", file=sys.stderr)
        return 2

    logs.setup(args.log_level or cfg.log_level)
    logs.log.info("lgtvd %s starting — TV %s", __version__, cfg.host)
    logs.log.info("configuration: %s", ", ".join(cfg.sources) or "built-in defaults only")

    daemon = Daemon(cfg)
    service = Service(daemon)
    loop = GLib.MainLoop()

    # Kod wyjścia decyduje, czy systemd nas wskrzesi. Zatrzymanie usługi to
    # sukces; utrata nazwy na szynie w trakcie działania to awaria, po której
    # proces jest już do niczego i ma wstać na nowo.
    exit_code = 0

    def shutdown(*_args) -> bool:
        logs.log.info("shutting down")
        loop.quit()
        return GLib.SOURCE_REMOVE

    def name_lost() -> None:
        nonlocal exit_code
        exit_code = 1
        logs.log.error(
            "lost the %s name on the session bus — another instance took it "
            "or the bus went away", dbus_name)
        loop.quit()

    service.own_name(on_lost=name_lost)

    # GLibUnix to nowsza nazwa tego samego; starsze wydania jej nie mają, więc
    # sięgamy po nią tylko wtedy, gdy istnieje.
    try:
        gi.require_version("GLibUnix", "2.0")
        from gi.repository import GLibUnix

        add_signal_watch = GLibUnix.signal_add
    except (ValueError, ImportError):
        add_signal_watch = GLib.unix_signal_add

    for sig in (signal.SIGINT, signal.SIGTERM):
        add_signal_watch(GLib.PRIORITY_DEFAULT, sig, shutdown)

    daemon.start()

    # Odpytywanie chodzi tylko wtedy, gdy jest komu patrzeć: panel melduje
    # otwarcie i zamknięcie, a demon przelicza z tego tempo. Przy zamkniętym
    # panelu zegar nie jest w ogóle zakładany — proces śpi, telewizor też.
    poll_source = 0

    def schedule() -> bool:
        nonlocal poll_source
        if poll_source:
            GLib.source_remove(poll_source)
            poll_source = 0
        interval = daemon.poll_interval()
        if interval > 0:
            poll_source = GLib.timeout_add_seconds(interval, tick)
        return GLib.SOURCE_REMOVE

    def tick() -> bool:
        nonlocal poll_source
        poll_source = 0
        # Kolejne obudzenie planujemy PRZED zgłoszeniem zadania. Gdyby submit
        # rzucił, harmonogram i tak przetrwa — inaczej jeden wyjątek kasuje
        # odpytywanie do końca życia procesu, bez żadnego śladu w dzienniku.
        schedule()
        if daemon.should_poll():
            daemon.worker.submit("poll", daemon.poll, log_action=False)
        return GLib.SOURCE_REMOVE

    # Tempo zmienia się także z wątku roboczego (wejście w „włączam…”
    # i wyjście z niego), a zegary GLib należą do pętli głównej.
    daemon.on_cadence_change = lambda: GLib.idle_add(schedule)
    schedule()

    try:
        loop.run()
    finally:
        service.unregister()
        daemon.stop()
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
