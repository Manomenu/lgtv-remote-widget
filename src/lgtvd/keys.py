"""Wstrzykiwanie naciśnięć pilota do warstwy wejściowej telewizora.

Ustalone doświadczalnie na tym firmwarze — szczegóły i sposób pomiaru
w docs/webos-notes.md:

  * „dalej/wstecz” to na tym pilocie rocker kanałów (góra/dół), który wysyła kody **402
    i 403** (KEY_CHANNELUP / KEY_CHANNELDOWN), a nie klawisze multimedialne.
    Zarejestrowane przez nasłuchiwanie wszystkich urządzeń wejściowych
    w trakcie naciskania prawdziwego pilota.
  * Naciśnięcia z prawdziwego pilota przychodzą na urządzeniu o nazwie
    „LGE M-RCU - Builtin [2]”, więc tam je wstrzykujemy — najbliżej oryginału.
  * ``/dev/input/event0`` przyjmuje zapisy i nie dostarcza nic; kilka innych
    urządzeń dostarcza. Numer urządzenia NIE jest stały: między dwoma
    pomiarami tego samego dnia lista urosła z 7 do 11 pozycji, bo doszło
    audio Bluetooth, mysz i klawiatura IoT.

Dlatego urządzenie jest wyszukiwane po NAZWIE, a skonfigurowana ścieżka służy
tylko za zapas. Wyszukiwanie robi skrypt po stronie telewizora, żeby całość
kosztowała jedno połączenie i nie wymagała pamiętania stanu.
"""

from __future__ import annotations

import base64
import shlex

from .config import Config
from .ssh import Transport

# Skrypt biegnie na telewizorze. Pisze parę zdarzeń: naciśnięcie, synchronizacja,
# krótka pauza, puszczenie, synchronizacja — dokładnie tak, jak wygląda
# pojedyncze wciśnięcie przycisku na prawdziwym pilocie.
#
# struct "llHHi" to input_event na 64-bitowym jądrze: dwa pola timeval (jądro
# i tak wstawia własny czas, więc idą zera), typ, kod, wartość.
_REMOTE = r"""
import glob, os, struct, sys, time

wanted, fallback, code = sys.argv[1], sys.argv[2], int(sys.argv[3])


def device_name(path):
    node = "/sys/class/input/%s/device/name" % os.path.basename(path)
    try:
        with open(node) as handle:
            return handle.read().strip()
    except OSError:
        return ""


device = ""
if wanted:
    for path in sorted(glob.glob("/dev/input/event*")):
        if device_name(path) == wanted:
            device = path
            break
device = device or fallback


def event(kind, key, value):
    return struct.pack("llHHi", 0, 0, kind, key, value)


fd = os.open(device, os.O_WRONLY)
try:
    os.write(fd, event(1, code, 1)); os.write(fd, event(0, 0, 0))
    # Prawdziwy pilot trzyma przycisk około 160 ms (zmierzone). Zbyt krótkie
    # naciśnięcie aplikacja może uznać za drgnięcie styku i zignorować, więc
    # trzymamy podobnie długo zamiast strzelać najkrócej, jak się da.
    time.sleep(0.12)
    os.write(fd, event(1, code, 0)); os.write(fd, event(0, 0, 0))
finally:
    os.close(fd)
print("OK " + device)
"""


def tap(transport: Transport, cfg: Config, code: int) -> str:
    """Wciska i puszcza jeden klawisz. Zwraca użyte urządzenie.

    Skrypt jedzie zakodowany w base64, żeby cudzysłowy i znaki specjalne nie
    miały szans niczego popsuć po drodze przez powłokę lokalną, SSH i powłokę
    na telewizorze.
    """
    payload = base64.b64encode(_REMOTE.encode("utf-8")).decode("ascii")
    command = (
        f"echo {payload} | base64 -d > /tmp/.lgtvd-key.py && "
        f"python3 /tmp/.lgtvd-key.py {shlex.quote(cfg.key_device_name)} "
        f"{shlex.quote(cfg.key_device)} {int(code)}"
    )
    return transport.check(command).strip()
