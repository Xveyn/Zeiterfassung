"""devices: Gerätenamen für die Sync-Anzeige (Konfliktdialog, Einstellungen).

Reine Logik ohne Tk und ohne I/O — der Hostname wird über den `hostname`-
Parameter hereingereicht, statt `socket` zu monkeypatchen.

Alles hier muss mit Fremddaten umgehen können: die Registry kommt aus dem
Remote-Sync-Doc und ist damit genauso wenig vertrauenswürdig wie jedes andere
Remote-Feld.
"""

import pytest

from src import devices


class TestSanitizeDeviceName:
    def test_trims_whitespace(self):
        assert devices.sanitize_device_name("  Laptop Arbeit  ") == "Laptop Arbeit"

    def test_strips_control_characters(self):
        assert devices.sanitize_device_name("Lap\ntop\tArbeit\x00") == "Lap top Arbeit"

    def test_collapses_runs_of_whitespace(self):
        assert devices.sanitize_device_name("Laptop     Arbeit") == "Laptop Arbeit"

    def test_caps_length(self):
        long_name = "A" * 200
        result = devices.sanitize_device_name(long_name)
        assert len(result) == devices.MAX_NAME_LENGTH

    def test_non_string_becomes_empty(self):
        assert devices.sanitize_device_name(None) == ""
        assert devices.sanitize_device_name(42) == ""
        assert devices.sanitize_device_name({"name": "x"}) == ""

    def test_empty_stays_empty(self):
        assert devices.sanitize_device_name("   ") == ""


class TestDefaultDeviceName:
    def test_uses_hostname(self):
        assert devices.default_device_name(hostname=lambda: "Sven-PC") == "Sven-PC"

    def test_sanitizes_hostname(self):
        assert devices.default_device_name(hostname=lambda: "  Sven-PC  ") == "Sven-PC"

    def test_empty_when_hostname_unavailable(self):
        def _raise():
            raise OSError("no hostname")

        assert devices.default_device_name(hostname=_raise) == ""

    def test_empty_when_hostname_blank(self):
        assert devices.default_device_name(hostname=lambda: "") == ""

    def test_localhost_is_not_a_name(self):
        """`localhost` beschreibt jedes Gerät und keines — als Vorbelegung
        wertlos, dann lieber die ID zeigen."""
        assert devices.default_device_name(hostname=lambda: "localhost") == ""
        assert devices.default_device_name(hostname=lambda: "LOCALHOST.localdomain") == ""


class TestDeviceLabel:
    REGISTRY = {"6800a51a9f3c4d2e": {"name": "Laptop Arbeit", "updated_at": "2026-07-02T19:10:00Z"}}

    def test_name_and_short_id_when_known(self):
        assert devices.device_label("6800a51a9f3c4d2e", self.REGISTRY) == "Laptop Arbeit · 6800a51a…"

    def test_short_id_only_when_unknown(self):
        assert devices.device_label("34a0480f1122", self.REGISTRY) == "34a0480f…"

    def test_short_id_only_when_name_is_empty(self):
        registry = {"34a0480f1122": {"name": "", "updated_at": "2026-07-02T19:10:00Z"}}
        assert devices.device_label("34a0480f1122", registry) == "34a0480f…"

    def test_short_ids_are_not_truncated(self):
        assert devices.device_label("abc", {}) == "abc"

    def test_missing_id_is_question_mark(self):
        assert devices.device_label("", {}) == "?"
        assert devices.device_label(None, {}) == "?"

    def test_registry_name_is_sanitized(self):
        """Der Name stammt aus dem Remote-Doc und landet in einem Tk-Label."""
        registry = {"6800a51a9f3c4d2e": {"name": "A" * 200, "updated_at": ""}}
        label = devices.device_label("6800a51a9f3c4d2e", registry)
        assert label == "A" * devices.MAX_NAME_LENGTH + " · 6800a51a…"

    def test_survives_broken_registry(self):
        for broken in (None, [], "nope", {"6800a51a9f3c4d2e": "nope"}, {"6800a51a9f3c4d2e": None}):
            assert devices.device_label("6800a51a9f3c4d2e", broken) == "6800a51a…"


