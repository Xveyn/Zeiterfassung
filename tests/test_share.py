import datetime as _dt
import json

import pytest

from src.share import (
    KIND,
    SCHEMA_VERSION,
    ShareValidationError,
    apply_import,
    apply_reservation_import,
    build_share_doc,
    diff_reservations_against_local,
    diff_share_against_local,
    filter_records_by_category,
    filter_records_by_range,
    parse_share_doc,
    serialize_share_doc,
)


def _bytes(obj):
    return json.dumps(obj).encode("utf-8")


def _eslot(start, end, pause=0, kategorie=""):
    return {"start": start, "end": end, "pause": pause, "kategorie": kategorie}


def _rslot(start, end, kategorie=""):
    return {"start": start, "end": end, "kategorie": kategorie}


def _erec(*slots):
    return {"slots": list(slots)}


def _v1(**fields):
    base = {"kind": "zeiterfassung-share", "schema_version": 1}
    base.update(fields)
    return _bytes(base)


def _v2(**fields):
    base = {"kind": "zeiterfassung-share", "schema_version": 2}
    base.update(fields)
    return _bytes(base)


def _v3(**fields):
    base = {"kind": "zeiterfassung-share", "schema_version": 3}
    base.update(fields)
    return _bytes(base)


# --- generische Header-Validierung ---


def test_parse_rejects_broken_json():
    with pytest.raises(ShareValidationError, match="JSON"):
        parse_share_doc(b"{not json")


def test_parse_rejects_non_object_toplevel():
    with pytest.raises(ShareValidationError, match="JSON-Objekt"):
        parse_share_doc(_bytes(["array", "instead"]))


def test_parse_rejects_wrong_kind():
    with pytest.raises(ShareValidationError, match="geteilte Zeiterfassung"):
        parse_share_doc(_bytes({"kind": "something-else", "schema_version": 1, "entries": {}}))


def test_parse_rejects_missing_kind():
    with pytest.raises(ShareValidationError, match="geteilte Zeiterfassung"):
        parse_share_doc(_bytes({"schema_version": 1, "entries": {}}))


def test_parse_rejects_missing_schema_version():
    with pytest.raises(ShareValidationError, match="schema_version"):
        parse_share_doc(_bytes({"kind": "zeiterfassung-share", "entries": {}}))


def test_parse_rejects_future_schema_version():
    with pytest.raises(ShareValidationError, match="neueren Version"):
        parse_share_doc(_bytes({"kind": "zeiterfassung-share", "schema_version": 4, "entries": {}}))


def test_parse_rejects_past_schema_version():
    with pytest.raises(ShareValidationError, match="schema_version"):
        parse_share_doc(_bytes({"kind": "zeiterfassung-share", "schema_version": 0, "entries": {}}))


# --- v1: alte Shape, beim Lesen in Slots gewrappt ---


def test_parse_v1_entries_only_wrapped_into_slots():
    doc = parse_share_doc(_v1(entries={"2026-05-14": {"start": "08:00", "end": "16:00", "pause": 0}}))
    assert doc["schema_version"] == 1
    assert doc["entries"] == {"2026-05-14": _erec(_eslot("08:00", "16:00", 0, ""))}


def test_parse_v1_rejects_missing_entries():
    with pytest.raises(ShareValidationError, match="entries"):
        parse_share_doc(_v1())


def test_parse_v1_rejects_bad_date_key():
    with pytest.raises(ShareValidationError, match="Datum"):
        parse_share_doc(_v1(entries={"not-a-date": {"start": "08:00", "end": "16:00", "pause": 0}}))


def test_parse_v1_rejects_extra_entry_field():
    with pytest.raises(ShareValidationError, match="unbekannt"):
        parse_share_doc(_v1(entries={"2026-05-14": {"start": "08:00", "end": "16:00", "pause": 0, "deleted": True}}))


def test_parse_v1_rejects_missing_entry_field():
    with pytest.raises(ShareValidationError, match="fehlend"):
        parse_share_doc(_v1(entries={"2026-05-14": {"start": "08:00", "end": "16:00"}}))


