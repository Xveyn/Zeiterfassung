"""Dienst über der Relay-Verbindung der Handy-Erfassung (#358, PR 3b), Tk-frei.

`RelayLink` hält die Sockets; dieser Dienst hält die **Regeln**: welche Boxen verbunden sind, wann
das offene Geheimnis (`MobileBoxStore.pending`) gebunden, verbunden oder abgeräumt wird, und der
Lebenszyklus wie bei `MobileService` (`apply`/`shutdown`/`reopen`).

Welche Boxen verbunden sind (`_wanted`)
---------------------------------------
Bei `mobile_enabled` aus, beim Beenden (`context.closing()`) oder nach `shutdown`: keine. Sonst die
gebundenen Geheimnisse, das offene nur bei aktiver Kopplungssitzung (`PairingSession.is_active`), und
die **ungebundenen Reste** (s. u.), weil das Handy sie schon benutzt.

Das offene Geheimnis (Regeln aus `mobile_box_store`)
---------------------------------------------------
- Nach einem Neustart ist ein `pending` verwaist (der Code lebte nur im Speicher): der erste
  `apply` mit eingeschalteter Handy-Erfassung räumt es ab (`clear_pending` und `delete_box`).
- `close_pairing` (Dialog zu) und `_on_idle` (alle `idle_tick_s` im Arbeits-Thread, fängt den
  stillen Ablauf des Codes) räumen ein `pending` ohne aktive Sitzung ebenso ab.
- Eine Koppel-Anfrage bindet im Arbeits-Thread: `RelayAdapter.process` → `bind(id, expected=<Box der
  Anfrage>)`. Ein zwischendurch neu geöffnetes Pairing bleibt so unangetastet.
- **Gescheitertes `bind`** (`OSError`, `MobileBoxReadOnly`): das Gerät ist gekoppelt, die Box noch
  `pending`. `(id, Geheimnis)` landet als ungebundener Rest im Speicher, bleibt verbunden, wird von
  keinem Aufräumen gelöscht und in jedem `_on_idle` (und vor jedem `open_pairing`) erneut gebunden.
  Ein Rest, den ein neues `open_pairing` aus dem Store verdrängt hat, bleibt für diese Sitzung
  verbunden, lässt sich aber nicht mehr binden (nach einem Neustart: neu koppeln).

Thread-Regeln
-------------
- `apply` im UI-Thread, die Arbeit im Worker (`run`); `open_pairing`, `close_pairing` und
  `forget_devices` im Worker. `_handle` und `_on_idle` ruft der Link aus seinem **einen**
  Arbeits-Thread; nur dort läuft `RelayAdapter.process` (ein Adapter je Dienst-Instanz).
- `_pair_lock` serialisiert „Koppel-Anfrage verarbeiten und binden“ gegen jedes Öffnen, Schließen
  und Abräumen des offenen Geheimnisses: der Code kann ablaufen und der Dialog schließen, während
  eine Koppel-Anfrage läuft — geräumt wird erst nach dem Binden, das Geheimnis geht nicht verloren
  (Review Focus 7). Unter ihm laufen Store-Aufrufe (Datei), nie ein Netzaufruf (`delete_box`,
  `put`); unter einem Lock des Stores läuft nichts von hier.
- `shutdown` blockiert höchstens die Frist des Links (`LinkTiming.join_s`).

Das Box-Geheimnis steht nie in einem Log oder Statusfeld; Logs nennen `relay_link.short_mark`.
"""
from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Iterable
from typing import Any

