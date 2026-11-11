# pyright: reportOptionalMemberAccess=true
"""Prüfung und Umrechnung des Formularstands je Einstellungs-Tab (#132).

Der Inhalt des früheren `dialog.save_settings`, aufgeteilt auf die Tabs,
die ihn tragen. Jeder Tab liefert seinen **rohen** Formularstand
(`FieldSet.values()` — Text aus Entries/Comboboxen, Bools aus Häkchen);
hier wird er geprüft (`validate_*` → `(Titel, Meldung)` oder `None`) und in
Settings-Werte umgerechnet (`*_updates` → Dict für `Settings.apply_updates`).

Tk-frei und getestet. Die Umrechnung ist so tolerant wie vorher: was
das frühere `save_settings` still auf einen Fallback setzte, tut es hier auch.
"""

import datetime
import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from src.default_times import MODE_GENERAL, mode_code, spread
from src.devices import sanitize_device_name
from src.api_service import (
    DEFAULT_PORT, MAX_PORT, MIN_PORT, REASON_INVALID_PORT, REASON_PORT_IN_USE,
    REASON_TOKEN_UNAVAILABLE, STATE_ERROR, STATE_RUNNING, STATE_STARTING,
    ApiStatus, parse_port,
)
from src.holidays_region import country_choices, region_choices
from src.i18n import N_, t
from src.mobile_service import (
    DEFAULT_PORT as MOBILE_DEFAULT_PORT, REASON_ADDRESS_GONE, REASON_NO_ADDRESS,
    REASON_INVALID_PORT as MOBILE_INVALID_PORT, REASON_PORT_IN_USE as MOBILE_PORT_IN_USE,
    STATE_ERROR as MOBILE_ERROR, STATE_RUNNING as MOBILE_RUNNING,
    STATE_STARTING as MOBILE_STARTING, MobileStatus,
)
from src.mobile_pairing import pair_count
from src.mobile_sync import WINDOW_CAP_CHOICES, window_cap
from src.mobile_store import MobileStoreReadOnly
from src.netinfo import is_lan_address
from src.send_reminder import shift_for_label
from src.settings import (
    WEEKDAY_KEYS, clamp_ui_scale, parse_hourly_rate, parse_reminder_minutes,
    resolve_calendar_id,
)
from src.time_utils import (
    short_day_names, format_iso_date, format_iso_datetime, validate_entry, validate_period,
)
from src.updater import frequency_for_label

_log = logging.getLogger(__name__)

WSL_KEYS = (
    "werkstudent_limit_enabled", "werkstudent_limit_start",
    "werkstudent_limit_end", "werkstudent_limit_max_hours",
)


def date_iso(day: str, month: str, year: str) -> str | None:
    """ISO-Datum aus den drei Combobox-Werten, `None` bei Unsinn/31.02."""
    try:
        return datetime.date(int(year), int(month), int(day)).isoformat()
    except (TypeError, ValueError):
        return None


def _wsl_date(raw: Mapping[str, Any], which: str) -> str | None:
    prefix = f"werkstudent_limit_{which}"
    return date_iso(raw[f"{prefix}.day"], raw[f"{prefix}.month"],
                    raw[f"{prefix}.year"])


def validate_work(raw: Mapping[str, Any]) -> tuple[str, str] | None:
    if mode_code(raw["default_times_mode"]) == MODE_GENERAL:
        ok, msg = validate_entry(raw["default_start_all"], raw["default_end_all"])
        if not ok:
            return t("regeln.arbeit_zeit_titel"), msg
    else:
        for key, label in zip(WEEKDAY_KEYS, short_day_names(), strict=True):
            ok, msg = validate_entry(raw[f"default_start_{key}"],
                                     raw[f"default_end_{key}"])
            if not ok:
                return t("regeln.arbeit_zeit_titel"), f"{label}: {msg}"
    # Der Zeitraum zählt nur, wenn das Limit an ist — wie bisher.
    if raw["werkstudent_limit_enabled"]:
        start, end = _wsl_date(raw, "start"), _wsl_date(raw, "end")
        if start is None or end is None:
            return (t("regeln.limit_zeitraum_titel"),
                    t("regeln.datum_waehlen"))
        ok, msg = validate_period(start, end)
        if not ok:
            return t("regeln.limit_zeitraum_titel"), msg
    return None


def region_code_for_label(country: str, label: str) -> str:
    """Anzeigename → Regionscode des Landes; Unbekanntes und „keine Region“
    → "". Nur für die Auswahl im Dialog: der Code wird aus `region_choices`
    abgeleitet, nie aus übersetztem Text geparst."""
    return next((code for code, lbl in region_choices(country)
                 if lbl == label), "")


def country_code_for_label(label: str) -> str:
    """Länder-Anzeigename → Code; Unbekanntes → "DE" (der Default)."""
    return next((code for code, lbl in country_choices() if lbl == label), "DE")


