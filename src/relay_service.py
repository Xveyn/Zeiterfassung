"""Dienst über der Relay-Verbindung der Handy-Erfassung (#358), Tk-frei.

`RelayLink` hält die Sockets, dieser Dienst die **Regeln**: welche Boxen verbunden sind, wann das
offene Geheimnis (`MobileBoxStore.pending`) gebunden, verbunden oder abgeräumt wird, und der
Lebenszyklus wie bei `MobileService` (`apply`/`shutdown`/`reopen`). `_pair_lock` serialisiert
Kopplung und Binden gegen Öffnen, Schließen und Abräumen, nie über einem Netzaufruf. Regeln,
Threads und Sperrreihenfolge: `src/CLAUDE.md`, „Threading-Modell“, „Regeln der Relay-Verbindung“.
Das Geheimnis steht nie in Log oder Statusfeld (`relay_link.short_mark`).
"""
from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Iterable
from typing import Any, NamedTuple

from src import box_relay, mobile_pairing, ws_client
from src.mobile_box_cursor import MobileBoxCursor
from src.mobile_box_store import MobileBoxReadOnly, MobileBoxStore
from src.mobile_relay_codec import FrameError, decode_request, relay_link
from src.mobile_routes import MobileContext
from src.relay_adapter import RelayAdapter
from src.relay_link import DEFAULT_TIMING, LinkTiming, RelayLink, short_mark
from src.time_utils import utc_now_iso
from src.ws_client import Connect

log = logging.getLogger(__name__)

STATE_OFF = "off"

_STORE_ERRORS = (MobileBoxReadOnly, OSError)


def _is_pair_request(payload: bytes) -> bool:
    try:
        return decode_request(payload).path == "/v1/pair"
    except FrameError:
        return False                 # der Adapter verwirft die Nutzlast ohnehin


class RelayPairing(NamedTuple):
    """Eine geöffnete Relay-Kopplung: der Koppel-Link und der Code ihrer Sitzung (kanonisch). Mit dem
    Code schließt der Aufrufer genau diese Sitzung (`RelayService.close_pairing`)."""
    link: str
    code: str


