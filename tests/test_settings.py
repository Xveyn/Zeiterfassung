import json
from unittest.mock import patch

import pytest
from src.settings import Settings, WEEKDAY_KEYS, SYNCED_SETTING_KEYS

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


def test_corrupt_json_is_quarantined(tmp_path):
    # M4: korruptes settings.json wird nach .corrupt-<stamp> in Quarantäne
    # verschoben (wie die anderen drei Stores), nicht kommentarlos verworfen.
    path = tmp_path / "settings.json"
    path.write_text("not json{{{", encoding="utf-8")

    s = Settings(str(path))

    assert s.get("default_pause") == 30
    quarantined = list(tmp_path.glob("settings.json.corrupt-*"))
    assert len(quarantined) == 1
    assert quarantined[0].read_text(encoding="utf-8") == "not json{{{"
    # Original ist weg → frisches Save legt es sauber neu an.
    assert not path.exists()


def test_non_dict_toplevel_is_quarantined(tmp_path):
    # Gültiges JSON, aber falsches Toplevel (Liste) ist ebenso korrupt.
    path = tmp_path / "settings.json"
    path.write_text("[1, 2, 3]", encoding="utf-8")

    s = Settings(str(path))

    assert s.get("recipient") == ""
    quarantined = list(tmp_path.glob("settings.json.corrupt-*"))
    assert len(quarantined) == 1
    assert quarantined[0].read_text(encoding="utf-8") == "[1, 2, 3]"


def test_quarantine_rename_failure_falls_back_to_defaults(tmp_path):
    # Schlägt der Quarantäne-Rename fehl (z.B. Windows-Filelock), darf der
    # Boot nicht crashen — Defaults greifen, die Datei bleibt liegen.
    path = tmp_path / "settings.json"
    path.write_text("not json{{{", encoding="utf-8")

    with patch("src.settings.os.replace", side_effect=OSError("locked")):
        s = Settings(str(path))

    assert s.get("default_pause") == 30
    assert path.exists()
    assert list(tmp_path.glob("settings.json.corrupt-*")) == []

def test_recipient_default(tmp_settings):
    assert tmp_settings.get("recipient") == ""

def test_autostart_default(tmp_settings):
    assert tmp_settings.get("autostart") is False


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


# --- Sync metadata (1.12.0) ---


def test_sync_enabled_default_is_false(tmp_settings):
    assert tmp_settings.get("sync_enabled") is False


def test_device_id_default_is_empty(tmp_settings):
    """device_id wird beim ersten App-Start in main.py befüllt, nicht hier."""
    assert tmp_settings.get("device_id") == ""


def test_last_pull_at_default_is_empty(tmp_settings):
    assert tmp_settings.get("last_pull_at") == ""


def test_drive_etag_default_is_empty(tmp_settings):
    assert tmp_settings.get("drive_etag") == ""


def test_sync_meta_persists(tmp_path):
    path = str(tmp_path / "settings.json")
    s1 = Settings(path)
    s1.set("sync_enabled", True)
    s1.set("device_id", "dev-uuid")
    s1.set("last_pull_at", "2026-05-14T10:00:00Z")
    s1.set("drive_etag", "etag-123")
    s2 = Settings(path)
    assert s2.get("sync_enabled") is True
    assert s2.get("device_id") == "dev-uuid"
    assert s2.get("last_pull_at") == "2026-05-14T10:00:00Z"
    assert s2.get("drive_etag") == "etag-123"


# --- set_synced / get_synced_doc / apply_synced (1.12.0) ---


def test_set_synced_records_metadata(tmp_path):
    """set_synced(key, value) speichert value im flachen Dict und führt
    Per-Field-Metadaten in _synced_meta."""
    path = str(tmp_path / "settings.json")
    s = Settings(path)
    s.device_id_for_sync = "dev-1"  # Wird von main.py gesetzt
    s.set_synced("recipient", "a@b.de")
    assert s.get("recipient") == "a@b.de"
    meta = s.get_synced_doc()
    assert meta["recipient"]["value"] == "a@b.de"
    assert meta["recipient"]["device_id"] == "dev-1"
    assert meta["recipient"]["modified_at"].endswith("Z")


