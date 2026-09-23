"""Legt Demo-Daten an, mit denen die App aus dem Repo startet.

Für Screenshots (`docs/screenshots/`) und zum Ausprobieren: Max Mustermann
mit zwei Monaten Arbeitszeit in drei Kategorien, Reservierungen für die
kommenden Tage, einem Urlaub im laufenden Monat, zwei SMTP-Konten und zwei
Webhooks. Alle Daten sind relativ zu heute gebaut, damit die Monatsansicht
beim Start immer gefüllt ist.

    python scripts/demo_data.py                  # in den Datenordner des Repos
    python scripts/demo_data.py --ohne-kalender  # ohne Kalender-Abgleich
    python scripts/demo_data.py --force          # vorhandene Daten ersetzen
    ZEITERFASSUNG_DATA_DIR=/tmp/demo python scripts/demo_data.py

Ziel ist, was `paths.get_base_path()` im Repo-Modus liefert — das
Projekt-Root (alle Dateien dort sind gitignored) bzw. `ZEITERFASSUNG_DATA_DIR`.
Liegen dort schon Daten, bricht das Skript ab; `--force` ersetzt sie.

**Kein Zugriff auf den Schlüsselbund** — weder hier noch beim nächsten
App-Start. Die SMTP-Konten tragen ihr Passwort im Datensatz
(`password_location="file"`, dann fragt `keyring_store.get_secret` den
Schlüsselbund gar nicht), die Webhooks haben keine Authentifizierung (ohne
Secret zieht `secret_migration` beim Start nichts um), und es gibt kein
`token.json`. Was ihn trotzdem anfasst, sind Handgriffe in der App: ein
Demo-Konto oder einen Demo-Webhook **löschen** (räumt den zugehörigen
Eintrag ab) und im SMTP-Dialog ein Passwort **eintippen und speichern**.

**Kalender-Abgleich:** Reservierungen zeigt die App nur mit eingeschaltetem
Abgleich (`App._reservations_active`), deshalb ist er standardmäßig an. Ohne
Google-Anmeldung meldet die App dann nach jedem Speichern einer Reservierung
oder eines Urlaubs „Google-Verbindung abgelaufen" (lokal ist gespeichert),
und der Google-Tab zeigt „Kalenderliste nicht geladen". `--ohne-kalender`
schaltet ihn aus; die Reservierungen liegen trotzdem vor.

Adressen und URLs stammen ausschließlich aus den reservierten
Beispiel-Domains (RFC 2606, `example.com`/`example.org`).
"""

import argparse
import datetime
import os
import sys

# Dieses Skript liegt in scripts/, gehört aber zum Repo-Root: es importiert
# aus `src/`. Ohne den sys.path-Eintrag scheitert schon der Import unten
# (vgl. scripts/release_notes.py). Kein `os.chdir` — der Zielordner kommt
# aus `paths.get_base_path()`.
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from src.holidays_de import get_holidays  # noqa: E402  (nach Bootstrap)
from src.reservations import ReservationStore  # noqa: E402
from src.settings import Settings  # noqa: E402
from src.smtp_store import SmtpStore  # noqa: E402
from src.storage import Storage  # noqa: E402
from src.vacations import VacationStore, expand_days  # noqa: E402
from src.webhook_store import WebhookStore  # noqa: E402

# Alle Dateien, die das Skript schreibt — und damit die, deren Existenz es
# ohne --force als „hier liegen schon Daten" wertet.
DATA_FILES = ("zeiterfassung.json", "reservations.json", "vacations.json",
              "smtp.json", "webhooks.json", "settings.json")

STATE = "BY"
CATEGORIES = ["Büro", "Homeoffice", "Kundentermin"]


def _slot(start, end, pause, kategorie):
    return {"start": start, "end": end, "pause": pause, "kategorie": kategorie}


def _workday_slots(day):
    """Ein wiederkehrender Wochenrhythmus — abwechslungsreich genug, dass
    Kalender und Bericht nach echter Nutzung aussehen."""
    weekday = day.weekday()
    if weekday == 0:   # Montag: Büro
        return [_slot("08:00", "16:30", 30, "Büro")]
    if weekday == 1:   # Dienstag: Homeoffice
        return [_slot("08:30", "17:00", 45, "Homeoffice")]
    if weekday == 3:   # Donnerstag: geteilter Tag
        return [_slot("08:00", "12:00", 0, "Büro"),
                _slot("13:00", "17:15", 0, "Kundentermin")]
    return [_slot("08:00", "16:30", 30, "Büro")]


def _vacation_week(today):
    """Montag bis Freitag der zweiten vollen Woche des laufenden Monats —
    so liegt der Urlaub immer in der Monatsansicht, die die App beim Start
    zeigt."""
    first = today.replace(day=1)
    monday = first + datetime.timedelta(days=(7 - first.weekday()) % 7 + 7)
    return monday, monday + datetime.timedelta(days=4)