def test_parse_v1_rejects_bad_time_format():
    with pytest.raises(ShareValidationError, match="Startzeit"):
        parse_share_doc(_v1(entries={"2026-05-14": {"start": "8:00", "end": "16:00", "pause": 0}}))


def test_parse_v1_rejects_negative_pause():
    with pytest.raises(ShareValidationError, match="Pause"):
        parse_share_doc(_v1(entries={"2026-05-14": {"start": "08:00", "end": "16:00", "pause": -5}}))


def test_parse_v1_rejects_bool_as_pause():
    with pytest.raises(ShareValidationError, match="Pause"):
        parse_share_doc(_v1(entries={"2026-05-14": {"start": "08:00", "end": "16:00", "pause": True}}))


def test_parse_v1_rejects_bad_end_time():
    with pytest.raises(ShareValidationError, match="Endzeit"):
        parse_share_doc(_v1(entries={"2026-05-14": {"start": "08:00", "end": "16:0", "pause": 0}}))


def test_parse_v1_rejects_unreal_time():
    with pytest.raises(ShareValidationError, match="Startzeit"):
        parse_share_doc(_v1(entries={"2026-05-14": {"start": "25:00", "end": "16:00", "pause": 0}}))


# --- v2: alte Shape (entries+reservations), beim Lesen gewrappt ---


def test_parse_v2_entries_only_wrapped():
    doc = parse_share_doc(_v2(entries={"2026-05-14": {"start": "08:00", "end": "16:00", "pause": 0}}))
    assert doc["entries"] == {"2026-05-14": _erec(_eslot("08:00", "16:00", 0, ""))}


def test_parse_v2_reservations_only_wrapped():
    doc = parse_share_doc(_v2(reservations={"2026-05-14": {"start": "08:00", "end": "12:00"}}))
    assert doc["reservations"] == {"2026-05-14": _erec(_rslot("08:00", "12:00", ""))}


def test_parse_v2_both_wrapped():
    doc = parse_share_doc(_v2(
        entries={"2026-05-14": {"start": "08:00", "end": "16:00", "pause": 0}},
        reservations={"2026-05-15": {"start": "09:00", "end": "12:00"}},
    ))
    assert doc["entries"] == {"2026-05-14": _erec(_eslot("08:00", "16:00", 0, ""))}
    assert doc["reservations"] == {"2026-05-15": _erec(_rslot("09:00", "12:00", ""))}


def test_parse_v2_empty_entries_with_reservations_ok():
    doc = parse_share_doc(_v2(entries={}, reservations={"2026-05-14": {"start": "08:00", "end": "12:00"}}))
    assert doc["reservations"] == {"2026-05-14": _erec(_rslot("08:00", "12:00", ""))}


def test_parse_v2_rejects_both_missing():
    with pytest.raises(ShareValidationError, match="weder"):
        parse_share_doc(_v2())


def test_parse_v2_rejects_both_empty():
    with pytest.raises(ShareValidationError, match="weder"):
        parse_share_doc(_v2(entries={}, reservations={}))


def test_parse_v2_reservation_rejects_pause_field():
    with pytest.raises(ShareValidationError, match="unbekannt"):
        parse_share_doc(_v2(reservations={"2026-05-14": {"start": "08:00", "end": "12:00", "pause": 0}}))


def test_parse_v2_reservation_rejects_missing_field():
    with pytest.raises(ShareValidationError, match="fehlend"):
        parse_share_doc(_v2(reservations={"2026-05-14": {"start": "08:00"}}))


def test_parse_v2_reservation_rejects_bad_time():
    with pytest.raises(ShareValidationError, match="Startzeit"):
        parse_share_doc(_v2(reservations={"2026-05-14": {"start": "25:00", "end": "12:00"}}))


def test_parse_v2_reservation_rejects_bad_date_key():
    with pytest.raises(ShareValidationError, match="Datum"):
        parse_share_doc(_v2(reservations={"not-a-date": {"start": "08:00", "end": "12:00"}}))