def test_set_synced_persists_metadata_across_reload(tmp_path):
    path = str(tmp_path / "settings.json")
    s1 = Settings(path)
    s1.device_id_for_sync = "dev-1"
    s1.set_synced("name", "Max Mustermann")
    s2 = Settings(path)
    meta = s2.get_synced_doc()
    assert meta["name"]["value"] == "Max Mustermann"
    assert meta["name"]["device_id"] == "dev-1"


def test_apply_synced_overwrites_value_and_meta(tmp_path):
    """apply_synced(merged_settings) wird vom Sync-Pfad genutzt: setzt sowohl
    flat value als auch _synced_meta-Eintrag."""
    path = str(tmp_path / "settings.json")
    s = Settings(path)
    s.apply_synced({
        "recipient": {"value": "remote@x.de", "modified_at": "2026-05-14T10:00:00Z",
                       "device_id": "other-dev"},
    })
    assert s.get("recipient") == "remote@x.de"
    assert s.get_synced_doc()["recipient"]["device_id"] == "other-dev"


def test_apply_synced_skips_uncoercible_value(tmp_path):
    """N5: ein Remote-Wert, der nicht in den erwarteten Typ castbar ist
    (hier: hourly_rate als nicht-numerischer String), wird verworfen — der
    lokale Wert bleibt, statt Garbage zu übernehmen."""
    path = str(tmp_path / "settings.json")
    s = Settings(path)
    s.apply_synced({
        "hourly_rate": {"value": "not-a-number", "modified_at": "2026-05-14T10:00:00Z",
                        "device_id": "other-dev"},
    })
    assert s.get("hourly_rate") == 0.0            # Default unverändert
    assert "hourly_rate" not in s.get_synced_doc()  # Meta nicht gestempelt


def test_apply_synced_coerces_numeric_string(tmp_path):
    """N5-Gegentest: ein castbarer Wert (Zahl als String) wird übernommen und
    in den Zieltyp gecastet — Sync bleibt tolerant gegenüber JSON-Zahlformaten."""
    path = str(tmp_path / "settings.json")
    s = Settings(path)
    s.apply_synced({
        "hourly_rate": {"value": "15", "modified_at": "2026-05-14T10:00:00Z",
                        "device_id": "other-dev"},
    })
    assert s.get("hourly_rate") == 15.0
    assert isinstance(s.get("hourly_rate"), float)


def test_get_synced_doc_empty_when_nothing_set(tmp_settings):
    assert tmp_settings.get_synced_doc() == {}


def test_set_synced_stamps_meta_per_key(tmp_path):
    """Regression: simulate Settings-Dialog save behavior — synced keys must
    stamp _synced_meta, otherwise sync silently drops them."""
    from src.settings import Settings
    s = Settings(str(tmp_path / "settings.json"))
    s.device_id_for_sync = "dev-1"
    updates = {"recipient": "a@b.de", "name": "Max", "default_pause": 45}
    synced = {k: v for k, v in updates.items() if k in SYNCED_SETTING_KEYS}
    plain = {k: v for k, v in updates.items() if k not in SYNCED_SETTING_KEYS}
    for key, value in synced.items():
        s.set_synced(key, value)
    if plain:
        s.set_many(plain)
    doc = s.get_synced_doc()
    assert "recipient" in doc and doc["recipient"]["value"] == "a@b.de"
    assert "name" in doc and doc["name"]["value"] == "Max"
    # non-synced key not in synced_doc
    assert "default_pause" not in doc
    # but still in regular settings
    assert s.get("default_pause") == 45


# --- share_recipient (per-device, not synced) ---


