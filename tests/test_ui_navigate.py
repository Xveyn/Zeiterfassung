"""_navigate ersetzt _prev/_next. Getestet ohne Tk über einen Stub mit den
relevanten Attributen; _refresh ist ein No-op."""

from src.ui import App


class _Stub:
    def __init__(self, **kw):
        self.__dict__.update(kw)
        self.refreshed = 0

    def _refresh(self):
        self.refreshed += 1


def _nav(stub, direction):
    App._navigate(stub, direction)


def test_month_forward_within_year():
    s = _Stub(view_mode="month", year=2026, month=6)
    _nav(s, +1)
    assert (s.year, s.month) == (2026, 7)
    assert s.refreshed == 1


def test_month_backward_wraps_to_previous_year():
    s = _Stub(view_mode="month", year=2026, month=1)
    _nav(s, -1)
    assert (s.year, s.month) == (2025, 12)


def test_month_forward_wraps_to_next_year():
    s = _Stub(view_mode="month", year=2026, month=12)
    _nav(s, +1)
    assert (s.year, s.month) == (2027, 1)


def test_week_forward_advances_seven_days():
    # KW 26/2026 -> +1 Woche = KW 27
    s = _Stub(view_mode="week", iso_year=2026, current_week=26)
    _nav(s, +1)
    assert (s.iso_year, s.current_week) == (2026, 27)


def test_week_backward_crosses_year_boundary():
    # KW 1/2026 -> -1 Woche landet in 2025
    s = _Stub(view_mode="week", iso_year=2026, current_week=1)
    _nav(s, -1)
    assert s.iso_year == 2025
    assert s.current_week >= 52
