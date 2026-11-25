"""Regeln der Slot-Notiz: bereinigen, prüfen, Notizen am Eintrag."""

import json
import pathlib

import pytest

from src import slot_notes as sn
from src.slot_notes import NoteError

_PATH = pathlib.Path(__file__).parent.parent / "pwa" / "test" / "fixtures" / "note-cases.json"
CASES = json.loads(_PATH.read_text(encoding="utf-8"))


def _slot(start, end="12:00", **extra):
    return {"start": start, "end": end, "pause": 0, "kategorie": "", **extra}


def test_fixture_max_len_ist_die_konstante():
    assert CASES["max_len"] == sn.MAX_NOTE_LEN == 200


@pytest.mark.parametrize("case", CASES["clean"])
def test_clean_note(case):
    assert sn.clean_note(case["in"]) == case["out"]


@pytest.mark.parametrize("case", CASES["check"])
def test_check_note(case):
    if case["ok"]:
        assert sn.check_note(case["in"]) == case["out"]
    else:
        with pytest.raises(NoteError):
            sn.check_note(case["in"])


@pytest.mark.parametrize("case", CASES["group"])
def test_group_key(case):
    assert sn.group_key(case["in"]) == case["key"]


@pytest.mark.parametrize("case", CASES["suggestions"])
def test_suggestions_fixture(case):
    # Die Fixture enthält einen gelöschten Tag (Tombstone) nur für die PWA; die App-Form kennt ihn nicht.
    days = {k: v for k, v in case["days"].items() if not v.get("deleted")}
    kwargs = {"limit": case["limit"]} if "limit" in case else {}
    assert sn.suggestions(days, case["kategorie"], **kwargs) == case["out"]


def test_check_note_meldungen():
    with pytest.raises(NoteError) as e:
        sn.check_note(5)
    assert e.value.message == "notiz muss Text sein."
    with pytest.raises(NoteError) as e:
        sn.check_note("a\nb")
    assert e.value.message == "notiz darf keine Steuerzeichen enthalten."
    with pytest.raises(NoteError) as e:
        sn.check_note("x" * 201)
    assert e.value.message == "notiz darf höchstens 200 Zeichen haben."


@pytest.mark.parametrize("text", ["a\u2028b", "a\u2029b"])
def test_line_separators_are_rejected_like_control_characters(text):
    with pytest.raises(NoteError) as e:
        sn.check_note(text)
    assert e.value.message == "notiz darf keine Steuerzeichen enthalten."


def test_has_key():
    assert sn.has_key({"notes": "kaputt"})
    assert not sn.has_key({"slots": []})


def test_notes_of_filtert():
    entry = {
        "slots": [_slot("08:00")],
        "notes": {"08:00": " K ", "09:00": "x", 5: "y", "08:00x": 1},
    }
    assert sn.notes_of(entry) == {"08:00": "K"}


@pytest.mark.parametrize("notes", ["kaputt", None, 5, [], {"08:00": 3}, {"08:00": "  "}])
def test_notes_of_fremddaten(notes):
    assert sn.notes_of({"slots": [_slot("08:00")], "notes": notes}) == {}


def test_notes_of_ohne_schluessel_und_kaputte_slots():
    assert sn.notes_of({"slots": [_slot("08:00")]}) == {}
    assert sn.notes_of({"slots": "x", "notes": {"08:00": "K"}}) == {}
    assert sn.notes_of({"slots": [None, 3], "notes": {"08:00": "K"}}) == {}


def test_with_notes_gleiche_startzeit_beide_und_start_none_keine():
    slots = [_slot("08:00"), _slot("08:00", "10:00"), _slot(None)]
    out = sn.with_notes(slots, {"08:00": "K"})
    assert [s.get("notiz") for s in out] == ["K", "K", None]
    assert "notiz" not in slots[0]


def test_with_notes_verwirft_mitgebrachte_notiz():
    out = sn.with_notes([_slot("08:00", notiz="alt"), _slot("09:00", notiz="x")], {"08:00": "K"})
    assert out[0]["notiz"] == "K"
    assert "notiz" not in out[1]


