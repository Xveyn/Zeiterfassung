"""Anzeige-Modell des Konfliktdialogs (Tk-frei)."""

from src import conflict_view as cv
from src.settings import SYNCED_SETTING_KEYS

OWN = "6800a51a-own"
OTHER = "34a0480f-other"
REGISTRY = {OTHER: {"name": "Laptop", "updated_at": "2026-06-01T00:00:00Z"}}


def _slot(start="09:00", end="17:00", pause=30, kat="Office"):
    return {"start": start, "end": end, "pause": pause, "kategorie": kat}


def _cand(device, stamp, slots=None, deleted=False, **extra):
    c = {"device_id": device, "modified_at": stamp, "deleted": deleted,
         "slots": slots if slots is not None else []}
    c.update(extra)
    return c


def _entry(a, b, key="2026-06-01"):
    return {"id": "c1", "kind": "entry", "key": key, "candidates": [a, b]}


def _setting(a, b, key="workweek_only"):
    return {"id": "c2", "kind": "setting", "key": key, "candidates": [a, b]}


# --- Titel und Liste ---------------------------------------------------------

def test_titles_use_weekday_and_german_date():
    c = _entry(_cand(OWN, "x"), _cand(OTHER, "y"))
    assert cv.conflict_title(c) == "Montag, 01.06.2026"
    assert cv.list_label(c) == "Mo, 01.06.2026"


def test_unparsable_entry_key_is_shown_raw():
    c = _entry(_cand(OWN, "x"), _cand(OTHER, "y"), key="kaputt")
    assert cv.conflict_title(c) == "kaputt"
    assert cv.list_label(c) == "kaputt"


def test_setting_titles_are_plain_language_with_raw_fallback():
    assert cv.conflict_title(_setting({}, {})) == "Nur Werktage"
    assert cv.list_label(_setting({}, {}, key="unbekannt_x")) == "unbekannt_x"


def test_every_synced_setting_has_a_label():
    # Neuer synchronisierter Schlüssel ohne Klartext fiele im Dialog auf den
    # rohen Schlüssel zurück — dieser Test erinnert daran, ihn zu benennen.
    assert set(SYNCED_SETTING_KEYS) <= set(cv.SETTING_LABELS)


def test_group_conflicts_splits_and_sorts():
    e2 = _entry({}, {}, key="2026-06-12")
    e1 = _entry({}, {}, key="2026-06-02")
    s2 = _setting({}, {}, key="workweek_only")
    s1 = _setting({}, {}, key="werkstudent_limit_enabled")
    entries, settings = cv.group_conflicts([e2, s2, e1, s1])
    assert [c["key"] for c in entries] == ["2026-06-02", "2026-06-12"]
    assert [c["key"] for c in settings] == ["workweek_only",
                                            "werkstudent_limit_enabled"]


# --- Werte ------------------------------------------------------------------

def test_format_setting_value():
    f = cv.format_setting_value
    assert f("workweek_only", True) == "an"
    assert f("workweek_only", False) == "aus"
    assert f("recipient", "") == cv.EMPTY_TEXT
    assert f("recipient", None) == cv.EMPTY_TEXT
    assert f("werkstudent_limit_start", "2026-04-01") == "01.04.2026"
    assert f("hourly_rate", 12.5) == "12,50 €"
    assert f("werkstudent_limit_max_hours", 20.0) == "20 h"
    assert f("categories", ["Büro", "Home"]) == "Büro, Home"
    assert f("category_times", {"Büro": {}}) == "Büro"
    assert f("name", "Sven") == "Sven"


# --- Karten: Gerätenamen -----------------------------------------------------

def test_own_card_comes_first_and_keeps_candidate_index():
    c = _entry(_cand(OTHER, "2026-06-23T15:53:00Z", [_slot("09:30", "16:00", 30, "")]),
               _cand(OWN, "2026-06-26T20:00:00Z", [_slot()]))
    cards = cv.build_cards(c, REGISTRY, OWN, "Sven-PC")
    assert [x.is_own for x in cards] == [True, False]
    assert [x.index for x in cards] == [1, 0]
    assert cards[0].title == cv.OWN_TITLE
    assert cards[0].device_line == "Sven-PC"


def test_other_card_shows_device_name_instead_of_generic_title():
    c = _entry(_cand(OWN, "a", [_slot()]), _cand(OTHER, "b", [_slot()]))
    other = cv.build_cards(c, REGISTRY, OWN, "Sven-PC")[1]
    assert other.title == "Laptop"
    assert other.device_line == ""


