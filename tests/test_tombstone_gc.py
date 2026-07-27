"""Audit N6: Tombstones dürfen nicht unbegrenzt wachsen.

Ein Tombstone existiert nur, um beim Sync ein veraltetes Save eines anderen
Geräts zu schlagen. Hatte ein Store nachweislich nie einen Sync-Partner, ist
er wirkungsloser Ballast und wird beim Start verworfen. Wer je gesynct hat,
behält seine Tombstones — dort räumt ausschließlich die Kompaktierung auf
(Watermark-Protokoll), sonst kämen gelöschte Tage zurück.
"""

from src import main as main_module
from src import sync_history
from src.reservations import ReservationStore
from src.reservations_sync import drop_orphan_reservation_tombstones
from src.settings import Settings
from src.storage import Storage
from src.sync import drop_orphan_tombstones


def _storage_with_tombstone(tmp_path):
    st = Storage(str(tmp_path / "z.json"), device_id="dev")
    st.save("2026-07-01", [{"start": "08:00", "end": "16:00", "pause": 30}])
    st.save("2026-07-02", [{"start": "08:00", "end": "16:00", "pause": 30}])
    st.delete("2026-07-02")
    return st


def _settings(tmp_path, **over):
    s = Settings(str(tmp_path / "s.json"))
    for k, v in over.items():
        s.set(k, v)
    return s


# --- Storage ---------------------------------------------------------------

def test_never_synced_drops_tombstones(tmp_path):
    st = _storage_with_tombstone(tmp_path)
    settings = _settings(tmp_path, sync_enabled=False, last_pull_at="")
    assert drop_orphan_tombstones(st, settings) == 1
    assert "2026-07-02" not in st.get_all_raw()
    assert "2026-07-01" in st.get_all_raw()   # echte Einträge bleiben


def test_dropped_tombstones_survive_reload(tmp_path):
    """Muss auf der Platte landen, sonst wächst die Datei trotzdem weiter."""
    st = _storage_with_tombstone(tmp_path)
    settings = _settings(tmp_path, sync_enabled=False, last_pull_at="")
    drop_orphan_tombstones(st, settings)
    reloaded = Storage(str(tmp_path / "z.json"), device_id="dev")
    assert "2026-07-02" not in reloaded.get_all_raw()


def test_sync_enabled_keeps_tombstones(tmp_path):
    st = _storage_with_tombstone(tmp_path)
    settings = _settings(tmp_path, sync_enabled=True, last_pull_at="")
    assert drop_orphan_tombstones(st, settings) == 0
    assert st.get_all_raw()["2026-07-02"]["deleted"] is True


def test_sync_disabled_but_previously_synced_keeps_tombstones(tmp_path):
    """Der gefährliche Fall: Sync war mal an, das Remote kennt den Tag noch.
    Würde der Tombstone hier fallen, käme der gelöschte Tag beim
    Wiedereinschalten zurück."""
    st = _storage_with_tombstone(tmp_path)
    settings = _settings(tmp_path, sync_enabled=False,
                         last_pull_at="2026-06-30T10:00:00Z")
    assert drop_orphan_tombstones(st, settings) == 0
    assert st.get_all_raw()["2026-07-02"]["deleted"] is True


def test_no_tombstones_does_not_write(tmp_path):
    """Kein Disk-Write, wenn es nichts zu tun gibt (jeder Start sonst ein
    unnötiger Roundtrip)."""
    st = Storage(str(tmp_path / "z.json"), device_id="dev")
    st.save("2026-07-01", [{"start": "08:00", "end": "16:00", "pause": 30}])
    settings = _settings(tmp_path, sync_enabled=False, last_pull_at="")
    before = (tmp_path / "z.json").stat().st_mtime_ns
    assert drop_orphan_tombstones(st, settings) == 0
    assert (tmp_path / "z.json").stat().st_mtime_ns == before


# --- Reservierungen --------------------------------------------------------

def _reservations_with_tombstone(tmp_path):
    rs = ReservationStore(str(tmp_path / "r.json"))
    rs.save("2026-07-01", [{"start": "09:00", "end": "12:00", "kategorie": "A"}])
    rs.save("2026-07-03", [{"start": "09:00", "end": "12:00", "kategorie": "A"}])
    rs.delete("2026-07-03")
    return rs


def test_reservations_never_reconciled_drops_tombstones(tmp_path):
    rs = _reservations_with_tombstone(tmp_path)
    settings = _settings(tmp_path, gcal_enabled=False, last_calendar_sync_at="")
    assert drop_orphan_reservation_tombstones(rs, settings) == 1
    assert "2026-07-03" not in rs.get_all_raw()
    assert "2026-07-01" in rs.get_all_raw()