def test_share_recipient_default_empty(tmp_path):
    from src.settings import Settings
    s = Settings(str(tmp_path / "s.json"))
    assert s.get("share_recipient") == ""


def test_share_recipient_persists(tmp_path):
    from src.settings import Settings
    path = str(tmp_path / "s.json")
    s1 = Settings(path)
    s1.set("share_recipient", "bob@example.com")
    s2 = Settings(path)
    assert s2.get("share_recipient") == "bob@example.com"


def test_gcal_defaults_present():
    from src.settings import DEFAULTS
    assert DEFAULTS["gcal_enabled"] is False
    assert DEFAULTS["gcal_calendar_id"] == ""
    assert DEFAULTS["last_calendar_sync_at"] == ""


def test_gcal_calendar_id_is_synced_setting():
    assert "gcal_calendar_id" in SYNCED_SETTING_KEYS


def test_sync_reexports_settings_whitelist():
    """Single Source of Truth (Issue #48): sync.py definiert die Whitelist nicht
    mehr selbst, sondern importiert sie aus settings.py. Identität (`is`) erzwingt
    strukturell, dass keine divergierende Zweitdefinition zurückkehrt — sonst
    mergt sync.py einen Key nicht (stiller Sync-Datenverlust)."""
    from src.settings import SYNCED_SETTING_KEYS as a
    from src.sync import SYNCED_SETTING_KEYS as b
    assert a is b


# --- categories (Multi-Slot-Feature, AP2) ---


def test_categories_default_is_empty_list(tmp_settings):
    assert tmp_settings.get("categories") == []


def test_categories_is_synced_setting():
    assert "categories" in SYNCED_SETTING_KEYS


def test_categories_persists_list(tmp_path):
    path = str(tmp_path / "settings.json")
    s1 = Settings(path)
    s1.set("categories", ["Büro", "Homeoffice"])
    s2 = Settings(path)
    assert s2.get("categories") == ["Büro", "Homeoffice"]


def test_categories_non_list_falls_back_to_default(tmp_path, caplog):
    """Ein Nicht-Listen-Wert wird von _coerce abgelehnt → Default []."""
    path = _write_json(tmp_path, json.dumps({"categories": "Büro"}))
    with caplog.at_level("WARNING"):
        s = Settings(path)
    assert s.get("categories") == []
    assert any("categories" in rec.message for rec in caplog.records)


def test_categories_synced_doc_roundtrip(tmp_path):
    path = str(tmp_path / "settings.json")
    s = Settings(path)
    s.device_id_for_sync = "dev-1"
    s.set_synced("categories", ["Büro", "Kundentermin"])
    doc = s.get_synced_doc()
    assert doc["categories"]["value"] == ["Büro", "Kundentermin"]
    assert doc["categories"]["device_id"] == "dev-1"


# --- category_times (Per-Kategorie-Standardzeiten) ---


def test_category_times_default_is_empty_dict(tmp_settings):
    assert tmp_settings.get("category_times") == {}


def test_category_times_is_synced_setting():
    assert "category_times" in SYNCED_SETTING_KEYS


def test_category_times_persists_dict(tmp_path):
    path = str(tmp_path / "settings.json")
    value = {"Office": {"start": "09:00", "end": "17:00", "pause": 0}}
    s1 = Settings(path)
    s1.set("category_times", value)
    s2 = Settings(path)
    assert s2.get("category_times") == value


def test_category_times_non_dict_falls_back_to_default(tmp_path, caplog):
    path = _write_json(tmp_path, json.dumps({"category_times": ["kaputt"]}))
    with caplog.at_level("WARNING"):
        s = Settings(path)
    assert s.get("category_times") == {}
    assert any("category_times" in rec.message for rec in caplog.records)


# --- Issue #51: aus settings_dialog.save_settings extrahierte pure Logik ---


