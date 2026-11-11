import types
from unittest.mock import MagicMock

from src.dialogs import conflicts_dialog
from src.dialogs.conflicts_dialog import ConflictsDialog, _entry_chosen


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
        _unresolved=[selected] if selected is not None else [],
        _rows=[],
        _refresh_list=MagicMock(),
        _on_resolved=MagicMock(),
        _show_message=MagicMock(),
    )
    stub.settings.get.return_value = "devABCDEF"
    stub.listbox.size.return_value = 0
    # _refresh_list ruft self._on_select(pos) auf — die echte Implementierung
    # binden, damit _selected nach der Vorselektion prüfbar ist.
    stub._show_conflict = MagicMock()
    stub._select_pos = MagicMock()
    stub._on_select = lambda pos=None: ConflictsDialog._on_select(stub, pos)
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
    stub._show_conflict.assert_called_once_with(stub._selected)


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


# --- Gruppierte Liste und Weiterspringen -------------------------------------

def _store_with(*conflicts):
    store = MagicMock()
    store.get_all.return_value = list(conflicts)
    return store


def _setting_c(key, cid):
    return {"id": cid, "kind": "setting", "key": key,
            "candidates": [{"value": True, "device_id": "a"},
                           {"value": False, "device_id": "b"}]}


def test_refresh_list_groups_days_before_settings_with_counts():
    stub = _dialog_stub(selected=None)
    stub.conflicts_store.get_all.return_value = [
        _setting_c("workweek_only", "s1"),
        _entry_conflict("2026-06-12", "c2"),
        _entry_conflict("2026-06-02", "c1"),
    ]

    ConflictsDialog._refresh_list(stub)

    shown = [c[0][0] for c in stub.listbox.insert.call_args_list]  # (index, text)
    texts = [c[0][1] for c in stub.listbox.insert.call_args_list]
    assert shown == ["end"] * 5
    assert texts == ["ZEITEN · 2", "  Di, 02.06.2026", "  Fr, 12.06.2026",
                     "EINSTELLUNGEN · 1", "  Nur Werktage"]
    assert [c["id"] for c in stub._unresolved] == ["c1", "c2", "s1"]


def test_refresh_list_after_resolving_selects_the_next_one():
    stub = _dialog_stub(selected=None)
    stub.conflicts_store.get_all.return_value = [
        _entry_conflict("2026-06-02", "c1"), _entry_conflict("2026-06-03", "c2"),
    ]

    ConflictsDialog._refresh_list(stub, keep_pos=1)

    stub._select_pos.assert_called_once_with(1)


def test_refresh_list_after_resolving_the_last_one_clamps_the_position():
    stub = _dialog_stub(selected=None)
    stub.conflicts_store.get_all.return_value = [_entry_conflict("2026-06-02", "c1")]

    ConflictsDialog._refresh_list(stub, keep_pos=5)

    stub._select_pos.assert_called_once_with(0)


def test_refresh_list_says_done_when_nothing_is_left():
    stub = _dialog_stub(selected=None)
    stub.conflicts_store.get_all.return_value = []

    ConflictsDialog._refresh_list(stub, keep_pos=0)

    stub._show_message.assert_called_once_with(conflicts_dialog.done_text())
    assert stub._selected is None


def test_resolve_passes_the_position_so_the_next_conflict(monkeypatch):
    monkeypatch.setattr(conflicts_dialog.sync, "resolve_conflict",
                        lambda *a, **k: None)
    first, second = _entry_conflict("2026-06-02", "c1"), _entry_conflict("2026-06-03", "c2")
    stub = _dialog_stub(selected=second)
    stub._unresolved = [first, second]

    ConflictsDialog._resolve_with_candidate(stub, 1)

    stub._refresh_list.assert_called_once_with(keep_pos=1)


def test_resolve_uses_the_candidate_index_not_the_card_position(monkeypatch):
    # Die Karten sind sortiert (eigenes Gerät zuerst); gewählt wird über den
    # Index des Kandidaten, nicht über die Spalte.
    seen = {}
    monkeypatch.setattr(conflicts_dialog.sync, "resolve_conflict",
                        lambda cid, chosen, *a, **k: seen.update(chosen=chosen))
    conflict = _entry_conflict("2026-06-02", "c1")
    stub = _dialog_stub(selected=conflict)

    ConflictsDialog._resolve_with_candidate(stub, 1)

    assert seen["chosen"]["slots"] == conflict["candidates"][1]["slots"]


def test_header_row_is_not_selectable():
    conflict = _entry_conflict("2026-06-02", "c1")
    stub = _dialog_stub(selected=conflict)
    stub._unresolved = [conflict]
    stub._rows = [("header", "Zeiten · 1"), ("conflict", conflict)]
    stub._row_of = lambda pos: ConflictsDialog._row_of(stub, pos)
    stub.listbox.curselection.return_value = (0,)

    ConflictsDialog._on_select(stub)

    # Auswahl zurück auf die Zeile des angezeigten Konflikts, nichts neu gezeigt.
    stub.listbox.selection_set.assert_called_once_with(1)
    stub._show_conflict.assert_not_called()
