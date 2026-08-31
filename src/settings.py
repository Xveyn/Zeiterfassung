from __future__ import annotations

import contextlib
import datetime
import json
import logging
import os
import threading
from typing import Any, Iterator, Protocol

from src.json_store import atomic_write_json
from src.time_utils import utc_now_iso


class SettingsLike(Protocol):
    """Minimalvertrag der Settings für die reinen Regel-Module.

    `workweek`, `weekly_limit` und `pause_requirement` brauchen von den
    Settings ausschließlich `get(key)` — und ihre Tests reichen dafür ein
    schlichtes `dict` herein, was die Docstrings dort auch ausdrücklich
    zulassen („Settings-artiges Dict/Objekt"). Ein `Settings`-Typ in diesen
    Signaturen wäre also eine Zusage, die auf der Aufruferseite niemand hält.

    `key` ist positionsgebunden (`/`): `dict.get` nimmt seinen Schlüssel nur
    positional, ohne das Slash wäre ein einfaches dict nicht zuweisbar.
    """

    def get(self, key: str, /) -> Any: ...


WEEKDAY_KEYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")  # Index = datetime.weekday()

SYNCED_SETTING_KEYS = (
    "recipient", "name", "hourly_rate",
    "mail_subject", "mail_greeting", "mail_content", "mail_closing",
    "gcal_calendar_id", "categories", "category_times",
    "werkstudent_limit_enabled", "werkstudent_limit_start",
    "werkstudent_limit_end", "werkstudent_limit_max_hours",
    "pause_warning_enabled",
    "workweek_only",
)

DEFAULTS = {
    "default_pause": 30,
    "recipient": "",
    "share_recipient": "",
    "autostart": False,
    "name": "",
    "mail_subject": "Zeiterfassung — {zeitraum}",
    "mail_greeting": "Sehr geehrte Damen und Herren,",
    "mail_content": "anbei erhalten Sie meine Zeiterfassung für den Zeitraum {zeitraum}.",
    "mail_closing": "Mit freundlichen Grüßen",
    "hourly_rate": 0.0,
    "state": "",
    "last_update_check_at": "",
    "dismissed_version": "",
    "update_check_frequency": "daily",
    "update_toast_shown_version": "",
    "prerelease_updates_enabled": False,
    "default_start_mon": "08:00",
    "default_start_tue": "08:00",
    "default_start_wed": "08:00",
    "default_start_thu": "08:00",
    "default_start_fri": "08:00",
    "default_start_sat": "08:00",
    "default_start_sun": "08:00",
    "default_end_mon": "16:00",
    "default_end_tue": "16:00",
    "default_end_wed": "16:00",
    "default_end_thu": "16:00",
    "default_end_fri": "16:00",
    "default_end_sat": "16:00",
    "default_end_sun": "16:00",
    "show_weekend": True,
    "workweek_only": False,
    "always_on_top": False,
    "minimize_to_tray": False,
    "reminders_enabled": False,
    "reminder_minutes_before": 15,
    "send_reminder_enabled": False,
    "send_reminder_day": 1,
    "send_reminder_time": "18:00",
    "send_reminder_last_fired_month": "",
    # Tagesbezogene Sende-Erinnerung (an Reservierungs-Slots gekoppelt) und
    # Verschiebung des Monatstermins. Alle gerätelokal — bewusst NICHT in
    # SYNCED_SETTING_KEYS, wie die übrigen Benachrichtigungs-Keys.
    "send_reminder_reservations_enabled": False,
    "send_reminder_default_minutes": 15,
    # "none" | "backward" (vorziehen) | "forward" (nachziehen).
    "send_reminder_weekend_shift": "none",
    "send_reminder_shift_holidays": False,
    "send_period_from_last_reminder": False,
    "send_period_anchor_monthly": False,
    "sender_email": "",
    "sync_enabled": False,
    "device_id": "",
    # Lesbarer Name dieses Geräts + Spiegel der Namen aller bekannten Geräte
    # ({device_id: {name, updated_at}}, s. devices.py). Beide bewusst NICHT in
    # SYNCED_SETTING_KEYS: ein synchronisierter Key wäre ein einziger globaler
    # Wert, die Geräte würden sich gegenseitig den Namen überschreiben. Der
    # Transport läuft stattdessen über die Registry im Sync-Doc.
    "device_name": "",
    "known_devices": {},
    # Merker für die einmalige Hostnamen-Vorbelegung (main._ensure_device_name):
    # ein leerer device_name ist ein gültiger Zustand ("zeig mir die ID"), kein
    # fehlender Wert — ohne diesen Merker wäre beides nicht unterscheidbar.
    "device_name_initialized": False,
    "last_pull_at": "",
    "drive_etag": "",
    "gc_watermark": "",
    "gcal_enabled": False,
    "gcal_calendar_id": "",
    "last_calendar_sync_at": "",
    "categories": [],
    "category_times": {},
    "ui_scale": 1.0,
    "werkstudent_limit_enabled": False,
    "werkstudent_limit_start": "",
    "werkstudent_limit_end": "",
    "werkstudent_limit_max_hours": 20.0,
    "pause_warning_enabled": True,
    # Vorbelegung des Sammelfelds im Urlaubs-Dialog. Bewusst NICHT in
    # SYNCED_SETTING_KEYS — wie default_pause und die Wochenplan-Zeiten, die
    # dort ebenfalls nicht stehen; der Urlaubs-Store synchronisiert ohnehin
    # nicht.
    "vacation_hours_per_day": 8.0,
}

