"""Włączanie i wyłączanie — pętla czekania, ponawianie, pakiet budzący."""

import contextlib

import pytest

from lgtvd import power, tv
from lgtvd.config import Config


class FakeClock:
    """Zegar sterowany z testu; nic tu naprawdę nie śpi."""

    def __init__(self):
        self.now = 1000.0

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class FakeTransport:
    pass


@pytest.fixture
def clock(monkeypatch):
    c = FakeClock()
    monkeypatch.setattr(power.time, "monotonic", c.monotonic)
    monkeypatch.setattr(power.time, "sleep", c.sleep)
    return c


def _states(monkeypatch, sequence, clock=None, cost=0.0):
    """Podstawia kolejne odczyty stanu; ``cost`` to czas jednego sondowania."""
    seen = iter(sequence)
    last = [sequence[-1]]

    def fake(transport):
        if clock is not None:
            clock.now += cost
        with contextlib.suppress(StopIteration):
            last[0] = next(seen)
        return last[0]

    monkeypatch.setattr(tv, "power_state", fake)


# -- pakiet budzący ------------------------------------------------------------


def test_a_malformed_mac_is_refused():
    with pytest.raises(power.PowerError, match="invalid MAC"):
        power._magic_packet("nonsense")


def test_the_magic_packet_has_the_shape_the_nic_expects():
    packet = power._magic_packet("AA:BB:CC:DD:EE:FF")
    assert len(packet) == 102              # 6 x 0xff + 16 x 6 bajtów
    assert packet[:6] == b"\xff" * 6
    assert packet[6:12] == bytes.fromhex("aabbccddeeff")


def test_separators_in_the_mac_do_not_matter():
    assert power._magic_packet("aa-bb-cc-dd-ee-ff") == power._magic_packet("aabbccddeeff")


def test_turning_on_without_a_mac_says_so():
    with pytest.raises(power.PowerError, match="no MAC address"):
        power.turn_on(FakeTransport(), Config(host="tv", mac=""))


# -- pętla czekania ------------------------------------------------------------


def test_waiting_returns_as_soon_as_the_state_is_reached(clock, monkeypatch):
    _states(monkeypatch, ["standby", "standby", "active"])
    state = power._wait_for(
        FakeTransport(), want_awake=True, limit=90, retry_every=5, resend=lambda: None
    )
    assert state == "active"


def test_no_probe_is_started_once_the_deadline_has_passed(clock, monkeypatch):
    """Po przekroczeniu limitu nie zaczynamy kolejnego sondowania.

    Jedno sondowanie to w najgorszym razie dwa wywołania ssh z ConnectTimeout.
    Gdy limit sprawdzano dopiero PO powrocie, pętla płaciła ten czas nawet
    wtedy, gdy było już pewne, że wynik pójdzie do kosza.
    """
    # Dobrane tak, żeby oba warianty dało się rozróżnić: przy sondowaniu po
    # 10 s i pauzie 2 s obiegi wypadają w 0, 12, 24 i 36 s, więc czwarty
    # startuje już PO limicie 35 s. Ze sprawdzeniem limitu po sondowaniu ten
    # czwarty się odbywa; ze sprawdzeniem przed — nie.
    probes = []

    def fake(transport):
        probes.append(clock.now - 1000.0)
        clock.now += 10.0
        return "standby"

    monkeypatch.setattr(tv, "power_state", fake)

    with pytest.raises(power.PowerError, match="within 35s"):
        power._wait_for(
            FakeTransport(), want_awake=True, limit=35, retry_every=5, resend=lambda: None
        )

    assert probes, "the loop has to probe at least once"
    assert all(at < 35 for at in probes), (
        f"a probe was started after the deadline had passed: {probes}"
    )


def test_the_timeout_message_names_the_last_state_seen(clock, monkeypatch):
    _states(monkeypatch, ["standby"] * 100, clock=clock, cost=1.0)
    with pytest.raises(power.PowerError, match="last seen: standby"):
        power._wait_for(
            FakeTransport(), want_awake=True, limit=10, retry_every=5, resend=lambda: None
        )


def test_the_command_is_repeated_while_waiting(clock, monkeypatch):
    _states(monkeypatch, ["standby"] * 100, clock=clock, cost=0.0)
    sent = []
    with pytest.raises(power.PowerError):
        power._wait_for(
            FakeTransport(), want_awake=True, limit=20, retry_every=5,
            resend=lambda: sent.append(1),
        )
    assert len(sent) >= 2, "a dropped magic packet must be followed by another"


def test_cancelling_stops_the_wait_immediately(clock, monkeypatch):
    _states(monkeypatch, ["standby"] * 100)
    with pytest.raises(power.PowerError, match="cancelled"):
        power._wait_for(
            FakeTransport(), want_awake=True, limit=90, retry_every=5,
            resend=lambda: None, cancelled=lambda: True,
        )


# -- wyłączanie ----------------------------------------------------------------


def test_the_power_key_fallback_fires_at_most_once(clock, monkeypatch):
    """KEY_POWER to PRZEŁĄCZNIK: powtórzony po zgaśnięciu włączyłby TV z powrotem."""
    monkeypatch.setattr(tv, "power_off", lambda transport: False)
    _states(monkeypatch, ["active"] * 100, clock=clock, cost=0.0)

    taps = []
    import lgtvd.keys
    monkeypatch.setattr(lgtvd.keys, "tap",
                        lambda transport, device, code: taps.append(code))

    with pytest.raises(power.PowerError):
        power.turn_off(FakeTransport(), Config(host="tv", off_timeout=30, retry_every=1))

    assert taps == [116], "the power key must be tapped exactly once"


def test_a_clean_power_off_never_reaches_the_fallback(clock, monkeypatch):
    monkeypatch.setattr(tv, "power_off", lambda transport: True)
    _states(monkeypatch, ["active", "standby"])

    import lgtvd.keys

    def forbidden(*args, **kwargs):
        raise AssertionError("the fallback must stay untouched")

    monkeypatch.setattr(lgtvd.keys, "tap", forbidden)

    state = power.turn_off(FakeTransport(), Config(host="tv", off_timeout=30))
    assert state == "standby"