def test_parse_hourly_rate_valid():
    from src.settings import parse_hourly_rate
    assert parse_hourly_rate("12.5") == 12.5


def test_parse_hourly_rate_empty_or_blank_is_zero():
    from src.settings import parse_hourly_rate
    assert parse_hourly_rate("") == 0.0
    assert parse_hourly_rate("   ") == 0.0


def test_parse_hourly_rate_strips_whitespace():
    from src.settings import parse_hourly_rate
    assert parse_hourly_rate("  8  ") == 8.0


def test_parse_hourly_rate_invalid_is_zero():
    from src.settings import parse_hourly_rate
    # Tolerantes Parsen (Dialog soll bei Tippfehlern nicht blocken).
    assert parse_hourly_rate("abc") == 0.0
    # Aktuelles Verhalten: Komma-Dezimal wird NICHT unterstützt (float() wirft) → 0.0.
    assert parse_hourly_rate("12,5") == 0.0


# --- Werkstudenten-Limit (Wochenstunden-Grenze für einen Zeitraum, #98) ---


def test_werkstudent_limit_defaults(tmp_settings):
    assert tmp_settings.get("werkstudent_limit_enabled") is False
    assert tmp_settings.get("werkstudent_limit_start") == ""
    assert tmp_settings.get("werkstudent_limit_end") == ""
    assert tmp_settings.get("werkstudent_limit_max_hours") == 20.0


def test_werkstudent_limit_keys_are_synced():
    assert "werkstudent_limit_enabled" in SYNCED_SETTING_KEYS
    assert "werkstudent_limit_start" in SYNCED_SETTING_KEYS
    assert "werkstudent_limit_end" in SYNCED_SETTING_KEYS
    assert "werkstudent_limit_max_hours" in SYNCED_SETTING_KEYS


def test_werkstudent_limit_persists(tmp_path):
    path = str(tmp_path / "settings.json")
    s1 = Settings(path)
    s1.set_many({
        "werkstudent_limit_enabled": True,
        "werkstudent_limit_start": "2026-04-01",
        "werkstudent_limit_end": "2026-07-15",
        "werkstudent_limit_max_hours": 18.0,
    })
    s2 = Settings(path)
    assert s2.get("werkstudent_limit_enabled") is True
    assert s2.get("werkstudent_limit_start") == "2026-04-01"
    assert s2.get("werkstudent_limit_end") == "2026-07-15"
    assert s2.get("werkstudent_limit_max_hours") == 18.0


def test_split_synced_updates_partitions_by_whitelist():
    from src.settings import split_synced_updates
    updates = {
        "recipient": "a@b.de",   # synced
        "name": "X",             # synced
        "autostart": True,       # plain
        "default_pause": 30,     # plain
    }
    synced, plain = split_synced_updates(updates)
    assert synced == {"recipient": "a@b.de", "name": "X"}
    assert plain == {"autostart": True, "default_pause": 30}


def test_split_synced_updates_empty():
    from src.settings import split_synced_updates
    assert split_synced_updates({}) == ({}, {})


def test_apply_updates_routes_synced_per_key_and_plain_in_one_call():
    from unittest.mock import MagicMock
    settings = MagicMock()
    updates = {
        "recipient": "a@b.de", "name": "X",   # synced
        "autostart": True, "default_pause": 30,  # plain
    }
    Settings.apply_updates(settings, updates)
    synced_calls = {c.args for c in settings.set_synced.call_args_list}
    assert synced_calls == {("recipient", "a@b.de"), ("name", "X")}
    settings.set_many.assert_called_once_with({"autostart": True, "default_pause": 30})


def test_apply_updates_no_plain_skips_set_many():
    from unittest.mock import MagicMock
    settings = MagicMock()
    Settings.apply_updates(settings, {"recipient": "a@b.de"})
    settings.set_synced.assert_called_once_with("recipient", "a@b.de")
    settings.set_many.assert_not_called()


