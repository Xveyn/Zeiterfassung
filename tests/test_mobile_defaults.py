"""`mobile_sync.build_defaults` / `desktop_info`: Standardzeiten und Desktop-Angaben für die PWA (#288)."""
import pytest

from src import mobile_sync
from src.settings import WEEKDAY_KEYS


class FakeSettings(dict):
    def get(self, key, default=None):
        return super().get(key, default)


def settings(**values):
    base = {"default_pause": 30}
    for day in WEEKDAY_KEYS:
        base[f"default_start_{day}"] = "08:00"
        base[f"default_end_{day}"] = "16:00"
    base.update(values)
    return FakeSettings(base)


def test_weekday_defaults_and_global_pause_are_sent():
    result = mobile_sync.build_defaults(settings(default_start_fri="09:00", default_end_fri="13:30"), [])

    assert result["pause"] == 30
    assert result["weekdays"]["fri"] == {"start": "09:00", "end": "13:30"}
    assert set(result["weekdays"]) == set(WEEKDAY_KEYS)
    assert result["category_times"] == {}


def test_invalid_weekday_times_and_pause_fall_back_to_empty_values():
    result = mobile_sync.build_defaults(
        settings(default_start_mon="25:00", default_end_mon=None, default_pause="x"), [])

    assert result["weekdays"]["mon"] == {"start": "", "end": ""}
    assert result["pause"] == 0


def test_category_times_general_form_is_cleaned():
    result = mobile_sync.build_defaults(settings(category_times={
        "Projekt": {"start": "09:00", "end": "17:00", "pause": 45, "evil": "x"},
        "Leer": {"start": "", "end": None},
    }), ["Projekt", "Leer"])

    assert result["category_times"]["Projekt"] == {"start": "09:00", "end": "17:00", "pause": 45}
    assert result["category_times"]["Leer"] == {}


def test_category_times_per_day_form_is_cleaned():
    result = mobile_sync.build_defaults(settings(category_times={"Büro": {
        "mode": "per_day", "pause": 15,
        "days": {"mon": {"start": "07:00", "end": "15:00"}, "xyz": {"start": "01:00"},
                 "tue": {"start": "bad"}}}}), ["Büro"])

    assert result["category_times"]["Büro"] == {
        "mode": "per_day", "pause": 15, "days": {"mon": {"start": "07:00", "end": "15:00"}, "tue": {}}}


def test_only_known_categories_are_sent_and_garbage_is_ignored():
    result = mobile_sync.build_defaults(settings(category_times={
        "Fremd": {"start": "09:00"}, "Projekt": "kaputt"}), ["Projekt"])

    assert result["category_times"] == {}
    assert mobile_sync.build_defaults(settings(category_times="kaputt"), ["Projekt"])["category_times"] == {}


@pytest.mark.parametrize("pause", [-5, True, 10_000])
def test_out_of_range_pause_is_dropped(pause):
    result = mobile_sync.build_defaults(settings(category_times={"P": {"pause": pause}}), ["P"])

    assert result["category_times"]["P"] == {}


@pytest.mark.parametrize("system,expected", [
    ("Windows", "Windows"), ("Darwin", "macOS"), ("Linux", "Linux"), ("FreeBSD", "")])
def test_desktop_info_maps_the_platform(system, expected):
    info = mobile_sync.desktop_info("Büro-PC", "1.24.0", system)

    assert info == {"name": "Büro-PC", "version": "1.24.0", "platform": expected}
