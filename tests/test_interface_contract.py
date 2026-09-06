"""Interfejs D-Bus musi zgadzać się po obu stronach.

Demon opisuje go w XML-u w ``src/lgtvd/dbus.py``, rozszerzenie ma własną kopię
w ``extension/client.js`` — z niej ``Gio.DBusProxy.makeProxyWrapper`` generuje
metody proxy. Rozjazd nie daje żadnego błędu przy ładowaniu: metody, której
zabrakło w XML-u rozszerzenia, po prostu nie ma na proxy, a jej wywołanie
rzuca ``TypeError`` dopiero w chwili kliknięcia.

Tak właśnie zniknęło odświeżanie stanu przy otwieraniu panelu: ``SetActive``
było wołane, a nie było zadeklarowane.

Testy czytają OBA pliki jako tekst, bez importowania czegokolwiek, żeby
działały też tam, gdzie nie ma PyGObject.
"""

from __future__ import annotations

import re
from pathlib import Path
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[1]
DAEMON = ROOT / "src" / "lgtvd" / "dbus.py"
CLIENT = ROOT / "extension" / "client.js"

IFACE = "org.maniumek.LgtvRemote1"


def _members(xml: str) -> tuple[dict[str, str], dict[str, str]]:
    """Zwraca (metody -> sygnatura argumentów, właściwości -> typ).

    Nazwa interfejsu po stronie demona siedzi w f-stringu jako ``{INTERFACE}``
    i przy czytaniu pliku nie jest podstawiana, więc bierzemy po prostu
    jedyny interfejs w dokumencie zamiast szukać go po nazwie.
    """
    node = ElementTree.fromstring(xml.replace("{INTERFACE}", IFACE))
    interfaces = list(node.iter("interface"))
    assert len(interfaces) == 1, "spodziewany dokładnie jeden interfejs"
    interface = interfaces[0]
    methods = {
        m.get("name"): "".join(
            a.get("type", "") for a in m.findall("arg") if a.get("direction", "in") == "in"
        )
        for m in interface.findall("method")
    }
    properties = {p.get("name"): p.get("type") for p in interface.findall("property")}
    return methods, properties


def daemon_xml() -> str:
    text = DAEMON.read_text(encoding="utf-8")
    return re.search(r'INTROSPECTION = f?"""(.*?)"""', text, re.S).group(1)


def client_xml() -> str:
    text = CLIENT.read_text(encoding="utf-8")
    return re.search(r"const IFACE = `(.*?)`;", text, re.S).group(1)


def test_the_extension_declares_every_method_the_daemon_offers():
    daemon_methods, _ = _members(daemon_xml())
    client_methods, _ = _members(client_xml())
    assert client_methods == daemon_methods


def test_the_extension_declares_every_property_the_daemon_offers():
    _, daemon_props = _members(daemon_xml())
    _, client_props = _members(client_xml())
    assert client_props == daemon_props


def _without_comments(text: str) -> str:
    """Komentarze potrafią zawierać przykłady wywołań — te nie są kodem."""
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return re.sub(r"^\s*//.*$", "", text, flags=re.M)


def test_every_method_the_extension_calls_is_declared():
    """Wywołania w JS muszą mieć pokrycie w XML-u — inaczej proxy ich nie ma."""
    text = _without_comments(CLIENT.read_text(encoding="utf-8"))
    declared, _ = _members(client_xml())
    called = set(re.findall(r"this\._proxy\.(\w+?)Async\s*\(", text))
    missing = sorted(called - set(declared))
    assert not missing, f"wołane, a niezadeklarowane w XML: {missing}"
