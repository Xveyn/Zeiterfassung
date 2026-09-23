"""scripts/demo_data.py: Demo-Daten für die App aus dem Repo (Screenshots,
Ausprobieren). Das Wichtigste daran ist, was NICHT passiert: kein Zugriff auf
den Schlüsselbund des Betriebssystems — weder beim Anlegen noch beim
nächsten Start der App (Secret-Umzug)."""

import datetime
import importlib.util
import json
import os
import sys

import pytest

from src import keyring_store, secret_migration, smtp_store, webhook_secrets, webhook_store
from src.reservations import ReservationStore
from src.settings import Settings
from src.storage import Storage
from src.vacations import VacationStore, conflicting_days

_SCRIPT = os.path.join(os.path.dirname(__file__), "..", "scripts", "demo_data.py")
_spec = importlib.util.spec_from_file_location("_demo_data", _SCRIPT)
demo_data = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(demo_data)

TODAY = datetime.date(2026, 9, 23)   # ein Mittwoch


@pytest.fixture
def no_keyring(monkeypatch):
    """Jeder Weg in den Schlüsselbund schlägt laut fehl."""
    def boom(*_a, **_k):
        raise AssertionError("Schlüsselbund angefasst")

    for name in ("put", "fetch", "remove", "get_secret", "set_secret",
                 "delete_secret", "persist_password"):
        monkeypatch.setattr(keyring_store, name, boom)
    # Auch ein direkter `import keyring` irgendwo darunter fiele auf.
    monkeypatch.setitem(sys.modules, "keyring", None)


def test_build_is_deterministic():
    assert demo_data.build_demo(TODAY) == demo_data.build_demo(TODAY)


def test_entries_lie_in_the_past_reservations_in_the_future():
    demo = demo_data.build_demo(TODAY)
    today = TODAY.isoformat()
    assert demo["entries"] and demo["reservations"]
    assert all(d <= today for d in demo["entries"])
    assert all(d >= today for d in demo["reservations"])
    # Die Hero-Ansicht (aktueller Monat) soll schon Einträge zeigen.
    assert any(d.startswith("2026-09") for d in demo["entries"])


def test_today_is_split_between_worked_and_reserved():
    """Motiv des Tages-Dialogs: vormittags erfasst, nachmittags reserviert,
    die Reservierung trägt die Sende-Erinnerung."""
    demo = demo_data.build_demo(TODAY)
    today = TODAY.isoformat()
    (worked,) = demo["entries"][today]
    (reserved,) = demo["reservations"][today]
    assert worked["end"] <= reserved["start"]
    assert reserved.get("send_reminder_minutes")


def test_vacation_is_in_the_current_month_and_collides_with_nothing():
    demo = demo_data.build_demo(TODAY)
    (vac,) = demo["vacations"]
    assert vac["from"].startswith("2026-09")
    blocked = conflicting_days(vac["days"], demo["entries"],
                               demo["reservations"])
    assert blocked == []


def test_categories_used_exist_in_settings():
    demo = demo_data.build_demo(TODAY)
    known = set(demo["settings"]["categories"])
    used = {s["kategorie"] for slots in demo["entries"].values() for s in slots}
    used |= {s["kategorie"] for slots in demo["reservations"].values() for s in slots}
    assert used <= known


def test_smtp_accounts_are_valid_and_keep_the_password_in_the_file():
    accounts = demo_data.build_demo(TODAY)["smtp"]
    assert len(accounts) >= 2
    for account in accounts:
        others = [a for a in accounts if a is not account]
        assert smtp_store.validate_record(account, others) == (True, "")
        # "file": keyring_store.get_secret fragt den Schlüsselbund dann nicht.
        assert account["password_location"] == "file"


def test_webhooks_are_valid_and_carry_no_secret():
    hooks = demo_data.build_demo(TODAY)["webhooks"]
    assert len(hooks) >= 2
    for hook in hooks:
        others = [h for h in hooks if h is not hook]
        assert webhook_store.validate_record(hook, others) == (True, "")
        # Ohne Secret zieht secret_migration beim App-Start nichts um.
        assert hook["auth"] == {"mode": "none"}
        assert not webhook_secrets.plaintext_secret(hook)


def test_only_reserved_example_domains():
    """Keine echten Adressen, auch nicht zufällig: nur RFC-2606-Domains."""
    text = json.dumps(demo_data.build_demo(TODAY), ensure_ascii=False)
    for token in text.replace('"', " ").split():
        if "@" in token or "://" in token:
            assert "example." in token, token


def test_without_calendar_switches_the_calendar_off():
    assert demo_data.build_demo(TODAY)["settings"]["gcal_enabled"] is True
    off = demo_data.build_demo(TODAY, with_calendar=False)["settings"]
    assert off["gcal_enabled"] is False


def test_write_creates_readable_stores_without_touching_the_keyring(
        tmp_path, no_keyring):
    demo = demo_data.build_demo(TODAY)
    written = demo_data.write_demo(str(tmp_path), demo)

    assert sorted(written) == sorted(demo_data.DATA_FILES)
    p = lambda name: str(tmp_path / name)   # noqa: E731
    assert set(Storage(p("zeiterfassung.json")).get_all()) == set(demo["entries"])
    assert set(ReservationStore(p("reservations.json")).get_all()) == set(demo["reservations"])
    assert len(VacationStore(p("vacations.json")).get_all()) == 1
    assert len(smtp_store.SmtpStore(p("smtp.json")).get_all()) == len(demo["smtp"])
    hooks = webhook_store.WebhookStore(p("webhooks.json"))
    assert len(hooks.get_all()) == len(demo["webhooks"])
    assert Settings(p("settings.json")).get("name") == "Max Mustermann"

    # Der nächste App-Start: der Secret-Umzug findet nichts und bleibt dem
    # Schlüsselbund fern (no_keyring würde sonst auslösen).
    report = secret_migration.migrate(p("token.json"), hooks)
    assert report == secret_migration.MigrationReport()


def test_write_refuses_to_overwrite_existing_data(tmp_path, no_keyring):
    (tmp_path / "settings.json").write_text("{}", encoding="utf-8")
    demo = demo_data.build_demo(TODAY)

    with pytest.raises(FileExistsError):
        demo_data.write_demo(str(tmp_path), demo)
    assert (tmp_path / "settings.json").read_text(encoding="utf-8") == "{}"

    demo_data.write_demo(str(tmp_path), demo, force=True)
    assert Settings(str(tmp_path / "settings.json")).get("name") == "Max Mustermann"
