import json
from unittest.mock import patch

import pytest
from src.settings import Settings, WEEKDAY_KEYS

@pytest.fixture
def tmp_settings(tmp_path):
    return Settings(str(tmp_path / "settings.json"))

def test_defaults(tmp_settings):
    assert tmp_settings.get("recipient") == ""
    assert tmp_settings.get("default_pause") == 30

def test_save_and_load(tmp_settings):
    tmp_settings.set("recipient", "test@example.com")
    assert tmp_settings.get("recipient") == "test@example.com"

def test_set_default_pause(tmp_settings):
    tmp_settings.set("default_pause", 45)
    assert tmp_settings.get("default_pause") == 45

def test_persistence(tmp_path):
    path = str(tmp_path / "settings.json")
    s1 = Settings(path)
    s1.set("recipient", "test@example.com")
    s1.set("default_pause", 15)
    s2 = Settings(path)
    assert s2.get("recipient") == "test@example.com"
    assert s2.get("default_pause") == 15

def test_corrupted_file(tmp_path):
    path = str(tmp_path / "settings.json")
    with open(path, "w") as f:
        f.write("not json{{{")
    s = Settings(path)
    assert s.get("recipient") == ""
    assert s.get("default_pause") == 30

def test_recipient_default(tmp_settings):
    assert tmp_settings.get("recipient") == ""

def test_autostart_default(tmp_settings):
    assert tmp_settings.get("autostart") == False


def test_last_update_check_at_default(tmp_settings):
    assert tmp_settings.get("last_update_check_at") == ""


def test_dismissed_version_default(tmp_settings):
    assert tmp_settings.get("dismissed_version") == ""


def test_set_many_writes_once(tmp_settings):
    """set_many ruft _save_to_disk genau einmal auf."""
    with patch.object(tmp_settings, "_save_to_disk") as mock_save:
        tmp_settings.set_many({"recipient": "a@b.de", "default_pause": 45})
    assert mock_save.call_count == 1


def test_set_many_updates_data(tmp_settings):
    tmp_settings.set_many({"recipient": "a@b.de", "default_pause": 45})
    assert tmp_settings.get("recipient") == "a@b.de"
    assert tmp_settings.get("default_pause") == 45


def test_set_many_empty_is_noop(tmp_settings):
    """Leeres Dict triggert keinen Disk-Write."""
    with patch.object(tmp_settings, "_save_to_disk") as mock_save:
        tmp_settings.set_many({})
    mock_save.assert_not_called()


def test_set_is_wrapper_around_set_many(tmp_settings):
    with patch.object(tmp_settings, "_save_to_disk") as mock_save:
        tmp_settings.set("recipient", "x@y.de")
    assert mock_save.call_count == 1
    assert tmp_settings.get("recipient") == "x@y.de"


def _write_json(tmp_path, payload):
    path = tmp_path / "settings.json"
    with open(path, "w", encoding="utf-8") as f:
        f.write(payload)
    return str(path)


def test_load_casts_string_to_int(tmp_path):
    path = _write_json(tmp_path, json.dumps({"default_pause": "30"}))
    s = Settings(path)
    assert s.get("default_pause") == 30


def test_load_keeps_default_when_int_cast_fails(tmp_path, caplog):
    path = _write_json(tmp_path, json.dumps({"default_pause": "abc"}))
    with caplog.at_level("WARNING"):
        s = Settings(path)
    assert s.get("default_pause") == 30
    assert any("default_pause" in rec.message for rec in caplog.records)


def test_load_bool_strictness_string_value(tmp_path, caplog):
    path = _write_json(tmp_path, json.dumps({"autostart": "true"}))
    with caplog.at_level("WARNING"):
        s = Settings(path)
    assert s.get("autostart") is False
    assert any("autostart" in rec.message for rec in caplog.records)


def test_load_bool_strictness_int_value(tmp_path, caplog):
    path = _write_json(tmp_path, json.dumps({"autostart": 1}))
    with caplog.at_level("WARNING"):
        s = Settings(path)
    assert s.get("autostart") is False


def test_load_int_for_float_default(tmp_path):
    path = _write_json(tmp_path, json.dumps({"hourly_rate": 25}))
    s = Settings(path)
    assert s.get("hourly_rate") == 25.0
    assert isinstance(s.get("hourly_rate"), float)


def test_load_unknown_key_is_ignored(tmp_path):
    path = _write_json(tmp_path, json.dumps({"old_field": "x", "recipient": "a@b.de"}))
    s = Settings(path)
    assert s.get("old_field") is None
    assert s.get("recipient") == "a@b.de"


def test_load_removed_email_key_is_ignored(tmp_path):
    """Der frühere 'email'-Key (in 1.11.2 entfernt) wird stillschweigend verworfen."""
    path = _write_json(tmp_path, json.dumps({"email": "user@example.com"}))
    s = Settings(path)
    assert s.get("email") is None


def test_load_toplevel_not_dict_resets_to_defaults(tmp_path, caplog):
    path = _write_json(tmp_path, json.dumps([1, 2, 3]))
    with caplog.at_level("WARNING"):
        s = Settings(path)
    assert s.get("default_pause") == 30
    assert s.get("recipient") == ""
    assert any("Toplevel" in rec.message or "toplevel" in rec.message for rec in caplog.records)


