"""Tests der gemeinsamen Store-Mechanik (R2).

Die beiden Invarianten N1 (fsync vor replace) und N4 (Quarantäne statt
stillem Verwerfen) lagen vorher in vier bzw. drei Kopien und wurden je Store
mitgetestet. Sie stehen jetzt an einer Stelle — und werden hier direkt
geprüft, statt nur indirekt über die Stores.
"""

import json
import logging
import os
from unittest import mock

import pytest

from src.json_store import atomic_write_json, load_json_or_quarantine, quarantine_corrupt


# --- atomic_write_json ----------------------------------------------------

def test_write_roundtrip(tmp_path):
    path = str(tmp_path / "t.json")
    atomic_write_json(path, {"a": 1, "text": "Grüße"})
    with open(path, encoding="utf-8") as f:
        assert json.load(f) == {"a": 1, "text": "Grüße"}


def test_write_keeps_umlauts_unescaped(tmp_path):
    """ensure_ascii=False: die Dateien sollen im Support-Fall lesbar sein."""
    path = str(tmp_path / "t.json")
    atomic_write_json(path, {"k": "Zeiterfassung für Mär"})
    assert "für Mär" in (tmp_path / "t.json").read_text(encoding="utf-8")


def test_fsync_happens_before_replace(tmp_path, monkeypatch):
    """N1: Das Rename darf erst durabel werden, wenn die Datenblöcke es sind.
    Geprüft wird die Reihenfolge, nicht nur das Vorkommen beider Aufrufe."""
    calls = []
    real_fsync, real_replace = os.fsync, os.replace
    monkeypatch.setattr(os, "fsync", lambda fd: (calls.append("fsync"), real_fsync(fd))[0])
    monkeypatch.setattr(
        os, "replace", lambda a, b: (calls.append("replace"), real_replace(a, b))[0])

    atomic_write_json(str(tmp_path / "t.json"), {"a": 1})

    # Unter POSIX folgt nach dem Rename noch der fsync des Verzeichnisses —
    # entscheidend ist, dass die Datei VOR dem Rename gesynct ist.
    assert calls[:2] == ["fsync", "replace"]


def test_failed_dump_leaves_target_and_no_temp_file(tmp_path):
    """Scheitert schon das Serialisieren, bleibt die alte Datei unangetastet
    und keine halbe Temp-Datei liegen."""
    path = tmp_path / "t.json"
    atomic_write_json(str(path), {"stand": "alt"})
    original = path.read_bytes()

    with pytest.raises(TypeError):
        atomic_write_json(str(path), {"nicht": object()})

    assert path.read_bytes() == original
    assert [p.name for p in tmp_path.iterdir()] == ["t.json"]


def test_temp_name_is_unique_per_write(tmp_path):
    """Kein fester `<ziel>.tmp`: liegt dort etwas (Leiche eines alten Laufs,
    paralleler Schreiber), darf das den Save nicht verhindern."""
    path = tmp_path / "t.json"
    (tmp_path / "t.json.tmp").mkdir()

    atomic_write_json(str(path), {"a": 1})

    assert json.loads(path.read_text(encoding="utf-8")) == {"a": 1}


@pytest.mark.skipif(os.name == "nt", reason="Verzeichnis-fsync nur unter POSIX")
def test_directory_is_synced_after_replace_on_posix(tmp_path, monkeypatch):
    """Erst der fsync des Verzeichnisses macht das Rename selbst durabel."""
    import stat
    calls = []
    real_fsync, real_replace = os.fsync, os.replace

    def fsync(fd):
        calls.append("fsync-dir" if stat.S_ISDIR(os.fstat(fd).st_mode) else "fsync")
        return real_fsync(fd)

    monkeypatch.setattr(os, "fsync", fsync)
    monkeypatch.setattr(
        os, "replace", lambda a, b: (calls.append("replace"), real_replace(a, b))[0])

    atomic_write_json(str(tmp_path / "t.json"), {"a": 1})

    assert calls == ["fsync", "replace", "fsync-dir"]


def test_replace_error_removes_tmp_and_reraises(tmp_path):
    """Scheitert das Rename, darf weder eine Temp-Leiche liegenbleiben noch
    der Fehler verschluckt werden — der Aufrufer muss den Save scheitern
    sehen, die alte Datei bleibt unangetastet."""
    path = tmp_path / "t.json"
    atomic_write_json(str(path), {"stand": "alt"})
    original = path.read_bytes()

    with mock.patch("os.replace", side_effect=OSError("disk full")):
        with pytest.raises(OSError):
            atomic_write_json(str(path), {"stand": "neu"})

    assert path.read_bytes() == original
    assert [p.name for p in tmp_path.iterdir() if p.name.endswith(".tmp")] == []


# --- quarantine_corrupt ---------------------------------------------------

def test_quarantine_moves_file_and_logs(tmp_path, caplog):
    path = tmp_path / "kaputt.json"
    path.write_text("{ das ist kein JSON", encoding="utf-8")

    with caplog.at_level(logging.WARNING):
        target = quarantine_corrupt(str(path))

    assert not path.exists()
    assert os.path.exists(target)
    assert os.path.basename(target).startswith("kaputt.json.corrupt-")
    assert any("Quarantäne" in r.message for r in caplog.records)


def test_quarantine_preserves_content(tmp_path):
    """N4 rettet die Daten — der Nutzer soll die Datei noch retten können."""
    path = tmp_path / "kaputt.json"
    path.write_text("halb geschriebene Nutzdaten", encoding="utf-8")

    target = quarantine_corrupt(str(path))

    with open(target, encoding="utf-8") as f:
        assert f.read() == "halb geschriebene Nutzdaten"


# --- load_json_or_quarantine ----------------------------------------------

def test_load_missing_file_returns_none(tmp_path):
    assert load_json_or_quarantine(str(tmp_path / "gibtsnicht.json")) is None


def test_load_valid_file_returns_object(tmp_path):
    path = tmp_path / "t.json"
    path.write_text('{"a": 1}', encoding="utf-8")
    assert load_json_or_quarantine(str(path)) == {"a": 1}


def test_load_corrupt_file_quarantines_and_returns_none(tmp_path):
    path = tmp_path / "t.json"
    path.write_text("{ kaputt", encoding="utf-8")

    assert load_json_or_quarantine(str(path)) is None

    assert not path.exists()
    assert [p.name for p in tmp_path.iterdir() if ".corrupt-" in p.name]


def test_load_json_null_returns_none(tmp_path):
    """Datei enthält gültiges JSON `null`. Vorher landete dieses None
    ungeprüft im `_data` des Stores und ließ die Migration mit
    AttributeError auflaufen; jetzt ist es vom Fall 'nicht vorhanden'
    nicht mehr unterscheidbar — und der Store startet leer."""
    path = tmp_path / "t.json"
    path.write_text("null", encoding="utf-8")
    assert load_json_or_quarantine(str(path)) is None
