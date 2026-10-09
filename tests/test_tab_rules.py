"""Tests für tab_rules.py (#132, PR 2): Prüfung und Umrechnung je Tab —
der aufgeteilte Inhalt des früheren `save_settings`."""

import pytest

from src.dialogs.settings_dialog import tab_rules as tr
from src.holidays_de import STATES
from src.settings import WEEKDAY_KEYS
from src.send_reminder import SHIFT_LABELS
from src.updater import FREQUENCY_OPTIONS


def work_raw(**overrides):
    raw = {
        "workweek_only": False,
        "default_pause": "30",
        "pause_warning_enabled": True,
        "hourly_rate": "15.5",
        "werkstudent_limit_enabled": False,
        "werkstudent_limit_start.year": "2026",
        "werkstudent_limit_start.month": "4",
        "werkstudent_limit_start.day": "1",
        "werkstudent_limit_end.year": "2026",
        "werkstudent_limit_end.month": "9",
        "werkstudent_limit_end.day": "30",
        "werkstudent_limit_max_hours": "20",
        "state": STATES[1][1],
        "show_weekend": True,
    }
    for key in WEEKDAY_KEYS:
        raw[f"default_start_{key}"] = "08:00"
        raw[f"default_end_{key}"] = "16:00"
    raw.update(overrides)
    return raw


OLD_WSL = {
    "werkstudent_limit_enabled": False,
    "werkstudent_limit_start": "2025-10-01",
    "werkstudent_limit_end": "2026-03-31",
    "werkstudent_limit_max_hours": 20.0,
}


def test_date_iso():
    assert tr.date_iso("1", "4", "2026") == "2026-04-01"
    assert tr.date_iso("31", "2", "2026") is None
    assert tr.date_iso("", "4", "2026") is None
    assert tr.date_iso("x", "4", "2026") is None


def test_validate_work_ok():
    assert tr.validate_work(work_raw()) is None


def test_validate_work_names_the_weekday():
    raw = work_raw(default_start_wed="17:00", default_end_wed="09:00")
    result = tr.validate_work(raw)
    assert result is not None
    title, msg = result
    assert title == "Standard-Arbeitszeit ungültig"
    assert msg.startswith("Mi: ")


def test_validate_work_checks_period_only_when_enabled():
    backwards = {"werkstudent_limit_end.year": "2025"}
    assert tr.validate_work(work_raw(**backwards)) is None
    result = tr.validate_work(work_raw(werkstudent_limit_enabled=True, **backwards))
    assert result is not None
    title, _ = result
    assert title == "Werkstudenten-Limit-Zeitraum ungültig"


def test_validate_work_rejects_unparseable_date_when_enabled():
    raw = work_raw(werkstudent_limit_enabled=True,
                   **{"werkstudent_limit_start.day": ""})
    result = tr.validate_work(raw)
    assert result is not None
    title, _ = result
    assert title == "Werkstudenten-Limit-Zeitraum ungültig"


def test_work_updates_converts_types():
    upd = tr.work_updates(work_raw(), OLD_WSL)
    assert upd["default_pause"] == 30
    assert upd["hourly_rate"] == 15.5
    assert upd["werkstudent_limit_start"] == "2026-04-01"
    assert upd["werkstudent_limit_end"] == "2026-09-30"
    assert upd["werkstudent_limit_max_hours"] == 20.0
    assert upd["default_start_sat"] == "08:00"
    assert upd["pause_warning_enabled"] is True
    assert upd["workweek_only"] is False


def test_work_updates_falls_back_on_bad_numbers():
    # Wie das frühere save_settings: Stundenlohn tolerant auf 0.0,
    # Wochenlimit auf den bisherigen Wert.
    upd = tr.work_updates(
        work_raw(hourly_rate="abc", werkstudent_limit_max_hours="20,5"), OLD_WSL)
    assert upd["hourly_rate"] == 0.0
    assert upd["werkstudent_limit_max_hours"] == 20.0


def test_work_updates_keeps_old_date_when_unparseable():
    upd = tr.work_updates(
        work_raw(**{"werkstudent_limit_end.day": "x"}), OLD_WSL)
    assert upd["werkstudent_limit_end"] == "2026-03-31"