from src import box_relay, ws_client
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

    def open_pairing(self) -> str | None:
        """Öffnet eine Kopplungssitzung samt neuem offenen Geheimnis und liefert den Koppel-Link
        `<PWA>#relay=<Geheimnis>:<Code>`; `None`, wenn der Store nicht schreibbar ist."""
        if self._closed:
            return None
        previous: str | None = None
        with self._pair_lock:
            self._retry_unbound_locked()
            code = self._context.pairing.open()
            try:
                secret, previous = self._boxes.open_pending(self._now())
            except _STORE_ERRORS as exc:
                self._context.pairing.close()
                log.warning("Relay-Kopplung: offenes Geheimnis nicht angelegt (%s)",
                            type(exc).__name__)
                return None
            if previous is not None and previous in self._unbound.values():
                # Ein gekoppeltes Handy benutzt diese Box schon (Binden scheiterte): nie löschen.
                log.warning("Relay-Box %s: ungebundener Rest bleibt für diese Sitzung verbunden",
                            short_mark(previous))
                previous = None
        if previous is not None:
            self._delete_box(previous)
        self._sync_boxes()
        return relay_link(secret, code)

    def close_pairing(self) -> None:
        """Schließt die Kopplungssitzung und räumt das offene Geheimnis ab (Dialog zu)."""
        self._context.pairing.close()
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
        if secret is not None:
            self._delete_box(secret)

    # --- Arbeits-Thread des Links -------------------------------------------------------------

    def _handle(self, secret: str, payload: bytes) -> None:
        """Beantwortet eine Anfrage (Arbeits-Thread des Links): Verarbeiten → Binden → Antworten."""
        if _is_pair_request(payload):
            with self._pair_lock:
                result = self._adapter.process(payload)
                if result.paired_device_id is not None:
                    self._bind_locked(result.paired_device_id, secret)
        else:
            result = self._adapter.process(payload)
        if result.frame is not None:
            self._link.put(secret, result.frame)

    def _bind_locked(self, device_id: str, secret: str) -> bool:
        """Bindet das offene Geheimnis `secret` an das Gerät. `True`, wenn erledigt (gebunden oder
        nicht mehr bindbar); bei einem Schreibfehler wird es ein ungebundener Rest."""
        try:
            self._boxes.bind(device_id, expected=secret)
        except _STORE_ERRORS as exc:
            if self._unbound.get(device_id) != secret:
                log.warning("Relay-Box %s: Binden nach der Kopplung gescheitert (%s), "
                            "neuer Versuch folgt", short_mark(secret), type(exc).__name__)
            self._unbound = {**self._unbound, device_id: secret}
            return False
        except ValueError:
            log.warning("Relay-Box %s: Geräte-ID nicht bindbar", short_mark(secret))
        self._drop_unbound_locked(device_id)
        return True

    def _drop_unbound_locked(self, device_id: str) -> str | None:
        secret = self._unbound.get(device_id)
        if secret is not None:
            self._unbound = {k: v for k, v in self._unbound.items() if k != device_id}
        return secret

    def _retry_unbound_locked(self) -> None:
        for device_id, secret in list(self._unbound.items()):
            if self._boxes.get(device_id) == secret:
                self._drop_unbound_locked(device_id)          # anderswo schon gebunden
            elif self._boxes.pending() == secret:
                self._bind_locked(device_id, secret)
            # sonst: verdrängt, bleibt für diese Sitzung verbunden

    def _on_idle(self) -> None:
        """Alle `idle_tick_s` im Arbeits-Thread: Reste binden, abgelaufenes Pairing abräumen."""
        if self._closed:
            return
        with self._pair_lock:
            self._retry_unbound_locked()
        self._clean_pending()
        self._sync_boxes()

    # --- Widerruf (Worker) --------------------------------------------------------------------

    def forget_devices(self, ids: Iterable[str] | None) -> None:
        """Räumt die Boxen widerrufener Geräte ab (`None` = alle widerrufenen bzw. unbekannten).
        Ein Gerät, das inzwischen (wieder) gekoppelt und nicht widerrufen ist, bleibt."""
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
            keep = self._boxes.all_secrets() + list(self._unbound.values())
        self._cursor.retain(keep)
        for secret in dropped:
            self._delete_box(secret)
        self._sync_boxes()

    def _forgettable(self, device_id: str) -> bool:
        record = self._context.devices.get(device_id)
        return record is None or bool(record.get("revoked"))

    # --- Zustand ------------------------------------------------------------------------------

    def _wanted(self) -> list[str]:
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
