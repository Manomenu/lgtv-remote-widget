"""Kolejność źródeł konfiguracji i konwersja typów."""

import textwrap

import pytest

from lgtvd import config


def write(tmp_path, text):
    path = tmp_path / "config.ini"
    path.write_text(textwrap.dedent(text), encoding="utf-8")
    return path


def test_defaults_apply_when_the_file_is_silent(tmp_path):
    cfg = config.load(write(tmp_path, "[tv]\nhost = tv\n"))
    assert cfg.host == "tv"
    assert cfg.key_next == 208          # KEY_FASTFORWARD
    assert cfg.poll_idle == 30


def test_file_overrides_defaults(tmp_path):
    cfg = config.load(write(tmp_path, """
        [tv]
        host = other-tv
        [keys]
        next = 163
    """))
    assert cfg.host == "other-tv"
    assert cfg.key_next == 163


def test_environment_beats_the_file(tmp_path, monkeypatch):
    path = write(tmp_path, "[tv]\nhost = from-file\n")
    monkeypatch.setenv("LGTV_HOST", "from-env")
    cfg = config.load(path)
    assert cfg.host == "from-env"
    assert "environment" in cfg.sources


def test_blank_environment_does_not_override(tmp_path, monkeypatch):
    path = write(tmp_path, "[tv]\nhost = from-file\n")
    monkeypatch.setenv("LGTV_HOST", "   ")
    assert config.load(path).host == "from-file"


def test_booleans_and_numbers_are_converted(tmp_path):
    cfg = config.load(write(tmp_path, """
        [tv]
        host = tv
        [cast]
        enabled = no
        [keys]
        previous = 0xA8
    """))
    assert cfg.cast_enabled is False
    assert cfg.key_previous == 168


def test_unreadable_value_names_the_setting(tmp_path):
    path = write(tmp_path, "[tv]\nhost = tv\n[keys]\nnext = banana\n")
    with pytest.raises(ValueError, match=r"keys\.next"):
        config.load(path)


def test_empty_host_is_refused(tmp_path):
    with pytest.raises(ValueError, match=r"tv\.host"):
        config.load(write(tmp_path, "[tv]\nhost =\n"))