# --- v3: Slot-Format ---


def test_parse_v3_entries_slots():
    doc = parse_share_doc(_v3(entries={"2026-05-14": _erec(_eslot("08:00", "12:00", 0, "Büro"),
                                                           _eslot("13:00", "17:00", 30, "HO"))}))
    assert doc["entries"]["2026-05-14"]["slots"][0] == _eslot("08:00", "12:00", 0, "Büro")
    assert doc["entries"]["2026-05-14"]["slots"][1] == _eslot("13:00", "17:00", 30, "HO")


def test_parse_v3_reservations_slots():
    doc = parse_share_doc(_v3(reservations={"2026-05-14": _erec(_rslot("09:00", "12:00", "Termin"))}))
    assert doc["reservations"]["2026-05-14"]["slots"][0] == _rslot("09:00", "12:00", "Termin")


def test_parse_v3_both():
    doc = parse_share_doc(_v3(
        entries={"2026-05-14": _erec(_eslot("08:00", "16:00", 0, ""))},
        reservations={"2026-05-15": _erec(_rslot("09:00", "12:00", ""))},
    ))
    assert doc["entries"] and doc["reservations"]


def test_parse_v3_rejects_both_missing():
    with pytest.raises(ShareValidationError, match="weder"):
        parse_share_doc(_v3())


def test_parse_v3_rejects_record_without_slots_key():
    with pytest.raises(ShareValidationError, match="slots"):
        parse_share_doc(_v3(entries={"2026-05-14": {"start": "08:00", "end": "16:00", "pause": 0}}))


def test_parse_v3_rejects_entry_slot_extra_field():
    with pytest.raises(ShareValidationError, match="unbekannt"):
        parse_share_doc(_v3(entries={"2026-05-14": {"slots": [
            {"start": "08:00", "end": "16:00", "pause": 0, "kategorie": "", "x": 1}]}}))


def test_parse_v3_rejects_entry_slot_missing_field():
    with pytest.raises(ShareValidationError, match="fehlend"):
        parse_share_doc(_v3(entries={"2026-05-14": {"slots": [
            {"start": "08:00", "end": "16:00", "pause": 0}]}}))


def test_parse_v3_rejects_entry_slot_bad_time():
    with pytest.raises(ShareValidationError, match="Startzeit"):
        parse_share_doc(_v3(entries={"2026-05-14": {"slots": [_eslot("25:00", "16:00", 0, "")]}}))


def test_parse_v3_rejects_entry_slot_negative_pause():
    with pytest.raises(ShareValidationError, match="Pause"):
        parse_share_doc(_v3(entries={"2026-05-14": {"slots": [_eslot("08:00", "16:00", -1, "")]}}))


def test_parse_v3_rejects_entry_slot_bool_pause():
    with pytest.raises(ShareValidationError, match="Pause"):
        parse_share_doc(_v3(entries={"2026-05-14": {"slots": [
            {"start": "08:00", "end": "16:00", "pause": True, "kategorie": ""}]}}))


def test_parse_v3_rejects_reservation_slot_with_pause():
    with pytest.raises(ShareValidationError, match="unbekannt"):
        parse_share_doc(_v3(reservations={"2026-05-14": {"slots": [
            {"start": "08:00", "end": "12:00", "pause": 0, "kategorie": ""}]}}))


def test_parse_v3_rejects_bad_date_key():
    with pytest.raises(ShareValidationError, match="Datum"):
        parse_share_doc(_v3(entries={"not-a-date": _erec(_eslot("08:00", "16:00", 0, ""))}))


# --- build_share_doc ---


class _FakeStorage:
    def __init__(self, entries):
        self._entries = entries

    def get_all(self):
        return dict(self._entries)


class _FakeResStore:
    def __init__(self, data):
        self._d = data

    def get_all(self):
        return dict(self._d)


