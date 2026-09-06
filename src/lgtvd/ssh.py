"""Jedno połączenie SSH do telewizora na cały czas życia demona.

Zestawienie sesji SSH kosztuje ~150 ms. Przy suwaku głośności, który wysyła
polecenie kilka razy na sekundę, to różnica między „reaguje” a „zacina się”.
ControlMaster utrzymuje jedno gniazdo, przez które kolejne polecenia lecą
w ~30 ms.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass

from .config import Config
from .logs import log
from .paths import runtime_dir


class SshError(RuntimeError):
    """Telewizor nie odpowiedział — wyłączony, poza siecią albo zerwana sesja."""


@dataclass(slots=True)
class Result:
    code: int
    out: str
    err: str

    @property
    def ok(self) -> bool:
        return self.code == 0


class Transport:
    def __init__(self, cfg: Config) -> None:
        self._cfg = cfg
        socket_dir = runtime_dir()
        socket_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        # %C to skrót hosta/portu/użytkownika liczony przez ssh — krótka nazwa
        # gniazda, bez ryzyka przekroczenia limitu długości ścieżki uniksowej.
        self._control_path = str(socket_dir / "ssh-%C")
        self._ssh = shutil.which("ssh") or "ssh"

    # -- niskopoziomowo --------------------------------------------------------

    def _args(self, timeout: int) -> list[str]:
        return [
            self._ssh,
            "-T",
            "-o", "BatchMode=yes",
            "-o", f"ConnectTimeout={timeout}",
            "-o", "ControlMaster=auto",
            "-o", f"ControlPath={self._control_path}",
            "-o", f"ControlPersist={self._cfg.control_persist}",
            "-o", "ServerAliveInterval=15",
            "-o", "ServerAliveCountMax=2",
            self._cfg.host,
        ]

    def run(self, command: str, timeout: int | None = None) -> Result:
        """Uruchamia polecenie na telewizorze. Nie rzuca — zwraca wynik."""
        connect_timeout = self._cfg.connect_timeout
        wall = timeout if timeout is not None else connect_timeout + 15
        try:
            proc = subprocess.run(
                [*self._args(connect_timeout), command],
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=wall,
            )
        except subprocess.TimeoutExpired:
            return Result(124, "", f"timed out after {wall}s")
        except OSError as exc:
            return Result(127, "", str(exc))
        return Result(proc.returncode, proc.stdout, proc.stderr)

    def check(self, command: str, timeout: int | None = None) -> str:
        result = self.run(command, timeout)
        if not result.ok:
            raise SshError(result.err.strip() or f"ssh exited with {result.code}")
        return result.out

    # -- utrzymanie ------------------------------------------------------------

    def alive(self) -> bool:
        """Czy telewizor odpowiada. Krótki limit — to ma być szybkie pytanie."""
        return self.run("true", timeout=self._cfg.connect_timeout + 2).ok

    def close(self) -> None:
        """Zamyka wspólne gniazdo, żeby nie zostawiać po sobie procesu ssh."""
        try:
            subprocess.run(
                [
                    self._ssh,
                    "-o", f"ControlPath={self._control_path}",
                    "-O", "exit",
                    self._cfg.host,
                ],
                stdin=subprocess.DEVNULL,
                capture_output=True,
                timeout=5,
            )
        except (subprocess.SubprocessError, OSError) as exc:
            log.debug("closing the shared ssh socket failed: %s", exc)
