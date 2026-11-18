"""Reihenfolge der Slots eines Tages (#520): chronologisch nach Startzeit."""

from src.slot_order import ordered, sorted_slots


def _slot(start, end, kat="", pause=0):
    return {"start": start, "end": end, "pause": pause, "kategorie": kat}


def test_issue_beispiel_spaeter_angelegter_fruehere_slot_steht_vorn():
    # #520: 9–11 gelöscht und neu angelegt → steht hinter 11–13.
    slots = [_slot("11:00", "13:00"), _slot("09:00", "11:00")]
    assert [s["start"] for s in sorted_slots(slots)] == ["09:00", "11:00"]


def test_ordered_liefert_den_urspruenglichen_index_mit():
    slots = [_slot("11:00", "13:00"), _slot("09:00", "11:00")]
    assert [(i, s["start"]) for i, s in ordered(slots)] == [(1, "09:00"), (0, "11:00")]


def test_gleiche_startzeit_frueheres_ende_zuerst():
    slots = [_slot("09:00", "12:00"), _slot("09:00", "10:00")]
    assert [s["end"] for s in sorted_slots(slots)] == ["10:00", "12:00"]


def test_gleiche_zeit_dann_nach_kategorie_dann_nach_listenposition():
    slots = [
        _slot("09:00", "10:00", "B"),
        _slot("09:00", "10:00", "A"),
        _slot("09:00", "10:00", "A", pause=5),
    ]
    assert [(i, s["kategorie"]) for i, s in ordered(slots)] == [(1, "A"), (2, "A"), (0, "B")]


def test_unlesbare_startzeit_kommt_ans_ende_in_listenreihenfolge():
    slots = [_slot(None, "10:00"), _slot("08:00", "09:00"), {"end": "11:00"}]
    assert [i for i, _ in ordered(slots)] == [1, 0, 2]


def test_leere_liste_und_eingabe_bleibt_unveraendert():
    assert ordered([]) == []
    slots = [_slot("11:00", "12:00"), _slot("09:00", "10:00")]
    snapshot = [dict(s) for s in slots]
    sorted_slots(slots)
    assert slots == snapshot


def test_slots_sind_dieselben_objekte():
    # Reservierungs-Slots tragen Zusatzfelder (gcal_event_id, send_reminder_minutes):
    # sortiert wird nur die Reihenfolge, nie der Inhalt.
    slot = {**_slot("09:00", "10:00"), "gcal_event_id": "abc", "send_reminder_minutes": 15}
    assert sorted_slots([_slot("11:00", "12:00"), slot])[0] is slot


def test_gemeinsame_fixture_mit_der_pwa():
    # Gegenstück: pwa/test/slot-order.test.js liest dieselbe Datei.
    import json
    import pathlib
    path = pathlib.Path(__file__).parent.parent / "pwa" / "test" / "fixtures" / "slot-order-cases.json"
    cases = json.loads(path.read_text(encoding="utf-8"))["chrono"]
    assert cases
    for row in cases:
        assert [i for i, _ in ordered(row["slots"])] == row["order"], row["name"]