def test_apply_updates_persists_routing_on_real_settings(tmp_settings):
    # End-to-end gegen echte Settings: synced-Key bekommt Sync-Metadaten,
    # plain-Key nicht.
    tmp_settings.apply_updates({"recipient": "a@b.de", "autostart": True})
    assert tmp_settings.get("recipient") == "a@b.de"
    assert tmp_settings.get("autostart") is True
    assert "recipient" in tmp_settings.get_synced_doc()
    assert "autostart" not in tmp_settings.get_synced_doc()


def test_resolve_calendar_id_selected_label_in_map():
    from src.settings import resolve_calendar_id
    cal_map = {"Privat": "cal_123", "Arbeit": "cal_456"}
    assert resolve_calendar_id(cal_map, "Arbeit", "cal_123") == "cal_456"


def test_resolve_calendar_id_unknown_label_falls_back_to_current():
    from src.settings import resolve_calendar_id
    assert resolve_calendar_id({}, "Weg", "cal_current") == "cal_current"


def test_resolve_calendar_id_unknown_and_no_current_is_primary():
    from src.settings import resolve_calendar_id
    assert resolve_calendar_id({}, "Weg", "") == "primary"
    assert resolve_calendar_id({}, "Weg", None) == "primary"


def test_ui_scale_default(tmp_settings):
    assert tmp_settings.get("ui_scale") == 1.0


def test_ui_scale_is_not_synced():
    # Gerätespezifisch -> darf nicht per Drive synchronisieren.
    assert "ui_scale" not in SYNCED_SETTING_KEYS


def test_clamp_ui_scale_within_range():
    from src.settings import clamp_ui_scale
    assert clamp_ui_scale(1.25) == 1.25
    assert clamp_ui_scale(0.75) == 0.75
    assert clamp_ui_scale(2.0) == 2.0


def test_clamp_ui_scale_below_min_clamps_to_075():
    from src.settings import clamp_ui_scale
    assert clamp_ui_scale(0.5) == 0.75


def test_clamp_ui_scale_above_max_clamps_to_2():
    from src.settings import clamp_ui_scale
    assert clamp_ui_scale(3.0) == 2.0


def test_clamp_ui_scale_string_is_cast():
    from src.settings import clamp_ui_scale
    assert clamp_ui_scale("1.5") == 1.5


def test_clamp_ui_scale_invalid_falls_back_to_1():
    from src.settings import clamp_ui_scale
    assert clamp_ui_scale(None) == 1.0
    assert clamp_ui_scale("abc") == 1.0


def test_per_day_category_times_roundtrips(tmp_path):
    path = str(tmp_path / "settings.json")
    s = Settings(path)
    pd = {"Homeoffice": {"mode": "per_day", "pause": 0,
                         "days": {"mon": {"start": "09:00", "end": "18:00"}}}}
    s.set_synced("category_times", pd)
    # frisch laden → verschachtelte Struktur kommt unverändert zurück (Dict-Passthrough)
    assert Settings(path).get("category_times") == pd


# --- parse_reminder_minutes (Reservierungs-Erinnerungen) ---
from src.settings import parse_reminder_minutes  # noqa: E402


def test_parse_reminder_minutes_valid():
    assert parse_reminder_minutes("15") == 15
    assert parse_reminder_minutes("0") == 0
    assert parse_reminder_minutes("120") == 120
    assert parse_reminder_minutes(30) == 30


def test_parse_reminder_minutes_out_of_range():
    assert parse_reminder_minutes("121") is None
    assert parse_reminder_minutes("-1") is None


def test_parse_reminder_minutes_non_numeric():
    assert parse_reminder_minutes("abc") is None
    assert parse_reminder_minutes("") is None
    assert parse_reminder_minutes("15.5") is None
    assert parse_reminder_minutes(None) is None