def test_work_updates_carries_state_and_weekend():
    upd = tr.work_updates(work_raw(), OLD_WSL)
    assert upd["state"] == STATES[1][0]
    assert upd["show_weekend"] is True


def test_wsl_snapshot_from_settings_and_updates_agree():
    upd = tr.work_updates(work_raw(), OLD_WSL)
    assert tr.wsl_snapshot(upd) == {
        "enabled": False, "start": "2026-04-01", "end": "2026-09-30",
        "max_hours": 20.0}
    assert tr.wsl_snapshot(OLD_WSL)["start"] == "2025-10-01"


def app_raw(**overrides):
    raw = {
        "autostart": False,
        "always_on_top": False, "minimize_to_tray": True, "ui_scale": 125,
    }
    raw.update(overrides)
    return raw


def reminders_raw(**overrides):
    raw = {
        "reminders_enabled": True, "reminder_minutes_before": "15",
        "send_reminder_enabled": True, "send_reminder_day": "28",
        "send_reminder_time": "09:00",
        "send_reminder_weekend_shift": SHIFT_LABELS["backward"],
        "send_reminder_shift_holidays": False,
        "send_reminder_reservations_enabled": True,
        "send_reminder_default_minutes": "30",
    }
    raw.update(overrides)
    return raw


def test_slider_percent_snaps_to_five():
    assert tr.slider_percent(101.3) == 100
    assert tr.slider_percent(103.0) == 105
    assert tr.slider_percent(200.0) == 200


def test_validate_reminders():
    assert tr.validate_reminders(reminders_raw()) is None
    for bad in ("abc", "-5", "121", "7.5", ""):
        result = tr.validate_reminders(reminders_raw(reminder_minutes_before=bad))
        assert result is not None
        title, _ = result
        assert title == "Erinnerungszeit ungültig"


def test_app_updates_converts():
    upd = tr.app_updates(app_raw())
    assert upd["ui_scale"] == 1.25
    assert upd["autostart"] is False


def test_reminders_updates_converts():
    upd = tr.reminders_updates(reminders_raw())
    assert set(upd) == set(tr.REMINDER_KEYS)
    assert upd["reminder_minutes_before"] == 15
    assert upd["send_reminder_day"] == 28
    assert upd["send_reminder_weekend_shift"] == "backward"
    assert upd["send_reminder_default_minutes"] == 30


def test_reminders_updates_keeps_values_of_disabled_options():
    # Ausgegraut heißt nicht gelöscht: schaltet man die Erinnerung ab, bleiben
    # Minuten und Tag gespeichert und sind beim Wiedereinschalten da.
    upd = tr.reminders_updates(reminders_raw(
        reminders_enabled=False, send_reminder_enabled=False))
    assert upd["reminders_enabled"] is False
    assert upd["reminder_minutes_before"] == 15
    assert upd["send_reminder_day"] == 28


def test_shift_moves():
    assert tr.shift_moves(SHIFT_LABELS["none"]) is False
    assert tr.shift_moves(SHIFT_LABELS["backward"]) is True
    assert tr.shift_moves(SHIFT_LABELS["forward"]) is True


def test_app_updates_clamps_scale():
    assert tr.app_updates(app_raw(ui_scale=500))["ui_scale"] == 2.0


def sending_raw(**overrides):
    raw = {k: f"<{k}>" for k in tr.MAIL_KEYS}
    raw.update({"send_period_from_last_reminder": True,
                "send_period_anchor_monthly": False})
    raw.update(overrides)
    return raw


def test_sending_updates():
    upd = tr.sending_updates(sending_raw())
    assert set(upd) == set(tr.SENDING_KEYS)
    assert upd["mail_subject"] == "<mail_subject>"
    assert upd["send_period_from_last_reminder"] is True
    assert upd["send_period_anchor_monthly"] is False


def test_google_updates_sanitizes_device_name():
    upd = tr.google_updates({"device_name": "  Laptop\x07 ", "gcal_calendar": "x"})
    assert upd == {"device_name": "Laptop"}


def test_calendar_update():
    cal_map = {"Arbeit": "abc@group", "Privat": "primary"}
    assert tr.calendar_update(cal_map, "Arbeit", "primary", True) == "abc@group"
    assert tr.calendar_update(cal_map, "Privat", "primary", True) is None
    # Liste noch nicht geladen: nie vorschnell "primary" festschreiben.
    assert tr.calendar_update({}, "primary", "abc@group", True) is None
    assert tr.calendar_update(cal_map, "Arbeit", "primary", False) is None


