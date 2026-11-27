import datetime

import pytest


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


def test_vacation_snapshot_honours_workweek_only():
    """Ein Urlaubs-Samstag mit Stunden darf im Nur-Werktage-Modus nicht in
    'Zu vergüten gesamt' zählen — er ist im Kalender unsichtbar und aus der
    Stundentabelle gestrichen."""
    from src import workweek

    snapshot = {"2026-07-03": 480, "2026-07-04": 480}   # Fr, Sa
    assert workweek.filter_for_report(snapshot, {"workweek_only": True}) == {
        "2026-07-03": 480}
    assert workweek.filter_for_report(
        snapshot, {"workweek_only": False}) == snapshot


def test_period_has_no_content_blocks_when_vacation_is_outside_range():
    """Urlaub existiert nur im Januar, gewählter Zeitraum ist März: weder
    Einträge noch Urlaub liegen IM Zeitraum -> die Leer-Prüfung muss blocken.
    Der ungefilterte Store-weite Snapshot allein (vacation_days nicht leer)
    darf die Prüfung nicht durchwinken — sonst verschickt ein JSON-Webhook
    ein leeres, aber valides Dokument als vermeintlichen Erfolg."""
    from src.dialogs.send_dialog import period_has_no_content

    vacation_days = {"2026-01-10": 480, "2026-01-11": 480}
    assert period_has_no_content(
        ranged=None, vacation_days=vacation_days,
        date_from=datetime.date(2026, 3, 1), date_to=datetime.date(2026, 3, 31),
    ) is True


def test_period_has_no_content_does_not_block_vacation_in_range():
    """Der reine Urlaubsmonat aus Task 8 muss weiter sendbar bleiben: Urlaub
    liegt IM gewählten Zeitraum, es gibt keine Einträge -> nicht blocken."""
    from src.dialogs.send_dialog import period_has_no_content

    vacation_days = {"2026-03-10": 480, "2026-03-11": 480}
    assert period_has_no_content(
        ranged=None, vacation_days=vacation_days,
        date_from=datetime.date(2026, 3, 1), date_to=datetime.date(2026, 3, 31),
    ) is False


# ----- Vorschau: Urlaub gekappt wie im Bericht (Xveyn#97) -----

def _preview(**kw):
    """Die Vorschau ohne Häkchen „Krankheit ausweisen“ (reiner Urlaubs-Weg)."""
    from src.dialogs.period_picker import absence_preview
    return absence_preview(sick_days=None, **kw)


def test_vacation_preview_sums_the_period_without_worktime():
    assert _preview(
        date_from=datetime.date(2026, 9, 1), date_to=datetime.date(2026, 9, 30),
        all_entries={}, categories=None,
        vacation_days={"2026-09-01": 480, "2026-09-02": 480}) == (960, 0, [])


def test_vacation_preview_counts_only_days_in_the_range():
    minutes, _, _ = _preview(
        date_from=datetime.date(2026, 9, 1), date_to=datetime.date(2026, 9, 30),
        all_entries={}, categories=None,
        vacation_days={"2026-09-01": 480, "2026-10-01": 480})
    assert minutes == 480


def test_vacation_preview_caps_against_worktime_like_the_report():
    # Ohne Kappung zeigte die Vorschau „+ 8.0h Urlaub", der erzeugte Bericht
    # aber 4.0h — die beiden duerfen sich nicht widersprechen.
    from tests.conftest import ist_slot
    minutes, sick, notices = _preview(
        date_from=datetime.date(2026, 9, 1), date_to=datetime.date(2026, 9, 30),
        all_entries={"2026-09-01": {"slots": [ist_slot("08:00", "12:00")]}},
        categories=None, vacation_days={"2026-09-01": 480})
    assert (minutes, sick) == (240, 0)
    assert len(notices) == 1 and "01.09.2026" in notices[0]


def test_vacation_preview_uses_the_selected_categories_only():
    from tests.conftest import ist_slot
    assert _preview(
        date_from=datetime.date(2026, 9, 1), date_to=datetime.date(2026, 9, 30),
        all_entries={"2026-09-01": {
            "slots": [ist_slot("08:00", "12:00", kategorie="B")]}},
        categories={"A"}, vacation_days={"2026-09-01": 480}) == (480, 0, [])


def test_vacation_preview_without_vacation_is_zero():
    assert _preview(
        date_from=datetime.date(2026, 9, 1), date_to=datetime.date(2026, 9, 30),
        all_entries={}, categories=None, vacation_days={}) == (0, 0, [])