def work_updates(raw: Mapping[str, Any],
                 old: Mapping[str, Any]) -> dict[str, Any]:
    """Settings-Werte des Arbeitszeit-Tabs. `old` trägt die bisherigen
    `WSL_KEYS`-Werte: ein nicht lesbares Wochenlimit oder Datum behält den
    gespeicherten Wert, statt zu werfen."""
    try:
        max_hours = float(raw["werkstudent_limit_max_hours"])
    except (TypeError, ValueError):
        max_hours = old["werkstudent_limit_max_hours"]
    country = country_code_for_label(raw["country"])
    region = region_code_for_label(country, raw["region"])
    updates: dict[str, Any] = {
        "default_pause": int(raw["default_pause"]),
        "pause_warning_enabled": bool(raw["pause_warning_enabled"]),
        "reservations_enabled": bool(raw["reservations_enabled"]),
        "hourly_rate": parse_hourly_rate(raw["hourly_rate"]),
        "werkstudent_limit_enabled": bool(raw["werkstudent_limit_enabled"]),
        "werkstudent_limit_start": (_wsl_date(raw, "start")
                                    or old["werkstudent_limit_start"]),
        "werkstudent_limit_end": (_wsl_date(raw, "end")
                                  or old["werkstudent_limit_end"]),
        "werkstudent_limit_max_hours": max_hours,
        "workweek_only": bool(raw["workweek_only"]),
        "country": country,
        "region": region,
        # Für DE bleibt `state` aktuell, damit ein Downgrade dieselbe Region
        # zeigt; andere Länder haben dort keine Entsprechung.
        "state": region if country == "DE" else "",
        "show_weekend": bool(raw["show_weekend"]),
    }
    mode = mode_code(raw["default_times_mode"])
    updates["default_times_mode"] = mode
    if mode == MODE_GENERAL:
        # Ein Paar für alle sieben Tage — auch für die bei „Nur Werktage"
        # ausgeblendeten, damit kein Tag einen alten Wert behält.
        updates.update(spread(raw["default_start_all"], raw["default_end_all"]))
    else:
        # Alle sieben Tage, auch Sa/So bei „Nur Werktage": die Werte bleiben
        # so erhalten und sind sofort wieder da, wenn der Modus zurückgenommen
        # wird.
        for key in WEEKDAY_KEYS:
            updates[f"default_start_{key}"] = raw[f"default_start_{key}"]
            updates[f"default_end_{key}"] = raw[f"default_end_{key}"]
    return updates


def wsl_snapshot(values: Mapping[str, Any]) -> dict[str, Any]:
    """Die Form, die `weekly_limit.period_scan_needed` vergleicht — aus
    Settings-Werten oder aus `work_updates`."""
    return {
        "enabled": values["werkstudent_limit_enabled"],
        "start": values["werkstudent_limit_start"],
        "end": values["werkstudent_limit_end"],
        "max_hours": values["werkstudent_limit_max_hours"],
    }


# ---- Versand -------------------------------------------------------------

MAIL_KEYS = ("recipient", "name", "mail_subject", "mail_greeting",
             "mail_content", "mail_closing")
SENDING_KEYS = MAIL_KEYS + ("send_period_from_last_reminder",
                            "send_period_anchor_monthly")


def sending_updates(raw: Mapping[str, Any]) -> dict[str, Any]:
    updates: dict[str, Any] = {key: raw[key] for key in MAIL_KEYS}
    updates["send_period_from_last_reminder"] = bool(
        raw["send_period_from_last_reminder"])
    updates["send_period_anchor_monthly"] = bool(raw["send_period_anchor_monthly"])
    return updates


# ---- Google --------------------------------------------------------------

def google_updates(raw: Mapping[str, Any]) -> dict[str, Any]:
    # Am Rand saniert (Länge, Steuerzeichen): der Name reist über die
    # Sync-Registry zu anderen Geräten und landet dort in einem Label.
    return {"device_name": sanitize_device_name(raw["device_name"])}


def calendar_update(cal_map: Mapping[str, str], selected: str,
                    stored_id: str | None, gcal_enabled: bool) -> str | None:
    """Neue Kalender-ID, falls sie sich ändert, sonst `None`.

    Nur mit geladener Liste (`cal_map` gefüllt): davor steht in der Combobox
    die gespeicherte ID statt eines Klarnamens, und ein vorschnelles
    Speichern schriebe über `resolve_calendar_id` "primary" fest."""
    if not gcal_enabled or not cal_map:
        return None
    new_id = resolve_calendar_id(dict(cal_map), selected, stored_id or "")
    return new_id if new_id != stored_id else None


# ---- Erinnerungen --------------------------------------------------------

REMINDER_KEYS = (
    "reminders_enabled", "reminder_minutes_before",
    "send_reminder_enabled", "send_reminder_day", "send_reminder_time",
    "send_reminder_weekend_shift", "send_reminder_shift_holidays",
    "send_reminder_reservations_enabled", "send_reminder_default_minutes",
    "mobile_push_enabled", "mobile_push_reservation", "mobile_push_send",
    "mobile_push_suppress_toast",
)


def shift_moves(label: str) -> bool:
    """Verschiebt die gewählte Wochenend-Regel den Termin überhaupt? Nur
    dann hat „auch Feiertage" eine Wirkung (und ist bedienbar)."""
    return shift_for_label(label) != "none"


def validate_reminders(raw: Mapping[str, Any]) -> tuple[str, str] | None:
    if parse_reminder_minutes(raw["reminder_minutes_before"]) is None:
        return (t("regeln.erinnerung_zeit_titel"),
                t("regeln.erinnerung_zeit_text"))
    return None


