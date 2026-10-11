#!/usr/bin/env python3
"""Dev-Server für die Handy-PWA: die ECHTE Handy-Instanz plus `pwa/` statisch.

    python scripts/pwa_devserver.py                 # Web :8099, Handy-Server :17654
    python scripts/pwa_devserver.py --address 127.0.0.1

Startet den `MobileService` der App (gleiche Routen, gleiche Prüfungen, gleiche Sync-Logik) auf
einer temporären Datenablage und serviert `pwa/` unter `http://localhost:<port>/`. `localhost`
ist eine sichere Origin: der Service Worker läuft dort. Die erlaubte Origin des Handy-Servers
ist die Dev-Adresse (statt `https://xveyn.github.io`). Gedruckt werden die Adresse, ein Koppel-Link
mit frischem Code und der Ordner der Desktop-Daten (`zeiterfassung.json` zum Nachsehen).

Werkzeug zum Entwickeln und für Browser-Tests (auch Playwright); nicht Teil der App, nicht
gebündelt. Reine stdlib plus die App-Module.
"""
from __future__ import annotations

import argparse
import contextlib
import datetime
import functools
import http.server
import pathlib
import sys
import tempfile
import threading
from collections.abc import Iterator

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
PWA = ROOT / "pwa"

from src import mobile_keys, mobile_routes, netinfo  # noqa: E402
from src.conflicts_store import ConflictsStore  # noqa: E402
from src.mobile_keys import MobileKeyStore  # noqa: E402
from src.mobile_service import STATE_RUNNING, MobileService  # noqa: E402
from src.mobile_store import MobileStore  # noqa: E402
from src.mobile_pairing import PairingSession  # noqa: E402
from src.settings import Settings  # noqa: E402
from src.storage import Storage  # noqa: E402


class _Handler(http.server.SimpleHTTPRequestHandler):
    extensions_map = {**http.server.SimpleHTTPRequestHandler.extensions_map,
                      ".webmanifest": "application/manifest+json", ".js": "text/javascript",
                      ".mjs": "text/javascript", ".json": "application/json", ".png": "image/png"}

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")            # Dev: immer frisch
        super().end_headers()

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        return None


class _NoKeyring:
    """Ersatz für `keyring_store`: legt nie etwas ab. Der Dev-Server darf den Schlüsselbund des
    Entwicklers nicht anfassen (Muster wie `demo_data.py`); die Geräteschlüssel bleiben deshalb in
    der Datei des Dev-Datenordners (`location: file`) und überstehen so einen Neustart."""

    @staticmethod
    def put(key: str, value: str) -> bool:
        return False

    @staticmethod
    def fetch(key: str) -> str | None:
        return None

    @staticmethod
    def remove(key: str) -> None:
        return None


class Dev:
    def __init__(self, service: MobileService, web: http.server.ThreadingHTTPServer,
                 web_port: int, api_port: int, address: str, data_dir: pathlib.Path,
                 storage: Storage, settings: Settings) -> None:
        self.service, self._web = service, web
        self.storage, self.settings = storage, settings
        self.web_port, self.api_port, self.address, self.data_dir = web_port, api_port, address, data_dir

    def new_code(self) -> str:
        return self.service.pairing.open()

    def pair_link(self, code: str) -> str | None:
        return self.service.pair_link(code)