def test_other_card_without_known_name_shows_short_id():
    c = _entry(_cand(OWN, "a", [_slot()]), _cand("fremdes-geraet-1", "b", [_slot()]))
    other = cv.build_cards(c, REGISTRY, OWN, "")[1]
    assert other.title == cv.OTHER_TITLE
    assert other.device_line == "fremdes-…"


def test_own_card_without_name_falls_back_to_short_id():
    c = _entry(_cand(OWN, "a", [_slot()]), _cand(OTHER, "b", [_slot()]))
    own = cv.build_cards(c, REGISTRY, OWN, "")[0]
    assert own.device_line == "6800a51a…"


def test_missing_or_garbage_device_ids_do_not_raise():
    c = _entry(_cand(None, "a", [_slot()]), _cand(["x"], "b", [_slot()]))
    cards = cv.build_cards(c, "kein-dict", OWN, "")
    assert [x.title for x in cards] == [cv.OTHER_TITLE, cv.OTHER_TITLE]
    assert [x.device_line for x in cards] == ["", ""]


def test_two_other_devices_keep_candidate_order():
    c = _entry(_cand("aaaa-1111", "a", [_slot()]), _cand("bbbb-2222", "b", [_slot()]))
    assert [x.index for x in cv.build_cards(c, {}, OWN, "")] == [0, 1]


def test_wrong_number_of_candidates_gives_no_cards():
    c = {"id": "x", "kind": "entry", "key": "2026-06-01", "candidates": [{}]}
    assert cv.build_cards(c, {}, OWN, "") == []
    assert cv.build_cards({"candidates": "kaputt"}, {}, OWN, "") == []


# --- Karten: Zeitstempel -----------------------------------------------------

def test_modified_text_and_newer_marker():
    c = _entry(_cand(OWN, "2026-06-26T20:00:00Z", [_slot()]),
               _cand(OTHER, "2026-06-23T15:53:00Z", [_slot()]))
    own, other = cv.build_cards(c, REGISTRY, OWN, "")
    assert own.modified == "geändert 26.06.2026 20:00"
    assert own.newer is True
    assert other.newer is False


def test_modified_text_is_in_local_time(monkeypatch):
    # #534: `modified_at` steht in UTC, die Karte zeigt die Ortszeit (Datum eingeschlossen).
    import datetime
    monkeypatch.setattr("src.time_utils.local_zone", lambda: datetime.timezone(datetime.timedelta(hours=2)))
    c = _entry(_cand(OWN, "2026-06-26T22:30:00Z", [_slot()]),
               _cand(OTHER, "2026-06-23T15:53:00Z", [_slot()]))
    own, other = cv.build_cards(c, REGISTRY, OWN, "")
    assert own.modified == "geändert 27.06.2026 00:30"
    assert other.modified == "geändert 23.06.2026 17:53"


def test_a_timestamp_that_is_not_a_string_gives_no_modified_text():
    c = _entry(_cand(OWN, 12345678901, [_slot()]), _cand(OTHER, {"x": 1}, [_slot()]))
    assert [x.modified for x in cv.build_cards(c, REGISTRY, OWN, "")] == ["", ""]


def test_equal_or_missing_timestamps_mark_nobody_newer():
    same = _entry(_cand(OWN, "t", [_slot()]), _cand(OTHER, "t", [_slot()]))
    assert [x.newer for x in cv.build_cards(same, REGISTRY, OWN, "")] == [False, False]
    none = _entry(_cand(OWN, None, [_slot()]), _cand(OTHER, "", [_slot()]))
    cards = cv.build_cards(none, REGISTRY, OWN, "")
    assert [x.newer for x in cards] == [False, False]
    assert [x.modified for x in cards] == ["", ""]


# --- Karten: Unterschiede ----------------------------------------------------

def test_slot_differences_are_flagged_per_field():
    c = _entry(_cand(OWN, "a", [_slot("09:00", "17:00", 30, "Office")]),
               _cand(OTHER, "b", [_slot("09:30", "16:00", 30, "")]))
    own, other = cv.build_cards(c, REGISTRY, OWN, "")
    s = own.slots[0]
    assert (s.start.differs, s.end.differs, s.category.differs, s.pause.differs) == (
        True, True, True, False)
    assert s.category.text == "Office"
    assert s.pause.text == "Pause 30 min"
    assert other.slots[0].category.text == cv.NO_CATEGORY


def test_identical_slots_flag_nothing():
    c = _entry(_cand(OWN, "a", [_slot()]), _cand(OTHER, "b", [_slot()]))
    for card in cv.build_cards(c, REGISTRY, OWN, ""):
        s = card.slots[0]
        assert not any(f.differs for f in (s.start, s.end, s.category, s.pause))


