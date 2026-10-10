# src/mobile_service.py
"""Lebenszyklus der Handy-Instanz (#221), Tk-frei.

`MobileService.apply()` liest `mobile_enabled`/`mobile_port`/`mobile_address` aus den
Settings und bringt den Server in den passenden Zustand — im Worker, nie im
UI-Thread (`netinfo` löst einen Hostnamen auf und kann blockieren). Das Ergebnis ist
ein `MobileStatus` samt Grund, den der Tab „Mobil" (PR 5) anzeigt.

Gebunden wird nur auf die gewählte LAN-Adresse (`netinfo.pick_address`), nie auf
`0.0.0.0`. Fehlt die gewählte Adresse (DHCP, anderes WLAN), ist der Zustand `error`
mit dem Grund `address_gone` und es läuft nichts: die Adresse wird nie still durch
eine andere ersetzt. Bei jedem Statuswechsel weg von „läuft" wird die offene
Kopplungssitzung geschlossen — ein Code ohne Server ist nutzlos.

Die Geräteverwaltung (`list_devices`, `revoke`, `revoke_all`) und `pair_link` liegen
hier, weil sie sich den `devices_lock` mit den Routen teilen müssen. `revoke` und
`revoke_all` schreiben (Datei): im Worker aufrufen. `list_devices` liest nur den
Speicher des Stores (`MobileStore.get_all` kopiert, kein Dateizugriff) und darf im
UI-Thread laufen; sie wartet höchstens auf den kurzen Store-Lock.
"""
from __future__ import annotations

import dataclasses
import errno
import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from src import mobile_pairing, mobile_routes, netinfo
from src.api_auth import Policy
from src.api_server import ApiServer
from src.api_service import parse_port

if TYPE_CHECKING:
    from src.mobile_store import Record

_log = logging.getLogger(__name__)

DEFAULT_PORT = 17654

STATE_OFF = "off"
STATE_RUNNING = "running"
STATE_STARTING = "starting"
STATE_ERROR = "error"

REASON_INVALID_PORT = "invalid_port"
REASON_NO_ADDRESS = "no_address"
REASON_ADDRESS_GONE = "address_gone"
REASON_PORT_IN_USE = "port_in_use"
REASON_START_FAILED = "start_failed"
REASON_CLOSED = "closed"

# Windows meldet einen belegten Port mit WSAEADDRINUSE (10048), einen mit
# SO_EXCLUSIVEADDRUSE fremd gebundenen mit WSAEACCES (10013).
_WINERRORS_IN_USE = (10048, 10013)


@dataclass(frozen=True)
class MobileStatus:
    state: str
    address: str | None = None
    port: int | None = None
    reason: str = ""


def _port_in_use(exc: OSError) -> bool:
    return (exc.errno in (errno.EADDRINUSE, errno.EACCES)
            or getattr(exc, "winerror", None) in _WINERRORS_IN_USE)