@pytest.mark.parametrize("category_on,note_on,expected",
                         [(True, True, True), (True, False, False),
                          (False, True, False), (False, False, False)])
def test_note_breakdown_needs_the_category_breakdown(category_on, note_on, expected):
    from src.dialogs.period_picker import note_breakdown_active
    assert note_breakdown_active(category_on, note_on) is expected


# ----- Krankheit: Vorschau und Leer-Prüfung -----

def test_absence_preview_matches_report_numbers():
    """Die Vorschau rechnet wie der Bericht: Krankheit gewinnt gegen Urlaub,
    beide werden gegen die Ist-Zeit gekappt, Hinweise in Berichtsreihenfolge."""
    from src.dialogs.period_picker import absence_preview
    from src.report import generate_report
    from tests.conftest import ist_slot

    entries = {"2026-09-02": {"slots": [ist_slot("08:00", "10:00")]}}
    vacation = {"2026-09-01": 480, "2026-09-02": 480, "2026-09-03": 480}
    sick = {"2026-09-02": 480, "2026-09-03": 240}
    df, dt = datetime.date(2026, 9, 1), datetime.date(2026, 9, 30)

    vac, sck, notices = absence_preview(df, dt, entries, None, vacation, sick)
    # 02.09.: Krankheit 480 - 120 Ist = 360, Urlaub 0; 03.09.: Krankheit 240, Urlaub 0
    assert (vac, sck) == (480, 600)
    assert len(notices) == 2
    assert notices[0].startswith("An 1 Tag (02.09.2026) ist Arbeitszeit erfasst")
    assert "lag Krankheit im Urlaub" in notices[1]

    html, _ = generate_report(df, dt, entries, vacation_days=vacation,
                              sick_days=sick)
    for n in notices:
        assert n in html


@pytest.mark.parametrize("work,vacation,sick", [
    # Krankheit ganz weggekappt: kein Block, aber der Satz.
    ({"2026-09-02": ("08:00", "16:00")}, {}, {"2026-09-02": 480}),
    ({"2026-09-02": ("08:00", "16:00")}, {"2026-09-03": 480}, {"2026-09-02": 480}),
    # Urlaub gekappt, Krankheit gekappt, Krankheit im Urlaub.
    ({"2026-09-01": ("08:00", "10:00"), "2026-09-02": ("08:00", "16:00")},
     {"2026-09-01": 480, "2026-09-02": 480, "2026-09-03": 480},
     {"2026-09-02": 480, "2026-09-03": 0}),
    ({"2026-09-01": ("08:00", "10:00")}, {"2026-09-01": 480}, None),
    ({}, {"2026-09-01": 480}, None),
    ({}, {}, {}),
])
def test_preview_notices_are_the_report_footnotes(work, vacation, sick):
    """Vorschau und Bericht reden wortgleich und in derselben Reihenfolge
    über dieselben Kürzungen — auch wenn kein Krankheits-Block entsteht."""
    import html as html_mod
    import re

    from src.dialogs.period_picker import absence_preview
    from src.report import HTML_STYLE, generate_report
    from tests.conftest import ist_slot

    entries = {d: {"slots": [ist_slot(a, b)]} for d, (a, b) in work.items()}
    df, dt = datetime.date(2026, 9, 1), datetime.date(2026, 9, 30)
    _, _, notices = absence_preview(df, dt, entries, None, vacation, sick)
    html, _ = generate_report(df, dt, entries, vacation_days=vacation,
                              sick_days=sick)
    footnote = re.escape(f'<p style="{HTML_STYLE["footnote"]}">')
    footnotes = [html_mod.unescape(t)
                 for t in re.findall(footnote + "(.*?)</p>", html or "")]
    assert footnotes == notices


class _SickStore:
    def __init__(self, days):
        self.days = days
        self.calls = 0

    def day_minutes(self):
        self.calls += 1
        return dict(self.days)


def test_report_sick_days_is_none_without_checkbox():
    """Häkchen aus: nichts aus dem Store, Bericht und Webhook bitgleich."""
    from src.dialogs.period_picker import report_sick_days
    store = _SickStore({"2026-09-01": 480})
    assert report_sick_days(False, store, {"workweek_only": False}) is None
    assert store.calls == 0
    assert report_sick_days(True, None, {"workweek_only": False}) is None