def test_update_tab_updates():
    raw = {"update_check_frequency": FREQUENCY_OPTIONS[1][1],
           "prerelease_updates_enabled": True}
    assert tr.update_tab_updates(raw) == {
        "update_check_frequency": FREQUENCY_OPTIONS[1][0],
        "prerelease_updates_enabled": True}
    raw["auto_update_enabled"] = False
    assert tr.update_tab_updates(raw)["auto_update_enabled"] is False


# Die Schlüssel, die das frühere dialog.save_settings geschrieben hat —
# wörtlich aus dessen `updates`-Dict (plus die Wochentage und die beiden
# Sonderfälle auto_update_enabled und gcal_calendar_id). Speichern je Tab
# darf keinen davon verlieren und keinen dazuerfinden.
_legacy_keys_base = {
    "autostart", "default_pause", "recipient", "name", "mail_subject",
    "mail_greeting", "mail_content", "mail_closing", "hourly_rate", "state",
    "show_weekend", "always_on_top", "minimize_to_tray", "reminders_enabled",
    "reminder_minutes_before", "send_reminder_enabled", "send_reminder_day",
    "send_reminder_time", "send_reminder_weekend_shift",
    "send_reminder_shift_holidays", "send_reminder_reservations_enabled",
    "send_reminder_default_minutes", "send_period_from_last_reminder",
    "send_period_anchor_monthly", "update_check_frequency",
    "prerelease_updates_enabled", "ui_scale", "werkstudent_limit_enabled",
    "werkstudent_limit_start", "werkstudent_limit_end",
    "werkstudent_limit_max_hours", "pause_warning_enabled", "workweek_only",
    "device_name", "auto_update_enabled",
}
LEGACY_KEYS = (
    _legacy_keys_base |
    {f"default_start_{k}" for k in WEEKDAY_KEYS} |  # type: ignore[reportGeneralTypeIssues]
    {f"default_end_{k}" for k in WEEKDAY_KEYS}
)


def test_tabs_together_write_exactly_the_legacy_keys():
    written = [
        tr.work_updates(work_raw(), OLD_WSL),
        tr.reminders_updates(reminders_raw()),
        tr.sending_updates(sending_raw()),
        tr.google_updates({"device_name": "", "gcal_calendar": ""}),
        tr.app_updates(app_raw()),
        tr.update_tab_updates({"update_check_frequency": FREQUENCY_OPTIONS[0][1],
                               "prerelease_updates_enabled": False,
                               "auto_update_enabled": True}),
    ]
    keys = [k for upd in written for k in upd]
    assert len(keys) == len(set(keys)), "ein Schlüssel in zwei Tabs"
    assert set(keys) == LEGACY_KEYS


# --- API-Tab (#92, PR 3) ----------------------------------------------------------

from src import single_instance  # noqa: E402
from src.api_service import (  # noqa: E402
    DEFAULT_PORT, REASON_INVALID_PORT, REASON_PORT_IN_USE, REASON_START_FAILED,
    REASON_TOKEN_UNAVAILABLE, STATE_ERROR, STATE_OFF, STATE_RUNNING, STATE_STARTING,
    ApiStatus,
)


def api_raw(**overrides):
    raw = {"api_enabled": True, "api_port": "17653"}
    raw.update(overrides)
    return raw


@pytest.mark.parametrize("port", ["17653", " 8080 ", "1024", "65535"])
def test_validate_api_accepts_valid_ports(port):
    assert tr.validate_api(api_raw(api_port=port)) is None


@pytest.mark.parametrize("port", ["", "abc", "0", "80", "1023", "65536", "70000",
                                  "17653.5", "-5", "٨٠٨٠", "9" * 5000, "0x50", " "])
def test_validate_api_rejects_everything_else(port):
    result = tr.validate_api(api_raw(api_port=port))

    assert result is not None
    title, message = result
    assert title and "1024" in message and "65535" in message


def test_validate_api_checks_the_port_even_when_the_api_is_off():
    # Ein kaputter Port im Feld soll nicht erst beim späteren Einschalten auffallen.
    assert tr.validate_api(api_raw(api_enabled=False, api_port="abc")) is not None


