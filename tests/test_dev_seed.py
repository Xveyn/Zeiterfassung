import json
import os

from src.dev import seed


def test_seed_if_empty_creates_files(tmp_path):
    base = str(tmp_path)
    seed.seed_if_empty(base)
    z = json.loads((tmp_path / "zeiterfassung.json").read_text(encoding="utf-8"))
    assert len(z) >= 1
    # Einträge haben die volle Storage-Form inkl. Sync-Metadaten
    first = next(iter(z.values()))
    assert set(first) == {"start", "end", "pause", "modified_at", "device_id", "deleted"}
    assert (tmp_path / "settings.json").exists()
    assert (tmp_path / "credentials.json").exists()
    # KEIN token.json — sonst Token-Popups beim Dev-Start
    assert not (tmp_path / "token.json").exists()


def test_seed_if_empty_is_noop_when_entries_exist(tmp_path):
    base = str(tmp_path)
    (tmp_path / "zeiterfassung.json").write_text('{"keep": 1}', encoding="utf-8")
    seed.seed_if_empty(base)
    z = json.loads((tmp_path / "zeiterfassung.json").read_text(encoding="utf-8"))
    assert z == {"keep": 1}


def test_reseed_overwrites(tmp_path):
    base = str(tmp_path)
    (tmp_path / "zeiterfassung.json").write_text('{"keep": 1}', encoding="utf-8")
    seed.reseed(base)
    z = json.loads((tmp_path / "zeiterfassung.json").read_text(encoding="utf-8"))
    assert "keep" not in z
    assert len(z) >= 1
