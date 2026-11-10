import pytest

from src import region
from src.settings import SYNCED_SETTING_KEYS, Settings


def _settings(tmp_path, **values):
    s = Settings(str(tmp_path / "settings.json"))
    if values:
        s.set_many(values)
    return s


def test_migrate_copies_valid_state(tmp_path):
    s = _settings(tmp_path, state="BY")
    assert region.migrate_state(s) is True
    assert s.get("country") == "DE"
    assert s.get("region") == "BY"
    assert s.get(region.MIGRATED_KEY) is True
    assert s.get("state") == "BY"


@pytest.mark.parametrize("bad", ["XX", None, 5, ["BY"]])
def test_migrate_garbled_state_gives_empty_region(tmp_path, bad):
    s = _settings(tmp_path, state=bad)
    assert region.migrate_state(s) is True
    assert s.get("region") == ""
    assert s.get(region.MIGRATED_KEY) is True


def test_migrate_runs_only_once(tmp_path):
    s = _settings(tmp_path, state="BY")
    region.migrate_state(s)
    s.set("state", "HH")
    assert region.migrate_state(s) is False
    assert s.get("region") == "BY"


def test_country_region_defaults(tmp_path):
    assert region.country_region(_settings(tmp_path)) == ("DE", "")
    assert region.country_region(
        _settings(tmp_path, country="ZZ", region="BY")) == ("DE", "BY")
    assert region.country_region(
        _settings(tmp_path, country="", region="XX")) == ("DE", "")


def test_normalize_language_and_country():
    assert region.normalize_language("de") == "de"
    for bad in ("xx", "", None, 5):
        assert region.normalize_language(bad) == "de"
    assert region.normalize_country("DE") == "DE"
    for bad in ("ZZ", "", None, ["DE"]):
        assert region.normalize_country(bad) == "DE"


def test_new_keys_are_device_local():
    for key in ("country", "region", "region_migrated"):
        assert key not in SYNCED_SETTING_KEYS