class RelayService:
    def __init__(self, settings: Any, context: MobileContext, boxes: MobileBoxStore,
                 cursor: MobileBoxCursor, *, run: Callable[..., None],
                 connect: Connect = ws_client.connect,
                 delete_box: Callable[[str], bool] = box_relay.delete_box,
                 now: Callable[[], str] = utc_now_iso,
                 timing: LinkTiming = DEFAULT_TIMING) -> None:
        self._settings = settings
        self._context = context
        self._boxes = boxes
        self._cursor = cursor
        self._run = run
        self._connect = connect
        self._delete_box = delete_box
        self._now = now
        self._timing = timing
        self._adapter = RelayAdapter(context)
        self._pair_lock = threading.Lock()
        # Ungebundene Reste: Geräte-ID → Geheimnis. Geändert nur unter `_pair_lock` und immer durch
        # ein neues Dict ersetzt: Leser außerhalb (`_wanted`, `states_by_device` im UI-Thread) nehmen
        # die Referenz ohne Lock und warten so nie auf ein Binden (Datei, unter Windows `icacls`).
        self._unbound: dict[str, str] = {}
        self._orphan_checked = False
        self._closed = False
        self._link = self._new_link()

    def _new_link(self) -> RelayLink:
        return RelayLink(self._connect, self._handle, self._cursor, on_idle=self._on_idle,
                         timing=self._timing)

    # --- Lebenszyklus -------------------------------------------------------------------------

    def apply(self) -> None:
        """Bringt die Verbindungen in den Zustand der Settings. Im UI-Thread aufrufen; die Arbeit
        (Datei, Netz) läuft im Worker."""
        if self._closed:
            return
        self._run(self._reconcile)

    def _active(self) -> bool:
        return (not self._closed and bool(self._settings.get("mobile_enabled"))
                and not self._context.closing())

    def _reconcile(self) -> None:
        if self._closed:
            return
        if self._active() and not self._orphan_checked:
            self._orphan_checked = True
            self._clean_pending()
        self._sync_boxes()

    def shutdown(self) -> None:
        """Trennt alle Boxen und sperrt weitere Arbeit; blockiert höchstens die Frist des Links."""
        self._closed = True
        self._link.shutdown()

    def reopen(self) -> None:
        """Macht `shutdown` rückgängig (Skalierungs-Neustart gescheitert); der nächste `apply()`
        verbindet wieder."""
        if not self._closed:
            return
        self._link = self._new_link()
        self._closed = False

    # --- Kopplung (Worker) --------------------------------------------------------------------

    def open_pairing(self) -> RelayPairing | None:
        """Öffnet eine Kopplungssitzung samt neuem offenen Geheimnis und liefert Koppel-Link
        `<PWA>#relay=<Geheimnis>:<Code>` und Code. `None` (ohne Sitzung): Dienst geschlossen,
        Handy-Erfassung aus, Store nicht schreibbar oder ein ungebundener Rest wartet noch aufs
        Binden."""
        if not self._active():
            return None
        secret: str | None = None
        code: str | None = None
        previous: str | None = None
        with self._pair_lock:
            replaced = self._retry_unbound_locked()
            if self._unbound:
                # Keine Sitzung schließen: geöffnet hat dieser Aufruf noch keine, eine offene gehört
                # einem anderen Weg (LAN-Koppeldialog).
                log.warning("Relay-Kopplung abgelehnt: eine gekoppelte Box ist noch nicht gebunden")
            else:
                secret, code, previous = self._open_pending_locked()
            self._sync_boxes_locked()
        self._drop_remote(replaced + ([previous] if previous is not None else []))
        if secret is None or code is None:
            return None
        link = relay_link(secret, code)
        canonical = mobile_pairing.normalize_code(code)
        if link is None or canonical is None:
            return None
        return RelayPairing(link, canonical)

    def _open_pending_locked(self) -> tuple[str | None, str | None, str | None]:
        """Öffnet Sitzung und offenes Geheimnis; `(Geheimnis, Code, altes_zum_Löschen)`."""
        code = self._context.pairing.open()
        try:
            secret, previous = self._boxes.open_pending(self._now())
        except _STORE_ERRORS as exc:
            self._context.pairing.close()
            log.warning("Relay-Kopplung: offenes Geheimnis nicht angelegt (%s)", type(exc).__name__)
            return None, None, None
        return secret, code, previous

    def close_pairing(self, code: str) -> None:
        """Schließt die Kopplungssitzung mit diesem Code (Dialog zu) und räumt ein offenes Geheimnis
        ohne aktive Sitzung ab. Eine Sitzung mit anderem Code bleibt offen: die Worker laufen
        ungeordnet, und inzwischen kann ein anderer Dialog seine eigene geöffnet haben."""
        self._context.pairing.close_if(code)
        self._clean_pending()
        self._sync_boxes()

    def _clean_pending(self) -> None:
        """Räumt ein offenes Geheimnis ohne aktive Sitzung ab, außer es ist ein ungebundener Rest."""
        with self._pair_lock:
            pending = self._boxes.pending()
            if (pending is None or self._context.pairing.is_active()
                    or pending in self._unbound.values()):
                return
            try:
                secret = self._boxes.clear_pending()
            except _STORE_ERRORS as exc:
                log.warning("Relay: offenes Geheimnis nicht verworfen (%s)", type(exc).__name__)
                return
            self._sync_boxes_locked()             # erst trennen, dann am Relay löschen
            keep = self._known_secrets_locked()
        if secret is not None:
            self._cursor.retain(keep)
            self._delete_box(secret)

    def _known_secrets_locked(self) -> list[str]:
        """Alle Geheimnisse, deren Cursor bleiben muss (gebunden, offen, ungebundene Reste)."""
        return self._boxes.all_secrets() + list(self._unbound.values())

    # --- Arbeits-Thread des Links -------------------------------------------------------------

    def _handle(self, secret: str, payload: bytes) -> None:
        """Beantwortet eine Anfrage (Arbeits-Thread des Links): Verarbeiten → Binden → Antworten."""
        replaced: list[str] = []
        if _is_pair_request(payload):
            with self._pair_lock:
                result = self._adapter.process(payload)
                # Beendet/entfernt, während die Anfrage lief: `mobile_box.json` nicht neu schreiben.
                if self._closed:
                    return
                if result.paired_device_id is not None:
                    replaced = self._bind_locked(result.paired_device_id, secret)
                    self._sync_boxes_locked()
        else:
            result = self._adapter.process(payload)
        if result.frame is not None and not self._closed:
            self._link.put(secret, result.frame)
        self._drop_remote(replaced)

    def _bind_locked(self, device_id: str, secret: str) -> list[str]:
        """Bindet das offene Geheimnis `secret` an das Gerät; bei einem Schreibfehler wird es ein
        ungebundener Rest. Liefert die dabei ersetzte alte Box des Geräts (nach dem Lock am Relay
        löschen), sonst eine leere Liste."""
        replaced: str | None = None
        try:
            _bound, replaced = self._boxes.bind(device_id, expected=secret)
        except _STORE_ERRORS as exc:
            if self._unbound.get(device_id) != secret:
                log.warning("Relay-Box %s: Binden nach der Kopplung gescheitert (%s), "
                            "neuer Versuch folgt", short_mark(secret), type(exc).__name__)
            self._unbound = {**self._unbound, device_id: secret}
            return []
        except ValueError:
            log.warning("Relay-Box %s: Geräte-ID nicht bindbar", short_mark(secret))
        self._drop_unbound_locked(device_id)
        return [replaced] if replaced is not None and replaced != secret else []

    def _drop_unbound_locked(self, device_id: str) -> str | None:
        secret = self._unbound.get(device_id)
        if secret is not None:
            self._unbound = {k: v for k, v in self._unbound.items() if k != device_id}
        return secret

    def _retry_unbound_locked(self) -> list[str]:
        """Bindet die ungebundenen Reste erneut; liefert die dabei ersetzten alten Boxen."""
        replaced: list[str] = []
        for device_id, secret in list(self._unbound.items()):
            if self._boxes.get(device_id) == secret:
                self._drop_unbound_locked(device_id)          # anderswo schon gebunden
            elif self._boxes.pending() == secret:
                replaced += self._bind_locked(device_id, secret)
            # sonst: verdrängt (nur theoretisch, `open_pairing` lehnt bei einem Rest ab),
            # bleibt für diese Sitzung verbunden
        return replaced

    def _drop_remote(self, secrets: list[str]) -> None:
        """Nach dem Lock: Cursor nicht mehr bekannter Boxen verwerfen, die Boxen am Relay löschen."""
        if not secrets:
            return
        with self._pair_lock:
            keep = self._known_secrets_locked()
        self._cursor.retain(keep)
        for secret in secrets:
            self._delete_box(secret)

    def _on_idle(self) -> None:
        """Alle `idle_tick_s` im Arbeits-Thread: Reste binden, abgelaufenes Pairing abräumen."""
        if not self._active():
            return
        with self._pair_lock:
            replaced = self._retry_unbound_locked()
            self._sync_boxes_locked()             # eine ersetzte Box erst trennen, dann löschen
        self._drop_remote(replaced)
        self._clean_pending()
        self._sync_boxes()

    # --- Widerruf (Worker) --------------------------------------------------------------------

    def forget_devices(self, ids: Iterable[str] | None) -> None:
        """Räumt die Boxen widerrufener Geräte ab (Hook von `MobileService.revoke`/`revoke_all`).
        Ein Gerät, das inzwischen (wieder) gekoppelt und nicht widerrufen ist, bleibt.

        **`None` heißt „alle widerrufenen oder unbekannten“, nicht „alle“.** Ein bedingungsloses
        Abräumen („Zeiterfassung entfernen“, `--forget-secrets`) nutzt `MobileBoxStore` und
        `box_relay.delete_box` direkt."""
        dropped: list[str] = []
        with self._pair_lock:
            known = set(self._boxes.known_ids()) | set(self._unbound)
            targets = known if ids is None else set(ids)
            targets = {device_id for device_id in targets if self._forgettable(device_id)}
            try:
                for device_id in sorted(targets):
                    secret = self._boxes.remove(device_id)
                    if secret is not None:
                        dropped.append(secret)
                    leftover = self._drop_unbound_locked(device_id)
                    if leftover is not None:
                        # Auch ein verdrängter Rest (nicht mehr `pending`) gehört am Relay gelöscht.
                        if self._boxes.pending() == leftover:
                            self._boxes.clear_pending()
                        if leftover not in dropped:
                            dropped.append(leftover)
            except _STORE_ERRORS as exc:
                log.warning("Relay: Boxen widerrufener Geräte nicht abgelegt (%s)",
                            type(exc).__name__)
            keep = self._known_secrets_locked()
            self._sync_boxes_locked()             # erst trennen, dann am Relay löschen
        self._cursor.retain(keep)
        for secret in dropped:
            self._delete_box(secret)

    def _forgettable(self, device_id: str) -> bool:
        record = self._context.devices.get(device_id)
        return record is None or bool(record.get("revoked"))

    # --- Zustand ------------------------------------------------------------------------------

    def _wanted(self) -> list[str]:
        """Nur unter `_pair_lock` (reines Speicherlesen)."""
        if not self._active():
            return []
        pending = self._boxes.pending()
        wanted = [s for s in self._boxes.all_secrets() if s != pending]
        leftovers = list(self._unbound.values())
        wanted += [s for s in leftovers if s not in wanted]
        if pending is not None and pending not in wanted and self._context.pairing.is_active():
            wanted.append(pending)
        return wanted

    def _sync_boxes(self) -> None:
        with self._pair_lock:
            self._sync_boxes_locked()

    def _sync_boxes_locked(self) -> None:
        """Schnappschuss und `set_boxes` in einem Zug unter `_pair_lock` (blockiert nie)."""
        if self._closed:
            return
        self._link.set_boxes(self._wanted())

    def states_by_device(self) -> dict[str, str]:
        """Geräte-ID → Zustand ihrer Box (`relay_link.STATE_*`, ohne Verbindung `off`). Nie ein
        Geheimnis; liest nur Speicher."""
        states = self._link.states()
        result: dict[str, str] = {}
        for device_id in self._boxes.known_ids():
            secret = self._boxes.get(device_id)
            result[device_id] = states.get(secret, STATE_OFF) if secret else STATE_OFF
        leftovers = self._unbound
        for device_id, secret in leftovers.items():
            result.setdefault(device_id, states.get(secret, STATE_OFF))
        return result