def test_effective_slots_erbt_bei_gleichem_start():
    old = [_slot("08:00", notiz="K")]
    assert sn.effective_slots([_slot("08:00", "13:00")], old)[0]["notiz"] == "K"


def test_effective_slots_leere_notiz_erbt_nicht():
    old = [_slot("08:00", notiz="K")]
    out = sn.effective_slots([_slot("08:00", notiz="")], old)
    assert "notiz" not in out[0]


def test_effective_slots_geaenderte_startzeit_erbt_nicht():
    old = [_slot("08:00", notiz="K")]
    assert "notiz" not in sn.effective_slots([_slot("08:30")], old)[0]


def test_effective_slots_eigene_notiz_bereinigt_und_start_none():
    out = sn.effective_slots([_slot("08:00", notiz=" A\n"), _slot(None)], [_slot(None, notiz="x")])
    assert out[0]["notiz"] == "A"
    assert "notiz" not in out[1]


def test_notes_from_slots():
    assert sn.notes_from_slots([_slot("08:00", notiz="K"), _slot("09:00")]) == {"08:00": "K"}


def _entry(slots, notes=None, stamp="2026-11-03T16:02:11Z", **extra):
    e = {"slots": slots, "modified_at": stamp, "device_id": "d", "deleted": False, **extra}
    if notes is not None:
        e["notes"] = notes
    return e


def test_supplement_uebernimmt_notizen_beschraenkt():
    entry = _entry([_slot("08:00")])
    other = _entry([_slot("08:00"), _slot("09:00")], {"08:00": "K", "09:00": "L"})
    out = sn.supplement(entry, other)
    assert out is not None and out["notes"] == {"08:00": "K"}
    assert "notes" not in entry


def test_supplement_leer_wenn_keine_startzeit_passt():
    out = sn.supplement(_entry([_slot("08:00")]), _entry([_slot("09:00")], {"09:00": "L"}))
    assert out is not None and out["notes"] == {}


def test_supplement_none_faelle():
    base = _entry([_slot("08:00")])
    withn = _entry([_slot("08:00")], {"08:00": "K"})
    assert sn.supplement(withn, withn) is None
    assert sn.supplement(base, base) is None
    assert sn.supplement(base, {**withn, "deleted": True}) == {**base, "notes": {}}
    assert sn.supplement({**base, "deleted": True}, withn) is None
    assert sn.supplement({**base, "modified_at": ""}, withn) is None


def test_supplement_gegen_tombstone_mit_schluessel_setzt_leere_notizen():
    entry = _entry([_slot("08:00")])
    tombstone = _entry([], {}, deleted=True)
    out = sn.supplement(entry, tombstone)
    assert out == {**entry, "notes": {}}
    assert "notes" not in entry


def test_supplement_gegen_tombstone_ohne_schluessel_gibt_nichts():
    assert sn.supplement(_entry([_slot("08:00")]), _entry([], deleted=True)) is None


def test_supplement_eines_geloeschten_eintrags_gibt_nichts():
    tombstone = {**_entry([]), "deleted": True}
    for other in (_entry([_slot("08:00")], {"08:00": "K"}), _entry([], {}, deleted=True),
                  _entry([_slot("08:00")])):
        assert sn.supplement(tombstone, other) is None


def test_supplement_gegen_tombstone_mit_nicht_anhebbarem_stempel_gibt_nichts():
    tombstone = _entry([], {}, deleted=True)
    for stamp in ("", "9999-12-31T23:59:59Z", "0999-01-01T00:00:00Z", None):
        assert sn.supplement({**_entry([_slot("08:00")]), "modified_at": stamp}, tombstone) is None


def test_bump_stamp():
    assert sn.bump_stamp("2026-11-03T23:59:59Z") == "2026-11-04T00:00:00Z"
    for bad in ("", None, "2026-11-03 10:00", 5):
        assert sn.bump_stamp(bad) is None


def _res(slots, notes=None, **extra):
    r = {"slots": slots, **extra}
    if notes is not None:
        r["notes"] = notes
    return r


