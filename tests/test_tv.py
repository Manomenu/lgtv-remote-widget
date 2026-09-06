"""Odczyt stanu telewizora z odpowiedzi szyny — bez telewizora."""

import pytest

from lgtvd import tv
from lgtvd.ssh import SshError


class FakeTransport:
    """Udaje transport: oddaje przygotowane odpowiedzi albo rzuca."""

    def __init__(self, replies=None, alive=True):
        self._replies = replies or {}
        self._alive = alive

    def check(self, command, timeout=None):
        for needle, reply in self._replies.items():
            if needle in command:
                if isinstance(reply, Exception):
                    raise reply
                return reply
        raise SshError("unexpected command: " + command)

    def alive(self):
        return self._alive


@pytest.mark.parametrize(("reported", "expected"), [
    ("Active", "active"),
    ("Screen Off", "screen-off"),
    ("Screen Saver", "screen-saver"),
    ("Active Standby", "standby"),
    ("Suspend", "standby"),
    ("Prepare Suspend", "standby"),
])
def test_known_power_states(reported, expected):
    reply = f'{{"returnValue":true,"state":"{reported}"}}'
    transport = FakeTransport({"getPowerState": reply})
    assert tv.power_state(transport) == expected


def test_unknown_state_counts_as_on():
    # Skoro szyna odpowiada, telewizor pracuje — nawet jeśli nazwał swój stan
    # inaczej, niż znamy.
    transport = FakeTransport({"getPowerState": '{"returnValue":true,"state":"Brand New"}'})
    assert tv.power_state(transport) == "active"


def test_silent_bus_with_working_ssh_is_standby():
    # Tak wygląda czuwanie przy Szybkim uruchamianiu+: sieć żyje, usługi nie.
    transport = FakeTransport({"getPowerState": SshError("no reply")}, alive=True)
    assert tv.power_state(transport) == "standby"


def test_no_ssh_at_all_is_offline():
    transport = FakeTransport({"getPowerState": SshError("no route")}, alive=False)
    assert tv.power_state(transport) == "offline"


def test_volume_and_mute_are_read_together():
    transport = FakeTransport({"getVolume": """
        {"returnValue":true,"volumeStatus":{"volume":17,"muteStatus":true}}
    """})
    assert tv.get_volume(transport) == (17, True)


def test_volume_is_clamped_to_the_scale():
    sent = []

    class Recorder(FakeTransport):
        def check(self, command, timeout=None):
            sent.append(command)
            return '{"returnValue":true}'

    assert tv.set_volume(Recorder(), 250) == 100
    assert tv.set_volume(Recorder(), -5) == 0
    assert '"volume":100' in sent[0]


def test_garbage_reply_is_reported_as_an_ssh_problem():
    transport = FakeTransport({"getPowerState": "sh: luna-send: not found"})
    # Nie da się tego odróżnić od milczącej szyny, więc pytamy o SSH.
    assert tv.power_state(transport) == "standby"
