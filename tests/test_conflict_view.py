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
    assert f("recipient", "") == cv.empty_text()
    assert f("recipient", None) == cv.empty_text()
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
    assert cards[0].title == cv.own_title()
    assert cards[0].device_line == "Sven-PC"


def test_other_card_shows_device_name_instead_of_generic_title():
    c = _entry(_cand(OWN, "a", [_slot()]), _cand(OTHER, "b", [_slot()]))
    other = cv.build_cards(c, REGISTRY, OWN, "Sven-PC")[1]
    assert other.title == "Laptop"
    assert other.device_line == ""


def test_other_card_without_known_name_shows_short_id():
    c = _entry(_cand(OWN, "a", [_slot()]), _cand("fremdes-geraet-1", "b", [_slot()]))
    other = cv.build_cards(c, REGISTRY, OWN, "")[1]
    assert other.title == cv.other_title()
    assert other.device_line == "fremdes-…"


def test_own_card_without_name_falls_back_to_short_id():
    c = _entry(_cand(OWN, "a", [_slot()]), _cand(OTHER, "b", [_slot()]))
    own = cv.build_cards(c, REGISTRY, OWN, "")[0]
    assert own.device_line == "6800a51a…"


def test_missing_or_garbage_device_ids_do_not_raise():
    c = _entry(_cand(None, "a", [_slot()]), _cand(["x"], "b", [_slot()]))
    cards = cv.build_cards(c, "kein-dict", OWN, "")
    assert [x.title for x in cards] == [cv.other_title(), cv.other_title()]
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
    assert other.slots[0].category.text == cv.no_category()


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
    assert own.deleted == cv.Field(cv.deleted_text(), True)
    assert own.slots == ()
    assert all(f.differs for f in (other.slots[0].start, other.slots[0].end))


def test_both_deleted_is_not_a_difference():
    c = _entry(_cand(OWN, "a", deleted=True), _cand(OTHER, "b", deleted=True))
    assert all(x.deleted == cv.Field(cv.deleted_text(), False)
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
