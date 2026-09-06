"""Model stanu demona — bez telewizora i bez szyny.

Te testy istnieją, bo cała warstwa orkiestracji nie miała ani jednego: literówka
w nazwie argumentu ``submit`` przechodziła przez przegląd i wyłączała
odpytywanie w tle, nie zostawiając po sobie nic poza ciszą.
"""

import inspect

import pytest

from lgtvd import daemon as daemon_mod
from lgtvd.config import Config
from lgtvd.worker import Worker


class FakeTransport:
    """Transport, który nie rozmawia z niczym."""

    def __init__(self, alive=True):
        self._alive = alive
        self.closed = False

    def check(self, command, timeout=None):
        raise AssertionError("no test should reach the TV")

    def alive(self):
        return self._alive

    def close(self):
        self.closed = True


class InlineWorker(Worker):
    """Kolejka wykonująca zadania od razu, w wątku testu.

    Dzięki temu testy nie mają w sobie ani jednego ``sleep`` i nie zależą od
    tego, kiedy wątek roboczy zdąży się obudzić.
    """

    def __init__(self):
        super().__init__()
        self.calls = []

    def start(self):
        pass

    def stop(self):
        pass

    def submit(self, name, func, *, supersedes=False, log_action=True, fields=None):
        if supersedes:
            self.epoch += 1
        self.calls.append(name)
        func()
        return self.epoch


@pytest.fixture
def daemon(monkeypatch):
    d = daemon_mod.Daemon(Config(host="tv"))
    d.transport = FakeTransport()
    d.worker = InlineWorker()
    return d


def _probe(**reading):
    def fake(transport, cfg):
        return reading
    return fake


# -- to, co przepuścił przegląd ------------------------------------------------


def test_every_submit_call_matches_the_worker_signature():
    """Każde wywołanie ``submit`` w pakiecie da się związać z jego sygnaturą.

    Sedno: ``__main__.tick`` wołał ``submit(..., user_action=False)``, czyli
    argument, którego nigdy nie było. Poller wywracał się przy KAŻDYM tiku,
    a widget po cichu zamarzał na ostatnio widzianym stanie.
    """
    import ast
    import pathlib

    signature = inspect.signature(Worker.submit)
    root = pathlib.Path(__file__).resolve().parents[1] / "src" / "lgtvd"
    checked = 0

    for path in sorted(root.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if not (isinstance(node.func, ast.Attribute) and node.func.attr == "submit"):
                continue
            kwargs = {kw.arg for kw in node.keywords if kw.arg is not None}
            # self + name + func, bo w źródle to zawsze wywołanie na obiekcie.
            try:
                signature.bind(None, *([None] * (len(node.args))), **dict.fromkeys(kwargs))
            except TypeError as exc:
                pytest.fail(f"{path.name}:{node.lineno} submit(...): {exc}")
            checked += 1

    assert checked, "no submit() calls found — has the worker been renamed?"


# -- stan ----------------------------------------------------------------------


def test_poll_publishes_power_and_volume(daemon, monkeypatch):
    monkeypatch.setattr(daemon_mod.tv, "probe",
                        _probe(power="active", volume=17, muted=False))
    monkeypatch.setattr(daemon_mod.cast, "state", lambda *a, **k: "stopped")

    seen = []
    daemon.on_change = seen.append
    daemon.poll()

    assert daemon.get("PowerState") == "active"
    assert daemon.get("Volume") == 17
    assert seen, "a state change must reach the observer"


def test_poll_reports_offline_when_probing_blows_up(daemon, monkeypatch):
    def boom(transport, cfg):
        raise RuntimeError("no route to host")

    monkeypatch.setattr(daemon_mod.tv, "probe", boom)
    daemon.poll()
    assert daemon.get("PowerState") == "offline"


def test_poll_keeps_out_of_the_way_while_power_is_switching(daemon, monkeypatch):
    def boom(transport, cfg):
        raise AssertionError("poll must not probe during a power transition")

    monkeypatch.setattr(daemon_mod.tv, "probe", boom)
    daemon._update(PowerState="turning-on")
    daemon.poll()
    assert daemon.get("PowerState") == "turning-on"


def test_observer_hears_only_real_changes(daemon):
    seen = []
    daemon.on_change = seen.append

    daemon._update(Volume=40)
    daemon._update(Volume=40)

    assert seen == [{"Volume": 40}]


def test_unknown_state_key_is_refused(daemon):
    with pytest.raises(KeyError):
        daemon._update(Nonsense=1)


# -- polecenia -----------------------------------------------------------------


def test_media_key_refuses_a_name_it_does_not_know(daemon):
    with pytest.raises(ValueError, match="unknown media key"):
        daemon.media_key("eject")


def test_volume_is_clamped_and_shown_before_the_tv_confirms(daemon, monkeypatch):
    sent = []
    monkeypatch.setattr(daemon_mod.tv, "set_volume",
                        lambda transport, value: sent.append(value))

    daemon.set_volume(250)
    assert daemon.get("Volume") == 100
    assert sent == [100]


def test_a_burst_from_the_slider_sends_only_the_last_value(daemon, monkeypatch):
    """Suwak sypie dziesiątkami zdarzeń; telewizor ma dostać jedno."""
    sent = []
    monkeypatch.setattr(daemon_mod.tv, "set_volume",
                        lambda transport, value: sent.append(value))

    # Kolejka wykonuje zadania natychmiast, więc żeby odtworzyć lawinę, trzyma
    # my pierwsze zadanie i puszczamy je dopiero po zebraniu całej serii.
    held = []
    daemon.worker.submit = lambda name, func, **kw: held.append(func) or 0

    for value in (10, 20, 30, 40):
        daemon.set_volume(value)

    assert len(held) == 1, "one queued job for the whole burst"
    held[0]()
    assert sent == [40]
    assert daemon.get("Volume") == 40


def test_turning_off_an_already_off_tv_does_nothing(daemon):
    daemon._update(PowerState="offline")
    daemon.set_power(False)
    assert daemon.worker.calls == []


def test_cast_is_refused_when_it_is_switched_off_in_the_configuration():
    d = daemon_mod.Daemon(Config(host="tv", cast_enabled=False))
    d.transport = FakeTransport()
    d.worker = InlineWorker()
    with pytest.raises(RuntimeError, match="disabled"):
        d.set_cast(True)


def test_stop_closes_the_shared_connection(daemon):
    daemon.stop()
    assert daemon.transport.closed