def test_extra_slot_without_counterpart_is_fully_flagged():
    c = _entry(_cand(OWN, "a", [_slot("08:00", "12:00"), _slot("13:00", "17:00")]),
               _cand(OTHER, "b", [_slot("08:00", "12:00")]))
    own = cv.build_cards(c, REGISTRY, OWN, "")[0]
    assert not own.slots[0].start.differs
    assert all(f.differs for f in (own.slots[1].start, own.slots[1].end,
                                   own.slots[1].category, own.slots[1].pause))


def test_zero_pause_reads_as_no_pause():
    c = _entry(_cand(OWN, "a", [_slot(pause=0)]), _cand(OTHER, "b", [_slot()]))
    assert cv.build_cards(c, REGISTRY, OWN, "")[0].slots[0].pause.text == "keine Pause"


def test_deleted_against_edited():
    c = _entry(_cand(OWN, "a", deleted=True), _cand(OTHER, "b", [_slot()]))
    own, other = cv.build_cards(c, REGISTRY, OWN, "")
    assert own.deleted == cv.Field(cv.DELETED_TEXT, True)
    assert own.slots == ()
    assert all(f.differs for f in (other.slots[0].start, other.slots[0].end))


def test_both_deleted_is_not_a_difference():
    c = _entry(_cand(OWN, "a", deleted=True), _cand(OTHER, "b", deleted=True))
    assert all(x.deleted == cv.Field(cv.DELETED_TEXT, False)
               for x in cv.build_cards(c, REGISTRY, OWN, ""))


def test_garbage_slots_do_not_raise():
    c = _entry(_cand(OWN, "a", ["kaputt", {"start": None, "pause": "x"}]),
               _cand(OTHER, "b", "nichts"))
    own = cv.build_cards(c, REGISTRY, OWN, "")[0]
    assert own.slots[1].start.text == "–"
    assert own.slots[1].pause.text == "keine Pause"


def test_setting_cards_carry_the_formatted_value():
    c = _setting({"device_id": OWN, "modified_at": "2026-06-26T20:00:00Z", "value": True},
                 {"device_id": OTHER, "modified_at": "2026-06-23T15:53:00Z", "value": False})
    own, other = cv.build_cards(c, REGISTRY, OWN, "")
    assert own.value == cv.Field("an", True)
    assert other.value == cv.Field("aus", True)
    assert own.slots == () and own.deleted is None


def test_slots_werden_nach_zeit_statt_nach_position_verglichen():
    # #520: dieselben zwei Slots, nur in anderer Listenreihenfolge, sind kein Unterschied.
    a, b = _slot("09:00", "11:00"), _slot("11:00", "13:00")
    c = _entry(_cand(OWN, "x", slots=[b, a]), _cand(OTHER, "y", slots=[a, b]))
    cards = cv.build_cards(c, REGISTRY, OWN, "Sven-PC")
    own = cards[0]
    assert [s.start.text for s in own.slots] == ["09:00", "11:00"]
    assert not any(f.differs for s in own.slots for f in (s.start, s.end, s.category, s.pause))


def test_slot_order_setting_is_shown_with_its_label():
    assert cv.SETTING_LABELS["slot_order_mode"] == "Reihenfolge der Slots"
    assert cv.format_setting_value("slot_order_mode", "category") == "Nach Kategorie"
    assert cv.format_setting_value("slot_order_mode", "chrono") == "Nach Uhrzeit"


# --- Notizen -----------------------------------------------------------------

def _note_cand(device, stamp, note=None, key=True):
    cand = {"device_id": device, "modified_at": stamp, "deleted": False,
            "slots": [{"start": "08:00", "end": "12:00", "pause": 0, "kategorie": "Montage"}]}
    if key:
        cand["notes"] = {"08:00": note} if note else {}
    return cand


def _note_cards(a, b):
    conflict = {"kind": "entry", "key": "2026-11-03", "candidates": [a, b]}
    return cv.build_cards(conflict, {}, "dev-a")


def test_note_differs_is_marked_on_both_cards():
    own, other = _note_cards(_note_cand("dev-a", "2026-11-03T10:00:00Z", "Kunde Mustermann"),
                             _note_cand("dev-b", "2026-11-03T11:00:00Z", "Kunde Müller"))
    assert own.slots[0].note == cv.Field("Kunde Mustermann", True)
    assert other.slots[0].note == cv.Field("Kunde Müller", True)
    assert own.slots[0].category == cv.Field("Montage", False)


