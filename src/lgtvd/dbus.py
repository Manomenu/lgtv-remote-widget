"""Wystawienie demona na szynie D-Bus sesji.

Gio pochodzi z PyGObject, które na systemie z GNOME jest zawsze — dzięki temu
demon nie ma ani jednej zależności spoza pakietów dystrybucji.

Wszystkie odpowiedzi wracają natychmiast: metody tylko kolejkują pracę i wracają,
a o jej wyniku informuje zmiana właściwości. Rozszerzenie Shella nigdy nie czeka.
"""

from __future__ import annotations

from gi.repository import Gio, GLib

from .daemon import Daemon
from .logs import log

BUS_NAME = "org.maniumek.LgtvRemote"
OBJECT_PATH = "/org/maniumek/LgtvRemote"
INTERFACE = "org.maniumek.LgtvRemote1"

INTROSPECTION = f"""
<node>
  <interface name="{INTERFACE}">
    <method name="SetPower">   <arg type="b" name="on"    direction="in"/></method>
    <method name="SetVolume">  <arg type="i" name="value" direction="in"/></method>
    <method name="SetMute">    <arg type="b" name="muted" direction="in"/></method>
    <method name="MediaKey">   <arg type="s" name="key"   direction="in"/></method>
    <method name="SetCast">    <arg type="b" name="on"    direction="in"/></method>
    <method name="Refresh"/>
    <property name="PowerState" type="s" access="read"/>
    <property name="Volume"     type="i" access="read"/>
    <property name="Muted"      type="b" access="read"/>
    <property name="CastState"  type="s" access="read"/>
    <property name="LastError"  type="s" access="read"/>
  </interface>
</node>
"""

_SIGNATURES = {
    "PowerState": "s",
    "Volume": "i",
    "Muted": "b",
    "CastState": "s",
    "LastError": "s",
}


class Service:
    def __init__(self, daemon: Daemon) -> None:
        self._daemon = daemon
        self._connection: Gio.DBusConnection | None = None
        self._registration = 0
        self._owner_id = 0
        daemon.on_change = self._on_change

    # -- rejestracja -----------------------------------------------------------

    def own_name(self, on_lost) -> None:
        self._owner_id = Gio.bus_own_name(
            Gio.BusType.SESSION,
            BUS_NAME,
            Gio.BusNameOwnerFlags.NONE,
            self._on_bus_acquired,
            None,
            lambda *_: on_lost(),
        )

    def _on_bus_acquired(self, connection: Gio.DBusConnection, _name: str) -> None:
        self._connection = connection
        node = Gio.DBusNodeInfo.new_for_xml(INTROSPECTION)
        self._registration = connection.register_object(
            OBJECT_PATH,
            node.interfaces[0],
            self._handle_call,
            self._handle_get,
            None,
        )
        log.info("listening on %s %s", BUS_NAME, OBJECT_PATH)

    def unregister(self) -> None:
        if self._connection and self._registration:
            self._connection.unregister_object(self._registration)
            self._registration = 0
        if self._owner_id:
            Gio.bus_unown_name(self._owner_id)
            self._owner_id = 0

    # -- metody ----------------------------------------------------------------

    def _handle_call(self, _conn, _sender, _path, _iface, method, params, invocation) -> None:
        try:
            if method == "SetPower":
                self._daemon.set_power(bool(params[0]))
            elif method == "SetVolume":
                self._daemon.set_volume(int(params[0]))
            elif method == "SetMute":
                self._daemon.set_mute(bool(params[0]))
            elif method == "MediaKey":
                self._daemon.media_key(str(params[0]))
            elif method == "SetCast":
                self._daemon.set_cast(bool(params[0]))
            elif method == "Refresh":
                self._daemon.request_poll_soon()
            else:
                invocation.return_error_literal(
                    Gio.dbus_error_quark(),
                    Gio.DBusError.UNKNOWN_METHOD,
                    f"unknown method {method}",
                )
                return
        except Exception as exc:
            log.warning("%s refused: %s", method, exc)
            invocation.return_error_literal(
                Gio.dbus_error_quark(), Gio.DBusError.FAILED, str(exc)
            )
            return
        invocation.return_value(None)

    # -- właściwości -----------------------------------------------------------

    def _handle_get(self, _conn, _sender, _path, _iface, name):
        value = self._daemon.snapshot().get(name)
        signature = _SIGNATURES.get(name)
        if signature is None:
            return None
        return GLib.Variant(signature, value)

    def _on_change(self, changes: dict) -> None:
        """Wołane z wątku roboczego — emisja musi trafić do pętli głównej."""
        GLib.idle_add(self._emit, changes, priority=GLib.PRIORITY_DEFAULT)

    def _emit(self, changes: dict) -> bool:
        if self._connection is None:
            return GLib.SOURCE_REMOVE
        body = GLib.Variant(
            "(sa{sv}as)",
            (
                INTERFACE,
                {k: GLib.Variant(_SIGNATURES[k], v) for k, v in changes.items()},
                [],
            ),
        )
        self._connection.emit_signal(
            None, OBJECT_PATH, "org.freedesktop.DBus.Properties",
            "PropertiesChanged", body,
        )
        return GLib.SOURCE_REMOVE