@contextlib.contextmanager
def running(data_dir: pathlib.Path, *, web_port: int, api_port: int, address: str,
            seed_days: int = 0, seed_slots: int = 1, window_max: int = 365) -> Iterator[Dev]:
    """Startet beide Server und räumt sie wieder ab. Port 0 = frei wählen. `seed_days` legt
    Beispieleinträge für die letzten Tage an (`seed_slots` Slots je Tag), `window_max` ist die
    Obergrenze des Lesefensters (#250)."""
    handler = functools.partial(_Handler, directory=str(PWA))
    web = http.server.ThreadingHTTPServer(("127.0.0.1", web_port), handler)
    web_port = web.server_address[1]
    threading.Thread(target=web.serve_forever, daemon=True, name="pwa-web").start()
    origin = f"http://localhost:{web_port}"
    # Die Handy-Instanz liest beides beim Start; nur dieses Skript ändert es.
    saved = (mobile_routes.PWA_ORIGIN, mobile_routes.PWA_URL)
    mobile_routes.PWA_ORIGIN, mobile_routes.PWA_URL = origin, f"{origin}/"
    saved_keyring = mobile_keys.keyring_store
    mobile_keys.keyring_store = _NoKeyring()          # type: ignore[assignment]
    data_dir.mkdir(parents=True, exist_ok=True)
    settings = Settings(str(data_dir / "settings.json"))
    settings.device_id_for_sync = "DESKTOP-DEV"
    settings.set_many({"mobile_enabled": True, "mobile_port": api_port or 17654,
                       "mobile_address": address, "mobile_notice_accepted": True,
                       "mobile_window_max_days": window_max,
                       "categories": ["Projekt", "Intern", "Support"],
                       # Zum Ausprobieren der Vorbelegung (#288): Projekt mit festen Zeiten,
                       # Support nur am Freitag abweichend, Intern ohne Eintrag (= Wochentag-Standard).
                       "category_times": {
                           "Projekt": {"start": "09:00", "end": "17:00", "pause": 45},
                           "Support": {"mode": "per_day", "pause": 15,
                                       "days": {"fri": {"start": "07:00", "end": "11:00"}}}}})
    storage = Storage(str(data_dir / "zeiterfassung.json"), device_id="DESKTOP-DEV")
    if seed_days > 0:
        storage.apply_merge(seed_entries(datetime.date.today(), days=seed_days, slots=seed_slots))
    context = mobile_routes.MobileContext(
        pairing=PairingSession(), devices=MobileStore(str(data_dir / "mobile_devices.json")),
        devices_lock=threading.RLock(), keys=MobileKeyStore(str(data_dir / "mobile_keys.json")),
        storage=storage,
        settings=settings, conflicts_store=ConflictsStore(str(data_dir / "conflicts.json")),
        base=str(data_dir), desktop_name=lambda: "Desktop (Dev)")

    def run(fn, done=None):
        result = fn()
        if done is not None:
            done(result)

    service = MobileService(settings, context, run=run, lan_candidates=lambda: [address])
    try:
        if api_port == 0:
            api_port = _free_port(address)
            settings.set("mobile_port", api_port)
        service.apply()
        if service.status.state != STATE_RUNNING:
            raise RuntimeError(f"Handy-Server startet nicht: {service.status}")
        yield Dev(service, web, web_port, service.status.port, address, data_dir, storage, settings)
    finally:
        mobile_routes.PWA_ORIGIN, mobile_routes.PWA_URL = saved      # Prozessweit: nicht in Tests lecken
        mobile_keys.keyring_store = saved_keyring
        service.shutdown()
        web.shutdown()
        web.server_close()


def seed_entries(today: datetime.date, *, days: int, slots: int) -> dict[str, dict[str, object]]:
    """Beispieleinträge für die Werktage der letzten `days` Tage (inklusive heute), je `slots` Slots.
    Zum Ausprobieren des Lesefensters (#250): ohne Daten gäbe es nichts nachzuladen."""
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    entries: dict[str, dict[str, object]] = {}
    for back in range(days):
        day = today - datetime.timedelta(days=back)
        if day.weekday() >= 5:
            continue
        entries[day.isoformat()] = {
            "slots": [{"start": f"{8 + k % 10:02d}:00", "end": f"{9 + k % 10:02d}:00", "pause": 0,
                       "kategorie": "Projekt"} for k in range(slots)],
            "modified_at": stamp, "device_id": "DESKTOP-DEV", "deleted": False}
    return entries


def _free_port(address: str) -> int:
    import socket
    with socket.socket() as sock:
        sock.bind((address, 0))
        return int(sock.getsockname()[1])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--port", type=int, default=8099, help="Port der Web-Seite (Standard 8099)")
    parser.add_argument("--api-port", type=int, default=17654, help="Port der Handy-Instanz (Standard 17654)")
    parser.add_argument("--address", default=None,
                        help="LAN-Adresse der Handy-Instanz (Standard: erste gefundene, sonst 127.0.0.1)")
    parser.add_argument("--data-dir", type=pathlib.Path, default=None, help="Datenordner (Standard: temporär)")
    parser.add_argument("--seed-days", type=int, default=0,
                        help="Beispieleinträge für die Werktage der letzten N Tage anlegen (Standard 0)")
    parser.add_argument("--seed-slots", type=int, default=1, help="Slots je Beispieltag (Standard 1)")
    parser.add_argument("--window-max", type=int, default=365, choices=(30, 90, 180, 365),
                        help="Obergrenze des Lesefensters in Tagen (Standard 365)")
    args = parser.parse_args(argv)
    address = args.address or (netinfo.lan_candidates() or ["127.0.0.1"])[0]
    data_dir = args.data_dir or pathlib.Path(tempfile.mkdtemp(prefix="zeiterfassung-pwa-dev-"))
    with running(data_dir, web_port=args.port, api_port=args.api_port, address=address,
                 seed_days=args.seed_days, seed_slots=args.seed_slots, window_max=args.window_max) as dev:
        code = dev.new_code()
        print(f"PWA:           http://localhost:{dev.web_port}/")
        print(f"Handy-Server:  http://{address}:{dev.api_port}")
        print(f"Koppel-Link:   {dev.pair_link(code)}")
        print(f"Code:          {code}")
        print(f"Desktop-Daten: {dev.data_dir}")
        print("Strg+C beendet.")
        try:
            threading.Event().wait()
        except KeyboardInterrupt:
            print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
