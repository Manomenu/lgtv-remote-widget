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

    def shutdown(*_args) -> bool:
        logs.log.info("shutting down")
        loop.quit()
        return GLib.SOURCE_REMOVE

    service.own_name(on_lost=shutdown)

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

    # Poller sam ustala, kiedy obudzić się następnym razem: częściej przy
    # otwartym panelu i w trakcie operacji, rzadko w spoczynku.
    def tick() -> bool:
        # Kolejne obudzenie planujemy PRZED zgłoszeniem zadania. Gdyby submit
        # rzucił, harmonogram i tak przetrwa — inaczej jeden wyjątek kasuje
        # odpytywanie do końca życia procesu, bez żadnego śladu w dzienniku.
        GLib.timeout_add_seconds(daemon.poll_interval(), tick)
        daemon.worker.submit("poll", daemon.poll, log_action=False)
        return GLib.SOURCE_REMOVE

    GLib.timeout_add_seconds(daemon.poll_interval(), tick)

    try:
        loop.run()
    finally:
        service.unregister()
        daemon.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
