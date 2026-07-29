# tests/test_tray_linux_dbus.py
"""SNI-Backend gegen einen ECHTEN dbus-daemon (#42).

Das ist die einzige Ebene, auf der die D-Bus-Signaturen und die Rückgabewerte
der @dbus_method-Methoden wirklich geprüft werden können (der Decorator liefert
beim Direktaufruf einen None-Wrapper). Gegenstelle sind ein Fake-Watcher und ein
Fake-Notification-Dienst auf einem eigenen Session-Bus.

Läuft nur auf Linux mit dbus_fast und dbus-daemon — sonst sauberer Skip.
Lokal (Windows-Dev-Maschine) über Docker, s. Plan Task 7.
"""

import asyncio
import os
import shutil
import subprocess
import sys
import threading
import time

import pytest

pytest.importorskip("dbus_fast")
if sys.platform != "linux":
    pytest.skip("Session-Bus gibt es nur auf Linux", allow_module_level=True)
if shutil.which("dbus-daemon") is None:
    pytest.skip("dbus-daemon nicht installiert", allow_module_level=True)

from typing import Annotated

from dbus_fast import BusType, PropertyAccess, Variant  # pyright: ignore[reportMissingImports]  # dbus-fast: nur auf Linux installiert
from dbus_fast.aio import MessageBus  # pyright: ignore[reportMissingImports]  # dbus-fast: nur auf Linux installiert
from dbus_fast.annotations import (  # pyright: ignore[reportMissingImports]  # dbus-fast: nur auf Linux installiert
    DBusBool, DBusDict, DBusInt32, DBusSignature, DBusStr, DBusUInt32,
)
from dbus_fast.service import ServiceInterface, dbus_method, dbus_property  # pyright: ignore[reportMissingImports]  # dbus-fast: nur auf Linux installiert

from src.tray_linux import ITEM_PATH, MENU_PATH, LinuxTrayBackend


class _FakeWatcher(ServiceInterface):
    """Minimaler org.kde.StatusNotifierWatcher — merkt sich die Anmeldungen.

    Annotationen wie im Produktivcode über die dbus_fast-Aliase: pyright prüft
    `tests` mit (pyproject.toml), String-Signaturen wären dort rot.
    """

    def __init__(self):
        super().__init__("org.kde.StatusNotifierWatcher")
        self.registered = []

    @dbus_method()
    def RegisterStatusNotifierItem(self, service: DBusStr):
        self.registered.append(service)

    @dbus_property(PropertyAccess.READ)
    def IsStatusNotifierHostRegistered(self) -> DBusBool:
        return True

    @dbus_property(PropertyAccess.READ)
    def RegisteredStatusNotifierItems(self) -> Annotated[list, DBusSignature("as")]:
        return list(self.registered)

    @dbus_property(PropertyAccess.READ)
    def ProtocolVersion(self) -> DBusInt32:
        return 0


class _FakeNotifications(ServiceInterface):
    """Minimaler org.freedesktop.Notifications — merkt sich die Toasts."""

    def __init__(self):
        super().__init__("org.freedesktop.Notifications")
        self.messages = []

    @dbus_method()
    def Notify(self, app_name: DBusStr, replaces_id: DBusUInt32, app_icon: DBusStr,
               summary: DBusStr, body: DBusStr,
               actions: Annotated[list, DBusSignature("as")],
               hints: DBusDict, timeout: DBusInt32) -> DBusUInt32:
        self.messages.append((app_name, summary, body))
        return 1


class _LoopThread:
    """Asyncio-Loop in einem eigenen Thread — für die Fakes und den Testclient.
    Das Backend bringt seinen eigenen Thread mit; beide müssen gleichzeitig
    laufen, sonst blockiert start() auf einer Registrierung, die niemand
    beantwortet."""

    def __init__(self):
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self.loop.run_forever, daemon=True)
        self.thread.start()

    def run(self, coro, timeout=15):
        return asyncio.run_coroutine_threadsafe(coro, self.loop).result(timeout=timeout)

    def close(self):
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join(timeout=5)
        self.loop.close()