def test_api_updates_converts_the_form_state():
    assert tr.api_updates(api_raw(api_port=" 8080 ")) == {
        "api_enabled": True, "api_port": 8080}
    assert tr.api_updates(api_raw(api_enabled=False)) == {
        "api_enabled": False, "api_port": 17653}


def test_api_updates_falls_back_to_the_default_port_like_the_other_tabs():
    assert tr.api_updates(api_raw(api_port="abc"))["api_port"] == DEFAULT_PORT


def test_api_tab_keys_do_not_collide_with_the_other_tabs():
    assert set(tr.api_updates(api_raw())) & LEGACY_KEYS == set()


@pytest.mark.parametrize("port,expected_fragment", [
    ("20000", "Mehrfachstart"), ("31999", "Mehrfachstart"), ("25000", "Mehrfachstart"),
    ("32768", "32768"), ("60000", "32768"), ("65535", "32768"),
])
def test_port_hint_warns_for_the_busy_ranges(port, expected_fragment):
    assert expected_fragment in tr.port_hint(port)


@pytest.mark.parametrize("port", ["17653", "1024", "19999", "32000", "32767", "abc", "", "0"])
def test_port_hint_is_empty_everywhere_else(port):
    assert tr.port_hint(port) == ""


def test_port_hint_range_matches_the_single_instance_range():
    # Der Hinweis nennt den Bereich des Mehrfachstart-Schutzes; ändert sich der,
    # muss der Hinweis mit.
    assert tr._SINGLE_INSTANCE_FROM == single_instance._PORT_BASE
    assert tr._SINGLE_INSTANCE_TO == single_instance._PORT_BASE + single_instance._PORT_SPAN - 1


def test_status_view_for_every_state():
    assert tr.status_view(ApiStatus(STATE_OFF)) == ("Aus.", "muted")
    assert tr.status_view(ApiStatus(STATE_STARTING, 17653)) == ("Startet …", "muted")
    assert tr.status_view(ApiStatus(STATE_RUNNING, 17653)) == (
        "Läuft auf 127.0.0.1:17653", "ok")


@pytest.mark.parametrize("reason", [REASON_INVALID_PORT, REASON_PORT_IN_USE,
                                    REASON_TOKEN_UNAVAILABLE, REASON_START_FAILED,
                                    "etwas-neues"])
def test_status_view_error_reasons_are_distinct_and_never_empty(reason):
    text, kind = tr.status_view(ApiStatus(STATE_ERROR, 17653, reason))
    assert kind == "error" and text.strip()


def test_status_view_port_in_use_names_the_port():
    text, _ = tr.status_view(ApiStatus(STATE_ERROR, 8080, REASON_PORT_IN_USE))
    assert "8080" in text


def test_status_view_reasons_have_different_texts():
    texts = {tr.status_view(ApiStatus(STATE_ERROR, 8080, r))[0]
             for r in (REASON_INVALID_PORT, REASON_PORT_IN_USE,
                       REASON_TOKEN_UNAVAILABLE, REASON_START_FAILED)}
    assert len(texts) == 4


def test_curl_example_uses_the_port_and_never_a_real_token():
    assert tr.curl_example("8080") == (
        'curl -H "Authorization: Bearer <Token>" http://127.0.0.1:8080/v1/status')
    assert "17653" in tr.curl_example("abc")          # Fallback auf den Standard


# --- API-Tab: Knopfzustände und Token-Zeile (Review-Fixes) -------------------------

@pytest.mark.parametrize("api_on", [True, False])
@pytest.mark.parametrize("token_known", [True, False])
@pytest.mark.parametrize("busy", [True, False])
def test_token_buttons_need_the_api_on_a_known_token_and_no_rotation(api_on, token_known, busy):
    expected = api_on and token_known and not busy
    assert tr.token_buttons_enabled(api_on=api_on, token_known=token_known, busy=busy) is expected


def test_token_label_shows_the_mask_or_the_hint_without_a_notice():
    assert tr.token_label_view(token_known=True, notice=None) == (tr.TOKEN_MASK, "muted")
    assert tr.token_label_view(token_known=False, notice=None) == (tr.TOKEN_MISSING, "muted")
    assert tr.token_label_view(token_known=True, notice="") == (tr.TOKEN_MASK, "muted")