def test_report_sick_days_with_checkbox_is_the_filtered_snapshot():
    from src.dialogs.period_picker import report_sick_days
    days = {"2026-09-04": 480, "2026-09-05": 240, "2026-09-07": 0}  # Fr, Sa, Mo
    assert report_sick_days(True, _SickStore(days),
                            {"workweek_only": False}) == days
    assert report_sick_days(True, _SickStore(days), {"workweek_only": True}) == {
        "2026-09-04": 480, "2026-09-07": 0}
    assert report_sick_days(True, _SickStore({}), {"workweek_only": True}) == {}


@pytest.mark.parametrize("name", ["send_dialog.py", "export_dialog.py"])
def test_dialogs_decide_sick_days_only_through_the_helper(name):
    from pathlib import Path
    source = (Path(__file__).parent.parent / "src" / "dialogs" / name).read_text(
        encoding="utf-8")
    assert "report_sick_days(picker.get_show_sick(), sick_store" in source
    assert "sick_store.day_minutes()" not in source


def test_absence_preview_without_sick_is_the_vacation_path():
    from src.dialogs.period_picker import absence_preview
    vac, sck, notices = absence_preview(
        datetime.date(2026, 9, 1), datetime.date(2026, 9, 30), {}, None,
        {"2026-09-01": 480}, None)
    assert (vac, sck, notices) == (480, 0, [])


def test_period_with_only_sick_days_has_content():
    from src.dialogs.send_dialog import period_has_no_content
    df, dt = datetime.date(2026, 3, 1), datetime.date(2026, 3, 31)
    assert period_has_no_content(
        None, None, df, dt, sick_days={"2026-03-10": 480}) is False
    assert period_has_no_content(
        None, None, df, dt, sick_days={"2026-01-10": 480}) is True
    assert period_has_no_content(
        None, None, df, dt, sick_days={"2026-03-10": 0}) is True
    assert period_has_no_content(None, None, df, dt) is True


def test_vacation_under_sick_day_without_minutes_is_no_content():
    """Krankheit gewinnt auch hier: der Urlaubstag unter einem 0-Minuten-
    Krankheitstag ist im Bericht 0, der Bericht also leer."""
    from src.dialogs.send_dialog import period_has_no_content
    from src.report import generate_report
    df, dt = datetime.date(2026, 9, 1), datetime.date(2026, 9, 30)
    vacation, sick = {"2026-09-02": 480}, {"2026-09-02": 0}
    assert generate_report(df, dt, {}, vacation_days=vacation,
                           sick_days=sick)[0] is None
    assert period_has_no_content(None, vacation, df, dt, sick_days=sick) is True


def _day_in(kategorie):
    from tests.conftest import ist_slot
    return {"2026-09-02": {"slots": [ist_slot("08:00", "16:00", 0, kategorie)]}}


@pytest.mark.parametrize("entries,categories,vacation,sick", [
    ({}, None, {"2026-09-02": 480}, {"2026-09-02": 0}),
    ({}, None, {"2026-09-02": 480}, None),
    ({}, None, {"2026-09-02": 480, "2026-09-03": 480}, {"2026-09-02": 0}),
    ({}, None, {}, {}),
    ({}, None, {"2026-08-31": 480}, {"2026-10-01": 480}),
    # Krankheit ganz weggekappt, die Ist-Zeit bleibt Inhalt.
    (_day_in("A"), None, None, {"2026-09-02": 480}),
    (_day_in("A"), None, {"2026-09-02": 480}, {"2026-09-02": 480}),
    # Ist-Zeit nur in abgewählter Kategorie: sie kappt nichts und zählt nicht.
    (_day_in("B"), {"A"}, None, {"2026-09-02": 480}),
    (_day_in("B"), {"A"}, {"2026-09-02": 480}, {"2026-09-02": 0}),
    (_day_in("B"), {"A"}, {"2026-09-02": 480}, None),
])
def test_period_has_no_content_agrees_with_the_report(entries, categories,
                                                       vacation, sick):
    from src.dialogs.send_dialog import period_has_no_content
    from src.report import filter_categories, filter_period, generate_report
    df, dt = datetime.date(2026, 9, 1), datetime.date(2026, 9, 30)
    ranged = filter_period(df, dt, entries)
    if ranged is not None:
        ranged = filter_categories(ranged, categories)
    html, _ = generate_report(df, dt, entries, categories=categories,
                              vacation_days=vacation, sick_days=sick)
    assert period_has_no_content(ranged, vacation, df, dt,
                                 sick_days=sick) is (html is None)
