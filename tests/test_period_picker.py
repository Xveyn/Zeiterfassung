import datetime


def test_selected_category_filter_empty_map_is_none():
    from src.dialogs.period_picker import selected_category_filter
    assert selected_category_filter({}) is None


def test_selected_category_filter_all_selected_is_none():
    from src.dialogs.period_picker import selected_category_filter
    assert selected_category_filter({"Büro": True, "HO": True}) is None


def test_selected_category_filter_partial_returns_selected_set():
    from src.dialogs.period_picker import selected_category_filter
    assert selected_category_filter({"Büro": True, "HO": False}) == {"Büro"}


def test_selected_category_filter_none_selected_returns_empty_set():
    # keiner ausgewählt ist NICHT "alle" -> leere Menge (Filter ohne Treffer),
    # exakt die bisherige send_dialog-Semantik.
    from src.dialogs.period_picker import selected_category_filter
    assert selected_category_filter({"Büro": False, "HO": False}) == set()


def test_selected_category_filter_only_uncategorized_is_nonempty():
    # "(ohne Kategorie)" = "" ist eine gültige, nicht-leere Auswahl: nur sie
    # angehakt -> {""}. Damit bleibt der Export-Button klickbar UND Zeiten ohne
    # Kategorie sind exportierbar (Filter "" -> Slots ohne kategorie).
    from src.dialogs.period_picker import selected_category_filter
    assert selected_category_filter({"": True, "Büro": False}) == {""}


class _S:
    def __init__(self, **kw):
        self._d = kw

    def get(self, key):
        return self._d.get(key)


class _MarkedStore:
    """get_all_raw mit genau einem markierten Tag (02.08.2026)."""

    def get_all_raw(self):
        return {"2026-08-02": {"slots": [{"send_reminder_minutes": 15}],
                               "modified_at": "x", "deleted": False}}


def test_resolve_send_period_off_by_default():
    from src.dialogs.send_dialog import resolve_send_period

    assert resolve_send_period(
        _S(send_period_from_last_reminder=False), None,
        datetime.date(2026, 9, 5)) is None


def test_resolve_send_period_without_store_is_none():
    from src.dialogs.send_dialog import resolve_send_period

    assert resolve_send_period(
        _S(send_period_from_last_reminder=True), None,
        datetime.date(2026, 9, 5)) is None


def test_resolve_send_period_uses_marked_days():
    from src.dialogs.send_dialog import resolve_send_period

    assert resolve_send_period(
        _S(send_period_from_last_reminder=True, send_period_anchor_monthly=False),
        _MarkedStore(), datetime.date(2026, 9, 5),
    ) == (datetime.date(2026, 8, 3), datetime.date(2026, 9, 5))


def test_resolve_send_period_with_monthly_anchor():
    from src.dialogs.send_dialog import resolve_send_period

    settings = _S(send_period_from_last_reminder=True,
                  send_period_anchor_monthly=True,
                  send_reminder_enabled=True,
                  send_reminder_day=23, send_reminder_time="16:30",
                  send_reminder_weekend_shift="none",
                  send_reminder_shift_holidays=False, state="")
    assert resolve_send_period(settings, _MarkedStore(), datetime.date(2026, 9, 5))         == (datetime.date(2026, 8, 24), datetime.date(2026, 9, 5))


def test_resolve_send_period_ignores_monthly_when_reminder_off():
    from src.dialogs.send_dialog import resolve_send_period

    settings = _S(send_period_from_last_reminder=True,
                  send_period_anchor_monthly=True,
                  send_reminder_enabled=False,
                  send_reminder_day=23, send_reminder_time="16:30",
                  send_reminder_weekend_shift="none",
                  send_reminder_shift_holidays=False, state="")
    assert resolve_send_period(settings, _MarkedStore(), datetime.date(2026, 9, 5))         == (datetime.date(2026, 8, 3), datetime.date(2026, 9, 5))


def test_resolve_send_period_no_anchor_before_today_is_none():
    from src.dialogs.send_dialog import resolve_send_period

    class _Empty:
        def get_all_raw(self):
            return {}

    assert resolve_send_period(
        _S(send_period_from_last_reminder=True, send_period_anchor_monthly=False),
        _Empty(), datetime.date(2026, 9, 5)) is None