def test_reminder_defaults_present_and_device_local():
    from src.settings import DEFAULTS, SYNCED_SETTING_KEYS
    assert DEFAULTS["reminders_enabled"] is False
    assert DEFAULTS["reminder_minutes_before"] == 15
    assert "reminders_enabled" not in SYNCED_SETTING_KEYS
    assert "reminder_minutes_before" not in SYNCED_SETTING_KEYS


def test_send_reminder_defaults_present_and_device_local():
    from src.settings import DEFAULTS, SYNCED_SETTING_KEYS
    assert DEFAULTS["send_reminder_enabled"] is False
    assert DEFAULTS["send_reminder_day"] == 1
    assert DEFAULTS["send_reminder_time"] == "18:00"
    assert DEFAULTS["send_reminder_last_fired_month"] == ""
    assert "send_reminder_enabled" not in SYNCED_SETTING_KEYS
    assert "send_reminder_day" not in SYNCED_SETTING_KEYS
    assert "send_reminder_time" not in SYNCED_SETTING_KEYS
    assert "send_reminder_last_fired_month" not in SYNCED_SETTING_KEYS


def test_update_tab_defaults_present_and_device_local():
    from src.settings import DEFAULTS, SYNCED_SETTING_KEYS
    assert DEFAULTS["update_check_frequency"] == "daily"
    assert DEFAULTS["update_toast_shown_version"] == ""
    assert "update_check_frequency" not in SYNCED_SETTING_KEYS
    assert "update_toast_shown_version" not in SYNCED_SETTING_KEYS


# --- override_in_memory (Audit M12) ---


def test_override_in_memory_sets_value_during_block(tmp_settings):
    tmp_settings.set("show_weekend", True)
    with tmp_settings.override_in_memory("show_weekend", False):
        assert tmp_settings.get("show_weekend") is False


def test_override_in_memory_restores_previous_after_block(tmp_settings):
    tmp_settings.set("show_weekend", True)
    with tmp_settings.override_in_memory("show_weekend", False):
        pass
    assert tmp_settings.get("show_weekend") is True


def test_override_in_memory_does_not_persist_to_disk(tmp_path):
    """Kern der M12-Kapselung: der temporäre Override darf settings.json NICHT
    anfassen — ein paralleler Reader (frischer Settings-Reload) sieht den alten
    Wert, auch während der with-Block läuft."""
    path = str(tmp_path / "settings.json")
    s1 = Settings(path)
    s1.set("show_weekend", True)
    with s1.override_in_memory("show_weekend", False):
        s2 = Settings(path)
        assert s2.get("show_weekend") is True  # Disk unverändert


def test_override_in_memory_restores_even_on_exception(tmp_settings):
    tmp_settings.set("show_weekend", True)
    with pytest.raises(RuntimeError):
        with tmp_settings.override_in_memory("show_weekend", False):
            raise RuntimeError("boom")
    assert tmp_settings.get("show_weekend") is True


def test_override_in_memory_removes_key_absent_before(tmp_settings):
    """War der Key vorher nicht in _data (nur via DEFAULTS sichtbar), wird er
    nach dem Block wieder entfernt statt auf dem Override-Wert kleben zu bleiben."""
    assert "some_transient_key" not in tmp_settings._data
    with tmp_settings.override_in_memory("some_transient_key", 42):
        assert tmp_settings.get("some_transient_key") == 42
    assert "some_transient_key" not in tmp_settings._data


def test_prerelease_updates_disabled_by_default():
    from src.settings import DEFAULTS

    assert DEFAULTS["prerelease_updates_enabled"] is False


def test_prerelease_updates_flag_is_device_local():
    # Update-Einstellungen werden bewusst nicht synchronisiert: der Rechner,
    # auf dem ein Testbuild geprüft wird, soll die anderen Geräte nicht in
    # den Pre-Kanal ziehen.
    from src.settings import SYNCED_SETTING_KEYS

    assert "prerelease_updates_enabled" not in SYNCED_SETTING_KEYS