class TestSanitizeRegistry:
    def test_keeps_valid_entries(self):
        raw = {"dev1": {"name": "Laptop", "updated_at": "2026-07-02T19:10:00Z"}}
        assert devices.sanitize_registry(raw) == {
            "dev1": {"name": "Laptop", "updated_at": "2026-07-02T19:10:00Z"},
        }

    def test_drops_entries_without_usable_name(self):
        raw = {"dev1": {"name": "   ", "updated_at": "2026-07-02T19:10:00Z"}}
        assert devices.sanitize_registry(raw) == {}

    def test_drops_non_dict_entries(self):
        raw = {"dev1": "nope", "dev2": {"name": "Laptop", "updated_at": "2026-07-02T19:10:00Z"}}
        assert set(devices.sanitize_registry(raw)) == {"dev2"}

    def test_drops_non_string_keys(self):
        raw = {1: {"name": "Laptop", "updated_at": "2026-07-02T19:10:00Z"}}
        assert devices.sanitize_registry(raw) == {}

    def test_missing_updated_at_becomes_empty_string(self):
        raw = {"dev1": {"name": "Laptop"}}
        assert devices.sanitize_registry(raw)["dev1"]["updated_at"] == ""

    def test_non_dict_registry_becomes_empty(self):
        for broken in (None, [], "nope", 42):
            assert devices.sanitize_registry(broken) == {}

    def test_drops_unknown_fields(self):
        """Ein fremdes Feld darf nicht in den lokalen Spiegel wandern — der
        wird beim nächsten Push wieder hochgeladen."""
        raw = {"dev1": {"name": "Laptop", "updated_at": "", "evil": "x" * 10_000}}
        assert devices.sanitize_registry(raw)["dev1"] == {"name": "Laptop", "updated_at": ""}

    def test_caps_registry_size(self):
        raw = {
            f"dev{i:03d}": {"name": f"Gerät {i}", "updated_at": f"2026-07-{i % 28 + 1:02d}T00:00:00Z"}
            for i in range(devices.MAX_DEVICES + 50)
        }
        assert len(devices.sanitize_registry(raw)) == devices.MAX_DEVICES

    def test_size_cap_keeps_the_most_recent(self):
        raw = {
            "alt": {"name": "Alt", "updated_at": "2020-01-01T00:00:00Z"},
            "neu": {"name": "Neu", "updated_at": "2026-01-01T00:00:00Z"},
        }
        capped = devices.sanitize_registry(raw, max_devices=1)
        assert set(capped) == {"neu"}


class TestMergeRegistries:
    def test_union_of_both_sides(self):
        local = {"dev1": {"name": "Laptop", "updated_at": "2026-07-01T00:00:00Z"}}
        remote = {"dev2": {"name": "PC", "updated_at": "2026-07-01T00:00:00Z"}}
        assert set(devices.merge_registries(local, remote)) == {"dev1", "dev2"}

    def test_newer_updated_at_wins(self):
        local = {"dev1": {"name": "Alter Name", "updated_at": "2026-07-01T00:00:00Z"}}
        remote = {"dev1": {"name": "Neuer Name", "updated_at": "2026-07-05T00:00:00Z"}}
        assert devices.merge_registries(local, remote)["dev1"]["name"] == "Neuer Name"

    def test_older_remote_does_not_overwrite(self):
        local = {"dev1": {"name": "Neuer Name", "updated_at": "2026-07-05T00:00:00Z"}}
        remote = {"dev1": {"name": "Alter Name", "updated_at": "2026-07-01T00:00:00Z"}}
        assert devices.merge_registries(local, remote)["dev1"]["name"] == "Neuer Name"

    def test_local_wins_on_equal_timestamps(self):
        local = {"dev1": {"name": "Lokal", "updated_at": "2026-07-05T00:00:00Z"}}
        remote = {"dev1": {"name": "Remote", "updated_at": "2026-07-05T00:00:00Z"}}
        assert devices.merge_registries(local, remote)["dev1"]["name"] == "Lokal"

    def test_sanitizes_both_sides(self):
        local = {"dev1": "kaputt"}
        remote = {"dev2": {"name": "  PC  ", "updated_at": ""}}
        merged = devices.merge_registries(local, remote)
        assert merged == {"dev2": {"name": "PC", "updated_at": ""}}

    def test_survives_broken_input(self):
        assert devices.merge_registries(None, None) == {}
        assert devices.merge_registries("nope", ["nope"]) == {}

    def test_does_not_mutate_inputs(self):
        local = {"dev1": {"name": "Laptop", "updated_at": "2026-07-01T00:00:00Z"}}
        remote = {"dev1": {"name": "PC", "updated_at": "2026-07-05T00:00:00Z"}}
        devices.merge_registries(local, remote)
        assert local["dev1"]["name"] == "Laptop"
        assert remote["dev1"]["name"] == "PC"