def reminders_updates(raw: Mapping[str, Any]) -> dict[str, Any]:
    """Settings-Werte des Erinnerungen-Tabs. Setzt `validate_reminders`
    voraus. Ausgegraute Optionen werden mitgeschrieben — ihr Wert bleibt
    erhalten, bis der Schalter wieder an ist."""
    minutes = parse_reminder_minutes(raw["reminder_minutes_before"])
    if minutes is None:
        raise ValueError("reminders_updates ohne vorheriges validate_reminders")
    return {
        "reminders_enabled": bool(raw["reminders_enabled"]),
        "reminder_minutes_before": minutes,
        "send_reminder_enabled": bool(raw["send_reminder_enabled"]),
        "send_reminder_day": int(raw["send_reminder_day"]),
        "send_reminder_time": raw["send_reminder_time"],
        "send_reminder_weekend_shift": shift_for_label(
            raw["send_reminder_weekend_shift"]),
        "send_reminder_shift_holidays": bool(raw["send_reminder_shift_holidays"]),
        "send_reminder_reservations_enabled": bool(
            raw["send_reminder_reservations_enabled"]),
        "send_reminder_default_minutes": int(raw["send_reminder_default_minutes"]),
        "mobile_push_enabled": bool(raw["mobile_push_enabled"]),
        "mobile_push_reservation": bool(raw["mobile_push_reservation"]),
        "mobile_push_send": bool(raw["mobile_push_send"]),
        "mobile_push_suppress_toast": bool(raw["mobile_push_suppress_toast"]),
    }


def phone_hint(device_count: int) -> str:
    """Die Zeile unter dem Handy-Schalter im Reiter „Erinnerungen“ (#331): wie viele Handys
    gekoppelt sind und wo die Erlaubnis für Benachrichtigungen erteilt wird. Die gilt je Gerät
    und Browser und lässt sich vom Desktop aus nicht setzen."""
    where = t("regeln.handy_wo")
    if device_count <= 0:
        return t("regeln.handy_keins", wo=where)
    if device_count == 1:
        return t("regeln.handy_anzahl.eins", anzahl=device_count, wo=where)
    return t("regeln.handy_anzahl.viele", anzahl=device_count, wo=where)


# ---- App -----------------------------------------------------------------

def slider_percent(value: float) -> int:
    """Skalierungs-Regler auf 5er-Schritte (ttk.Scale kennt kein
    `resolution`)."""
    return round(value / 5) * 5


def app_updates(raw: Mapping[str, Any]) -> dict[str, Any]:
    """Settings-Werte des App-Tabs."""
    return {
        "autostart": bool(raw["autostart"]),
        "always_on_top": bool(raw["always_on_top"]),
        "minimize_to_tray": bool(raw["minimize_to_tray"]),
        "ui_scale": clamp_ui_scale(slider_percent(float(raw["ui_scale"])) / 100),
        "auto_scale_restart": bool(raw.get("auto_scale_restart", False)),
    }


# ---- Updates -------------------------------------------------------------

def update_tab_updates(raw: Mapping[str, Any]) -> dict[str, Any]:
    updates: dict[str, Any] = {
        "update_check_frequency": frequency_for_label(raw["update_check_frequency"]),
        "prerelease_updates_enabled": bool(raw["prerelease_updates_enabled"]),
    }
    # Fehlt, wo die Plattform kein Selbst-Update kann (der Tab baut den
    # Schalter dann gar nicht) — der gespeicherte Wert bleibt unangetastet.
    if "auto_update_enabled" in raw:
        updates["auto_update_enabled"] = bool(raw["auto_update_enabled"])
    return updates


def last_check_text(last_check: str | None) -> str:
    """Anzeige der letzten erfolgreichen Update-Prüfung (`last_update_check_at`,
    nur ein Datum): „TT.MM.JJJJ" bzw. „noch nie"."""
    return format_iso_date(last_check, fallback=t("regeln.updates_noch_nie"))


# Symbol je Statusart. Bewusst nur Zeichen aus Pfeile/Dingbats/Verschiedene
# Symbole (U+2190–27BF): Segoe UI Symbol, DejaVu Sans und die macOS-
# Fallbackfonts haben sie; das Symbol trägt die Aussage auch ohne Farbe.
UPDATE_STATUS_SYMBOLS = {
    "current": "✓",
    "ready": "✓",
    "available": "↑",
    "failed": "⚠",
}


def update_status_kind(release: Any, show_download: bool) -> str:
    """Art des Prüfergebnisses für die Statuszeile: `failed` (kein Release),
    `available` (neuere Version) oder `current`."""
    if release is None:
        return "failed"
    return "available" if show_download else "current"


def update_status_text(kind: str, text: str) -> str:
    """Statustext mit Symbol; neutrale Texte (`muted`: Prüfe…, Fortschritt)
    bleiben ohne."""
    symbol = UPDATE_STATUS_SYMBOLS.get(kind)
    return f"{symbol} {text}" if symbol else text


@dataclass(frozen=True)
class ButtonView:
    primary: bool    # Hauptaktion (rot) oder Nebenaktion
    enabled: bool    # sonst gedämpft


def update_button_views(*, available: bool, checking: bool, updating: bool,
                        download_busy: bool) -> tuple[ButtonView, ButtonView]:
    """Rolle und Zustand von (Prüfen-, Installieren-/Download-)Knopf.

    Die Hauptaktion folgt dem Zustand: ist ein Update da, ist es das
    Installieren, sonst das Prüfen. Gedämpft ist der Prüfen-Knopf während
    eines Checks oder Updates, der andere während Update oder stillem
    Download. (Die Knöpfe sperren nur optisch — die Callbacks tragen ihre
    eigenen Guards.)"""
    check = ButtonView(primary=not available,
                       enabled=not (checking or updating))
    install = ButtonView(primary=available,
                         enabled=not (updating or download_busy))
    return check, install