def test_build_share_doc_basic():
    storage = _FakeStorage({"2026-05-14": _erec(_eslot("08:00", "16:00", 30, "Büro"))})
    doc = build_share_doc(storage, "alice@example.com")
    assert doc["kind"] == KIND
    assert doc["schema_version"] == SCHEMA_VERSION == 3
    assert doc["exported_by"] == "alice@example.com"
    assert doc["entries"] == {"2026-05-14": _erec(_eslot("08:00", "16:00", 30, "Büro"))}
    assert "exported_at" in doc and doc["exported_at"].endswith("Z")


def test_build_share_doc_none_sender_becomes_empty_string():
    doc = build_share_doc(_FakeStorage({}), None)
    assert doc["exported_by"] == ""


def test_build_doc_entries_only_omits_reservations():
    doc = build_share_doc(_FakeStorage({"2026-05-14": _erec(_eslot("08:00", "16:00", 0, ""))}), "a@b.de")
    assert "entries" in doc
    assert "reservations" not in doc
    assert doc["schema_version"] == 3


def test_build_doc_reservations_only():
    storage = _FakeStorage({"2026-05-14": _erec(_eslot("08:00", "16:00", 0, ""))})
    res = _FakeResStore({"2026-05-15": _erec(_rslot("09:00", "12:00", ""))})
    doc = build_share_doc(storage, "a@b.de", reservation_store=res,
                          include_entries=False, include_reservations=True)
    assert "entries" not in doc
    assert doc["reservations"] == {"2026-05-15": _erec(_rslot("09:00", "12:00", ""))}


def test_build_doc_category_filter_entries():
    storage = _FakeStorage({"2026-05-14": _erec(_eslot("08:00", "12:00", 0, "Büro"),
                                                _eslot("13:00", "17:00", 0, "HO"))})
    doc = build_share_doc(storage, "a@b.de", categories={"Büro"})
    assert doc["entries"] == {"2026-05-14": _erec(_eslot("08:00", "12:00", 0, "Büro"))}


def test_build_doc_category_filter_drops_empty_days():
    storage = _FakeStorage({"2026-05-14": _erec(_eslot("08:00", "12:00", 0, "Büro"))})
    doc = build_share_doc(storage, "a@b.de", categories={"Nichtvorhanden"})
    assert doc["entries"] == {}


# --- Zeitraum-Filter beim Export (Xveyn/Zeiterfassung#48) ---


def _days(*dates):
    """Records mit je einem belanglosen Slot, damit nur die Schlüssel zählen."""
    return {d: _erec(_eslot("08:00", "16:00", 0, "")) for d in dates}


def test_filter_range_bounds_are_inclusive():
    recs = _days("2026-05-13", "2026-05-14", "2026-05-15", "2026-05-16")
    out = filter_records_by_range(recs, _dt.date(2026, 5, 14), _dt.date(2026, 5, 15))
    assert sorted(out) == ["2026-05-14", "2026-05-15"]


def test_filter_range_open_start_keeps_everything_up_to_end():
    recs = _days("2026-05-13", "2026-05-14", "2026-05-15")
    out = filter_records_by_range(recs, None, _dt.date(2026, 5, 14))
    assert sorted(out) == ["2026-05-13", "2026-05-14"]


def test_filter_range_open_end_keeps_everything_from_start():
    recs = _days("2026-05-13", "2026-05-14", "2026-05-15")
    out = filter_records_by_range(recs, _dt.date(2026, 5, 14), None)
    assert sorted(out) == ["2026-05-14", "2026-05-15"]


def test_filter_range_both_none_returns_unchanged():
    recs = _days("2026-05-13", "2026-05-14")
    assert filter_records_by_range(recs, None, None) == recs


def test_filter_range_drops_unparsable_keys():
    recs = dict(_days("2026-05-14"))
    recs["kaputt"] = _erec(_eslot("08:00", "16:00", 0, ""))
    out = filter_records_by_range(recs, _dt.date(2026, 5, 1), _dt.date(2026, 5, 31))
    assert sorted(out) == ["2026-05-14"]


def test_filter_range_inverted_range_yields_nothing():
    recs = _days("2026-05-14")
    assert filter_records_by_range(
        recs, _dt.date(2026, 5, 20), _dt.date(2026, 5, 10)) == {}