class MobileService:
    def __init__(self, settings: Any, context: mobile_routes.MobileContext, *,
                 run: Callable[..., None],
                 on_status: Callable[[MobileStatus], None] | None = None,
                 lan_candidates: Callable[[], list[str]] = netinfo.lan_candidates) -> None:
        self._settings = settings
        # Die Routen fragen `closing` unter dem Lock: nach `shutdown()` (Beenden,
        # Entfernen, Neustart) koppelt und gleicht keine Route mehr ab.
        self._on_paired_outer = context.on_paired
        self._context = dataclasses.replace(context, closing=lambda: self._closed,
                                            on_paired=self._on_paired)
        self._run = run
        self._on_status = on_status
        self._lan_candidates = lan_candidates
        self._lock = threading.Lock()
        self._server: ApiServer | None = None
        self._running: tuple[str, int] | None = None
        self._status = MobileStatus(STATE_OFF)
        self._closed = False

    @property
    def status(self) -> MobileStatus:
        return self._status

    @property
    def pairing(self) -> mobile_pairing.PairingSession:
        return self._context.pairing

    def apply(self) -> None:
        """Bringt den Server in den Zustand der Settings. Im UI-Thread aufrufen; die
        Arbeit läuft im Worker, `on_status` kommt zurück. Sofort sichtbar wird
        „startet": die Adressauflösung kann dauern."""
        if self._closed:
            return
        port = parse_port(self._settings.get("mobile_port"))
        if (self._settings.get("mobile_enabled") and port is not None
                and (self._running is None or self._running[1] != port)):
            self._status = MobileStatus(STATE_STARTING, None, port)
        self._run(self._reconcile, self._publish)
        # Die Geräteschlüssel (#249) in einem eigenen Worker: ein hängender Schlüsselbund
        # (gesperrt, Prompt) darf weder den Serverstart noch den Statuswechsel aufhalten.
        self._run(self._maintain_keys)

    def _maintain_keys(self) -> None:
        """Räumt Schlüssel unbekannter Geräte ab, lädt die Schlüsselbund-Schlüssel in den Cache
        und zieht Datei-Schlüssel in den Schlüsselbund um. Blockiert (Worker). Jede Stufe für
        sich: ein Ausfall hält weder die übrigen noch den Dienst auf; was nicht geladen werden
        konnte, antwortet `503 key_unavailable` und wird beim nächsten Anfrage-Versuch
        nachgeladen."""
        if self._closed or not self._settings.get("mobile_enabled"):
            return
        keys = self._context.keys
        steps: list[tuple[str, Callable[[], Any]]] = [
            ("retain", lambda: keys.retain([r["id"] for r in self._context.devices.get_all()])),
            ("load", keys.load),
            ("migrate", keys.migrate),
        ]
        for name, step in steps:
            if self._closed:
                return
            try:
                step()
            except Exception:
                _log.warning("Handy-Erfassung: Schlüssel (%s) nicht bearbeitet", name, exc_info=True)

    def _on_paired(self) -> None:
        """Nach einer Kopplung (Server-Thread, außerhalb der Sperren): der Schlüssel liegt
        schon in der gehärteten Datei; der Umzug in den Schlüsselbund läuft im Worker."""
        try:
            self._on_paired_outer()
        finally:
            self._run(self._migrate_keys)

    def _migrate_keys(self) -> None:
        if self._closed:
            return
        try:
            self._context.keys.migrate()
        except Exception:
            _log.warning("Handy-Erfassung: Schlüsselumzug fehlgeschlagen", exc_info=True)

    def _publish(self, _result: MobileStatus) -> None:
        # Der aktuelle Stand, nicht das Ergebnis dieses Workers: kommen zwei Worker
        # vertauscht zurück, würde die UI sonst einen veralteten Status zeigen.
        if self._on_status is not None:
            self._on_status(self._status)

    def _reconcile(self) -> MobileStatus:
        with self._lock:
            try:
                return self._reconcile_locked()
            except Exception:
                # Der Runner würde den Fehler nur loggen und `on_done` nie rufen — der
                # Status bliebe stehen. Hier wird er zum Zustand.
                _log.exception("Handy-Instanz: Start/Stopp fehlgeschlagen")
                self._stop_server()
                self._status = MobileStatus(STATE_ERROR, None, None, REASON_START_FAILED)
                return self._status

    def _reconcile_locked(self) -> MobileStatus:
        if self._closed:
            return self._status
        if not self._settings.get("mobile_enabled"):
            self._stop_server()
            self._status = MobileStatus(STATE_OFF)
            return self._status
        port = parse_port(self._settings.get("mobile_port"))
        if port is None:
            self._stop_server()
            self._status = MobileStatus(STATE_ERROR, None, None, REASON_INVALID_PORT)
            return self._status
        configured = self._settings.get("mobile_address")
        configured = configured if isinstance(configured, str) else ""
        address = netinfo.pick_address(configured, self._lan_candidates())
        if address is None:
            self._stop_server()
            reason = REASON_ADDRESS_GONE if configured else REASON_NO_ADDRESS
            self._status = MobileStatus(STATE_ERROR, configured or None, port, reason)
            return self._status
        if self._running == (address, port) and self._server is not None:
            # Läuft schon. RUNNING setzen statt `_status` durchzureichen: `apply` kann
            # dazwischen „startet" geschrieben haben.
            self._status = MobileStatus(STATE_RUNNING, address, port)
            return self._status
        self._stop_server()
        if self._closed:                          # Beenden/Entfernen kam dazwischen
            return self._status
        context = self._context

        def policy_for_port(bound: int) -> Policy:
            return Policy(allowed_hosts=frozenset({f"{address}:{bound}"}),
                          allowed_origins=frozenset({mobile_routes.PWA_ORIGIN}),
                          bind_host=address)

        server = ApiServer(None, mobile_routes.make_verifier(context.devices, context.now),
                           port=port, policy_for_port=policy_for_port,
                           surface=mobile_routes.surface(context))
        try:
            server.start()
        except OSError as exc:
            reason = REASON_PORT_IN_USE if _port_in_use(exc) else REASON_START_FAILED
            _log.warning("Handy-Instanz: Start auf %s:%s scheitert (%s)", address, port,
                         reason, exc_info=True)
            self._status = MobileStatus(STATE_ERROR, address, port, reason)
            return self._status
        self._server = server
        self._running = (address, server.port)
        self._status = MobileStatus(STATE_RUNNING, address, server.port)
        return self._status

    def _stop_server(self) -> None:
        server, self._server = self._server, None
        self._running = None
        if server is not None:
            server.stop()
        # Ein Code ohne Server ist nutzlos, und beim Neustart auf anderer Adresse oder
        # anderem Port stimmte der QR-Code nicht mehr.
        self._context.pairing.close()

    def shutdown(self, lock_timeout: float = 1.0) -> None:
        """Stoppt den Server und sperrt weitere Starts. Blockiert höchstens
        `lock_timeout`: läuft gerade ein Start (der Worker hält den Lock), wird nicht
        gewartet — der Start prüft `_closed` und bricht selbst ab."""
        self._closed = True
        if not self._lock.acquire(timeout=lock_timeout):
            _log.warning("Handy-Instanz: Beenden wartet nicht auf einen laufenden Start")
            return
        try:
            self._stop_server()
            self._status = MobileStatus(STATE_OFF)
        finally:
            self._lock.release()

    def reopen(self) -> None:
        """Macht `shutdown` rückgängig (Skalierungs-Neustart ist gescheitert, die App
        läuft weiter). Der nächste `apply()` startet wieder."""
        self._closed = False

    # --- Geräte ---------------------------------------------------------------------------------

    def list_devices(self) -> list[Record]:
        """Die gekoppelten Geräte nach Name. Liest nur den Speicher, kein Dateizugriff."""
        return sorted(self._context.devices.get_all(),
                      key=lambda record: (record["name"].lower(), record["id"]))

    def key_locations(self) -> dict[str, str]:
        """`{device_id: "keyring" | "file"}` der Geräteschlüssel (#249). Liest nur den Speicher,
        fasst den Schlüsselbund nie an — darf im UI-Thread laufen."""
        return self._context.keys.where()

    def revoke(self, device_id: str) -> bool:
        """Widerruft ein Gerät (der Datensatz bleibt, die Antwort wird `token_revoked`).
        `False`, wenn es das Gerät nicht gibt."""
        with self._context.devices_lock:
            record = self._context.devices.get(device_id)
            if record is None:
                return False
            self._context.devices.save(mobile_pairing.revoke(record))
        # Außerhalb der Gerätesperre: der Schlüsselbund kann blockieren (Worker).
        self._context.keys.remove(device_id)
        return True

    def revoke_all(self) -> int:
        """Widerruft alle Geräte in **einem** Schreibvorgang; liefert die Zahl der
        vorhandenen Geräte (auch bereits widerrufene)."""
        with self._context.devices_lock:
            records = self._context.devices.get_all()
            self._context.devices.replace_all([mobile_pairing.revoke(r) for r in records])
        self._context.keys.retain([])
        return len(records)

    def pair_link(self, code: str) -> str | None:
        """Der Link im QR-Code: `<PWA>#pair=<ip>:<port>:<code>`. Das Fragment geht nie
        an einen Server und trägt nur Adresse und Kopplungscode (28 Zeichen), kein Token. `None`,
        solange der Server nicht läuft oder der Code keine Form eines Codes hat."""
        status = self._status
        canonical = mobile_pairing.normalize_code(code)
        if status.state != STATE_RUNNING or status.address is None or canonical is None:
            return None
        return f"{mobile_routes.PWA_URL}#pair={status.address}:{status.port}:{canonical}"
