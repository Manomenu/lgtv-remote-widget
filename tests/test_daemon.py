"""Model stanu demona — bez telewizora i bez szyny.

Te testy istnieją, bo cała warstwa orkiestracji nie miała ani jednego: literówka
w nazwie argumentu ``submit`` przechodziła przez przegląd i wyłączała
odpytywanie w tle, nie zostawiając po sobie nic poza ciszą.
"""

import inspect
import time

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


def test_cast_enabled_is_published_so_the_widget_can_hide_the_tile():
    """setup.cfg.example obiecuje, że wyłączenie castu chowa kafelek.

    Widget nie ma innego sposobu, żeby się o tym dowiedzieć, niż właściwość
    na szynie — bez niej kafelek zostawał na miejscu i po kliknięciu tylko
    zwracał błąd.
    """
    on = daemon_mod.Daemon(Config(host="tv", cast_enabled=True))
    off = daemon_mod.Daemon(Config(host="tv", cast_enabled=False))
    assert on.get("CastEnabled") is True
    assert off.get("CastEnabled") is False


def test_every_published_property_has_a_dbus_signature():
    """Stan demona, tabela sygnatur i XML introspekcji nie mogą się rozjechać.

    Właściwość dodana tylko po jednej stronie wraca przez szynę jako None, bez
    żadnego błędu po drodze — widget widzi wtedy pustkę i nie ma jak zgadnąć,
    dlaczego.

    Czytamy dbus.py przez AST, a nie importem: moduł ciągnie za sobą PyGObject,
    którego na maszynie budującej może nie być, a ta zgodność nie ma z nim nic
    wspólnego.
    """
    import ast
    import pathlib
    import re

    source = (pathlib.Path(__file__).resolve().parents[1]
              / "src" / "lgtvd" / "dbus.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    signatures = next(
        ast.literal_eval(node.value)
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(getattr(t, "id", None) == "_SIGNATURES" for t in node.targets)
    )

    published = set(daemon_mod.Daemon(Config(host="tv")).snapshot())
    assert published == set(signatures)

    # Ta sama lista musi stać w XML-u, inaczej właściwości nie widać z zewnątrz.
    declared = set(re.findall(r'<property name="(\w+)"', source))
    assert published == declared


def test_the_volume_job_does_not_block_the_queue(daemon, monkeypatch):
    """Głośność nie ma prawa zatrzymywać innych poleceń.

    Throttle był realizowany przez time.sleep() w wątku roboczym, czyli
    wstrzymywał WSZYSTKO — naciśnięcie „dalej” w trakcie kręcenia głośnością
    czekało na koniec cudzej pauzy.
    """
    monkeypatch.setattr(daemon_mod.tv, "set_volume", lambda transport, value: None)

    daemon.cfg.volume_throttle_ms = 5000
    started = time.monotonic()
    daemon.set_volume(30)
    daemon.set_volume(60)
    elapsed = time.monotonic() - started

    assert elapsed < 1.0, f"the volume path slept for {elapsed:.1f}s"


# -- anulowanie nie zostawia stanu przejściowego -------------------------------


def _cancels(transport, cfg, **kwargs):
    """Zaślepka operacji zasilania, która wykrywa unieważnienie i przerywa."""
    assert kwargs["cancelled"](), "the test worker must report the job as superseded"
    raise daemon_mod.power.PowerError("cancelled")


def _cancels_cast(transport, cfg, **kwargs):
    """To samo dla strumieniowania."""
    assert kwargs["cancelled"](), "the test worker must report the job as superseded"
    raise daemon_mod.cast.CastError("cancelled")


class CancellingWorker(InlineWorker):
    """Kolejka, w której KAŻDE zadanie zastaje się już unieważnione.

    Odtwarza to, co w praktyce robi drugie kliknięcie: licznik epok jest
    wspólny dla zasilania i strumieniowania, więc kliknięcie Screencastu
    unieważnia trwające włączanie telewizora i odwrotnie.
    """

    def superseded(self, epoch):
        return True


def test_a_cancelled_power_job_does_not_leave_the_state_stuck(monkeypatch):
    """Sedno: poll() celowo omija turning-on/turning-off.

    Gdyby anulowane zadanie zostawiło tam stan, nikt by go już nie zdjął —
    widget trzymałby kafelek wyłączony (busy) aż do restartu demona, czyli
    pilot przestawałby działać zupełnie.
    """
    d = daemon_mod.Daemon(Config(host="tv", mac="aa:bb:cc:dd:ee:ff"))
    d.transport = FakeTransport()
    d.worker = CancellingWorker()

    monkeypatch.setattr(daemon_mod.tv, "power_state", lambda transport: "standby")
    monkeypatch.setattr(daemon_mod.power, "turn_on", _cancels)

    d.set_power(True)

    assert d.get("PowerState") == "standby", "a cancelled job must clear the transient state"
    assert not d.get("PowerState").startswith("turning-")


def test_a_cancelled_power_job_survives_an_unreachable_tv(monkeypatch):
    """Nawet gdy nie da się zapytać telewizora, stan przejściowy musi zniknąć."""
    d = daemon_mod.Daemon(Config(host="tv", mac="aa:bb:cc:dd:ee:ff"))
    d.transport = FakeTransport()
    d.worker = CancellingWorker()

    def boom(transport):
        raise RuntimeError("the TV is gone")

    monkeypatch.setattr(daemon_mod.tv, "power_state", boom)
    monkeypatch.setattr(daemon_mod.power, "turn_on", _cancels)

    d.set_power(True)
    assert d.get("PowerState") == "offline"


def test_a_cancelled_cast_job_does_not_leave_the_tile_disabled(monkeypatch):
    """To samo dla strumieniowania: "starting" blokuje kafelek."""
    d = daemon_mod.Daemon(Config(host="tv"))
    d.transport = FakeTransport()
    d.worker = CancellingWorker()

    monkeypatch.setattr(daemon_mod.cast, "state", lambda *a, **k: "ready")
    monkeypatch.setattr(daemon_mod.cast, "start", _cancels_cast)

    d._update(PowerState="active")
    d.set_cast(True)

    assert d.get("CastState") == "ready", "a cancelled job must clear 'starting'"
