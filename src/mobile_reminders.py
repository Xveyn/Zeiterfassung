"""Erinnerungen auf dem Handy (#331), Tk-frei und ohne I/O: der Block `reminders` der
Abgleich-Antwort, das Relay-Geheimnis der Anfrage und die Frage, ob der Desktop-Toast
entfallen darf.

Das Handy plant seinen Push-Zeitplan selbst (`pwa/reminders-plan.js`); der Desktop liefert, was nur
er weiß: ob und wann erinnert wird (Schalter, Minuten) und die Sende-Zeitpunkte (Feiertage,
Verschiebung, markierte Reservierungs-Slots). Der Block steht **immer** in der Antwort, auch
ausgeschaltet — fehlte er dann, bliebe der alte Plan am Relay stehen, und das Handy meldete weiter.
"""
from __future__ import annotations

import datetime
import re
from collections.abc import Collection, Mapping
from typing import Any, Literal

from src.send_reminder import upcoming_send_times
from src.settings import Settings, parse_reminder_minutes

# 32 Zufallsbytes als base64url ohne Auffüllung — die Form, die der Relay als Bearer erwartet.
RELAY_SECRET_RE = re.compile(r"[A-Za-z0-9_-]{43}")
DEFAULT_MINUTES_BEFORE = 15
MAX_MINUTES_BEFORE = 1440


def _reservations_on(settings: Settings) -> bool:
    return bool(settings.get("mobile_push_enabled") and settings.get("reservations_enabled"))


def _minutes_before(settings: Settings) -> int:
    minutes = parse_reminder_minutes(settings.get("reminder_minutes_before"))
    return DEFAULT_MINUTES_BEFORE if minutes is None else minutes


def _marked_slots(raw: Mapping[str, Any] | None) -> list[tuple[datetime.date, str, int]]:
    """`(Datum, Ende, Minuten)` der Slots mit Sende-Erinnerung; Tombstones zählen nicht."""
    out: list[tuple[datetime.date, str, int]] = []
    for date_text, entry in (raw or {}).items():
        if not isinstance(entry, Mapping) or entry.get("deleted"):
            continue
        try:
            date = datetime.date.fromisoformat(date_text)
        except (TypeError, ValueError):
            continue
        for slot in entry.get("slots", []):
            minutes = slot.get("send_reminder_minutes") if isinstance(slot, Mapping) else None
            if isinstance(minutes, bool) or not isinstance(minutes, int) or not 0 <= minutes <= 120:
                continue
            end = slot.get("end")
            if isinstance(end, str):
                out.append((date, end, minutes))
    return out


def build_block(settings: Settings, reservation_store: Any, now: datetime.datetime, *,
                tz: datetime.tzinfo | None = None) -> dict[str, Any]:
    """Der Block `reminders` der Antwort. `now` ist die lokale (naive) Desktop-Zeit."""
    push = bool(settings.get("mobile_push_enabled"))
    reservations_on = bool(settings.get("reservations_enabled"))
    monthly_on = bool(settings.get("send_reminder_enabled"))
    daily_on = bool(settings.get("send_reminder_reservations_enabled")) and reservations_on
    send_on = push and bool(settings.get("mobile_push_send")) and (monthly_on or daily_on)

    at: list[str] = []
    if send_on:
        monthly = ({
            "day": settings.get("send_reminder_day"), "time": settings.get("send_reminder_time"),
            "shift": settings.get("send_reminder_weekend_shift"), "state": settings.get("state") or "",
            "holidays": bool(settings.get("send_reminder_shift_holidays")),
        } if monthly_on else None)
        slots = (_marked_slots(reservation_store.get_all_raw())
                 if daily_on and reservation_store is not None else [])
        at = upcoming_send_times(now, monthly=monthly, daily_slots=slots, tz=tz)
    return {
        "reservation": {
            "enabled": _reservations_on(settings) and bool(settings.get("mobile_push_reservation")),
            "minutes_before": _minutes_before(settings),
        },
        "send": {"enabled": send_on, "at": at},
    }


def parse_push(raw: object) -> str | None:
    """Das Relay-Geheimnis aus dem Teil `push` der Anfrage — Fremddaten. Alles, was nicht genau
    die erwartete Form hat, gilt als nicht gesendet (kein Fehler: ein Handy mit kaputtem Geheimnis
    soll weiter abgleichen können)."""
    if not isinstance(raw, Mapping):
        return None
    secret = raw.get("relay_secret")
    if isinstance(secret, str) and RELAY_SECRET_RE.fullmatch(secret):
        return secret
    return None


def phone_covers(settings: Settings, relay_device_ids: Collection[str],
                 kind: Literal["reservation", "send"]) -> bool:
    """Darf der Desktop-Toast dieser Art entfallen? Nur, wenn das Handy ihn mit Sicherheit
    bekommt: Schalter und „Toast unterdrücken“ an, die Art angehakt (Reservierungen dafür
    eingeschaltet) und mindestens ein gekoppeltes Gerät mit bekanntem Relay-Geheimnis.
    Schlimmstenfalls zwei Meldungen, nie keine."""
    if not (settings.get("mobile_push_enabled") and settings.get("mobile_push_suppress_toast")):
        return False
    if not relay_device_ids:
        return False
    if kind == "reservation":
        return bool(settings.get("mobile_push_reservation") and settings.get("reservations_enabled"))
    return bool(settings.get("mobile_push_send"))