class TestWithOwnEntry:
    def test_adds_own_entry(self):
        result = devices.with_own_entry({}, "dev1", "Laptop", "2026-07-05T00:00:00Z")
        assert result == {"dev1": {"name": "Laptop", "updated_at": "2026-07-05T00:00:00Z"}}

    def test_replaces_own_entry_regardless_of_timestamp(self):
        """Über den eigenen Namen entscheidet immer das eigene Gerät — auch
        wenn ein anderes Gerät einen neueren Stempel für diese ID trägt."""
        registry = {"dev1": {"name": "Fremdname", "updated_at": "2099-01-01T00:00:00Z"}}
        result = devices.with_own_entry(registry, "dev1", "Laptop", "2026-07-05T00:00:00Z")
        assert result["dev1"] == {"name": "Laptop", "updated_at": "2026-07-05T00:00:00Z"}

    def test_keeps_timestamp_when_name_unchanged(self):
        """Sonst trüge jeder Push einen neuen Stempel — das Sync-Doc wiche bei
        jedem Lauf ab, ohne dass sich etwas geändert hat."""
        registry = {"dev1": {"name": "Laptop", "updated_at": "2026-07-01T00:00:00Z"}}
        result = devices.with_own_entry(registry, "dev1", "Laptop", "2026-07-05T00:00:00Z")
        assert result["dev1"]["updated_at"] == "2026-07-01T00:00:00Z"

    def test_new_timestamp_when_name_changed(self):
        registry = {"dev1": {"name": "Laptop", "updated_at": "2026-07-01T00:00:00Z"}}
        result = devices.with_own_entry(registry, "dev1", "Laptop Arbeit", "2026-07-05T00:00:00Z")
        assert result["dev1"]["updated_at"] == "2026-07-05T00:00:00Z"

    def test_keeps_other_entries(self):
        registry = {"dev2": {"name": "PC", "updated_at": "2026-07-01T00:00:00Z"}}
        result = devices.with_own_entry(registry, "dev1", "Laptop", "2026-07-05T00:00:00Z")
        assert set(result) == {"dev1", "dev2"}

    def test_without_name_removes_own_entry(self):
        """Wer seinen Namen leert, verschwindet beim nächsten Push aus der
        Registry — sonst bliebe der alte Name für immer stehen."""
        registry = {"dev1": {"name": "Laptop", "updated_at": "2026-07-01T00:00:00Z"}}
        result = devices.with_own_entry(registry, "dev1", "", "2026-07-05T00:00:00Z")
        assert "dev1" not in result

    def test_without_device_id_changes_nothing(self):
        registry = {"dev2": {"name": "PC", "updated_at": "2026-07-01T00:00:00Z"}}
        assert devices.with_own_entry(registry, "", "Laptop", "2026-07-05T00:00:00Z") == registry

    def test_does_not_mutate_input(self):
        registry = {"dev2": {"name": "PC", "updated_at": "2026-07-01T00:00:00Z"}}
        devices.with_own_entry(registry, "dev1", "Laptop", "2026-07-05T00:00:00Z")
        assert set(registry) == {"dev2"}


@pytest.mark.parametrize("name", ["Büro-PC", "Laptop (privat)", "MacBook Pro M4"])
def test_realistic_names_survive_sanitizing(name):
    assert devices.sanitize_device_name(name) == name
