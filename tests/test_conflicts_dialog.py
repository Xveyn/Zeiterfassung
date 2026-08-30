import types
from unittest.mock import MagicMock

from src.dialogs import conflicts_dialog
from src.dialogs.conflicts_dialog import (
    ConflictsDialog, _entry_chosen, _fmt_entry_candidate, _fmt_setting_candidate,
)


def _cand(slots=None, deleted=False, modified_at="2026-05-20T10:00:00Z", device_id="devABCDEF"):
    c = {"modified_at": modified_at, "device_id": device_id, "deleted": deleted}
    if slots is not None:
        c["slots"] = slots
    return c


def test_entry_chosen_carries_slots():
    cand = _cand(slots=[{"start": "08:00", "end": "16:00", "pause": 30, "kategorie": "Büro"}])
    assert _entry_chosen(cand) == {
        "slots": [{"start": "08:00", "end": "16:00", "pause": 30, "kategorie": "Büro"}],
        "deleted": False,
    }


def test_entry_chosen_multi_slot_not_lost():
    slots = [{"start": "08:00", "end": "12:00", "pause": 0, "kategorie": "A"},
             {"start": "13:00", "end": "17:00", "pause": 30, "kategorie": "B"}]
    assert _entry_chosen(_cand(slots=slots))["slots"] == slots


def test_entry_chosen_deleted_candidate():
    assert _entry_chosen(_cand(slots=[], deleted=True)) == {"slots": [], "deleted": True}


def test_fmt_entry_candidate_lists_slots():
    cand = _cand(slots=[{"start": "08:00", "end": "12:00", "pause": 0, "kategorie": "Büro"},
                        {"start": "13:00", "end": "17:00", "pause": 30, "kategorie": ""}])
    text = _fmt_entry_candidate(cand, {})
    assert "08:00—12:00" in text
    assert "Büro" in text
    assert "13:00—17:00" in text


def test_fmt_entry_candidate_deleted():
    assert "GELÖSCHT" in _fmt_entry_candidate(_cand(slots=[], deleted=True), {})


# --- Gerätename statt nackter ID (Registry aus dem Sync-Doc) ----------------

_REGISTRY = {"devABCDEF12": {"name": "Laptop Arbeit", "updated_at": "2026-05-01T00:00:00Z"}}


def test_fmt_entry_candidate_shows_device_name():
    text = _fmt_entry_candidate(_cand(slots=[], device_id="devABCDEF12"), _REGISTRY)
    assert "Laptop Arbeit" in text
    assert "devABCDE…" in text


def test_fmt_entry_candidate_falls_back_to_short_id():
    """Unbekanntes Gerät (nie gepusht, alter Stand): exakt wie vor dem Feature."""
    text = _fmt_entry_candidate(_cand(slots=[], device_id="fremdes-geraet"), _REGISTRY)
    assert "fremdes-…" in text
    assert "·" not in text


def test_fmt_deleted_candidate_shows_device_name():
    cand = _cand(slots=[], deleted=True, device_id="devABCDEF12")
    assert "Laptop Arbeit" in _fmt_entry_candidate(cand, _REGISTRY)


def test_fmt_setting_candidate_shows_device_name():
    cand = {"value": "a@b.de", "modified_at": "2026-05-20T10:00:00Z",
            "device_id": "devABCDEF12"}
    assert "Laptop Arbeit" in _fmt_setting_candidate(cand, _REGISTRY)


# --- Doppel-Resolve-Guard (Follow-up #134 / Audit H3) -----------------------
# Seit #122 sind die A/B-Buttons nur noch OPTISCH disabled — der command feuert
# weiter. Gegen einen zweiten Klick auf den bereits aufgelösten Konflikt schützt
# allein der _selected-Guard in _resolve_with_candidate (is-None-Check + Reset
# auf None nach dem Resolve). Headless getestet über einen Stub-`self`, ohne
# Tk-Root: sync.resolve_conflict wird gezählt, die Tk-berührenden Helfer sind
# gemockt.

def _dialog_stub(selected, filter_key=None):
    stub = types.SimpleNamespace(
        _selected=selected,
        _filter_key=filter_key,
        _data_lock=None,
        settings=MagicMock(),
        storage=MagicMock(),
        conflicts_store=MagicMock(),
        top=MagicMock(),
        listbox=MagicMock(),
        btn_a=MagicMock(),
        btn_b=MagicMock(),
        detail_label=MagicMock(),
        _refresh_list=MagicMock(),
        _on_resolved=MagicMock(),
    )
    stub.settings.get.return_value = "devABCDEF"
    # _refresh_list ruft self._on_select(idx) auf — die echte Implementierung
    # binden, damit _selected/detail_label nach der Vorselektion prüfbar sind
    # (nicht die _refresh_list-Mock-Konvention der Resolve-Tests oben).
    stub._on_select = lambda idx=None: ConflictsDialog._on_select(stub, idx)
    return stub


def _setting_conflict():
    return {"id": "c1", "kind": "setting", "key": "stundenlohn",
            "candidates": [{"value": "A"}, {"value": "B"}]}


def test_resolve_noop_when_nothing_selected(monkeypatch):
    calls = []
    monkeypatch.setattr(conflicts_dialog.sync, "resolve_conflict",
                        lambda *a, **k: calls.append(1))
    stub = _dialog_stub(selected=None)

    ConflictsDialog._resolve_with_candidate(stub, 0)

    assert calls == []
    stub._refresh_list.assert_not_called()
    stub._on_resolved.assert_not_called()