def test_resolution_geloescht():
    assert sn.resolution_notes({"deleted": True, "slots": []}, [], None) is None


def test_resolution_eigene_notes():
    res = _res([_slot("08:00")], {"08:00": "K", "09:00": "x"})
    assert sn.resolution_notes(res, [], {"notes": {"08:00": "Z"}}) == {"08:00": "K"}


def test_resolution_kandidat_ohne_schluessel_borgt_von_anderem():
    a = _entry([_slot("08:00", "12:00")], {"08:00": "K"}, "2026-11-03T10:00:00Z", device_id="a")
    b = _entry([_slot("08:00", "12:00")], None, "2026-11-03T11:00:00Z", device_id="b")
    res = _res([_slot("08:00", "12:00")])
    assert sn.resolution_notes(res, [a, b], None) == {"08:00": "K"}


def test_resolution_kandidat_ohne_schluessel_borgt_beschraenkt():
    a = _entry([_slot("08:00"), _slot("09:00")], {"08:00": "K", "09:00": "L"}, device_id="a")
    b = _entry([_slot("08:00")], None, "2026-11-03T17:00:00Z", device_id="b")
    assert sn.resolution_notes(_res([_slot("08:00")]), [a, b], None) == {"08:00": "K"}


def test_resolution_passender_kandidat_mit_schluessel_gewinnt():
    a = _entry([_slot("08:00")], {"08:00": "KA"}, device_id="a")
    res = _res([_slot("08:00")])
    assert sn.resolution_notes(res, [a], {"notes": {"08:00": "KB"}, "slots": [_slot("08:00")]}) == {
        "08:00": "KA"
    }


def test_resolution_mehrere_passende_der_juengste():
    a = _entry([_slot("08:00")], {"08:00": "KA"}, "2026-11-03T10:00:00Z", device_id="a")
    b = _entry([_slot("08:00")], {"08:00": "KB"}, "2026-11-03T11:00:00Z", device_id="b")
    assert sn.resolution_notes(_res([_slot("08:00")]), [a, b], None) == {"08:00": "KB"}


def test_resolution_reihenfolgeunabhaengiger_slotvergleich():
    a = _entry([_slot("09:00"), _slot("08:00")], {"08:00": "K"})
    assert sn.resolution_notes(_res([_slot("08:00"), _slot("09:00")]), [a], None) == {"08:00": "K"}


def test_resolution_kein_kandidat_nimmt_replaced_beschraenkt():
    cand = _entry([_slot("10:00")], {"10:00": "X"})
    replaced = _entry([_slot("08:00"), _slot("09:00")], {"08:00": "K", "09:00": "L"})
    assert sn.resolution_notes(_res([_slot("08:00")]), [cand], replaced) == {"08:00": "K"}


def test_resolution_kein_kandidat_replaced_ohne_schluessel():
    assert sn.resolution_notes(_res([_slot("08:00")]), [], _entry([_slot("08:00")])) is None
    assert sn.resolution_notes(_res([_slot("08:00")]), [], None) is None


def test_resolution_passender_ohne_schluessel_niemand_hat_ihn_faellt_auf_replaced():
    a = _entry([_slot("08:00")], None, device_id="a")
    replaced = _entry([_slot("08:00")], {"08:00": "R"})
    assert sn.resolution_notes(_res([_slot("08:00")]), [a], replaced) == {"08:00": "R"}
    assert sn.resolution_notes(_res([_slot("08:00")]), [a], None) is None


def test_resolution_ignoriert_nicht_objekte():
    assert sn.resolution_notes(_res([_slot("08:00")]), [None, 5, "x"], None) is None


def test_bump_stamp_at_the_end_of_the_range_is_none():
    assert sn.bump_stamp("9999-12-31T23:59:59Z") is None


def test_bump_stamp_before_year_1000_is_none():
    # strftime schreibt solche Jahre je nach Plattform ohne führende Nullen; der Stempel
    # sortierte dann als Text hinter jeden echten.
    assert sn.bump_stamp("0500-01-01T00:00:00Z") is None


