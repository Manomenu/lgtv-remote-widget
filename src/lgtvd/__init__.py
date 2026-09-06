"""lgtvd — demon sterujący telewizorem LG (webOS) po SSH.

Wystawia stan i polecenia na szynie D-Bus sesji, żeby rozszerzenie GNOME Shell
mogło być cienką warstwą widoku: cała latencja (SSH, Wake-on-LAN, czekanie na
potwierdzenie) zostaje po tej stronie.
"""

__version__ = "1.0.0"
APP_ID = "lgtv-remote"