def test_build_doc_date_range_filters_entries():
    storage = _FakeStorage(_days("2026-05-13", "2026-05-14", "2026-05-15"))
    doc = build_share_doc(storage, "a@b.de",
                          date_from=_dt.date(2026, 5, 14), date_to=_dt.date(2026, 5, 15))
    assert sorted(doc["entries"]) == ["2026-05-14", "2026-05-15"]


def test_build_doc_date_range_filters_reservations():
    res = _FakeResStore({d: _erec(_rslot("09:00", "12:00", ""))
                         for d in ("2026-05-13", "2026-05-14")})
    doc = build_share_doc(_FakeStorage({}), "a@b.de", reservation_store=res,
                          include_entries=False, include_reservations=True,
                          date_from=_dt.date(2026, 5, 14), date_to=None)
    assert sorted(doc["reservations"]) == ["2026-05-14"]


def test_build_doc_date_range_and_category_filter_combine():
    storage = _FakeStorage({
        "2026-05-13": _erec(_eslot("08:00", "12:00", 0, "Büro")),
        "2026-05-14": _erec(_eslot("08:00", "12:00", 0, "Büro"),
                            _eslot("13:00", "17:00", 0, "HO")),
        "2026-05-15": _erec(_eslot("08:00", "12:00", 0, "HO")),
    })
    doc = build_share_doc(storage, "a@b.de", categories={"Büro"},
                          date_from=_dt.date(2026, 5, 14), date_to=_dt.date(2026, 5, 15))
    # 13. fällt am Datum, 15. an der Kategorie, vom 14. bleibt nur der Büro-Slot.
    assert doc["entries"] == {"2026-05-14": _erec(_eslot("08:00", "12:00", 0, "Büro"))}


def test_build_doc_date_range_without_hits_yields_empty_dict():
    storage = _FakeStorage(_days("2026-05-14"))
    doc = build_share_doc(storage, "a@b.de",
                          date_from=_dt.date(2026, 6, 1), date_to=_dt.date(2026, 6, 30))
    assert doc["entries"] == {}


def test_build_doc_range_may_empty_one_type_and_doc_stays_parsable():
    """Der Dialog laesst zu, dass im Zeitraum nur einer der beiden Typen
    Treffer hat (die Checkbox zeigt dann "(0 Tage)"). Das entstehende Doc mit
    leerem Typ-Dict muss der Validator akzeptieren — sonst baute die UI ein
    Dokument, das der Empfaenger nicht einlesen kann."""
    storage = _FakeStorage(_days("2026-05-14"))
    res = _FakeResStore({"2026-09-01": _erec(_rslot("09:00", "12:00", ""))})
    doc = build_share_doc(storage, "a@b.de", reservation_store=res,
                          include_entries=True, include_reservations=True,
                          date_from=_dt.date(2026, 5, 1), date_to=_dt.date(2026, 5, 31))
    assert doc["reservations"] == {}
    parsed = parse_share_doc(serialize_share_doc(doc))
    assert parsed["reservations"] == {}
    assert sorted(parsed["entries"]) == ["2026-05-14"]


def test_filter_by_category_is_public_and_drops_empty_days():
    """`filter_records_by_category` ist oeffentlich, weil der Teilen-Dialog
    seine Tages-Zahlen aus denselben Filtern zieht wie der Export."""
    recs = {"2026-05-14": _erec(_eslot("08:00", "12:00", 0, "Büro")),
            "2026-05-15": _erec(_eslot("08:00", "12:00", 0, "HO"))}
    assert filter_records_by_category(recs, None) == recs
    assert sorted(filter_records_by_category(recs, {"Büro"})) == ["2026-05-14"]
    assert filter_records_by_category(recs, {"Weg"}) == {}


def test_build_doc_without_range_is_unchanged():
    """Rückwärtskompatibilität: ohne Zeitraum bleibt es der volle Bestand."""
    recs = _days("2020-01-01", "2026-05-14")
    assert build_share_doc(_FakeStorage(recs), "a@b.de")["entries"] == recs