@pytest.fixture()
def bus_env(monkeypatch):
    """Eigener Session-Bus pro Test — kein Kontakt zum Bus des Entwicklers."""
    proc = subprocess.Popen(
        ["dbus-daemon", "--session", "--print-address", "--nofork"],
        stdout=subprocess.PIPE, text=True,
    )
    address = proc.stdout.readline().strip()
    monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", address)
    yield address
    proc.terminate()
    proc.wait(timeout=5)


class _Desktop:
    """Fake-Desktop auf dem Testbus: Watcher + Notification-Dienst + die Loop,
    auf der beide bedient werden."""

    def __init__(self, helper, bus, watcher, notifications):
        self.helper = helper
        self.bus = bus
        self.watcher = watcher
        self.notifications = notifications

    def run(self, coro, timeout=15):
        return self.helper.run(coro, timeout)

    def restart_watcher(self):
        """Simuliert einen plasmashell-Neustart: Name freigeben, neu belegen."""
        async def restart():
            await self.bus.release_name("org.kde.StatusNotifierWatcher")
            new_bus = await MessageBus(bus_type=BusType.SESSION).connect()
            new_bus.export("/StatusNotifierWatcher", self.watcher)
            await new_bus.request_name("org.kde.StatusNotifierWatcher")
            return new_bus

        self.bus = self.run(restart())


@pytest.fixture()
def desktop(bus_env):
    """Fake-Desktop: Watcher und Notification-Dienst laufen auf dem Testbus."""
    helper = _LoopThread()
    watcher, notifications = _FakeWatcher(), _FakeNotifications()

    async def serve():
        bus = await MessageBus(bus_type=BusType.SESSION).connect()
        bus.export("/StatusNotifierWatcher", watcher)
        bus.export("/org/freedesktop/Notifications", notifications)
        await bus.request_name("org.kde.StatusNotifierWatcher")
        await bus.request_name("org.freedesktop.Notifications")
        return bus

    bus = helper.run(serve())
    fake = _Desktop(helper, bus, watcher, notifications)
    yield fake
    fake.bus.disconnect()
    helper.close()


def _wait_for(predicate, timeout=5):
    """Auf eine Zustellung über den Bus warten (die läuft asynchron in fremden
    Threads) — statt sofort zu prüfen und sporadisch rot zu sein."""
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        time.sleep(0.05)
    return predicate()


def _backend(clicked, sync_visible=lambda: True):
    return LinuxTrayBackend(
        ".",
        on_show=lambda: clicked.append("show"),
        on_quit=lambda: clicked.append("quit"),
        actions=[("Senden", lambda: clicked.append("send"), None),
                 ("Sync", lambda: clicked.append("sync"), sync_visible)],
    )


def _by_label(layout):
    """Kinder eines GetLayout-Ergebnisses als `{label: (id, props)}`. Die Kinder
    kommen als Variants `(ia{sv}av)` über den Draht, die Properties als Variants
    darin — hier einmal ausgepackt, statt in jedem Test neu."""
    entries = {}
    for child in layout[2]:
        node_id, props, _kids = child.value
        if "label" in props:
            entries[props["label"].value] = (node_id, props)
    return entries


async def _menu_proxy(bus, name):
    introspection = await bus.introspect(name, MENU_PATH)
    return bus.get_proxy_object(name, MENU_PATH, introspection) \
              .get_interface("com.canonical.dbusmenu")


async def _item_proxy(bus, name):
    introspection = await bus.introspect(name, ITEM_PATH)
    return bus.get_proxy_object(name, ITEM_PATH, introspection) \
              .get_interface("org.kde.StatusNotifierItem")


def test_backend_registers_itself_with_the_watcher(desktop):
    backend = _backend([])
    backend.start()
    try:
        assert desktop.watcher.registered == [
            f"org.kde.StatusNotifierItem-{os.getpid()}-1"]
    finally:
        backend.stop()