@pytest.mark.parametrize("token_known", [True, False])
def test_a_notice_wins_over_the_mask_so_a_late_reread_cannot_overwrite_it(token_known):
    # Das Nachlesen des Tokens nach „Neu erzeugen“ kommt Millisekunden NACH der
    # Erfolgsmeldung zurück und rendert die Zeile neu — die Meldung muss gewinnen.
    assert tr.token_label_view(token_known=token_known, notice="Token erneuert.") == (
        "Token erneuert.", "ok")


def test_the_mask_never_contains_a_token_like_string():
    assert set(tr.TOKEN_MASK) == {"•"}


def test_leading_zeros_are_accepted_as_the_plain_number():
    # Entscheidung: „08080“ ist 8080 (harmlos, eindeutig) — weder Fehler noch Sonderfall.
    assert tr.validate_api(api_raw(api_port="08080")) is None
    assert tr.api_updates(api_raw(api_port="08080"))["api_port"] == 8080


def test_the_missing_token_text_does_not_promise_a_first_time_creation():
    # Die Maske steht auch, wenn die API läuft und die Datei extern gelöscht wurde.
    assert "ersten" not in tr.TOKEN_MISSING
    assert "lesbar" in tr.TOKEN_MISSING and "Einschalten" in tr.TOKEN_MISSING


# --- Mobil-Tab (#221, PR 5) -----------------------------------------------------------------

from src.mobile_service import (  # noqa: E402
    REASON_ADDRESS_GONE, REASON_INVALID_PORT, REASON_NO_ADDRESS, REASON_PORT_IN_USE,
    REASON_START_FAILED, MobileStatus,
)
from src.mobile_service import STATE_ERROR as M_ERROR  # noqa: E402
from src.mobile_service import STATE_OFF as M_OFF  # noqa: E402
from src.mobile_service import STATE_RUNNING as M_RUNNING  # noqa: E402
from src.mobile_service import STATE_STARTING as M_STARTING  # noqa: E402


def mobile_raw(**overrides):
    raw = {"mobile_enabled": True, "mobile_port": "17654", "mobile_address": tr.AUTO_ADDRESS}
    raw.update(overrides)
    return raw


def test_address_options_start_with_automatic_and_keep_the_order():
    assert tr.address_options(["192.168.1.20", "10.0.0.5"]) == [
        tr.AUTO_ADDRESS, "192.168.1.20", "10.0.0.5"]
    assert tr.address_options([]) == [tr.AUTO_ADDRESS]


def test_address_choice_round_trips():
    assert tr.address_from_choice(tr.AUTO_ADDRESS) == ""
    assert tr.address_from_choice("192.168.1.20") == "192.168.1.20"
    assert tr.address_to_choice("") == tr.AUTO_ADDRESS
    assert tr.address_to_choice("192.168.1.20") == "192.168.1.20"


def test_valid_mobile_input_passes_and_converts():
    assert tr.validate_mobile(mobile_raw()) is None
    assert tr.mobile_updates(mobile_raw()) == {
        "mobile_enabled": True, "mobile_port": 17654, "mobile_address": ""}
    assert tr.mobile_updates(mobile_raw(mobile_address="10.0.0.5", mobile_enabled=False,
                                        mobile_port=" 8080 ")) == {
        "mobile_enabled": False, "mobile_port": 8080, "mobile_address": "10.0.0.5"}


@pytest.mark.parametrize("port", ["", "abc", "80", "70000", "17654.5", "٨٠٨٠", "9" * 5000])
def test_an_invalid_port_is_refused_even_when_off(port):
    result = tr.validate_mobile(mobile_raw(mobile_port=port, mobile_enabled=False))
    assert result is not None and "Port" in result[0]


@pytest.mark.parametrize("address", [
    " 192.168.1.20", "192.168.1.20:17654", "8.8.8.8", "127.0.0.1", "0.0.0.0", "::1", "fe80::1",
    "192.168.001.001", "１９２.１６８.１.２０", "localhost", "192.168.1.256",
])
def test_an_address_that_is_not_a_lan_address_is_refused(address):
    result = tr.validate_mobile(mobile_raw(mobile_address=address))
    assert result is not None and "Adresse" in result[0]


