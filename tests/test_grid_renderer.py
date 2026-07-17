"""GridRenderer: reine Helfer ohne Tk (statics + Methoden, die nur settings/
conflicts_store lesen)."""

from unittest.mock import MagicMock

from src.time_utils import calculate_hours
from src.grid_renderer import GridRenderer


def _renderer(show_weekend=True, conflicts=None):
    settings = MagicMock(get=lambda k, d=None: {"show_weekend": show_weekend}.get(k, d))
    cstore = MagicMock(
        get_all=lambda: conflicts,
        unresolved_entry_keys=lambda: {
            c["key"] for c in conflicts
            if c.get("kind") == "entry" and not c.get("resolved")
        },
    ) if conflicts is not None else None
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


def test_tooltip_text_single_slot_shows_category():
    # Neu: schon bei EINEM Slot erscheint der Arbeitszeit-Block, damit die
    # Kategorie beim Hovern sichtbar wird (vorher erst ab >1 Slot).
    entry = {"slots": [{"start": "09:30", "end": "16:00", "kategorie": "Office"}]}
    assert GridRenderer._build_tooltip_text(entry, None, None) == (
        "Arbeitszeit:\n09:30-16:00  Office")


def test_tooltip_text_single_slot_without_category():
    entry = {"slots": [{"start": "09:30", "end": "16:00"}]}
    assert GridRenderer._build_tooltip_text(entry, None, None) == (
        "Arbeitszeit:\n09:30-16:00")


def test_tooltip_text_multi_slot_lists_all():
    entry = {"slots": [
        {"start": "08:00", "end": "12:00", "kategorie": "Büro"},
        {"start": "13:00", "end": "17:00"},
    ]}
    assert GridRenderer._build_tooltip_text(entry, None, None) == (
        "Arbeitszeit:\n08:00-12:00  Büro\n13:00-17:00")


def test_tooltip_text_combines_arbeitszeit_and_reservation():
    entry = {"slots": [{"start": "09:30", "end": "16:00", "kategorie": "Office"}]}
    reservation = {"slots": [{"start": "18:00", "end": "20:00"}]}
    assert GridRenderer._build_tooltip_text(entry, reservation, None) == (
        "Arbeitszeit:\n09:30-16:00  Office\n"
        "Reservierung:\n18:00-20:00")


def test_tooltip_text_empty_when_nothing():
    assert GridRenderer._build_tooltip_text(None, None, None) == ""


def test_tooltip_text_holiday_only_with_entry_or_reservation():
    entry = {"slots": [{"start": "09:30", "end": "16:00"}]}
    assert GridRenderer._build_tooltip_text(entry, None, "Neujahr") == (
        "Arbeitszeit:\n09:30-16:00\nFeiertag: Neujahr")
    # Feiertag ohne Eintrag/Reservierung -> kein kombinierter Tooltip
    assert GridRenderer._build_tooltip_text(None, None, "Neujahr") == ""


def test_tooltip_text_folds_conflict_into_combined():
    # M11: der Konflikt-Hinweis gehört in DENSELBEN Tooltip wie die
    # Arbeitszeit-Details — nicht als zweiter attach_tooltip an dieselbe Zelle.
    entry = {"slots": [{"start": "09:30", "end": "16:00", "kategorie": "Office"}]}
    assert GridRenderer._build_tooltip_text(entry, None, None, has_conflict=True) == (
        "Arbeitszeit:\n09:30-16:00  Office\nKonflikt — bitte auflösen")


def test_tooltip_text_conflict_only_when_no_other_units():
    # Konfliktzelle ohne Ist-Zeit/Reservierung: der Tooltip zeigt allein den
    # Konflikt-Hinweis (früher der separate attach_tooltip-Pfad).
    assert GridRenderer._build_tooltip_text(None, None, None, has_conflict=True) == (
        "Konflikt — bitte auflösen")


def test_tooltip_text_no_conflict_is_unchanged():
    entry = {"slots": [{"start": "09:30", "end": "16:00"}]}
    assert GridRenderer._build_tooltip_text(entry, None, None, has_conflict=False) == (
        "Arbeitszeit:\n09:30-16:00")


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


def test_fmt_cell_hours_mit_pause():
    entry = {"slots": [{"start": "09:10", "end": "14:50", "pause": 30}]}
    assert GridRenderer._fmt_cell_hours(entry) == "5,17 h · P30"


def test_fmt_cell_hours_pause_null_sichtbar():
    # Der bewusste Pause-0-Tag (<6h, keine Pflichtpause) muss als P0 erkennbar
    # sein, sonst sieht er wie ein Vertipper aus.
    entry = {"slots": [{"start": "09:10", "end": "14:50", "pause": 0}]}
    assert GridRenderer._fmt_cell_hours(entry) == "5,67 h · P0"


def test_fmt_cell_hours_summiert_mehrere_slots():
    entry = {"slots": [
        {"start": "08:00", "end": "12:00", "pause": 15},
        {"start": "13:00", "end": "17:00", "pause": 15},
    ]}
    assert GridRenderer._fmt_cell_hours(entry) == "7,50 h · P30"


def test_fmt_cell_hours_ohne_slots():
    assert GridRenderer._fmt_cell_hours({"slots": []}) == ""