def test_round_trip_build_serialize_parse():
    storage = _FakeStorage({
        "2026-05-14": _erec(_eslot("08:00", "16:00", 30, "Büro")),
        "2026-05-15": _erec(_eslot("09:00", "17:30", 45, "")),
    })
    doc = build_share_doc(storage, "alice@example.com")
    parsed = parse_share_doc(serialize_share_doc(doc))
    assert parsed["entries"] == doc["entries"]
    assert parsed["schema_version"] == SCHEMA_VERSION


def test_serialize_utf8_umlauts():
    doc = build_share_doc(_FakeStorage({"2026-05-14": _erec(_eslot("08:00", "16:00", 0, "Büro"))}),
                          "äöü@example.com")
    payload = serialize_share_doc(doc)
    assert b"\\u" not in payload
    assert parse_share_doc(payload)["exported_by"] == "äöü@example.com"


# --- diff (Arbeitszeiten) ---


def test_diff_only_additions():
    share = {"2026-05-14": _erec(_eslot("08:00", "16:00", 30, ""))}
    diff = diff_share_against_local(share, _FakeStorage({}))
    assert diff["additions"] == [("2026-05-14", _erec(_eslot("08:00", "16:00", 30, "")))]
    assert diff["conflicts"] == []
    assert diff["untouched"] == []


def test_diff_only_untouched():
    local = {"2026-05-14": _erec(_eslot("08:00", "16:00", 30, ""))}
    share = {"2026-05-14": _erec(_eslot("08:00", "16:00", 30, ""))}
    diff = diff_share_against_local(share, _FakeStorage(local))
    assert diff["untouched"] == ["2026-05-14"]
    assert diff["conflicts"] == []


def test_diff_slot_reorder_is_untouched():
    local = {"2026-05-14": _erec(_eslot("08:00", "12:00", 0, "A"), _eslot("13:00", "17:00", 0, "B"))}
    share = {"2026-05-14": _erec(_eslot("13:00", "17:00", 0, "B"), _eslot("08:00", "12:00", 0, "A"))}
    diff = diff_share_against_local(share, _FakeStorage(local))
    assert diff["untouched"] == ["2026-05-14"]


def test_diff_category_difference_is_conflict():
    local = {"2026-05-14": _erec(_eslot("08:00", "16:00", 30, "Büro"))}
    share = {"2026-05-14": _erec(_eslot("08:00", "16:00", 30, "HO"))}
    diff = diff_share_against_local(share, _FakeStorage(local))
    assert len(diff["conflicts"]) == 1
    assert diff["untouched"] == []


def test_diff_pause_difference_is_conflict():
    local = {"2026-05-14": _erec(_eslot("08:00", "16:00", 30, ""))}
    share = {"2026-05-14": _erec(_eslot("08:00", "16:00", 45, ""))}
    diff = diff_share_against_local(share, _FakeStorage(local))
    assert len(diff["conflicts"]) == 1


def test_diff_range_filter_inclusive_bounds():
    share = {"2026-05-10": _erec(_eslot("08:00", "16:00", 0, "")),
             "2026-05-15": _erec(_eslot("08:00", "16:00", 0, ""))}
    diff = diff_share_against_local(share, _FakeStorage({}),
                                    date_from=_dt.date(2026, 5, 10), date_to=_dt.date(2026, 5, 15))
    assert len(diff["additions"]) == 2
    assert diff["out_of_range"] == 0


def test_diff_range_filter_excludes_outside():
    share = {"2026-05-10": _erec(_eslot("08:00", "16:00", 0, "")),
             "2026-05-15": _erec(_eslot("08:00", "16:00", 0, ""))}
    diff = diff_share_against_local(share, _FakeStorage({}), date_from=_dt.date(2026, 5, 12))
    assert [d for d, _ in diff["additions"]] == ["2026-05-15"]
    assert diff["out_of_range"] == 1


# --- apply (Arbeitszeiten) ---


class _RecordingStorage:
    def __init__(self):
        self.save_many_calls = []

    def save_many(self, updates):
        self.save_many_calls.append(dict(updates))