_COERCE_FAILED = object()


def _coerce(value: Any, default: Any) -> Any:
    """Versuche `value` in den Typ von `default` zu casten.

    Liefert den gecasteten Wert oder `_COERCE_FAILED`. bool ist Subklasse
    von int — wir verlangen für bool-Defaults strikt einen bool, sonst
    wäre `1` versehentlich `True`.
    """
    target_type = type(default)
    if target_type is bool:
        return value if isinstance(value, bool) else _COERCE_FAILED
    if isinstance(value, target_type) and not isinstance(value, bool):
        return value
    try:
        if target_type is int:
            return int(value)
        if target_type is float:
            return float(value)
        if target_type is str:
            return str(value)
    except (TypeError, ValueError):
        return _COERCE_FAILED
    return _COERCE_FAILED


def _migrate_legacy_default_times(loaded: dict[str, Any]) -> None:
    """Spiegelt alte globale default_start/default_end auf Per-Tag-Keys.

    Modifiziert `loaded` in-place. Per-Tag-Keys haben Priorität — wenn ein
    Tag schon einen Wert hat, wird er nicht überschrieben.

    Nicht-strings (None, Zahlen) und leere Strings im Legacy-Feld werden
    ignoriert, damit `_coerce` nichts in die Per-Tag-Keys gespiegelt bekommt,
    was es dort nicht haben will.
    """
    def _legacy(key: str) -> str | None:
        value = loaded.get(key)
        return value if isinstance(value, str) and value else None

    legacy_start = _legacy("default_start")
    legacy_end = _legacy("default_end")
    if legacy_start is None and legacy_end is None:
        return
    for day in WEEKDAY_KEYS:
        if legacy_start is not None and f"default_start_{day}" not in loaded:
            loaded[f"default_start_{day}"] = legacy_start
        if legacy_end is not None and f"default_end_{day}" not in loaded:
            loaded[f"default_end_{day}"] = legacy_end


# --- Reine Helfer für den Settings-Dialog-Save-Pfad (ohne Tk, headless testbar,
# extrahiert aus settings_dialog.save_settings, Issue #51). settings.py bleibt
# bewusst stdlib-only — kein holidays/google-Import (sync.py importiert dieses
# Modul, vgl. Issue #48). Das State-Label→Code-Mapping lebt deshalb in
# holidays_de.code_for_state_label, nicht hier.


def parse_hourly_rate(raw: str | None) -> float:
    """Parst die Stundensatz-Eingabe (String) zu float. Leer/nur Whitespace oder
    ungültig → 0.0 (bewusst tolerant: der Dialog soll bei Tippfehlern nicht
    blocken). Komma-Dezimal wird nicht unterstützt (float() wirft → 0.0)."""
    raw = (raw or "").strip()
    if not raw:
        return 0.0
    try:
        return float(raw)
    except ValueError:
        return 0.0


def parse_reminder_minutes(raw: Any) -> int | None:
    """Parst die 'Minuten vor Ende'-Eingabe zu int in [0, 120]. Ungültig
    (nicht-numerisch, negativ, > 120, Kommazahl) -> None. Der Dialog nutzt None
    als Fehlersignal (anders als parse_hourly_rate, das tolerant auf 0.0 fällt —
    hier ist eine bewusste Validierung gewünscht)."""
    try:
        value = int(str(raw).strip())
    except (ValueError, TypeError, AttributeError):
        return None
    if 0 <= value <= 120:
        return value
    return None