def test_keyless_card_shows_the_note_it_inherits():
    own, other = _note_cards(_note_cand("dev-a", "2026-11-03T10:00:00Z", "Kunde Mustermann"),
                             _note_cand("dev-b", "2026-11-03T11:00:00Z", None, key=False))
    assert own.slots[0].note == cv.Field("Kunde Mustermann", False)
    assert other.slots[0].note == cv.Field("Kunde Mustermann", False)


def test_keyless_card_inherits_nothing_at_another_start():
    keyless = _note_cand("dev-b", "2026-11-03T11:00:00Z", None, key=False)
    keyless["slots"] = [{"start": "09:00", "end": "12:00", "pause": 0, "kategorie": "Montage"}]
    own, other = _note_cards(_note_cand("dev-a", "2026-11-03T10:00:00Z", "Kunde Mustermann"),
                             keyless)
    assert other.slots[0].note == cv.Field(cv.NO_NOTE, True)
    assert own.slots[0].note == cv.Field("Kunde Mustermann", True)


def test_keyless_card_against_empty_notes_has_no_note():
    own, other = _note_cards(_note_cand("dev-a", "2026-11-03T10:00:00Z", None, key=True),
                             _note_cand("dev-b", "2026-11-03T11:00:00Z", None, key=False))
    assert own.slots[0].note is None and other.slots[0].note is None


def test_keyless_card_against_deleted_card_has_no_note():
    deleted = {"device_id": "dev-b", "modified_at": "2026-11-03T11:00:00Z", "deleted": True,
               "slots": [], "notes": {}}
    own, _other = _note_cards(_note_cand("dev-a", "2026-11-03T10:00:00Z", None, key=False),
                              deleted)
    assert own.slots[0].note is None


def test_empty_notes_key_against_a_noted_card_reads_keine_notiz():
    own, other = _note_cards(_note_cand("dev-a", "2026-11-03T10:00:00Z", "Kunde Mustermann"),
                             _note_cand("dev-b", "2026-11-03T11:00:00Z", None, key=True))
    assert other.slots[0].note == cv.Field(cv.NO_NOTE, True)
    assert own.slots[0].note == cv.Field("Kunde Mustermann", True)


def test_same_note_is_shown_unmarked():
    own, other = _note_cards(_note_cand("dev-a", "2026-11-03T10:00:00Z", "Kunde Mustermann"),
                             _note_cand("dev-b", "2026-11-03T11:00:00Z", "Kunde Mustermann"))
    assert own.slots[0].note == cv.Field("Kunde Mustermann", False)


def test_cards_without_notes_have_no_note_field():
    own, other = _note_cards(_note_cand("dev-a", "2026-11-03T10:00:00Z", None, key=False),
                             _note_cand("dev-b", "2026-11-03T11:00:00Z", None, key=False))
    assert own.slots[0].note is None and other.slots[0].note is None


def test_foreign_notes_do_not_raise():
    cand = _note_cand("dev-a", "2026-11-03T10:00:00Z")
    cand["notes"] = ["kaputt"]
    cards = _note_cards(cand, _note_cand("dev-b", "2026-11-03T11:00:00Z", "x"))
    assert cards[0].slots[0].note == cv.Field(cv.NO_NOTE, True)


def test_note_against_missing_slot_on_the_other_card_differs():
    a = _note_cand("dev-a", "2026-11-03T10:00:00Z", "Kunde Mustermann")
    b = _note_cand("dev-b", "2026-11-03T11:00:00Z", None, key=False)
    b["slots"] = []
    assert _note_cards(a, b)[0].slots[0].note == cv.Field("Kunde Mustermann", True)


def test_entry_choice_carries_notes_only_with_key():
    keyed = _note_cand("dev-a", "2026-11-03T10:00:00Z", "Kunde Mustermann")
    assert cv.entry_choice(keyed) == {"slots": keyed["slots"], "deleted": False,
                                      "notes": {"08:00": "Kunde Mustermann"}}
    plain = _note_cand("dev-a", "2026-11-03T10:00:00Z", None, key=False)
    assert cv.entry_choice(plain) == {"slots": plain["slots"], "deleted": False}
    assert cv.entry_choice({"slots": [], "deleted": True, "notes": {}}) == {
        "slots": [], "deleted": True}


def test_sick_basis_value_is_shown_in_words():
    assert cv.SETTING_LABELS["sick_hours_basis"] == "Grundlage der Krankheitsstunden"
    assert cv.format_setting_value(
        "sick_hours_basis", "average_3m") == "Durchschnitt der letzten 3 Monate"