def test_resolve_resets_selected_after_success(monkeypatch):
    monkeypatch.setattr(conflicts_dialog.sync, "resolve_conflict",
                        lambda *a, **k: None)
    monkeypatch.setattr(conflicts_dialog, "set_secondary_button_enabled",
                        lambda *a, **k: None)
    stub = _dialog_stub(selected=_setting_conflict())

    ConflictsDialog._resolve_with_candidate(stub, 0)

    # Guard-Reset ist PFLICHT — sonst löst ein Folgeklick den alten Konflikt neu.
    assert stub._selected is None
    stub._refresh_list.assert_called_once()


def test_resolve_success_notifies_on_resolved(monkeypatch):
    """Nach erfolgreichem Resolve muss der Kalender (App._refresh) Bescheid
    bekommen — sonst zeigt die Zelle hinter dem Dialog weiter den alten
    Konflikt-Hinweis/die alte Ist-Zeit."""
    monkeypatch.setattr(conflicts_dialog.sync, "resolve_conflict",
                        lambda *a, **k: None)
    monkeypatch.setattr(conflicts_dialog, "set_secondary_button_enabled",
                        lambda *a, **k: None)
    stub = _dialog_stub(selected=_setting_conflict())

    ConflictsDialog._resolve_with_candidate(stub, 0)

    stub._on_resolved.assert_called_once_with()


def test_resolve_failure_does_not_notify_on_resolved(monkeypatch):
    monkeypatch.setattr(conflicts_dialog.sync, "resolve_conflict",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setattr(conflicts_dialog, "themed_showerror", lambda *a, **k: None)
    stub = _dialog_stub(selected=_setting_conflict())

    ConflictsDialog._resolve_with_candidate(stub, 0)

    stub._on_resolved.assert_not_called()


def test_second_resolve_is_noop(monkeypatch):
    calls = []
    monkeypatch.setattr(conflicts_dialog.sync, "resolve_conflict",
                        lambda *a, **k: calls.append(1))
    monkeypatch.setattr(conflicts_dialog, "set_secondary_button_enabled",
                        lambda *a, **k: None)
    stub = _dialog_stub(selected=_setting_conflict())

    ConflictsDialog._resolve_with_candidate(stub, 0)  # löst auf
    ConflictsDialog._resolve_with_candidate(stub, 0)  # muss No-op sein

    assert len(calls) == 1
    stub._refresh_list.assert_called_once()


def test_resolve_with_filter_key_closes_dialog_instead_of_refreshing(monkeypatch):
    """Gefiltert (Linksklick auf einen Tag) gibt es nach dem Auflösen kein
    'nächster Konflikt' in dieser Ansicht — der Dialog schließt sich selbst,
    statt _refresh_list auf die jetzt leere/gefilterte Liste anzuwenden."""
    monkeypatch.setattr(conflicts_dialog.sync, "resolve_conflict",
                        lambda *a, **k: None)
    stub = _dialog_stub(selected=_entry_conflict("2026-06-03", "c2"),
                        filter_key="2026-06-03")

    ConflictsDialog._resolve_with_candidate(stub, 0)

    stub.top.destroy.assert_called_once_with()
    stub._refresh_list.assert_not_called()
    stub._on_resolved.assert_called_once_with()


# --- Filtern per filter_key (Linksklick auf Konflikttag) --------------------
# App._open_dialog öffnet den Dialog mit filter_key=date_str, statt die volle
# Liste aller offenen Konflikte zu zeigen.

def _entry_conflict(key, cid):
    return {
        "id": cid, "kind": "entry", "key": key,
        "candidates": [_cand(slots=[{"start": "08:00", "end": "16:00",
                                     "pause": 0, "kategorie": ""}]),
                       _cand(slots=[{"start": "09:00", "end": "17:00",
                                     "pause": 0, "kategorie": ""}])],
    }


def test_refresh_list_filters_to_matching_key(monkeypatch):
    monkeypatch.setattr(conflicts_dialog, "set_secondary_button_enabled",
                        lambda *a, **k: None)
    stub = _dialog_stub(selected=None, filter_key="2026-06-03")
    stub.conflicts_store.get_all.return_value = [
        _entry_conflict("2026-06-02", "c1"),
        _entry_conflict("2026-06-03", "c2"),
    ]

    ConflictsDialog._refresh_list(stub)

    # Der nicht passende Konflikt (2026-06-02) ist komplett draußen, nicht nur
    # unselektiert — die Listbox zeigt gefiltert nur den einen Tag.
    assert [c["id"] for c in stub._unresolved] == ["c2"]
    stub.listbox.selection_set.assert_called_once_with(0)
    assert stub._selected["id"] == "c2"


def test_refresh_list_without_filter_key_keeps_full_list():
    stub = _dialog_stub(selected=None, filter_key=None)
    stub.conflicts_store.get_all.return_value = [
        _entry_conflict("2026-06-02", "c1"),
        _entry_conflict("2026-06-03", "c2"),
    ]

    ConflictsDialog._refresh_list(stub)

    assert len(stub._unresolved) == 2
    stub.listbox.selection_set.assert_not_called()
    assert stub._selected is None


def test_refresh_list_filter_key_not_found_selects_nothing():
    # z.B. weil der Konflikt zwischenzeitlich anders (Zweitgerät) aufgelöst wurde.
    stub = _dialog_stub(selected=None, filter_key="2026-06-09")
    stub.conflicts_store.get_all.return_value = [_entry_conflict("2026-06-02", "c1")]

    ConflictsDialog._refresh_list(stub)

    assert stub._unresolved == []
    stub.listbox.selection_set.assert_not_called()
    assert stub._selected is None