def test_resolution_matches_a_candidate_with_the_defaults_of_the_merge_signature():
    """`pause` fehlt → 0, `kategorie` fehlt → "" (wie `sync._slots_signature`)."""
    cand = {"slots": [{"start": "08:00", "end": "12:00"}], "notes": {"08:00": "K"},
            "modified_at": "2026-11-03T10:00:00Z", "device_id": "A"}
    res = {"slots": [{"start": "08:00", "end": "12:00", "pause": 0, "kategorie": ""}]}
    assert sn.resolution_notes(res, [cand], {"slots": [], "notes": {"08:00": "R"}}) == {"08:00": "K"}


def test_resolution_signature_with_mixed_value_types_does_not_raise():
    cand = {"slots": [{"start": None, "end": 5}, {"start": "08:00", "end": "12:00"}],
            "notes": {"08:00": "K"}}
    res = {"slots": [{"start": "08:00", "end": "12:00"}, {"start": None, "end": 5}]}
    assert sn.resolution_notes(res, [cand], None) == {"08:00": "K"}


def test_label_joins_category_and_note():
    assert sn.label("Montage", "Kunde Mustermann") == "Montage · Kunde Mustermann"
    assert sn.label("Montage", "") == "Montage"
    assert sn.label("", "Kunde Mustermann") == "Kunde Mustermann"
    assert sn.label(None, None) == ""
    assert sn.label("Montage", "a\nb") == "Montage · ab"


def test_shorten_counts_code_points():
    assert sn.shorten("x" * 60) == "x" * 60
    assert sn.shorten("x" * 61) == "x" * 59 + "…"
    assert sn.shorten("😀" * 61) == "😀" * 59 + "…"


def test_suggestions_newest_first_once_per_group_key():
    entries = {
        "2026-11-02": {"slots": [{"start": "08:00", "kategorie": "Montage", "notiz": "Kunde Müller"}]},
        "2026-11-03": {"slots": [{"start": "08:00", "kategorie": "Montage", "notiz": "kunde müller"},
                                 {"start": "13:00", "kategorie": "Büro", "notiz": "Ablage"}]},
        "2026-11-04": {"slots": [{"start": "08:00", "kategorie": "Montage", "notiz": "Kunde Mustermann"},
                                 {"start": "13:00", "kategorie": "Montage"}]},
    }
    assert sn.suggestions(entries, "Montage") == ["Kunde Mustermann", "kunde müller", "Ablage"]
    assert sn.suggestions(entries, "Büro") == ["Ablage", "Kunde Mustermann", "kunde müller"]
    assert sn.suggestions(entries, "") == ["Kunde Mustermann", "kunde müller", "Ablage"]
    assert sn.suggestions(entries, "Montage", limit=1) == ["Kunde Mustermann"]


def test_suggestions_offer_a_note_of_another_category_once():
    # Dieselbe Notiz unter der gewählten und einer anderen Kategorie steht nur einmal da, in der
    # Schreibweise und an der Stelle der gewählten Kategorie.
    entries = {
        "2026-11-02": {"slots": [{"start": "08:00", "kategorie": "Montage", "notiz": "Außendienst Kundentermin A"}]},
        "2026-11-05": {"slots": [{"start": "08:00", "kategorie": "", "notiz": "außendienst kundentermin a"},
                                 {"start": "13:00", "kategorie": "", "notiz": "Büro"}]},
    }
    assert sn.suggestions(entries, "Montage") == ["Außendienst Kundentermin A", "Büro"]
    assert sn.suggestions(entries, "Service") == ["außendienst kundentermin a", "Büro"]


def test_suggestions_and_has_notes_survive_foreign_shapes():
    entries = {"2026-11-02": {"slots": "kaputt"}, "2026-11-03": {}, "2026-11-04": {"slots": [None, {"notiz": 5}]}}
    assert sn.suggestions(entries, "") == []
    assert sn.has_notes(entries) is False
    assert sn.has_notes({"2026-11-02": {"slots": [{"start": "08:00", "notiz": " x "}]}}) is True


def test_label_keeps_the_category_as_stored():
    assert sn.label(" Büro ", "") == " Büro "
    assert sn.label(5, "x") == "x"
