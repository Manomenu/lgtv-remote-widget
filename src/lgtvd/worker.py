"""Jeden wątek roboczy na wszystkie polecenia do telewizora.

Wszystko idzie po kolei, i to jest cecha, nie ograniczenie: telewizor ma jedno
gniazdo SSH i jedną szynę usług, więc równoległe polecenia najwyżej wchodziłyby
sobie w drogę. Kolejka gwarantuje przy okazji, że stan czytany po wykonaniu
polecenia jest stanem PO nim, a nie w jego trakcie.

Zadania dzielą się na dwa rodzaje i to rozróżnienie jest tu najważniejsze:

  * ``supersedes=True`` — polecenia DŁUGIE i wykluczające się (włącz/wyłącz
    telewizor, zacznij/przerwij strumieniowanie). Nowe unieważnia poprzednie:
    nie ma sensu czekać 90 sekund na włączenie, skoro użytkownik zdążył kliknąć
    „wyłącz”.

  * ``supersedes=False`` — polecenia KRÓTKIE i sumujące się (klawisze pilota,
    wyciszenie, głośność, odpytywanie). Każde ma zadziałać. Trzy szybkie
    kliknięcia „dalej” to trzy przewinięcia, a nie jedno.
"""

from __future__ import annotations

import queue
import threading
import time
from collections.abc import Callable

from .logs import log, record


class Worker:
    def __init__(self) -> None:
        self._queue: queue.SimpleQueue = queue.SimpleQueue()
        self._thread = threading.Thread(target=self._run, name="lgtvd-worker", daemon=True)
        self._stopping = threading.Event()
        #: Rośnie przy każdym poleceniu unieważniającym. Długie operacje
        #: sprawdzają, czy numer się nie zmienił — jeśli tak, ktoś kliknął coś
        #: nowego i nie ma sensu czekać dalej na poprzedni cel.
        self.epoch = 0
        self._lock = threading.Lock()

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stopping.set()
        self._queue.put(None)

    # -- zgłaszanie zadań ------------------------------------------------------

    def submit(
        self,
        name: str,
        func: Callable[[], object],
        *,
        supersedes: bool = False,
        log_action: bool = True,
        fields: dict | None = None,
    ) -> int:
        """Kolejkuje zadanie i zwraca numer epoki, pod którą je przyjęto.

        ``fields`` trafia do wpisu w actions.log, żeby jedna akcja dawała jedną
        linię z kompletem szczegółów, zamiast dwóch niepełnych.
        """
        with self._lock:
            if supersedes:
                self.epoch += 1
            epoch = self.epoch
        self._queue.put((name, func, epoch, supersedes, log_action, fields or {}))
        return epoch

    def superseded(self, epoch: int) -> bool:
        """Czy w międzyczasie przyszło nowsze polecenie unieważniające."""
        with self._lock:
            return epoch != self.epoch

    @property
    def backlog(self) -> int:
        return self._queue.qsize()

    # -- pętla -----------------------------------------------------------------

    def _run(self) -> None:
        while not self._stopping.is_set():
            item = self._queue.get()
            if item is None:
                break
            name, func, epoch, supersedes, log_action, fields = item

            if supersedes and self.superseded(epoch):
                log.debug("%s dropped — a newer command arrived", name)
                continue

            started = time.monotonic()
            try:
                func()
            except Exception as exc:
                duration = time.monotonic() - started
                log.warning("%s failed: %s", name, exc, exc_info=log.isEnabledFor(10))
                if log_action:
                    record(name, "error", duration,
                           **fields, detail=str(exc).replace("\n", " ")[:200])
            else:
                if log_action:
                    record(name, "ok", time.monotonic() - started, **fields)