def test_menu_layout_carries_all_entries_in_order(desktop):
    backend = _backend([])
    backend.start()
    try:
        async def read_labels():
            bus = await MessageBus(bus_type=BusType.SESSION).connect()
            menu = await _menu_proxy(bus, desktop.watcher.registered[0])
            _revision, layout = await menu.call_get_layout(0, -1, [])
            _root_id, _root_props, children = layout
            labels = []
            for child in children:
                props = child.value[1]
                labels.append(props["label"].value if "label" in props else "—")
            bus.disconnect()
            return labels

        assert desktop.run(read_labels()) == [
            "Anzeigen", "—", "Senden", "Sync", "—", "Beenden",
        ]
    finally:
        backend.stop()


def test_clicking_a_menu_entry_runs_its_callback(desktop):
    clicked = []
    backend = _backend(clicked)
    backend.start()
    try:
        async def click_send():
            bus = await MessageBus(bus_type=BusType.SESSION).connect()
            menu = await _menu_proxy(bus, desktop.watcher.registered[0])
            _revision, layout = await menu.call_get_layout(0, -1, [])
            send_id = next(
                child.value[0] for child in layout[2]
                if child.value[1].get("label") is not None
                and child.value[1]["label"].value == "Senden"
            )
            await menu.call_event(send_id, "clicked", Variant("s", ""), 0)
            bus.disconnect()

        desktop.run(click_send())
        assert clicked == ["send"]
    finally:
        backend.stop()


def test_visibility_is_reevaluated_on_every_open(desktop):
    """Der Kern der Linux-Zusage: `visible` wird bei JEDEM Öffnen neu
    ausgewertet (AboutToShow → refresh → Revision +1 → LayoutUpdated), statt
    beim Start eingefroren zu werden. Damit verhält sich Linux LIVE wie
    Windows, nicht als Snapshot wie macOS — und genau das ist nur über den
    Draht belegbar."""
    visible = {"sync": True}
    backend = _backend([], sync_visible=lambda: visible["sync"])
    backend.start()
    try:
        async def reopen_after_toggle():
            bus = await MessageBus(bus_type=BusType.SESSION).connect()
            menu = await _menu_proxy(bus, desktop.watcher.registered[0])

            first_revision, layout = await menu.call_get_layout(0, -1, [])
            assert _by_label(layout)["Sync"][1]["visible"].value is True

            visible["sync"] = False
            assert await menu.call_about_to_show(0) is True

            revision, layout = await menu.call_get_layout(0, -1, [])
            assert revision == first_revision + 1
            assert _by_label(layout)["Sync"][1]["visible"].value is False

            # Zweites Öffnen ohne Änderung: nichts neu zu laden, Revision bleibt.
            assert await menu.call_about_to_show(0) is False
            unchanged, _layout = await menu.call_get_layout(0, -1, [])
            assert unchanged == revision

            bus.disconnect()

        desktop.run(reopen_after_toggle())
    finally:
        backend.stop()