def test_mobile_updates_write_exactly_the_three_form_keys():
    assert set(tr.mobile_updates(mobile_raw())) == {
        "mobile_enabled", "mobile_port", "mobile_address"}


@pytest.mark.parametrize("status,kind,fragment", [
    (MobileStatus(M_OFF), "muted", "Aus"),
    (MobileStatus(M_STARTING, None, 17654), "muted", "Startet"),
    (MobileStatus(M_RUNNING, "192.168.1.20", 17654), "ok", "192.168.1.20:17654"),
    (MobileStatus(M_ERROR, None, None, REASON_INVALID_PORT), "error", "Port"),
    (MobileStatus(M_ERROR, None, 17654, REASON_NO_ADDRESS), "error", "Netzwerk"),
    (MobileStatus(M_ERROR, "10.9.9.9", 17654, REASON_ADDRESS_GONE), "error", "10.9.9.9"),
    (MobileStatus(M_ERROR, "192.168.1.20", 17654, REASON_PORT_IN_USE), "error", "17654"),
    (MobileStatus(M_ERROR, "192.168.1.20", 17654, REASON_START_FAILED), "error", "Protokoll"),
])
def test_the_status_view(status, kind, fragment):
    text, got_kind = tr.mobile_status_view(status)
    assert got_kind == kind and fragment in text


def test_an_unknown_error_reason_still_gets_a_sentence():
    text, kind = tr.mobile_status_view(MobileStatus(M_ERROR, None, None, "ganz neu"))
    assert kind == "error" and "Protokoll" in text


def test_the_vanished_address_status_offers_the_choice():
    text, _kind = tr.mobile_status_view(
        MobileStatus(M_ERROR, "10.9.9.9", 17654, REASON_ADDRESS_GONE))
    assert "wählen" in text.lower()


NOW_ISO = "2026-10-08T12:00:00Z"


def device(**overrides):
    record = {"id": "phone-0001", "name": "Pixel von Sven", "revoked": False,
              "last_seen": "2026-10-07T09:15:00Z", "expires_at": "2026-11-06T09:15:00Z"}
    record.update(overrides)
    return record


def test_a_device_row_shows_name_last_seen_and_expiry_in_german_format():
    text = tr.device_row_text(device(), NOW_ISO)
    assert "Pixel von Sven" in text and "07.10.2026 09:15" in text and "06.11.2026" in text
    assert "widerrufen" not in text and "abgelaufen" not in text


def test_a_revoked_device_is_marked():
    assert "widerrufen" in tr.device_row_text(device(revoked=True), NOW_ISO)


def test_an_expired_device_is_marked_from_the_second_it_expires():
    assert "abgelaufen" not in tr.device_row_text(device(expires_at="2026-10-08T12:00:01Z"), NOW_ISO)
    assert "abgelaufen" in tr.device_row_text(device(expires_at="2026-10-08T12:00:00Z"), NOW_ISO)


def test_a_device_row_survives_missing_fields():
    text = tr.device_row_text({"id": "x", "name": ""}, NOW_ISO)
    assert isinstance(text, str) and text


@pytest.mark.parametrize("seconds,expected", [
    (300, "5:00"), (299, "4:59"), (61, "1:01"), (60, "1:00"), (9, "0:09"), (0, "0:00"),
    (-5, "0:00"),
])
def test_the_countdown(seconds, expected):
    assert tr.format_countdown(seconds) == expected


def test_the_first_enable_notice_names_the_three_things_the_spec_demands():
    notice = tr.FIRST_ENABLE_NOTICE
    assert "unverschlüsselt" in notice
    assert "vertrauenswürdig" in notice
    assert "Autostart" in notice


def dev(device_id, token_hash, name="P", revoked=False, previous=""):
    # `previous_token_hash` ist leer nach dem Koppeln und gefüllt nach jedem Abgleich
    # (`mobile_pairing.renew`): daran unterscheidet `pair_changes` beides.
    return {"id": device_id, "token_hash": token_hash, "name": name, "revoked": revoked,
            "previous_token_hash": previous}


def test_pair_changes_finds_a_new_device():
    changes = tr.pair_changes([dev("a", "h1")], [dev("a", "h1"), dev("b", "h2", "Neu")])
    assert [d["name"] for d in changes.added] == ["Neu"] and changes.replaced == []