def test_reservations_gcal_enabled_keeps_tombstones(tmp_path):
    rs = _reservations_with_tombstone(tmp_path)
    settings = _settings(tmp_path, gcal_enabled=True, last_calendar_sync_at="")
    assert drop_orphan_reservation_tombstones(rs, settings) == 0
    assert rs.get_all_raw()["2026-07-03"]["deleted"] is True


def test_reservations_previously_reconciled_keeps_tombstones(tmp_path):
    """Der Tombstone steuert das Löschen des Kalender-Events — solange je
    abgeglichen wurde, darf er nicht verschwinden."""
    rs = _reservations_with_tombstone(tmp_path)
    settings = _settings(tmp_path, gcal_enabled=False,
                         last_calendar_sync_at="2026-06-30T10:00:00Z")
    assert drop_orphan_reservation_tombstones(rs, settings) == 0
    assert rs.get_all_raw()["2026-07-03"]["deleted"] is True


# --- Startup-Sweep ---------------------------------------------------------

def test_startup_sweep_covers_both_stores(tmp_path):
    """Der Sweep aus main() muss BEIDE Stores anfassen — ein vergessener wäre
    von aussen nicht zu sehen, die Datei wüchse einfach weiter."""
    st = _storage_with_tombstone(tmp_path)
    rs = _reservations_with_tombstone(tmp_path)
    settings = _settings(tmp_path, sync_enabled=False, last_pull_at="",
                         gcal_enabled=False, last_calendar_sync_at="")
    assert main_module._sweep_orphan_tombstones(st, rs, settings, str(tmp_path)) == 2
    assert "2026-07-02" not in st.get_all_raw()
    assert "2026-07-03" not in rs.get_all_raw()


def test_startup_sweep_is_noop_for_synced_setup(tmp_path):
    st = _storage_with_tombstone(tmp_path)
    rs = _reservations_with_tombstone(tmp_path)
    settings = _settings(tmp_path, sync_enabled=True, last_pull_at="",
                         gcal_enabled=True, last_calendar_sync_at="")
    assert main_module._sweep_orphan_tombstones(st, rs, settings, str(tmp_path)) == 0
    assert st.get_all_raw()["2026-07-02"]["deleted"] is True
    assert rs.get_all_raw()["2026-07-03"]["deleted"] is True


def test_startup_sweep_handles_stores_independently(tmp_path):
    """Sync aus, gcal an: nur die Storage-Tombstones dürfen fallen."""
    st = _storage_with_tombstone(tmp_path)
    rs = _reservations_with_tombstone(tmp_path)
    settings = _settings(tmp_path, sync_enabled=False, last_pull_at="",
                         gcal_enabled=True, last_calendar_sync_at="")
    assert main_module._sweep_orphan_tombstones(st, rs, settings, str(tmp_path)) == 1
    assert "2026-07-02" not in st.get_all_raw()
    assert rs.get_all_raw()["2026-07-03"]["deleted"] is True


# --- F: persistenter Marker schlägt einen settings.json-Reset --------------

def test_startup_sweep_skips_when_marker_present(tmp_path):
    """Der F-Fall: settings.json wurde (z.B. per M4-Quarantäne) auf Defaults
    zurückgesetzt und sieht wie 'nie gesynct/abgeglichen' aus. Der persistente
    Marker beweist das Gegenteil — die Tombstones bleiben."""
    st = _storage_with_tombstone(tmp_path)
    rs = _reservations_with_tombstone(tmp_path)
    settings = _settings(tmp_path, sync_enabled=False, last_pull_at="",
                         gcal_enabled=False, last_calendar_sync_at="")
    sync_history.mark_synced(str(tmp_path))
    sync_history.mark_reconciled(str(tmp_path))
    assert main_module._sweep_orphan_tombstones(st, rs, settings, str(tmp_path)) == 0
    assert st.get_all_raw()["2026-07-02"]["deleted"] is True
    assert rs.get_all_raw()["2026-07-03"]["deleted"] is True


def test_startup_sweep_marker_gates_each_store(tmp_path):
    """Marker nur für den Drive-Sync gesetzt: die Storage-Tombstones bleiben,
    die Reservierungs-Tombstones (nie abgeglichen, kein Marker) fallen."""
    st = _storage_with_tombstone(tmp_path)
    rs = _reservations_with_tombstone(tmp_path)
    settings = _settings(tmp_path, sync_enabled=False, last_pull_at="",
                         gcal_enabled=False, last_calendar_sync_at="")
    sync_history.mark_synced(str(tmp_path))
    assert main_module._sweep_orphan_tombstones(st, rs, settings, str(tmp_path)) == 1
    assert st.get_all_raw()["2026-07-02"]["deleted"] is True   # Marker -> behalten
    assert "2026-07-03" not in rs.get_all_raw()                # kein Marker -> gefallen
