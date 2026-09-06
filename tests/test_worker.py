"""Kolejka poleceń: kolejność, odrzucanie nieaktualnych, odporność na wyjątki."""

import threading
import time

from lgtvd.worker import Worker


def run_worker():
    worker = Worker()
    worker.start()
    return worker


def test_tasks_run_in_order():
    worker = run_worker()
    seen = []
    done = threading.Event()

    for n in range(5):
        worker.submit(f"task{n}", lambda n=n: seen.append(n), log_action=False)
    worker.submit("last", done.set, log_action=False)

    assert done.wait(5)
    assert seen == [0, 1, 2, 3, 4]
    worker.stop()


def test_a_failing_task_does_not_kill_the_queue():
    worker = run_worker()
    done = threading.Event()

    def boom():
        raise RuntimeError("the TV said no")

    worker.submit("boom", boom)
    worker.submit("after", done.set, log_action=False)

    assert done.wait(5)
    worker.stop()


def test_a_newer_long_command_supersedes_the_one_still_queued():
    """Włączanie i wyłączanie wykluczają się — liczy się ostatnie kliknięcie."""
    worker = Worker()
    ran = []
    gate = threading.Event()

    # Pierwsze zadanie blokuje wątek, żeby dwa kolejne zdążyły trafić do kolejki
    # razem — dokładnie tak, jak przy dwóch szybkich kliknięciach.
    worker.submit("block", gate.wait, log_action=False)
    worker.start()

    first = worker.submit("first", lambda: ran.append("first"), supersedes=True)
    worker.submit("second", lambda: ran.append("second"), supersedes=True)
    assert worker.superseded(first)

    gate.set()
    deadline = time.monotonic() + 5
    while "second" not in ran and time.monotonic() < deadline:
        time.sleep(0.01)

    assert ran == ["second"]
    worker.stop()


def test_short_commands_all_run():
    """Trzy kliknięcia „dalej” to trzy przewinięcia, nie jedno.

    Klawisze pilota sumują się, więc nie wolno ich unieważniać nowszym
    poleceniem — inaczej szybkie klikanie gubi wszystko poza ostatnim.
    """
    worker = Worker()
    ran = []
    gate = threading.Event()
    done = threading.Event()

    worker.submit("block", gate.wait, log_action=False)
    worker.start()

    for n in range(3):
        worker.submit("media_key", lambda n=n: ran.append(n), log_action=False)
    worker.submit("done", done.set, log_action=False)

    gate.set()
    assert done.wait(5)
    assert ran == [0, 1, 2]
    worker.stop()


def test_a_long_command_does_not_cancel_short_ones():
    """Naciśnięcie „dalej” w trakcie włączania telewizora ma zadziałać."""
    worker = Worker()
    ran = []
    gate = threading.Event()
    done = threading.Event()

    worker.submit("block", gate.wait, log_action=False)
    worker.start()

    worker.submit("media_key", lambda: ran.append("key"), log_action=False)
    worker.submit("set_power", lambda: ran.append("power"),
                  supersedes=True, log_action=False)
    worker.submit("done", done.set, log_action=False)

    gate.set()
    assert done.wait(5)
    assert ran == ["key", "power"]
    worker.stop()
