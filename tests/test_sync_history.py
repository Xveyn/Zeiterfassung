"""F/N6: persistenter 'hat je gesynct/abgeglichen'-Marker.

Der Startup-Sweep verwirft verwaiste Tombstones nur auf Geräten, die nie
gesynct/abgeglichen haben. Leitete er das allein aus settings.json ab, würde
eine settings.json-Korruption (Reset auf Defaults, Audit M4) einen tatsächlich
gesyncten Rechner wie 'nie gesynct' aussehen lassen und seine Tombstones
verwerfen. Dieser Marker ist die dauerhafte, von settings.json unabhängige
Gegenprobe.
"""

from src import sync_history


def test_absent_marker_is_unmarked(tmp_path):
    """Kein Marker = frischer Single-Device-Nutzer: Sweep darf laufen."""
    base = str(tmp_path)
    assert sync_history.ever_synced(base) is False
    assert sync_history.ever_reconciled(base) is False


def test_mark_synced_persists_and_is_independent(tmp_path):
    base = str(tmp_path)
    sync_history.mark_synced(base)
    assert sync_history.ever_synced(base) is True
    assert sync_history.ever_reconciled(base) is False  # unabhängiges Flag


def test_mark_reconciled_persists_and_is_independent(tmp_path):
    base = str(tmp_path)
    sync_history.mark_reconciled(base)
    assert sync_history.ever_reconciled(base) is True
    assert sync_history.ever_synced(base) is False


def test_both_flags_coexist(tmp_path):
    base = str(tmp_path)
    sync_history.mark_synced(base)
    sync_history.mark_reconciled(base)
    assert sync_history.ever_synced(base) is True
    assert sync_history.ever_reconciled(base) is True


def test_marker_survives_process_boundary(tmp_path):
    """Muss auf der Platte liegen (der ganze Zweck: einen settings.json-Reset
    überleben) — ein frischer Lesezugriff sieht den Marker."""
    base = str(tmp_path)
    sync_history.mark_synced(base)
    assert (tmp_path / "sync_history.json").exists()
    assert sync_history.ever_synced(base) is True


def test_corrupt_marker_fails_safe_to_marked(tmp_path):
    """Datei da, aber unlesbar -> im Zweifel als gesetzt behandeln: lieber
    Tombstones behalten als fälschlich verwerfen."""
    base = str(tmp_path)
    (tmp_path / "sync_history.json").write_text("{ kein valides json", encoding="utf-8")
    assert sync_history.ever_synced(base) is True
    assert sync_history.ever_reconciled(base) is True


def test_mark_is_write_once_noop(tmp_path):
    """Zweites Markieren schreibt nicht erneut (sonst jeder Sync ein Write)."""
    base = str(tmp_path)
    sync_history.mark_synced(base)
    before = (tmp_path / "sync_history.json").stat().st_mtime_ns
    sync_history.mark_synced(base)
    assert (tmp_path / "sync_history.json").stat().st_mtime_ns == before