# --- Per-Wochentag-Defaults (1.10.0) ---


def test_per_weekday_defaults_present(tmp_settings):
    """Frische Settings haben für alle 7 Tage je 08:00 / 16:00."""
    for day in WEEKDAY_KEYS:
        assert tmp_settings.get(f"default_start_{day}") == "08:00"
        assert tmp_settings.get(f"default_end_{day}") == "16:00"


def test_old_default_start_end_no_longer_in_defaults(tmp_settings):
    """Die alten globalen Keys existieren nicht mehr — get liefert None."""
    assert tmp_settings.get("default_start") is None
    assert tmp_settings.get("default_end") is None


def test_migration_legacy_to_per_weekday(tmp_path):
    """Alte default_start/default_end werden auf alle 7 Tage gespiegelt."""
    path = _write_json(tmp_path, json.dumps({
        "default_start": "09:30",
        "default_end": "17:00",
    }))
    s = Settings(path)
    for day in WEEKDAY_KEYS:
        assert s.get(f"default_start_{day}") == "09:30"
        assert s.get(f"default_end_{day}") == "17:00"


def test_migration_partial_legacy_only_start(tmp_path):
    """Nur default_start im JSON: alle 7 default_start_* migriert,
    default_end_* bleibt Default."""
    path = _write_json(tmp_path, json.dumps({"default_start": "07:15"}))
    s = Settings(path)
    for day in WEEKDAY_KEYS:
        assert s.get(f"default_start_{day}") == "07:15"
        assert s.get(f"default_end_{day}") == "16:00"  # Default


def test_migration_partial_legacy_only_end(tmp_path):
    """Symmetrisch: nur default_end im JSON."""
    path = _write_json(tmp_path, json.dumps({"default_end": "18:30"}))
    s = Settings(path)
    for day in WEEKDAY_KEYS:
        assert s.get(f"default_start_{day}") == "08:00"  # Default
        assert s.get(f"default_end_{day}") == "18:30"


def test_migration_per_day_wins_over_legacy(tmp_path):
    """Per-Tag-Keys schlagen das alte Globalfeld."""
    path = _write_json(tmp_path, json.dumps({
        "default_start": "09:00",
        "default_start_mon": "07:00",
    }))
    s = Settings(path)
    assert s.get("default_start_mon") == "07:00"
    for day in ("tue", "wed", "thu", "fri", "sat", "sun"):
        assert s.get(f"default_start_{day}") == "09:00"


def test_migration_drops_legacy_keys_on_save(tmp_path):
    """Nach Migration + irgendeinem set_many sind die alten Keys
    nicht mehr in settings.json."""
    path = _write_json(tmp_path, json.dumps({
        "default_start": "09:30",
        "default_end": "17:00",
    }))
    s = Settings(path)
    s.set("recipient", "trigger@save.de")  # erzwingt Disk-Write
    with open(path, "r", encoding="utf-8") as f:
        on_disk = json.load(f)
    assert "default_start" not in on_disk
    assert "default_end" not in on_disk
    # Per-Tag-Keys sind drin
    assert on_disk["default_start_mon"] == "09:30"
    assert on_disk["default_end_sun"] == "17:00"


def test_migration_ignores_null_legacy(tmp_path):
    """null im JSON wird nicht migriert — Defaults bleiben bestehen."""
    path = _write_json(tmp_path, json.dumps({"default_start": None, "default_end": None}))
    s = Settings(path)
    for day in WEEKDAY_KEYS:
        assert s.get(f"default_start_{day}") == "08:00"
        assert s.get(f"default_end_{day}") == "16:00"


def test_migration_empty_string_legacy_skipped(tmp_path):
    """Leerer String wird nicht migriert."""
    path = _write_json(tmp_path, json.dumps({"default_start": "", "default_end": ""}))
    s = Settings(path)
    for day in WEEKDAY_KEYS:
        assert s.get(f"default_start_{day}") == "08:00"
        assert s.get(f"default_end_{day}") == "16:00"


# --- show_weekend (1.11.1) ---


def test_show_weekend_default_is_true(tmp_settings):
    """Frische Settings haben show_weekend=True (Backward-Compat)."""
    assert tmp_settings.get("show_weekend") is True


def test_show_weekend_persists_false(tmp_path):
    """set(False) persistiert über einen Reload."""
    path = str(tmp_path / "settings.json")
    s1 = Settings(path)
    s1.set("show_weekend", False)
    s2 = Settings(path)
    assert s2.get("show_weekend") is False


def test_show_weekend_string_falls_back_to_default(tmp_path, caplog):
    """JSON mit String 'false' wird von _coerce abgelehnt → Default True."""
    path = _write_json(tmp_path, json.dumps({"show_weekend": "false"}))
    with caplog.at_level("WARNING"):
        s = Settings(path)
    assert s.get("show_weekend") is True
    assert any("show_weekend" in rec.message for rec in caplog.records)


def test_show_weekend_missing_key_uses_default(tmp_path):
    """settings.json ohne show_weekend → Default True (alte Installationen)."""
    path = _write_json(tmp_path, json.dumps({"recipient": "a@b.de"}))
    s = Settings(path)
    assert s.get("show_weekend") is True