def last_check_line(last_check: str | None) -> str:
    """Metazeile unter den Knöpfen: „Zuletzt geprüft: 05.11.2026"."""
    return t("regeln.updates_zuletzt", datum=last_check_text(last_check))


def changelog_default_heading() -> str:
    """Überschrift der Changelog-Box ohne Versionsbezug."""
    return t("regeln.changelog_titel")


# Höhe der Changelog-Box in Zeilen: folgt dem Inhalt, aber nie kürzer als
# MIN (eine fast leere Box wirkt kaputt) und nie höher als MAX (darüber
# scrollt sie).
CHANGELOG_MIN_LINES = 4
CHANGELOG_MAX_LINES = 12


def changelog_heading(result: Mapping[str, Any], installed_id: str) -> str:
    """Überschrift der Changelog-Box: sagt, zu welcher Version der Text
    gehört. Pre-Releases tragen generierte Notes und behaupten deshalb keinen
    „Changelog"."""
    if result["changelog_notes"] is not None:
        return t("regeln.changelog_enthalten")
    release = result.get("latest_release")
    if release is not None and result["changelog_version"]:
        return t("regeln.changelog_neu_in", version=release.release_id)
    if result["changelog_version"]:
        return t("regeln.changelog_aenderungen_in", version=result["changelog_version"])
    return changelog_default_heading()


def changelog_box_lines(content_lines: int) -> int:
    """Sichtbare Zeilen der Changelog-Box zu `content_lines` Anzeigezeilen."""
    return max(CHANGELOG_MIN_LINES, min(CHANGELOG_MAX_LINES, content_lines))


def changelog_expected(result: Mapping[str, Any]) -> bool:
    """Ob zu einem Prüfergebnis (`updater.resolve_check_result`) überhaupt ein
    Changelog angezeigt werden kann. Nach einem gescheiterten Abruf gibt es
    weder eine Version zum Nachladen noch Release-Notes — die Box bliebe leer
    und wird dann ausgeblendet."""
    return bool(result["changelog_version"] or result["changelog_notes"])


# ---- API (#92) --------------------------------------------------------------

# Bereich, aus dem `single_instance` den Port je Installationsordner ableitet
# (20000–31999); `tests/test_tab_rules.py` hält ihn gegen Drift fest.
_SINGLE_INSTANCE_FROM = 20000
_SINGLE_INSTANCE_TO = 31999
# Ab hier vergeben Betriebssysteme kurzlebig Ports an andere Programme (Linux
# 32768+, Windows 49152+).
_EPHEMERAL_FROM = 32768

_API_ERRORS = {
    REASON_INVALID_PORT: N_("regeln.api_port_ungueltig"),
    REASON_PORT_IN_USE: N_("regeln.api_port_belegt"),
    REASON_TOKEN_UNAVAILABLE: N_("regeln.api_token_unlesbar"),
}


def validate_api(raw: Mapping[str, Any]) -> tuple[str, str] | None:
    """Der Port muss gültig sein — auch bei ausgeschalteter API, damit ein
    kaputter Wert nicht erst beim späteren Einschalten auffällt."""
    if parse_port(raw["api_port"]) is None:
        return (t("regeln.port_titel"),
                t("regeln.port_bereich", min=MIN_PORT, max=MAX_PORT))
    return None


def api_updates(raw: Mapping[str, Any]) -> dict[str, Any]:
    """Settings-Werte des API-Tabs. Tolerant wie die anderen Tabs: ein
    ungültiger Port fällt auf den Standard (`validate_api` fängt ihn vorher)."""
    return {
        "api_enabled": bool(raw["api_enabled"]),
        "api_port": parse_port(raw["api_port"]) or DEFAULT_PORT,
    }


def port_hint(raw_port: Any) -> str:
    """Hinweis zum eingegebenen Port, leer wenn es nichts zu sagen gibt."""
    port = parse_port(raw_port)
    if port is None:
        return ""
    if _SINGLE_INSTANCE_FROM <= port <= _SINGLE_INSTANCE_TO:
        return t("regeln.port_hinweis_mehrfachstart")
    if port >= _EPHEMERAL_FROM:
        return t("regeln.port_hinweis_ephemer", ab=_EPHEMERAL_FROM)
    return ""


def status_view(status: ApiStatus) -> tuple[str, str]:
    """(Text, Art) für die Statuszeile; Art ist `ok`, `muted` oder `error`."""
    if status.state == STATE_RUNNING:
        return t("regeln.api_laeuft", port=status.port), "ok"
    if status.state == STATE_STARTING:
        return t("regeln.startet"), "muted"
    if status.state == STATE_ERROR:
        text = t(_API_ERRORS.get(status.reason, N_("regeln.start_fehlgeschlagen")),
                 port=status.port)
        return text, "error"
    return t("regeln.aus"), "muted"


def curl_example(raw_port: Any) -> str:
    """Beispielaufruf für die Hinweiszeile; mit Platzhalter statt echtem Token."""
    port = parse_port(raw_port) or DEFAULT_PORT
    return t("regeln.api_curl", port=port)