def test_pair_changes_flags_a_replaced_live_device():
    changes = tr.pair_changes([dev("a", "h1", "Alt")], [dev("a", "h2", "Alt")])
    assert changes.added == [] and [d["name"] for d in changes.replaced] == ["Alt"]


def test_pair_changes_does_not_warn_when_the_replaced_device_was_revoked():
    changes = tr.pair_changes([dev("a", "h1", "Alt", revoked=True)], [dev("a", "h2", "Alt")])
    assert changes.replaced == [] and [d["name"] for d in changes.added] == ["Alt"]


def test_pair_changes_ignores_renewals_that_keep_the_token_state():
    assert tr.pair_changes([dev("a", "h1")], [dev("a", "h1")]).empty


def test_pair_changes_reports_nothing_for_an_unchanged_or_shrunk_list():
    assert tr.pair_changes([dev("a", "h1")], []).empty


def test_a_normal_sync_renewal_is_not_a_replacement():
    # Jeder Abgleich erneuert das Token (neuer token_hash, gefülltes previous_token_hash).
    # Das darf der offene Koppel-Dialog nie als „Gerät ersetzt" melden.
    changes = tr.pair_changes([dev("a", "h1")], [dev("a", "h2", previous="h1")])
    assert changes.empty


def test_two_renewals_in_a_row_are_still_not_a_replacement():
    changes = tr.pair_changes([dev("a", "h2", previous="h1")], [dev("a", "h3", previous="h1")])
    assert changes.empty


def test_a_new_pairing_of_an_existing_device_is_a_replacement_even_after_renewals():
    changes = tr.pair_changes([dev("a", "h3", "Alt", previous="h2")], [dev("a", "h9", "Alt")])
    assert [d["name"] for d in changes.replaced] == ["Alt"]


def test_a_phone_that_pairs_and_syncs_right_away_is_just_added():
    changes = tr.pair_changes([dev("a", "h1")], [dev("a", "h1"), dev("b", "h5", "Neu", previous="h4")])
    assert [d["name"] for d in changes.added] == ["Neu"] and changes.replaced == []


@pytest.mark.parametrize("active,left,paired,state,text", [
    (True, 299, False, "counting", "Gültig noch 4:59"),
    (True, 1, False, "counting", "Gültig noch 0:01"),
    (True, 0, False, "counting", "Gültig noch 0:00"),      # aktiv, aber unter einer Sekunde
    (False, 0, False, "expired", "Der Code ist abgelaufen"),
    (False, 0, True, "paired", ""),                           # in der letzten Sekunde gekoppelt
    (True, 120, True, "paired", ""),
])
def test_the_pair_poll_view(active, left, paired, state, text):
    got_state, got_text = tr.pair_poll_view(active=active, seconds_left=left, paired=paired)
    assert got_state == state and text in got_text


def test_only_a_counting_code_keeps_the_poll_running():
    assert tr.pair_poll_keeps_running("counting") is True
    assert tr.pair_poll_keeps_running("expired") is False
    assert tr.pair_poll_keeps_running("paired") is False


def test_revoke_outcome_reports_success_and_expected_write_errors():
    from src.mobile_store import MobileStoreReadOnly
    assert tr.revoke_outcome(lambda: 3) == {"ok": True, "result": 3}
    failed = tr.revoke_outcome(lambda: (_ for _ in ()).throw(OSError(28, "Platte voll")))
    assert failed["ok"] is False and isinstance(failed["error"], OSError)
    read_only = tr.revoke_outcome(lambda: (_ for _ in ()).throw(MobileStoreReadOnly("x")))
    assert read_only["ok"] is False and isinstance(read_only["error"], MobileStoreReadOnly)


def test_revoke_outcome_lets_a_programming_error_through():
    with pytest.raises(RuntimeError):
        tr.revoke_outcome(lambda: (_ for _ in ()).throw(RuntimeError("Bug")))


def test_the_revoke_error_text_names_the_consequence():
    text = tr.REVOKE_ERROR_TEXT
    assert "weiterhin" in text and "Datenordner" in text


def test_the_first_enable_notice_uses_real_line_breaks():
    assert "\n\n" in tr.FIRST_ENABLE_NOTICE
    assert "\\n" not in tr.FIRST_ENABLE_NOTICE