def split_synced_updates(updates: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Partitioniert ein updates-Dict in (synced, plain) anhand
    SYNCED_SETTING_KEYS. synced reist per Drive-Sync mit (set_synced), plain
    bleibt gerätelokal (set_many)."""
    synced = {k: v for k, v in updates.items() if k in SYNCED_SETTING_KEYS}
    plain = {k: v for k, v in updates.items() if k not in SYNCED_SETTING_KEYS}
    return synced, plain


def resolve_calendar_id(cal_map: dict[str, str], selected_label: str, current_id: str) -> str:
    """Mappt den im Dialog gewählten Kalender-Klarnamen über cal_map zurück auf
    die Kalender-ID. Unbekanntes Label → bisheriger Wert, ersatzweise
    "primary" (nie leer, damit der gcal-Abgleich einen gültigen Kalender hat)."""
    return cal_map.get(selected_label, current_id or "primary")


def clamp_ui_scale(value: Any) -> float:
    """Normalisiert den UI-Skalierungsfaktor defensiv: castet zu float und
    klemmt auf [0.75, 2.0]. Nicht-castbare Werte (None, Müll-String) → 1.0
    (Default). Schützt das tk-scaling vor korrupten settings.json-Werten und
    Slider-Ausreißern."""
    try:
        f = float(value)
    except (TypeError, ValueError):
        return 1.0
    return max(0.75, min(2.0, f))


class Settings:
    def __init__(self, filepath: str = "settings.json",
                 lock: threading.RLock | None = None) -> None:
        self.filepath = filepath
        # Geteilter Daten-Lock (Audit H1/H2) — siehe storage.py.
        self._lock = lock if lock is not None else threading.RLock()
        self._data: dict[str, Any] = dict(DEFAULTS)
        # {key: {"modified_at": ..., "device_id": ...}}
        self._synced_meta: dict[str, dict[str, str]] = {}
        self.device_id_for_sync = ""  # wird von main.py auf settings.device_id gesetzt
        self._load()

    def _load(self) -> None:
        if not os.path.exists(self.filepath):
            return
        try:
            with open(self.filepath, "r", encoding="utf-8") as f:
                loaded = json.load(f)
        except (json.JSONDecodeError, ValueError):
            self._quarantine_corrupt("JSON nicht parsebar")
            self._data = dict(DEFAULTS)
            return

        log = logging.getLogger(__name__)
        if not isinstance(loaded, dict):
            self._quarantine_corrupt(
                f"unerwartetes Toplevel-Format ({type(loaded).__name__})"
            )
            self._data = dict(DEFAULTS)
            return

        # _synced_meta aus der Datei extrahieren, sonst landet es als unbekannter Key
        synced_meta_raw = loaded.pop("_synced_meta", None)
        if isinstance(synced_meta_raw, dict):
            for k, v in synced_meta_raw.items():
                if not isinstance(v, dict):
                    continue
                if "modified_at" in v and "device_id" in v:
                    self._synced_meta[k] = {
                        "modified_at": str(v["modified_at"]),
                        "device_id": str(v["device_id"]),
                    }

        _migrate_legacy_default_times(loaded)

        for key, default_value in DEFAULTS.items():
            if key not in loaded:
                continue
            coerced = _coerce(loaded[key], default_value)
            if coerced is _COERCE_FAILED:
                log.warning(
                    "settings.json: Wert für %r (%r, Typ %s) ist nicht in Typ %s "
                    "castbar — verwende Default %r",
                    key, loaded[key], type(loaded[key]).__name__,
                    type(default_value).__name__, default_value,
                )
                continue
            self._data[key] = coerced
        # Unbekannte Keys aus loaded werden ignoriert (nicht in _data übernommen).

    def _quarantine_corrupt(self, reason: str) -> None:
        """Verschiebt ein korruptes settings.json nach `.corrupt-<stamp>`
        und loggt das Ereignis, statt es kommentarlos zu verwerfen (Audit
        M4/N4). Defaults setzt der Aufrufer.

        BEWUSST eigen statt `json_store.quarantine_corrupt` (R2): diese
        Variante greift auch bei einem nicht-Dict-Toplevel (nicht nur bei
        Parse-Fehlern), trägt den Grund in der Meldung — und vor allem
        **schluckt** sie einen fehlgeschlagenen Rename: die Settings werden
        beim Start gelesen, ein `OSError` hier würde den Start verhindern.
        Die Stores lassen ihn dagegen bewusst hochlaufen."""
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        target = f"{self.filepath}.corrupt-{stamp}"
        log = logging.getLogger(__name__)
        try:
            os.replace(self.filepath, target)
        except OSError:
            log.warning(
                "settings.json korrupt (%s); Quarantäne-Rename fehlgeschlagen "
                "— verwende Defaults", reason, exc_info=True,
            )
            return
        log.warning(
            "settings.json korrupt (%s) — nach %s in Quarantäne verschoben, "
            "verwende Defaults", reason, os.path.basename(target),
        )

    def _save_to_disk(self) -> None:
        payload = dict(self._data)
        if self._synced_meta:
            payload["_synced_meta"] = self._synced_meta
        atomic_write_json(self.filepath, payload)

    def get(self, key: str) -> Any:
        with self._lock:
            return self._data.get(key, DEFAULTS.get(key))

    def set(self, key: str, value: Any) -> None:
        self.set_many({key: value})

    def set_many(self, updates: dict[str, Any]) -> None:
        """Mehrere Werte setzen, einmal auf Platte schreiben.

        Leeres Dict ist No-op (kein Disk-Roundtrip).
        """
        if not updates:
            return
        with self._lock:
            self._data.update(updates)
            self._save_to_disk()

    @contextlib.contextmanager
    def override_in_memory(self, key: str, value: Any) -> Iterator[None]:
        """Überschreibt `key` NUR im Speicher (kein Disk-Save) für die Dauer
        des with-Blocks und stellt den vorherigen Zustand danach wieder her.

        Für transiente Mess-/Pre-Warm-Szenarien (GridRenderer.measure_max_width
        variiert show_weekend, um die maximale Fensterbreite zu proben), die
        einen Setting kurzzeitig verstellen müssen, ohne settings.json zu
        schreiben. Nicht für persistente Änderungen — dafür set()/set_many().
        Kapselt den früher direkten Zugriff auf `_data` von außen (Audit M12)."""
        with self._lock:
            had_key = key in self._data
            previous = self._data.get(key)
            self._data[key] = value
        try:
            yield
        finally:
            with self._lock:
                if had_key:
                    self._data[key] = previous
                else:
                    self._data.pop(key, None)

    def set_synced(self, key: str, value: Any) -> None:
        """Setzt einen whitelisted Sync-Key und stempelt Per-Field-Metadaten.
        Außerhalb der Whitelist verhält sich wie ein normales set()."""
        if key not in SYNCED_SETTING_KEYS:
            self.set(key, value)
            return
        with self._lock:
            self._data[key] = value
            self._synced_meta[key] = {
                "modified_at": utc_now_iso(),
                "device_id": self.device_id_for_sync,
            }
            self._save_to_disk()

    def apply_updates(self, updates: dict[str, Any]) -> None:
        """Routet ein updates-Dict aus dem Settings-Dialog auf den korrekten
        Persistenz-Pfad: Keys in SYNCED_SETTING_KEYS über set_synced (je ein
        Per-Field-Stempel + Disk-Write), der Rest in einem set_many. Single
        Entry-Point für den Dialog-Save (Issue #51)."""
        synced, plain = split_synced_updates(updates)
        for key, value in synced.items():
            self.set_synced(key, value)
        if plain:
            self.set_many(plain)

    def get_synced_doc(self) -> dict[str, dict[str, Any]]:
        """{key: {value, modified_at, device_id}} — Eingabe für den Sync-Merge.
        Nur Keys mit vorhandener Metadaten-Spur werden zurückgegeben."""
        with self._lock:
            doc = {}
            for key in SYNCED_SETTING_KEYS:
                meta = self._synced_meta.get(key)
                if meta is None:
                    continue
                doc[key] = {
                    "value": self._data.get(key, DEFAULTS.get(key)),
                    "modified_at": meta["modified_at"],
                    "device_id": meta["device_id"],
                }
            return doc

    def apply_synced(self, synced_doc: dict[str, Any]) -> None:
        """Übernimmt das Merge-Ergebnis: schreibt value in _data und Meta in
        _synced_meta. Schreibt einmal auf Platte."""
        if not synced_doc:
            return
        with self._lock:
            for key, payload in synced_doc.items():
                if key not in SYNCED_SETTING_KEYS:
                    continue
                if not isinstance(payload, dict) or "value" not in payload:
                    continue
                value = payload["value"]
                # Remote-Wert typprüfen wie beim lokalen _load (N5): ein
                # korrumpiertes/böswilliges Sync-Doc darf z.B. hourly_rate
                # nicht auf einen String setzen. Nicht castbar → überspringen
                # (lokaler Wert bleibt), statt Garbage zu übernehmen.
                if key in DEFAULTS:
                    coerced = _coerce(value, DEFAULTS[key])
                    if coerced is _COERCE_FAILED:
                        logging.getLogger(__name__).warning(
                            "Sync: Remote-Wert für %r (%r, Typ %s) ist nicht in "
                            "Typ %s castbar — übersprungen",
                            key, value, type(value).__name__,
                            type(DEFAULTS[key]).__name__,
                        )
                        continue
                    value = coerced
                self._data[key] = value
                self._synced_meta[key] = {
                    "modified_at": str(payload.get("modified_at", "")),
                    "device_id": str(payload.get("device_id", "")),
                }
            self._save_to_disk()
