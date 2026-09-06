"""Rozpoznawanie stanu strumieniowania — bez Sunshine'a i bez telewizora."""

import pytest

from lgtvd import cast, tv
from lgtvd.config import Config
from lgtvd.ssh import SshError


@pytest.fixture
def log(tmp_path, monkeypatch):
    """Podstawia dziennik Sunshine'a plikiem w katalogu testu."""
    path = tmp_path / "sunshine.log"
    path.write_text("", encoding="utf-8")
    monkeypatch.setattr(Config, "sunshine_log", property(lambda self: path))
    return path


@pytest.fixture
def cfg(log):
    return Config(host="tv")


def _sunshine(monkeypatch, up):
    monkeypatch.setattr(cast, "_sunshine_up", lambda cfg: up)


def _foreground(monkeypatch, app):
    if isinstance(app, Exception):
        def raiser(transport):
            raise app
        monkeypatch.setattr(tv, "foreground_app", raiser)
    else:
        monkeypatch.setattr(tv, "foreground_app", lambda transport: app)


# -- czytanie dziennika --------------------------------------------------------


def test_a_missing_log_is_not_an_error(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, "sunshine_log",
                        property(lambda self: tmp_path / "nie-ma-mnie.log"))
    assert cast._tail(Config(host="tv")) == ""
    assert cast._last_event(Config(host="tv")) == ""
    assert cast._count_connects(Config(host="tv")) == 0


def test_only_the_tail_of_a_huge_log_is_read(cfg, log):
    log.write_bytes(b"x" * (2 * cast._TAIL_BYTES) + b"\nCLIENT CONNECTED\n")
    assert len(cast._tail(cfg)) <= cast._TAIL_BYTES
    assert cast._last_event(cfg) == "CLIENT CONNECTED"


def test_a_disconnect_does_not_read_as_a_connect(cfg, log):
    """"CLIENT DISCONNECTED" zawiera "CONNECTED" — wzorce muszą brać całą frazę."""
    log.write_text("CLIENT CONNECTED\nCLIENT DISCONNECTED\n", encoding="utf-8")
    assert cast._last_event(cfg) == "CLIENT DISCONNECTED"
    assert cast._count_connects(cfg) == 1


def test_a_lost_video_source_counts_as_the_stream_ending(cfg, log):
    """Zerwanie po stronie PipeWire nie zapisuje się jako rozłączenie klienta."""
    log.write_text("CLIENT CONNECTED\nPipeWire stream stopped\n", encoding="utf-8")
    assert cast._last_event(cfg) == "PipeWire stream stopped"


# -- stan ----------------------------------------------------------------------


def test_no_sunshine_means_stopped(cfg, monkeypatch):
    _sunshine(monkeypatch, False)
    assert cast.state(None, cfg, tv_awake=True) == "stopped"


def test_disabled_in_the_configuration_means_stopped(log):
    assert cast.state(None, Config(host="tv", cast_enabled=False), tv_awake=True) == "stopped"


def test_a_sleeping_tv_is_ready_not_streaming(cfg, monkeypatch):
    _sunshine(monkeypatch, True)
    assert cast.state(None, cfg, tv_awake=False) == "ready"


def test_moonlight_in_front_and_a_live_client_is_streaming(cfg, log, monkeypatch):
    _sunshine(monkeypatch, True)
    _foreground(monkeypatch, cfg.moonlight_app_id)
    log.write_text("CLIENT CONNECTED\n", encoding="utf-8")
    assert cast.state(None, cfg, tv_awake=True) == "streaming"


def test_moonlight_in_front_but_the_client_left_is_only_ready(cfg, log, monkeypatch):
    _sunshine(monkeypatch, True)
    _foreground(monkeypatch, cfg.moonlight_app_id)
    log.write_text("CLIENT CONNECTED\nCLIENT DISCONNECTED\n", encoding="utf-8")
    assert cast.state(None, cfg, tv_awake=True) == "ready"


def test_another_app_in_front_is_ready(cfg, log, monkeypatch):
    _sunshine(monkeypatch, True)
    _foreground(monkeypatch, "com.webos.app.livetv")
    log.write_text("CLIENT CONNECTED\n", encoding="utf-8")
    assert cast.state(None, cfg, tv_awake=True) == "ready"


def test_a_silent_tv_does_not_upgrade_the_state(cfg, log, monkeypatch):
    """Gdy nie wiadomo, co jest na wierzchu, nie zgadujemy 'streaming'."""
    _sunshine(monkeypatch, True)
    _foreground(monkeypatch, SshError("no reply"))
    log.write_text("CLIENT CONNECTED\n", encoding="utf-8")
    assert cast.state(None, cfg, tv_awake=True) == "ready"