def build_demo(today, *, with_calendar=True):
    """Die Demo-Daten als Dicts, relativ zu `today`. Rein — schreibt nichts."""
    vac_from, vac_to = _vacation_week(today)
    vac_days = expand_days(vac_from.isoformat(), vac_to.isoformat(), 480, STATE)
    holidays = set()
    for year in {today.year - 1, today.year, today.year + 1}:
        holidays |= set(get_holidays(STATE, year))

    def free(day):
        return (day.weekday() >= 5 or day in holidays
                or vac_days.get(day.isoformat(), 0) > 0)

    # Ist-Zeit: jeder Werktag vom Ersten des Vormonats bis gestern.
    entries = {}
    start = (today.replace(day=1) - datetime.timedelta(days=1)).replace(day=1)
    day = start
    while day < today:
        if not free(day):
            entries[day.isoformat()] = _workday_slots(day)
        day += datetime.timedelta(days=1)
    # Ein Samstag mit Arbeit — damit „Nur Werktage" etwas auszublenden hat.
    saturday = start + datetime.timedelta(days=(5 - start.weekday()) % 7 + 7)
    entries[saturday.isoformat()] = [_slot("09:00", "13:00", 0, "Büro")]

    # Reservierungen: die nächsten fünf freien Werktage. Die erste trägt die
    # Sende-Erinnerung (send_reminder_minutes), die zweite ist geteilt.
    reservations = {}
    day = today + datetime.timedelta(days=1)
    while len(reservations) < 5:
        if not free(day):
            n = len(reservations)
            if n == 1:
                slots = [
                    {"start": "08:00", "end": "12:00", "kategorie": "Büro"},
                    {"start": "13:00", "end": "17:00", "kategorie": "Kundentermin"},
                ]
            else:
                slots = [{"start": "08:00", "end": "16:30",
                          "kategorie": "Homeoffice" if n % 2 else "Büro"}]
            if n == 0:
                slots[0]["send_reminder_minutes"] = 15
            reservations[day.isoformat()] = slots
        day += datetime.timedelta(days=1)

    vacations = [{"name": "Sommerurlaub", "from": vac_from.isoformat(),
                  "to": vac_to.isoformat(), "days": vac_days}]

    smtp = [
        {"id": "demo-smtp-firma", "name": "Firma", "enabled": True,
         "host": "smtp.example.com", "port": 587, "security": "starttls",
         "username": "max.mustermann", "from_addr": "max.mustermann@example.com",
         "recipient": "buchhaltung@example.com",
         "password_location": "file", "password": "demo"},
        {"id": "demo-smtp-privat", "name": "Privat", "enabled": False,
         "host": "mail.example.org", "port": 465, "security": "ssl",
         "username": "max", "from_addr": "max@example.org",
         "recipient": "steuer@example.org",
         "password_location": "file", "password": "demo"},
    ]

    webhooks = [
        {"id": "demo-webhook-zeitkonto", "name": "Zeitkonto",
         "url": "https://hooks.example.com/zeiterfassung", "enabled": True,
         "payload": {"json": True, "pdf": False}, "auth": {"mode": "none"}},
        {"id": "demo-webhook-archiv", "name": "Archiv",
         "url": "https://archiv.example.org/eingang", "enabled": False,
         "payload": {"json": False, "pdf": True}, "auth": {"mode": "none"}},
    ]

    settings = {
        "name": "Max Mustermann",
        "recipient": "buchhaltung@example.com",
        "sender_email": "max.mustermann@example.com",
        "state": STATE,
        "hourly_rate": 18.5,
        "categories": list(CATEGORIES),
        "category_times": {"Kundentermin": {"start": "09:00", "end": "15:00",
                                            "pause": 30}},
        "default_pause": 30,
        "reminders_enabled": True,
        "send_reminder_enabled": True,
        "send_reminder_day": 28,
        "send_reminder_reservations_enabled": True,
        "device_name": "Demo-Laptop",
        "sync_enabled": False,
        "gcal_enabled": bool(with_calendar),
        "gcal_calendar_id": "primary" if with_calendar else "",
    }

    return {"entries": entries, "reservations": reservations,
            "vacations": vacations, "smtp": smtp, "webhooks": webhooks,
            "settings": settings}


def write_demo(base, demo, *, force=False):
    """Schreibt `demo` über die Stores der App nach `base` — so stimmen
    Format, Validierung und Metadaten mit dem, was die App selbst schreibt.
    Liefert die geschriebenen Dateinamen.

    Liegt eine der `DATA_FILES` schon da, wirft `FileExistsError`, ohne
    etwas anzufassen; `force=True` ersetzt die vorhandenen Dateien."""
    existing = [n for n in DATA_FILES if os.path.exists(os.path.join(base, n))]
    if existing and not force:
        raise FileExistsError(
            f"In {base} liegen schon Daten ({', '.join(existing)}). "
            "--force ersetzt sie.")
    for name in existing:
        os.remove(os.path.join(base, name))
    os.makedirs(base, exist_ok=True)

    def path(name):
        return os.path.join(base, name)

    storage = Storage(path("zeiterfassung.json"), device_id="demo")
    storage.save_many({d: {"slots": slots} for d, slots in demo["entries"].items()})
    reservations = ReservationStore(path("reservations.json"))
    for d, slots in demo["reservations"].items():
        reservations.save(d, slots)
    vacations = VacationStore(path("vacations.json"))
    for vac in demo["vacations"]:
        vacations.save(None, vac["name"], vac["from"], vac["to"], vac["days"])
    smtp = SmtpStore(path("smtp.json"))
    for account in demo["smtp"]:
        smtp.save(account)
    hooks = WebhookStore(path("webhooks.json"))
    for hook in demo["webhooks"]:
        hooks.save(hook)
    Settings(path("settings.json")).set_many(demo["settings"])
    return list(DATA_FILES)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--ohne-kalender", action="store_true",
                        help="Kalender-Abgleich aus (keine Reservierungen sichtbar)")
    parser.add_argument("--force", action="store_true",
                        help="vorhandene Daten im Zielordner ersetzen")
    args = parser.parse_args(argv)

    from src.paths import get_base_path
    base = get_base_path()
    demo = build_demo(datetime.date.today(),
                      with_calendar=not args.ohne_kalender)
    try:
        written = write_demo(base, demo, force=args.force)
    except FileExistsError as e:
        print(e, file=sys.stderr)
        return 1
    print(f"Demo-Daten in {base}:")
    for name in written:
        print(f"  {name}")
    print("Starten mit: python -m src.main")
    return 0


if __name__ == "__main__":
    sys.exit(main())
