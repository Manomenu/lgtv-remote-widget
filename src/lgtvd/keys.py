"""Wstrzykiwanie naciśnięć pilota do warstwy wejściowej telewizora.

Ustalone doświadczalnie na tym firmwarze (szczegóły w docs/webos-notes.md):

  * ``/dev/input/event0`` deklaruje w bitmapie WSZYSTKIE kody klawiszy, ale
    webOS z niego nie czyta — zapis kończy się sukcesem i nic się nie dzieje.
  * ``/dev/input/event5`` obsługuje 45 kodów i to z niego webOS faktycznie
    czyta. Nie ma wśród nich KEY_NEXTSONG ani KEY_PREVIOUSSONG, są natomiast
    KEY_FASTFORWARD i KEY_REWIND — i to one pełnią rolę „dalej/wstecz”.

Kody siedzą w konfiguracji, żeby dało się je podmienić bez ruszania kodu.
"""

from __future__ import annotations

import base64
import shlex

from .ssh import Transport

# Skrypt biegnie na telewizorze. Pisze parę zdarzeń: naciśnięcie, synchronizacja,
# krótka pauza, puszczenie, synchronizacja — dokładnie tak, jak wygląda
# pojedyncze wciśnięcie przycisku na prawdziwym pilocie.
#
# struct "llHHi" to input_event na 64-bitowym jądrze: dwa pola timeval (jądro
# i tak wstawia własny czas, więc idą zera), typ, kod, wartość.
_REMOTE = r"""
import os, struct, sys, time

device, code = sys.argv[1], int(sys.argv[2])

def event(kind, key, value):
    return struct.pack("llHHi", 0, 0, kind, key, value)

fd = os.open(device, os.O_WRONLY)
try:
    os.write(fd, event(1, code, 1)); os.write(fd, event(0, 0, 0))
    time.sleep(0.04)
    os.write(fd, event(1, code, 0)); os.write(fd, event(0, 0, 0))
finally:
    os.close(fd)
print("OK")
"""


def tap(transport: Transport, device: str, code: int) -> None:
    """Wciska i puszcza jeden klawisz.

    Skrypt jedzie zakodowany w base64, żeby cudzysłowy i znaki specjalne nie
    miały szans niczego popsuć po drodze przez powłokę lokalną, SSH i powłokę
    na telewizorze.
    """
    payload = base64.b64encode(_REMOTE.encode("utf-8")).decode("ascii")
    command = (
        f"echo {payload} | base64 -d > /tmp/.lgtvd-key.py && "
        f"python3 /tmp/.lgtvd-key.py {shlex.quote(device)} {int(code)}"
    )
    transport.check(command)