# Kurzfassung der Routen für den API-Tab: (Pfad, was dahinter liegt). Die
# vollständige Tabelle samt Bodies steht in der README („Lokale HTTP-API“); ein
# Test hält beide zusammen. Platzhalter folgen der Sprache (JJJJ-MM-TT, JJJJ-Www, …),
# die Pfade ohne Platzhalter sind technisch und bleiben gleich.
def api_routes() -> tuple[tuple[str, str], ...]:
    return (
        ("GET /v1/status", t("regeln.api_route_status")),
        (t("regeln.api_pfad_eintraege"), t("regeln.api_route_eintraege")),
        (t("regeln.api_pfad_reservierungen"), t("regeln.api_route_reservierungen")),
        (t("regeln.api_pfad_urlaub"), t("regeln.api_route_urlaub")),
        (t("regeln.api_pfad_woche"), t("regeln.api_route_woche")),
        (t("regeln.api_pfad_monat"), t("regeln.api_route_monat")),
        ("GET /v1/categories", t("regeln.api_route_kategorien")),
        (t("regeln.api_pfad_feiertage"), t("regeln.api_route_feiertage")),
    )


def api_auth_hint() -> str:
    return t("regeln.api_auth_hinweis")



TOKEN_MASK = "•" * 24


def token_missing() -> str:
    """Statuszeile der Token-Zeile, solange kein lesbares Token existiert."""
    return t("regeln.token_fehlt")


def token_buttons_enabled(*, api_on: bool, token_known: bool, busy: bool) -> bool:
    """Ob „Token kopieren“ und „Neu erzeugen“ bedienbar sind: nur bei
    eingeschalteter API (Häkchen im Formular), vorhandenem Token und ohne
    laufende Rotation. Eine Stelle für beide Knöpfe — `set_secondary_button_
    enabled` dämpft nur die Optik, der Callback bleibt gebunden."""
    return api_on and token_known and not busy


def token_label_view(*, token_known: bool, notice: str | None) -> tuple[str, str]:
    """(Text, Art) der Token-Zeile; Art ist `ok` oder `muted`. Eine Rückmeldung
    (`notice`) geht vor der Maske: das Nachlesen des Tokens nach „Neu erzeugen“
    kommt Millisekunden nach der Erfolgsmeldung zurück und würde sie sonst
    überschreiben."""
    if notice:
        return notice, "ok"
    return (TOKEN_MASK if token_known else token_missing()), "muted"


# --- Mobil-Tab (#221) ---------------------------------------------------------------------------

def auto_address() -> str:
    """Auswahl „Automatisch“ der Adress-Combobox (gespeichert wird die leere Adresse)."""
    return t("regeln.adresse_automatisch")


def first_enable_notice() -> str:
    """Rückfrage beim ersten Einschalten der Handy-Erfassung."""
    return t("regeln.mobil_erster_hinweis")



_MOBILE_ERRORS = {
    MOBILE_INVALID_PORT: N_("regeln.mobil_port_ungueltig"),
    REASON_NO_ADDRESS: N_("regeln.mobil_keine_adresse"),
    REASON_ADDRESS_GONE: N_("regeln.mobil_adresse_weg"),
    MOBILE_PORT_IN_USE: N_("regeln.mobil_port_belegt"),
}


def address_options(candidates: list[str]) -> list[str]:
    """Die Auswahl der Adress-Combobox: „Automatisch“ (der Vorschlag der aktiven
    Verbindung) und die gefundenen LAN-Adressen."""
    return [auto_address(), *candidates]


def address_from_choice(choice: str) -> str:
    """Der Settings-Wert zu einer Auswahl: „Automatisch“ ist die leere Adresse."""
    return "" if choice == auto_address() else choice


def address_to_choice(address: str) -> str:
    """Die Auswahl zu einem Settings-Wert. Ein Müllwert (handbearbeitete `settings.json`,
    z. B. `123`) zeigt „Automatisch“, statt unverändert in der readonly-Combobox zu stehen
    und `validate_mobile` auch bei ausgeschaltetem Schalter zu stören. Eine gültige, aber
    gerade nicht vorhandene LAN-Adresse bleibt stehen (der Status meldet `address_gone`)."""
    return address if address and is_lan_address(address) else auto_address()


def window_cap_options() -> list[str]:
    """Die Auswahl der Combobox „Verlauf bis zu“ (Obergrenze des Lesefensters, #250)."""
    return [t("regeln.mobil_tage", tage=days) for days in WINDOW_CAP_CHOICES]


def window_cap_to_choice(days: object) -> str:
    return t("regeln.mobil_tage", tage=window_cap(days))


def window_cap_from_choice(choice: object) -> int:
    """Die Obergrenze zu einer Auswahl; alles Unlesbare ist das Maximum. Die Zahl
    steht in jeder Sprache vorn (`regeln.mobil_tage`)."""
    head = str(choice or "").split(" ", 1)[0]
    return window_cap(int(head)) if head.isdigit() else window_cap(None)


def validate_mobile(raw: Mapping[str, Any]) -> tuple[str, str] | None:
    """Port und Adresse müssen gültig sein — auch bei ausgeschaltetem Schalter, damit ein
    kaputter Wert nicht erst beim späteren Einschalten auffällt."""
    if parse_port(raw["mobile_port"]) is None:
        return (t("regeln.port_titel"),
                t("regeln.port_bereich", min=MIN_PORT, max=MAX_PORT))
    address = address_from_choice(str(raw["mobile_address"]))
    if address and not is_lan_address(address):
        return (t("regeln.adresse_titel"), t("regeln.adresse_text"))
    return None


def mobile_updates(raw: Mapping[str, Any]) -> dict[str, Any]:
    """Settings-Werte des Mobil-Tabs. Tolerant wie die anderen Tabs: ein ungültiger Port
    fällt auf den Standard (`validate_mobile` fängt ihn vorher)."""
    return {
        "mobile_enabled": bool(raw["mobile_enabled"]),
        "mobile_port": parse_port(raw["mobile_port"]) or MOBILE_DEFAULT_PORT,
        "mobile_address": address_from_choice(str(raw["mobile_address"])),
        "mobile_window_max_days": window_cap_from_choice(raw["mobile_window_max_days"]),
    }


