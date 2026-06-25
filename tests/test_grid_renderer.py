"""GridRenderer: reine Helfer ohne Tk (statics + Methoden, die nur settings/
conflicts_store lesen)."""

from unittest.mock import MagicMock

from src.time_utils import calculate_hours
from src.grid_renderer import GridRenderer


def _renderer(show_weekend=True, conflicts=None):
    settings = MagicMock(get=lambda k, d=None: {"show_weekend": show_weekend}.get(k, d))
    cstore = MagicMock(get_all=lambda: conflicts) if conflicts is not None else None
    return GridRenderer(
        root=object(), storage=object(), settings=settings,
        reservation_store=None, conflicts_store=cstore,
        on_cell_click=lambda d: None, on_cell_right_click=lambda d: None,
        reservations_active=lambda: False,
    )


def test_fmt_slot_line_with_category():
    assert GridRenderer._fmt_slot_line(
        {"start": "08:00", "end": "12:00", "kategorie": "Büro"}) == "08:00-12:00  Büro"


def test_fmt_slot_line_without_category():
    assert GridRenderer._fmt_slot_line(
        {"start": "08:00", "end": "12:00"}) == "08:00-12:00"


def test_truncate_clips_long_text():
    assert GridRenderer._truncate("Donnerstag", 5) == "Donn…"


def test_truncate_keeps_short_text():
    assert GridRenderer._truncate("Mo", 5) == "Mo"


def test_entry_hours_sums_slots():
    entry = {"slots": [
        {"start": "08:00", "end": "12:00", "pause": 0},
        {"start": "13:00", "end": "17:00", "pause": 0},
    ]}
    expected = round(
        calculate_hours("08:00", "12:00", pause_minutes=0)
        + calculate_hours("13:00", "17:00", pause_minutes=0), 2)
    assert _renderer()._entry_hours(entry) == expected == 8.0


def test_entry_hours_subtracts_pause():
    entry = {"slots": [{"start": "08:00", "end": "12:00", "pause": 30}]}
    assert _renderer()._entry_hours(entry) == 3.5


def test_visible_day_count_with_weekend():
    assert _renderer(show_weekend=True)._visible_day_count() == 7


def test_visible_day_count_without_weekend():
    assert _renderer(show_weekend=False)._visible_day_count() == 5


def test_dates_with_unresolved_conflicts_filters_entry_kind():
    conflicts = [
        {"key": "2026-06-01", "kind": "entry", "resolved": False},
        {"key": "2026-06-02", "kind": "entry", "resolved": True},
        {"key": "2026-06-03", "kind": "reservation", "resolved": False},
    ]
    assert _renderer(conflicts=conflicts)._dates_with_unresolved_conflicts() == {"2026-06-01"}


def test_dates_with_unresolved_conflicts_none_store():
    assert _renderer()._dates_with_unresolved_conflicts() == set()