def test_apply_import_single_call_for_all_decisions():
    s = _RecordingStorage()
    apply_import(s, [
        {"date": "2026-05-14", "entry": _erec(_eslot("08:00", "16:00", 30, "Büro"))},
        {"date": "2026-05-15", "entry": _erec(_eslot("09:00", "17:00", 0, ""))},
    ])
    assert len(s.save_many_calls) == 1
    assert s.save_many_calls[0] == {
        "2026-05-14": _erec(_eslot("08:00", "16:00", 30, "Büro")),
        "2026-05-15": _erec(_eslot("09:00", "17:00", 0, "")),
    }


def test_apply_import_integration_with_real_storage(tmp_path):
    from src.storage import Storage
    s = Storage(str(tmp_path / "z.json"), device_id="dev1")
    s.save("2026-05-14", [_eslot("08:00", "16:00", 30, "")])
    apply_import(s, [
        {"date": "2026-05-15", "entry": _erec(_eslot("09:00", "17:00", 0, ""))},
        {"date": "2026-05-14", "entry": _erec(_eslot("10:00", "18:00", 45, "Büro"))},
    ])
    entries = s.get_all()
    assert entries["2026-05-14"] == _erec(_eslot("10:00", "18:00", 45, "Büro"))
    assert entries["2026-05-15"] == _erec(_eslot("09:00", "17:00", 0, ""))


# --- diff + apply (Reservierungen) ---


def test_diff_reservations_additions_and_conflicts():
    store = _FakeResStore({"2026-05-14": _erec(_rslot("08:00", "12:00", ""))})
    share = {
        "2026-05-14": _erec(_rslot("09:00", "12:00", "")),  # conflict
        "2026-05-16": _erec(_rslot("10:00", "14:00", "")),  # addition
    }
    diff = diff_reservations_against_local(share, store)
    assert [d for d, _ in diff["additions"]] == ["2026-05-16"]
    assert [d for d, _l, _s in diff["conflicts"]] == ["2026-05-14"]


def test_diff_reservations_untouched():
    store = _FakeResStore({"2026-05-14": _erec(_rslot("08:00", "12:00", ""))})
    share = {"2026-05-14": _erec(_rslot("08:00", "12:00", ""))}
    diff = diff_reservations_against_local(share, store)
    assert diff["untouched"] == ["2026-05-14"]


class _RecordingResStore:
    def __init__(self):
        self.saved = []

    def save(self, date_str, slots):
        self.saved.append((date_str, slots))


def test_apply_reservation_import_calls_save_with_slots():
    store = _RecordingResStore()
    apply_reservation_import(store, [
        {"date": "2026-05-14", "entry": _erec(_rslot("08:00", "12:00", "Termin"))},
        {"date": "2026-05-15", "entry": _erec(_rslot("09:00", "13:00", ""))},
    ])
    assert store.saved == [
        ("2026-05-14", [_rslot("08:00", "12:00", "Termin")]),
        ("2026-05-15", [_rslot("09:00", "13:00", "")]),
    ]


def test_apply_reservation_import_empty_is_noop():
    store = _RecordingResStore()
    apply_reservation_import(store, [])
    assert store.saved == []


def test_share_doc_omits_send_reminder_minutes(tmp_path):
    from src.reservations import ReservationStore
    from src.share import build_share_doc, parse_share_doc, serialize_share_doc

    store = ReservationStore(str(tmp_path / "res.json"))
    store.save("2026-08-31", [{"start": "08:00", "end": "12:00",
                               "kategorie": "Office",
                               "send_reminder_minutes": 15}])
    doc = build_share_doc(_FakeStorage({}), "a@b.de", reservation_store=store,
                          include_entries=False, include_reservations=True)
    slot = doc["reservations"]["2026-08-31"]["slots"][0]
    assert set(slot.keys()) == {"start", "end", "kategorie"}
    # Das eigene Doc muss den eigenen, strikten Validator bestehen.
    parse_share_doc(serialize_share_doc(doc))