def mobile_status_view(status: MobileStatus) -> tuple[str, str]:
    """(Text, Art) für die Statuszeile; Art ist `ok`, `muted` oder `error`."""
    if status.state == MOBILE_RUNNING:
        return t("regeln.mobil_laeuft", adresse=status.address, port=status.port), "ok"
    if status.state == MOBILE_STARTING:
        return t("regeln.startet"), "muted"
    if status.state == MOBILE_ERROR:
        text = t(_MOBILE_ERRORS.get(status.reason, N_("regeln.start_fehlgeschlagen")),
                 address=status.address, port=status.port)
        return text, "error"
    return t("regeln.aus"), "muted"


def is_device_unpaired(record: Mapping[str, Any]) -> bool:
    """Das Handy hat sich selbst getrennt (`POST /v1/unpair`, #499)."""
    return record.get("revoked_by") == "device"


def visible_devices(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Die Geräte, die der Tab zeigt: ohne die widerrufenen. Deren Datensatz bleibt im Speicher
    (die Antwort an das Handy lautet `token_revoked`, und das Koppel-Fenster erkennt an ihm eine
    Neukopplung), in der Liste hat er aber nichts mehr verloren. Ausnahme: ein vom Handy getrenntes
    Gerät bleibt sichtbar, bis der Nutzer es entfernt — sonst ginge die Meldung verloren, wenn
    kein Toast zu sehen war (macOS ohne Tray)."""
    return [record for record in records
            if not record.get("revoked") or is_device_unpaired(record)]


def has_revocable(records: list[dict[str, Any]]) -> bool:
    """Gibt es ein Gerät, das „Alle widerrufen“ noch erreicht? Vom Handy getrennte stehen nur noch in der
    Liste, bis sie entfernt werden; widerrufen ist an ihnen nichts mehr."""
    return any(not is_device_unpaired(record) for record in records)


def revoke_button_label(record: Mapping[str, Any] | None) -> str:
    """Beschriftung des Knopfes unter der Liste: ein getrenntes Gerät gibt es nur noch zu entfernen."""
    if record is not None and is_device_unpaired(record):
        return t("regeln.knopf_entfernen")
    return t("regeln.knopf_widerrufen")


# Zustände der Relay-Box (`relay_link.STATE_*`, dazu `relay_service.STATE_OFF`) als Text. Die
# Schlüssel sind Literale: dieses Modul darf `relay_link` (und damit die WebSocket-Bibliothek)
# nicht importieren; ein Test hält sie gegen die Konstanten.
_RELAY_STATE_TEXTS = {
    "connecting": N_("regeln.relay_verbindet"),
    "connected": N_("regeln.relay_verbunden"),
    "backoff": N_("regeln.relay_gestoert"),
    "replaced": N_("regeln.relay_verdraengt"),
    "stopped": N_("regeln.relay_angehalten"),
    "off": N_("regeln.relay_getrennt"),
}


def pair_intro_lan() -> str:
    """Einleitung des Koppel-Dialogs im LAN-Modus."""
    return t("regeln.koppeln_einleitung_lan")


# Die Kamera-App funktioniert auf einem aktuellen iPhone, je nach iOS-Version öffnet sie den Link aber im
# Browser; dessen Speicher gehört nicht zur installierten Web-App. Der sichere Weg ist der Scan in der Web-App.
def pair_intro_relay() -> str:
    """Einleitung des Koppel-Dialogs im Relay-Modus."""
    return t("regeln.koppeln_einleitung_relay")


def relay_pair_hint() -> str:
    return t("regeln.relay_hinweis")


def relay_pair_refused_text() -> str:
    return t("regeln.relay_abgelehnt")


def relay_pair_error_text() -> str:
    return t("regeln.relay_fehler")



@dataclass(frozen=True)
class RelayOpenView:
    """Was der Koppel-Dialog mit dem Ergebnis von `open_pairing` tut: `show` zeichnet den QR-Code,
    `message` ist der Text bei Ablehnung oder Fehler, `close_codes` sind die Sitzungen, die er im
    Worker schließt."""
    show: bool
    message: str | None
    close_codes: tuple[str, ...]


def relay_open_view(*, alive: bool, code: str | None, failed: bool,
                    own_code: str | None) -> RelayOpenView:
    """Entscheidet über das Ergebnis von `RelayService.open_pairing` (UI-Thread). `code` ist der
    Code der neuen Sitzung (`None`: abgelehnt oder `failed`), `own_code` der der bisherigen Sitzung
    dieses Dialogs. Geschlossen wird nur, was dieser Dialog selbst geöffnet hat: eine
    Ablehnung lässt eine alte Sitzung sonst neben dem Ablehnungstext weiterlaufen (der QR-Code ist
    weg, das Handy könnte ihn noch einlösen), und ein Dialog, der inzwischen zu ist, räumt die
    gerade geöffnete Sitzung ab."""
    if not alive:
        return RelayOpenView(False, None, (code,) if code else ())
    old = (own_code,) if own_code else ()
    if code is not None and not failed:
        return RelayOpenView(True, None, ())
    return RelayOpenView(False, relay_pair_error_text() if failed else relay_pair_refused_text(), old)


def autostart_path_hint(system: str, path: str) -> str | None:
    """Zeile unter dem Autostart-Schalter: wo der Eintrag liegt bzw. angelegt wird. Nur Linux: dort
    hängt der Ort an `XDG_CONFIG_HOME`; unter Windows ist es ein Registry-Wert, unter macOS eine
    feste Plist."""
    return t("regeln.autostart_eintrag", pfad=path) if system == "Linux" else None


def relay_state_text(state: str) -> str:
    """Kurztext zum Zustand der Relay-Box eines Geräts; Unbekanntes bekommt einen Ersatztext."""
    return t(_RELAY_STATE_TEXTS.get(state, N_("regeln.relay_unbekannt")))


def relay_pair_enabled(*, saved_enabled: bool, has_relay: bool, busy: bool) -> bool:
    """Ob „Über Relay koppeln“ greift: der gespeicherte Stand zählt (der Dienst liest die
    Settings), nicht das ungespeicherte Formular, und der LAN-Status spielt keine Rolle."""
    return saved_enabled and has_relay and not busy


def device_row_text(record: Mapping[str, Any], now: str, relay_state: str | None = None) -> str:
    """Eine Zeile der Geräteliste: Name, zuletzt gesehen, gültig bis; abgelaufen ist markiert.
    Widerrufene Geräte kommen hier nicht an (`visible_devices`). `relay_state` (nur Geräte mit
    Box) hängt den Zustand der Relay-Verbindung an."""
    name = str(record.get("name") or record.get("id") or "?")
    if is_device_unpaired(record):
        return t("regeln.zeile_getrennt", name=name,
                 datum=format_iso_datetime(record.get("revoked_at")))
    mark = ""
    if str(record.get("expires_at") or "9999") <= now:
        mark = t("regeln.zeile_abgelaufen")
    seen = format_iso_datetime(record.get("last_seen"))
    until = format_iso_date(record.get("expires_at"))
    text = t("regeln.zeile_normal", name=name, marke=mark, zuletzt=seen, bis=until)
    if relay_state is not None:
        text += t("regeln.zeile_relay", zustand=relay_state_text(relay_state))
    return text


def keystore_summary(where: Mapping[str, str]) -> str:
    """Wo die Geräteschlüssel der gekoppelten Handys liegen (#249), für eine Zeile im Tab. Leer,
    solange kein Gerät einen Schlüssel hat. Nur lesen: kein Schlüsselbund-Aufruf im UI-Thread."""
    locations = {location for location in where.values() if location in ("keyring", "file")}
    if not locations:
        return ""
    if locations == {"keyring"}:
        return t("regeln.speicher_schluesselbund")
    if locations == {"file"}:
        return t("regeln.speicher_datei")
    return t("regeln.speicher_gemischt")


def format_countdown(seconds: int) -> str:
    """`299` → `4:59`. Negative Werte zeigen `0:00`."""
    seconds = max(0, int(seconds))
    return f"{seconds // 60}:{seconds % 60:02d}"


@dataclass(frozen=True)
class PairChanges:
    added: list[dict[str, Any]]
    replaced: list[dict[str, Any]]      # vorhandene, nicht widerrufene Geräte mit neuem Token

    @property
    def empty(self) -> bool:
        return not self.added and not self.replaced


def pair_changes(before: list[dict[str, Any]], after: list[dict[str, Any]]) -> PairChanges:
    """Was ein Koppeln am Gerätebestand geändert hat. Neu = unbekannte ID **oder** ein
    widerrufenes Gerät, das neu gekoppelt wurde. `replaced` = ein vorhandenes, nicht
    widerrufenes Gerät wurde neu gekoppelt (jemand hat sich mit seiner `device_id`
    gekoppelt): der Besitzer soll das sehen.

    Neu gekoppelt heißt: der `pair_count` des Datensatzes ist gestiegen — den zählt nur
    `issue_device` hoch. Token-Hashes taugen nicht dafür: jeder Abgleich erneuert das
    Token (ein gewöhnlicher Abgleich darf nie als Ersetzen gelten), und ein Handy synct
    gleich nach dem Koppeln, sodass sich beides in einem Poll vermischt."""
    known = {record["id"]: record for record in before}
    added: list[dict[str, Any]] = []
    replaced: list[dict[str, Any]] = []
    for record in after:
        old = known.get(record["id"])
        if old is None:
            added.append(record)
        elif pair_count(record) != pair_count(old):
            (added if old.get("revoked") else replaced).append(record)
    return PairChanges(added, replaced)


@dataclass(frozen=True)
class PairedNotice:
    title: str
    text: str
    warn: bool          # ein vorhandenes Gerät wurde ersetzt: Warn- statt Info-Dialog


def paired_notice(changes: PairChanges) -> PairedNotice:
    """Die Meldung, die nach dem Koppeln den Koppel-Dialog ablöst. Wurde dabei ein
    vorhandenes, nicht widerrufenes Gerät ersetzt, trägt sie zusätzlich die Warnung."""
    names = ", ".join(d["name"] for d in changes.added + changes.replaced)
    text = t("regeln.gekoppelt_text", namen=names)
    if not changes.replaced:
        return PairedNotice(t("regeln.gekoppelt_titel"), text, False)
    old = ", ".join(d["name"] for d in changes.replaced)
    text += t("regeln.gekoppelt_ersetzt", alt=old)
    return PairedNotice(t("regeln.gekoppelt_titel"), text, True)


def pair_failed_text() -> str:
    return t("regeln.koppeln_fehlgeschlagen")



def pair_poll_view(*, active: bool, seconds_left: int, paired: bool,
                   failed: bool = False) -> tuple[str, str]:
    """Was der Koppel-Dialog bei einem Poll zeigt: `(Zustand, Text)` mit dem Zustand
    `paired`, `failed`, `counting` oder `expired`. Ein Koppeln geht vor: es kann in der letzten
    Sekunde geschehen, wenn der Code schon nicht mehr aktiv ist. `failed` heißt: der Code wurde
    eingelöst, aber das Gerät ließ sich nicht speichern — ohne den Zustand zeigte der Dialog nur
    „abgelaufen“. Solange der Code aktiv ist, läuft der Countdown — auch bei `0:00`
    (`seconds_left` schneidet Sekundenbruchteile ab), sonst bliebe „0:01“ stehen und
    „abgelaufen“ käme nie."""
    if paired:
        return "paired", ""
    if failed:
        return "failed", pair_failed_text()
    if active:
        return "counting", t("regeln.code_gueltig", zeit=format_countdown(seconds_left))
    return "expired", t("regeln.code_abgelaufen")


def pair_poll_keeps_running(state: str) -> bool:
    """Nur ein laufender Countdown braucht den nächsten Poll."""
    return state == "counting"


def dismiss_error_text() -> str:
    return t("regeln.entfernen_fehler")


def revoke_error_text() -> str:
    return t("regeln.widerruf_fehler")



def revoke_prompt(name: str, *, has_box: bool) -> str:
    """Rückfrage vor dem Widerruf eines Geräts. Mit Relay-Box (`has_box`) sagt sie, dass auch die Box am Relay
    gelöscht wird und was das Handy danach zeigt: es bekommt keine Antwort mit `token_revoked` mehr, sondern
    die Meldung der Web-App „Der Desktop hat nicht geantwortet“."""
    text = t("regeln.widerruf_frage", name=name)
    if has_box:
        text += "\n\n" + t("regeln.box_hinweis")
    return text + t("regeln.fortfahren")


def revoke_all_prompt(*, boxes: int) -> str:
    """Rückfrage vor „Alle widerrufen“; `boxes` ist die Zahl der Geräte mit Relay-Box."""
    text = t("regeln.widerruf_alle")
    if boxes == 1:
        text += "\n\n" + t("regeln.box_hinweis")
    elif boxes > 1:
        text += t("regeln.widerruf_alle_boxen", boxen=boxes)
    return text + t("regeln.fortfahren")


_TEST_PUSH_TEXTS = {
    "ok": N_("regeln.test_ok"),
    "no_secret": N_("regeln.test_kein_geheimnis"),
    "no_subscription": N_("regeln.test_kein_abo"),
    "gone": N_("regeln.test_abo_abgelaufen"),
    "too_soon": N_("regeln.test_zu_frueh"),
    "rate_limited": N_("regeln.test_zu_viele"),
    "unknown_route": N_("regeln.test_unbekannte_route"),
    "offline": N_("regeln.test_offline"),
    "push_failed": N_("regeln.test_push_fehler"),
    "unauthorized": N_("regeln.test_nicht_erkannt"),
    "server": N_("regeln.test_server"),
}



_PUSH_CAUSE_TEXTS = {"network": N_("regeln.test_ursache_netz"),
                     "build": N_("regeln.test_ursache_schluessel")}


def test_push_text(kind: str) -> str:
    """Der Text zum Ergebnis von „Testbenachrichtigung“ (`MobileService.send_test`); eine unbekannte
    Art (ein künftiger Relay) wird zu „antwortet nicht“. `push_failed:<Ursache>` nennt, woran es lag
    (Status des Push-Dienstes, `network`, `build`). Dieselben Texte nutzt die Web-App."""
    base, _, cause = kind.partition(":")
    text = t(_TEST_PUSH_TEXTS.get(base if not cause or base == "push_failed" else kind,
                                  N_("regeln.test_server")))
    if base != "push_failed" or not cause:
        return text
    if cause.isascii() and cause.isdigit():
        detail: str | None = t("regeln.test_antwort", status=cause)
    else:
        detail = t(_PUSH_CAUSE_TEXTS[cause]) if cause in _PUSH_CAUSE_TEXTS else None
    return text if detail is None else t("regeln.test_mit_ursache", text=text[:-1], ursache=detail)


def test_push_outcome(action: Callable[[], str]) -> str:
    """Der Worker hinter „Testbenachrichtigung“: liefert die Art, wirft nie. Ohne diese Hülle ruft
    der Runner bei einer Ausnahme `on_done` nie, und der Reiter bliebe gesperrt."""
    try:
        return action()
    except Exception:
        _log.warning("Testbenachrichtigung fehlgeschlagen", exc_info=True)
        return "server"


def revoke_outcome(action: Callable[[], Any]) -> dict[str, Any]:
    """Der Worker hinter „Widerrufen": `{"ok": True, "result": …}` oder
    `{"ok": False, "error": e}` für die erwarteten Schreibfehler (Schreibschutz,
    `OSError`); alles andere ist ein Bug und fliegt durch. Ohne diese Hülle ruft der
    Runner bei einer Ausnahme `on_done` nie, und der Reiter bliebe gesperrt, ohne dass
    der Nutzer erfährt, dass das Gerät noch aktiv ist."""
    try:
        return {"ok": True, "result": action()}
    except (MobileStoreReadOnly, OSError) as exc:
        _log.warning("Widerruf fehlgeschlagen", exc_info=True)
        return {"ok": False, "error": exc}
