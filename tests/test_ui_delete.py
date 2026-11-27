from src.grid_renderer import GridRenderer
from src.ui import _delete_action, _delete_options


def test_delete_action_none_when_type_not_selected():
    assert _delete_action([{"start": "08:00"}], {"reservation:all"}, "entry") == ("none", None)


def test_delete_action_whole_type():
    assert _delete_action([{"start": "08:00"}], {"entry:all"}, "entry") == ("delete", None)


def test_delete_action_partial_keeps_rest():
    slots = [{"s": 0}, {"s": 1}, {"s": 2}]
    action, keep = _delete_action(slots, {"entry:1"}, "entry")
    assert action == "save"
    assert keep == [{"s": 0}, {"s": 2}]


def test_delete_action_all_indices_selected_becomes_delete():
    slots = [{"s": 0}, {"s": 1}]
    assert _delete_action(slots, {"entry:0", "entry:1"}, "entry") == ("delete", None)


def test_delete_action_prefix_isolation():
    slots = [{"s": 0}, {"s": 1}]
    # Nur Reservierungs-Keys gewählt → entry nicht betroffen.
    assert _delete_action(slots, {"reservation:0"}, "entry") == ("none", None)
    # Reservierungs-Teillöschung trifft den reservation-Prefix.
    action, keep = _delete_action(slots, {"reservation:0"}, "reservation")
    assert action == "save"
    assert keep == [{"s": 1}]


def test_delete_action_mixed_selection():
    entry_slots = [{"s": 0}, {"s": 1}]
    res_slots = [{"r": 0}]
    selected = {"entry:0", "reservation:all"}
    assert _delete_action(entry_slots, selected, "entry") == ("save", [{"s": 1}])
    assert _delete_action(res_slots, selected, "reservation") == ("delete", None)


def test_delete_options_chronologisch_mit_gespeichertem_index():
    # #520: Anzeige sortiert, der Schlüssel zeigt aber auf die gespeicherte Position —
    # sonst löschte ein Häkchen am 9–11-Slot den 11–13-Slot.
    from src.ui import _delete_options
    slots = [{"start": "11:00", "end": "13:00"}, {"start": "09:00", "end": "11:00"}]
    options = _delete_options(slots, "entry", "Arbeitszeit", lambda s: f"{s['start']}-{s['end']}")
    assert options == [("entry:1", "Arbeitszeit  09:00-11:00"),
                       ("entry:0", "Arbeitszeit  11:00-13:00")]
    # Und das Löschen des ersten angezeigten Slots lässt den anderen stehen.
    action, keep = _delete_action(slots, {"entry:1"}, "entry")
    assert (action, keep) == ("save", [{"start": "11:00", "end": "13:00"}])


def test_delete_options_ein_slot_ist_der_ganze_typ():
    from src.ui import _delete_options
    assert _delete_options([{"start": "09:00"}], "entry", "Arbeitszeit", str) == [
        ("entry:all", "Arbeitszeit")]
    assert _delete_options([], "entry", "Arbeitszeit", str) == []


def test_delete_options_folgen_dem_slot_modus_mit_gespeichertem_index():
    from src.ui import _delete_options
    slots = [{"start": "09:00", "kategorie": "Zeta"}, {"start": "13:00", "kategorie": "Alpha"}]
    fmt = lambda s: s["kategorie"]  # noqa: E731
    assert _delete_options(slots, "entry", "A", fmt, "category") == [
        ("entry:1", "A  Alpha"), ("entry:0", "A  Zeta")]
    assert _delete_options(slots[::-1], "entry", "A", fmt, "custom") == [
        ("entry:0", "A  Alpha"), ("entry:1", "A  Zeta")]


def test_delete_options_show_notes_and_keep_them():
    slots = [{"start": "08:00", "end": "12:00", "pause": 0, "kategorie": "Montage", "notiz": "Kunde Mustermann"},
             {"start": "13:00", "end": "17:00", "pause": 0, "kategorie": "Büro"}]
    options = _delete_options(slots, "entry", "Arbeitszeit", GridRenderer._fmt_slot_line)
    assert options[0] == ("entry:0", "Arbeitszeit  08:00-12:00  Montage · Kunde Mustermann")
    assert _delete_action(slots, {"entry:1"}, "entry") == ("save", [slots[0]])


def test_delete_day_offers_whole_sick_block(tmp_path):
    from src.sick_days import SickStore
    from src.ui import _sick_delete_option
    store = SickStore(str(tmp_path / "sick.json"), device_id="d")
    store.save_range({"2026-03-02": 480, "2026-03-03": 480, "2026-03-04": 0})
    block = store.block_for("2026-03-03")
    assert _sick_delete_option(block) == (
        "sick:2026-03-02", "Krankheit 02.03.2026 – 04.03.2026")
    store.delete_days(block.days)
    assert store.blocks() == []
