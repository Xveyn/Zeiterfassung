import json

import pytest

from src.share import ShareValidationError, parse_share_doc


def _bytes(obj):
    return json.dumps(obj).encode("utf-8")


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
        parse_share_doc(_bytes({
            "kind": "zeiterfassung-share",
            "schema_version": 2,
            "entries": {},
        }))


def test_parse_rejects_missing_entries():
    with pytest.raises(ShareValidationError, match="entries"):
        parse_share_doc(_bytes({"kind": "zeiterfassung-share", "schema_version": 1}))


def test_parse_rejects_bad_date_key():
    with pytest.raises(ShareValidationError, match="Datum"):
        parse_share_doc(_bytes({
            "kind": "zeiterfassung-share",
            "schema_version": 1,
            "entries": {"not-a-date": {"start": "08:00", "end": "16:00", "pause": 0}},
        }))


def test_parse_rejects_extra_entry_field():
    with pytest.raises(ShareValidationError, match="unbekannt"):
        parse_share_doc(_bytes({
            "kind": "zeiterfassung-share",
            "schema_version": 1,
            "entries": {"2026-05-14": {"start": "08:00", "end": "16:00", "pause": 0, "deleted": True}},
        }))


def test_parse_rejects_missing_entry_field():
    with pytest.raises(ShareValidationError, match="fehlend"):
        parse_share_doc(_bytes({
            "kind": "zeiterfassung-share",
            "schema_version": 1,
            "entries": {"2026-05-14": {"start": "08:00", "end": "16:00"}},
        }))


def test_parse_rejects_bad_time_format():
    with pytest.raises(ShareValidationError, match="Startzeit"):
        parse_share_doc(_bytes({
            "kind": "zeiterfassung-share",
            "schema_version": 1,
            "entries": {"2026-05-14": {"start": "8:00", "end": "16:00", "pause": 0}},
        }))


def test_parse_rejects_negative_pause():
    with pytest.raises(ShareValidationError, match="Pause"):
        parse_share_doc(_bytes({
            "kind": "zeiterfassung-share",
            "schema_version": 1,
            "entries": {"2026-05-14": {"start": "08:00", "end": "16:00", "pause": -5}},
        }))


def test_parse_rejects_bool_as_pause():
    """bool ist Subklasse von int — verhindern, dass True als pause=1 durchgeht."""
    with pytest.raises(ShareValidationError, match="Pause"):
        parse_share_doc(_bytes({
            "kind": "zeiterfassung-share",
            "schema_version": 1,
            "entries": {"2026-05-14": {"start": "08:00", "end": "16:00", "pause": True}},
        }))


def test_parse_rejects_past_schema_version():
    """schema_version < 1 ist defensiv reserviert — muss ShareValidationError werfen."""
    with pytest.raises(ShareValidationError, match="schema_version"):
        parse_share_doc(_bytes({
            "kind": "zeiterfassung-share",
            "schema_version": 0,
            "entries": {},
        }))


def test_parse_rejects_bad_end_time():
    """Ungültiges Format für end-Zeit schlägt mit passendem Fehler fehl."""
    with pytest.raises(ShareValidationError, match="Endzeit"):
        parse_share_doc(_bytes({
            "kind": "zeiterfassung-share",
            "schema_version": 1,
            "entries": {"2026-05-14": {"start": "08:00", "end": "16:0", "pause": 0}},
        }))


def test_parse_rejects_unreal_time():
    """Regex-valide aber unmögliche Uhrzeiten (25:00, 08:99) müssen abgelehnt werden."""
    with pytest.raises(ShareValidationError, match="Startzeit"):
        parse_share_doc(_bytes({
            "kind": "zeiterfassung-share",
            "schema_version": 1,
            "entries": {"2026-05-14": {"start": "25:00", "end": "16:00", "pause": 0}},
        }))


from src.share import build_share_doc, serialize_share_doc, KIND, SCHEMA_VERSION


class _FakeStorage:
    def __init__(self, entries):
        self._entries = entries

    def get_all(self):
        return dict(self._entries)


def test_build_share_doc_basic():
    storage = _FakeStorage({
        "2026-05-14": {"start": "08:00", "end": "16:00", "pause": 30},
    })
    doc = build_share_doc(storage, "alice@example.com")
    assert doc["kind"] == KIND
    assert doc["schema_version"] == SCHEMA_VERSION
    assert doc["exported_by"] == "alice@example.com"
    assert doc["entries"] == {"2026-05-14": {"start": "08:00", "end": "16:00", "pause": 30}}
    assert "exported_at" in doc and doc["exported_at"].endswith("Z")


def test_build_share_doc_empty_sender():
    storage = _FakeStorage({})
    doc = build_share_doc(storage, "")
    assert doc["exported_by"] == ""
    assert doc["entries"] == {}


def test_build_share_doc_none_sender_becomes_empty_string():
    storage = _FakeStorage({})
    doc = build_share_doc(storage, None)
    assert doc["exported_by"] == ""


def test_round_trip_build_serialize_parse():
    storage = _FakeStorage({
        "2026-05-14": {"start": "08:00", "end": "16:00", "pause": 30},
        "2026-05-15": {"start": "09:00", "end": "17:30", "pause": 45},
    })
    doc = build_share_doc(storage, "alice@example.com")
    payload = serialize_share_doc(doc)
    parsed = parse_share_doc(payload)
    assert parsed["entries"] == doc["entries"]
    assert parsed["kind"] == KIND
    assert parsed["schema_version"] == SCHEMA_VERSION


def test_serialize_utf8_umlauts():
    storage = _FakeStorage({})
    doc = build_share_doc(storage, "äöü@example.com")
    payload = serialize_share_doc(doc)
    assert b"\\u" not in payload  # ensure_ascii=False — Umlaute literal
    parsed = parse_share_doc(payload)
    assert parsed["exported_by"] == "äöü@example.com"