def test_the_remaining_dbusmenu_methods_answer_over_the_wire(desktop):
    """GetGroupProperties, GetProperty, EventGroup und AboutToShowGroup werden
    exportiert, aber von den übrigen Tests nie gerufen. Ihre Signaturen
    (`a(ia{sv})`, `v`, `a(isvu)`→`ai`, `ai`→`aiai`) gehen hier einmal wirklich
    über den Bus, statt nur beim Klassenaufbau geparst zu werden."""
    clicked = []
    visible = {"sync": True}
    backend = _backend(clicked, sync_visible=lambda: visible["sync"])
    backend.start()
    try:
        async def call_them():
            bus = await MessageBus(bus_type=BusType.SESSION).connect()
            menu = await _menu_proxy(bus, desktop.watcher.registered[0])
            _revision, layout = await menu.call_get_layout(0, -1, [])
            send_id, _props = _by_label(layout)["Senden"]

            groups = await menu.call_get_group_properties([send_id], [])
            assert [(node_id, props["label"].value) for node_id, props in groups] \
                == [(send_id, "Senden")]

            assert (await menu.call_get_property(send_id, "label")).value == "Senden"
            assert (await menu.call_get_property(send_id, "enabled")).value is True
            # Unbekannte Property: dokumentierter Fallback, kein D-Bus-Fehler.
            assert (await menu.call_get_property(send_id, "kein-solches-feld")).value == ""

            # Klick über EventGroup (statt Event) — der Adapter dispatcht genauso
            # (die Assertion unten bestätigt `clicked == ["send"]`); die leere
            # Rückgabe listet nur nicht gefundene IDs (hier keine).
            assert await menu.call_event_group(
                [[send_id, "clicked", Variant("s", ""), 0]]) == []

            assert await menu.call_about_to_show_group([0]) == [[], []]
            visible["sync"] = False
            assert await menu.call_about_to_show_group([0]) == [[0], []]

            bus.disconnect()

        desktop.run(call_them())
        assert clicked == ["send"]
    finally:
        backend.stop()


def test_left_click_activates_and_shows_the_window(desktop):
    clicked = []
    backend = _backend(clicked)
    backend.start()
    try:
        async def activate():
            bus = await MessageBus(bus_type=BusType.SESSION).connect()
            item = await _item_proxy(bus, desktop.watcher.registered[0])
            assert await item.get_item_is_menu() is False
            await item.call_activate(0, 0)
            bus.disconnect()

        desktop.run(activate())
        assert clicked == ["show"]
    finally:
        backend.stop()


def test_notify_reaches_the_notification_service(desktop):
    """Titel BEWUSST ungleich dem App-Namen: `_notify` schickt an Position 0 den
    hart kodierten "Zeiterfassung" und an Position 3 den Titel. Wäre der Titel
    hier auch "Zeiterfassung", erzeugte eine Vertauschung der beiden Positionen
    byte-gleich dasselbe Tupel — die Signatur-/Reihenfolge-Prüfung, für die
    dieser Test existiert, liefe ins Leere."""
    backend = _backend([])
    backend.start()
    try:
        backend.notify("Synchronisiert.", "Sync-Titel")
        # notify() ist bewusst fire-and-forget (es läuft auf dem Tk-Thread) —
        # also auf die Zustellung warten statt sofort zu prüfen.
        assert _wait_for(lambda: bool(desktop.notifications.messages))
        assert desktop.notifications.messages == [
            ("Zeiterfassung", "Sync-Titel", "Synchronisiert."),
        ]
    finally:
        backend.stop()


def test_item_reregisters_after_the_watcher_restarts(desktop):
    """plasmashell-Neustart: der Watcher verschwindet und kommt wieder — das
    Item muss sich von selbst neu anmelden, sonst ist das Icon dauerhaft weg."""
    backend = _backend([])
    backend.start()
    try:
        assert len(desktop.watcher.registered) == 1
        desktop.restart_watcher()
        assert _wait_for(lambda: len(desktop.watcher.registered) == 2)
        assert desktop.watcher.registered[1] == desktop.watcher.registered[0]
    finally:
        backend.stop()


def test_stop_releases_the_bus_name(desktop):
    backend = _backend([])
    backend.start()
    name = desktop.watcher.registered[0]
    backend.stop()

    async def owner_gone():
        bus = await MessageBus(bus_type=BusType.SESSION).connect()
        introspection = await bus.introspect("org.freedesktop.DBus", "/org/freedesktop/DBus")
        dbus_iface = bus.get_proxy_object(
            "org.freedesktop.DBus", "/org/freedesktop/DBus", introspection
        ).get_interface("org.freedesktop.DBus")
        has_owner = await dbus_iface.call_name_has_owner(name)
        bus.disconnect()
        return has_owner

    assert desktop.run(owner_gone()) is False
