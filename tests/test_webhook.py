"""Pure Webhook-Logik: URL-Regel, Auth, Payload, Transport, Fehler-Mapping."""

import pytest

from src.webhook import is_private_host, validate_url


@pytest.mark.parametrize("host", [
    "localhost", "127.0.0.1", "127.1.2.3", "::1",
    "10.0.0.5", "172.16.0.1", "172.31.255.254", "192.168.1.10",
    "100.64.0.1",                      # CGNAT (Tailscale u.ä.)
    "169.254.1.1", "fe80::1",          # Link-Local
    "fd00::1",                         # IPv6 ULA
    "nas.local", "server.lan", "printer.home.arpa", "api.internal",
    "nas",                             # Single-Label, nur lokal auflösbar
])
def test_private_hosts(host):
    assert is_private_host(host) is True


@pytest.mark.parametrize("host", [
    "example.com", "erp.example.com",
    "8.8.8.8",
    "172.32.0.1",                      # knapp außerhalb von 172.16/12
    "2606:4700::1111",
])
def test_public_hosts(host):
    assert is_private_host(host) is False


def test_http_allowed_inside_local_network():
    assert validate_url("http://192.168.1.10:5678/hook") == (True, "")


def test_http_rejected_for_public_host():
    ok, msg = validate_url("http://erp.example.com/hook")
    assert ok is False
    assert "https" in msg


def test_https_always_allowed():
    assert validate_url("https://erp.example.com/hook") == (True, "")


def test_unsupported_scheme_rejected():
    ok, msg = validate_url("ftp://example.com/x")
    assert ok is False
    assert msg


def test_missing_host_rejected():
    ok, msg = validate_url("https:///hook")
    assert ok is False
    assert msg


def test_ipv6_url_brackets_are_handled():
    assert validate_url("http://[::1]:8080/hook") == (True, "")


def test_broken_ipv6_url_is_rejected_not_raised():
    """urlsplit selbst wirft hier ValueError — validate_url muss das fangen,
    sonst landet die Exception im Tk-Excepthook statt in einer Meldung."""
    ok, msg = validate_url("http://[::1/hook")
    assert ok is False
    assert msg


def test_percent_encoded_host_is_not_treated_as_private():
    """urlsplit liefert '8%2e8%2e8%2e8' (kein Punkt → sähe wie ein
    Single-Label aus), urllib dekodiert beim Request aber zu 8.8.8.8 und
    schickt den Klartext-POST an eine öffentliche Adresse."""
    ok, msg = validate_url("http://8%2e8%2e8%2e8/hook")
    assert ok is False
    assert msg


def test_decimal_ip_notation_is_not_treated_as_private():
    """http://2130706433/ ist punktlos, wird vom OS aber aufgelöst."""
    ok, _ = validate_url("http://2130706433/hook")
    assert ok is False


@pytest.mark.parametrize("host", ["0x08080808", "0X08080808"])
def test_hex_ip_notation_is_not_treated_as_private(host):
    """http://0x08080808/ ist wie die Dezimalnotation punktlos und wird von
    glibc's inet_aton-Semantik zu 8.8.8.8 aufgelöst — derselbe Bypass wie bei
    der Dezimalnotation, nur mit Hex-Präfix (auch großgeschrieben, 0X...)."""
    ok, _ = validate_url(f"http://{host}/hook")
    assert ok is False


def test_userinfo_in_url_does_not_leak_into_host_check():
    ok, _ = validate_url("http://nas@8.8.8.8/hook")
    assert ok is False


def test_trailing_dot_host_still_private():
    assert validate_url("http://nas.local./hook") == (True, "")


from src.webhook import auth_headers, sign_hmac


def test_sign_hmac_matches_rfc4231_test_case_2():
    """RFC 4231, Test Case 2 — veröffentlichter Vektor, kein selbstgerechnetes
    Ergebnis (das wäre tautologisch)."""
    digest = sign_hmac("Jefe", b"what do ya want for nothing?")
    assert digest == (
        "5bdcc146bf60754e6a042426089575c75a003f089d2739839dec58b964ec3843"
    )


def test_auth_none_sends_no_header():
    assert auth_headers({"mode": "none"}, b"body") == {}


def test_auth_header_mode_passes_value_through():
    headers = auth_headers(
        {"mode": "header", "header": "Authorization", "value": "Bearer abc123"},
        b"body",
    )
    assert headers == {"Authorization": "Bearer abc123"}


def test_auth_header_mode_supports_custom_header_name():
    headers = auth_headers(
        {"mode": "header", "header": "X-API-Key", "value": "k"}, b"body")
    assert headers == {"X-API-Key": "k"}


def test_auth_hmac_signs_body_with_prefix():
    headers = auth_headers(
        {"mode": "hmac", "header": "X-Hub-Signature-256",
         "prefix": "sha256=", "secret": "Jefe"},
        b"what do ya want for nothing?",
    )
    assert headers == {
        "X-Hub-Signature-256":
            "sha256=5bdcc146bf60754e6a042426089575c75a003f089d2739839dec58b964ec3843"
    }


def test_auth_hmac_prefix_defaults_to_github_style():
    """Fehlender prefix-Schlüssel → der dokumentierte Default, nicht „kein
    Präfix". Empfänger im GitHub-Stil erwarten sha256=<hex>."""
    headers = auth_headers(
        {"mode": "hmac", "header": "X-Hub-Signature-256", "secret": "Jefe"},
        b"what do ya want for nothing?",
    )
    assert headers["X-Hub-Signature-256"].startswith("sha256=")


def test_auth_hmac_prefix_may_be_empty():
    headers = auth_headers(
        {"mode": "hmac", "header": "X-Sig", "prefix": "", "secret": "Jefe"},
        b"what do ya want for nothing?",
    )
    assert headers["X-Sig"].startswith("5bdcc146")


@pytest.mark.parametrize("bad", ["a\rb", "a\nb", "a\x00b"])
def test_control_characters_in_header_value_are_rejected(bad):
    with pytest.raises(ValueError):
        auth_headers({"mode": "header", "header": "Authorization", "value": bad},
                     b"body")


@pytest.mark.parametrize("bad", ["X\rY", "X\nY", "X\x00Y"])
def test_control_characters_in_header_name_are_rejected(bad):
    with pytest.raises(ValueError):
        auth_headers({"mode": "header", "header": bad, "value": "v"}, b"body")


def test_unknown_auth_mode_is_rejected():
    with pytest.raises(ValueError):
        auth_headers({"mode": "oauth"}, b"body")


import datetime
import json

from tests.conftest import ist_slot as _slot

from src.webhook import build_body, build_json_payload, total_minutes


def _entries():
    return {
        "2026-06-30": {"slots": [_slot("08:00", "16:00")]},          # außerhalb
        "2026-07-01": {"slots": [_slot("08:00", "16:00", pause=30, kategorie="A")]},
        "2026-07-02": {"slots": [_slot("09:00", "12:15", kategorie="B")]},
    }


def _payload(**over):
    base = dict(
        date_from=datetime.date(2026, 7, 1), date_to=datetime.date(2026, 7, 31),
        entries=_entries(), name="Sven", sender="sven@example.com",
        categories=None, generated_at="2026-08-26T09:14:00Z",
    )
    base.update(over)
    return build_json_payload(**base)


def test_payload_has_kind_and_version():
    doc = _payload()
    assert doc["kind"] == "zeiterfassung-report"
    assert doc["schema_version"] == 2
    assert doc["generated_at"] == "2026-08-26T09:14:00Z"
    assert doc["sender"] == "sven@example.com"
    assert doc["name"] == "Sven"
    assert doc["period"] == {"from": "2026-07-01", "to": "2026-07-31"}


def test_payload_drops_days_outside_the_period():
    assert list(_payload()["entries"]) == ["2026-07-01", "2026-07-02"]


def test_payload_slots_use_share_v3_shape():
    slot = _payload()["entries"]["2026-07-01"]["slots"][0]
    assert set(slot) == {"start", "end", "pause", "kategorie"}


def test_payload_strips_unknown_slot_fields():
    """Der Test oben allein wäre tautologisch: `ist_slot()` erzeugt genau die
    vier Felder, die er prüft. Erst ein Slot MIT Fremdfeld beweist, dass
    projiziert wird — und dieser Fall ist real, weil Storage._load Slots
    nicht normalisiert (nur der Schreibpfad tut das)."""
    entries = {"2026-07-01": {"slots": [
        {"start": "08:00", "end": "16:00", "pause": 30, "kategorie": "A",
         "gcal_event_id": "geheim", "interner_kram": 42},
    ]}}
    doc = _payload(entries=entries)
    assert set(doc["entries"]["2026-07-01"]["slots"][0]) == {
        "start", "end", "pause", "kategorie"}


def test_payload_fills_missing_slot_fields_like_storage_does():
    """Fehlende Felder bekommen dieselben Defaults wie in
    storage._normalize_slot (pause 0, kategorie ""). Ein None in `pause`
    würde total_minutes über calculate_hours in einen TypeError laufen
    lassen — der Empfänger bekommt so ein formstabiles Dokument."""
    entries = {"2026-07-01": {"slots": [{"start": "08:00", "end": "16:00"}]}}
    doc = _payload(entries=entries)
    slot = doc["entries"]["2026-07-01"]["slots"][0]
    assert set(slot) == {"start", "end", "pause", "kategorie"}
    assert slot["pause"] == 0
    assert slot["kategorie"] == ""
    assert doc["total_minutes"] == 480


def test_payload_categories_none_when_unfiltered():
    assert _payload()["categories"] is None


def test_payload_applies_category_filter():
    doc = _payload(categories=["A"])
    assert list(doc["entries"]) == ["2026-07-01"]
    assert doc["categories"] == ["A"]


def test_payload_empty_period_yields_empty_entries():
    doc = _payload(date_from=datetime.date(2030, 1, 1),
                   date_to=datetime.date(2030, 1, 31))
    assert doc["entries"] == {}
    assert doc["total_minutes"] == 0


def test_total_minutes_sums_glatte_werte():
    """CLAUDE.md: angezeigte Summen laufen über hours_to_minutes, nie über
    Dezimalstunden. 08:00-16:00 abzgl. 30 min = 450, 09:00-12:15 = 195."""
    entries = {
        "2026-07-01": {"slots": [_slot("08:00", "16:00", pause=30)]},
        "2026-07-02": {"slots": [_slot("09:00", "12:15")]},
    }
    assert total_minutes(entries) == 645


def test_total_minutes_rundet_je_slot_nicht_erst_am_ende():
    """Der eigentliche Beweis der Minuten-Regel aus CLAUDE.md.

    Fünf Slots à 7 min: `calculate_hours` rundet jeden auf 0,12 h (7 min sind
    0,1166… h). Je Slot auf Minuten gerundet und dann summiert ergibt 5 × 7 =
    35. Erst die Dezimalstunden zu summieren (5 × 0,12 = 0,60 h) und dann zu
    runden ergäbe 36 — eine Minute zu viel.

    Mit glatten Werten wie 7,5 h liefern beide Reihenfolgen dasselbe; ein Test
    nur damit wäre grün, auch wenn die Summierung falsch herum liefe.
    """
    entries = {
        "2026-07-01": {"slots": [
            _slot("08:00", "08:07"), _slot("09:00", "09:07"),
            _slot("10:00", "10:07"), _slot("11:00", "11:07"),
            _slot("12:00", "12:07"),
        ]},
    }
    assert total_minutes(entries) == 35


def test_body_json_only():
    ct, body = build_body(json_bytes=b'{"a":1}', pdf_bytes=None,
                          pdf_filename="r.pdf", boundary="B")
    assert ct == "application/json; charset=utf-8"
    assert body == b'{"a":1}'


def test_body_pdf_only():
    ct, body = build_body(json_bytes=None, pdf_bytes=b"%PDF-1.4",
                          pdf_filename="r.pdf", boundary="B")
    assert ct == "application/pdf"
    assert body == b"%PDF-1.4"


def test_body_multipart_contains_both_parts():
    ct, body = build_body(json_bytes=b'{"a":1}', pdf_bytes=b"%PDF-1.4",
                          pdf_filename="Zeiterfassung_20260701_20260731.pdf",
                          boundary="BOUNDARY")
    assert ct == 'multipart/form-data; boundary="BOUNDARY"'
    text = body.decode("latin-1")
    assert '--BOUNDARY\r\n' in text
    assert 'name="data"' in text
    assert "application/json" in text
    assert 'name="report"' in text
    assert 'filename="Zeiterfassung_20260701_20260731.pdf"' in text
    assert "application/pdf" in text
    assert text.endswith("--BOUNDARY--\r\n")
    assert b"%PDF-1.4" in body


def test_body_requires_at_least_one_payload():
    with pytest.raises(ValueError):
        build_body(json_bytes=None, pdf_bytes=None, pdf_filename="r.pdf",
                   boundary="B")


def test_payload_serializes_to_json():
    json.dumps(_payload())  # wirft nicht


import io
import socket
import urllib.error
import urllib.request

import src.webhook as wh
from src.webhook import classify_error, post


class _Resp(io.BytesIO):
    def __init__(self, status=200, body=b"ok"):
        super().__init__(body)
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_post_sends_headers_and_body(monkeypatch):
    seen = {}

    def fake_open(self, req, timeout=None):
        seen["url"] = req.full_url
        seen["data"] = req.data
        seen["ct"] = req.get_header("Content-type")
        seen["auth"] = req.get_header("Authorization")
        seen["timeout"] = timeout
        return _Resp(202)

    monkeypatch.setattr(urllib.request.OpenerDirector, "open", fake_open)
    status = post("https://example.com/hook",
                  {"Content-Type": "application/json", "Authorization": "Bearer x"},
                  b"{}")
    assert status == 202
    assert seen["url"] == "https://example.com/hook"
    assert seen["data"] == b"{}"
    assert seen["auth"] == "Bearer x"
    assert seen["timeout"] == 30


@pytest.mark.parametrize("code", [301, 302, 303, 307, 308])
def test_no_redirect_is_ever_followed(code):
    """Jeder Redirect endet als HTTPError. Würde urllib folgen, ginge bei
    301/302/303 der POST-Body verloren (die Anfrage wird zu einem GET) und
    der Auth-Header an einen womöglich fremden Host mit."""
    handler = wh._NoRedirectHandler()
    req = urllib.request.Request("https://a.example/hook", data=b"{}")
    with pytest.raises(urllib.error.HTTPError):
        handler.redirect_request(
            req, io.BytesIO(b""), code, "Moved", {}, "https://b.example/hook")


def test_redirect_is_blocked_even_to_the_same_host():
    """Auch ein harmloser trailing-slash-Redirect zählt — sonst verschwände
    der Body und die App meldete trotzdem Erfolg."""
    handler = wh._NoRedirectHandler()
    req = urllib.request.Request("https://a.example/hook", data=b"{}")
    with pytest.raises(urllib.error.HTTPError):
        handler.redirect_request(
            req, io.BytesIO(b""), 301, "Moved", {}, "https://a.example/hook/")


def test_opener_has_no_default_redirect_handler():
    """Gegenprobe auf der echten Opener-Kette: der Default-Handler von urllib
    darf nicht mehr drinhängen, sonst greift unser Ersatz gar nicht."""
    opener = wh._build_opener()
    handlers = [type(h).__name__ for h in opener.handlers]
    assert "HTTPRedirectHandler" not in handlers
    assert "_NoRedirectHandler" in handlers


@pytest.mark.parametrize("code", [301, 302, 303, 307, 308])
def test_classify_redirect_asks_for_the_final_url(code):
    res = classify_error(_http_error(code))
    assert res["kind"] == "redirect"
    assert res["tb"] is None


def _http_error(code, body=b""):
    return urllib.error.HTTPError(
        "https://example.com/hook", code, "Err", {}, io.BytesIO(body))


@pytest.mark.parametrize("code,kind", [
    (401, "auth"), (403, "auth"), (404, "notfound"),
    (400, "client"), (422, "client"),
    (500, "server"), (503, "server"),
])
def test_classify_http_status_codes(code, kind):
    res = classify_error(_http_error(code))
    assert res["ok"] is False
    assert res["kind"] == kind
    assert str(code) in res["detail"]


def test_http_error_is_a_server_answer_not_an_unexpected_crash():
    """Ohne den HTTPError-Zweig fiele ein 500 in den generischen Ast und käme
    mit Traceback als „unerwarteter Fehler" beim Nutzer an."""
    res = classify_error(_http_error(500))
    assert res["kind"] == "server"
    assert res["tb"] is None


def test_classify_server_error_includes_truncated_body():
    res = classify_error(_http_error(500, b"x" * 2000))
    assert "xxx" in res["detail"]
    assert len(res["detail"]) < 700


def test_classify_urlerror_is_offline():
    res = classify_error(urllib.error.URLError(socket.gaierror("no dns")))
    assert res["kind"] == "offline"
    assert res["tb"] is None


def test_classify_timeout_is_offline():
    assert classify_error(TimeoutError("timed out"))["kind"] == "offline"


def test_classify_unexpected_error_carries_traceback():
    try:
        raise RuntimeError("boom")
    except RuntimeError as e:
        res = classify_error(e)
    assert res["kind"] == "error"
    assert "RuntimeError" in res["tb"]


from src.webhook import deliver


def _record(**over):
    base = {
        "id": "abc", "name": "Server", "url": "https://example.com/hook",
        "enabled": True, "payload": {"json": True, "pdf": False},
        "auth": {"mode": "none"},
    }
    base.update(over)
    return base


def test_deliver_posts_and_reports_status(monkeypatch):
    seen = {}

    def fake_post(url, headers, body, timeout=30):
        seen.update(url=url, headers=headers, body=body)
        return 204

    monkeypatch.setattr(wh, "post", fake_post)
    res = deliver(_record(), json_bytes=b'{"a":1}', pdf_bytes=None,
                       pdf_filename="r.pdf")
    assert res == {"ok": True, "status": 204}
    assert seen["headers"]["Content-Type"] == "application/json; charset=utf-8"
    assert seen["body"] == b'{"a":1}'


def test_deliver_adds_auth_header(monkeypatch):
    seen = {}
    monkeypatch.setattr(wh, "post",
                        lambda url, headers, body, timeout=30: seen.update(headers=headers) or 200)
    deliver(
        _record(auth={"mode": "header", "header": "Authorization", "value": "Bearer t"}),
        json_bytes=b"{}", pdf_bytes=None, pdf_filename="r.pdf")
    assert seen["headers"]["Authorization"] == "Bearer t"


def test_deliver_rejects_http_to_public_host_before_posting(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("darf nicht gesendet werden")

    monkeypatch.setattr(wh, "post", boom)
    res = deliver(_record(url="http://erp.example.com/hook"),
                       json_bytes=b"{}", pdf_bytes=None, pdf_filename="r.pdf")
    assert res["ok"] is False
    assert res["kind"] == "config"
    assert "https" in res["detail"]


def test_deliver_maps_http_error(monkeypatch):
    def fake_post(*a, **k):
        raise _http_error(500, b"kaputt")

    monkeypatch.setattr(wh, "post", fake_post)
    res = deliver(_record(), json_bytes=b"{}", pdf_bytes=None,
                       pdf_filename="r.pdf")
    assert res["ok"] is False
    assert res["kind"] == "server"


def test_deliver_never_raises_on_unexpected_error(monkeypatch):
    def fake_post(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr(wh, "post", fake_post)
    res = deliver(_record(), json_bytes=b"{}", pdf_bytes=None,
                       pdf_filename="r.pdf")
    assert res["ok"] is False
    assert res["kind"] == "error"
    assert res["tb"]


def test_deliver_rejects_bad_auth_config_as_config_error(monkeypatch):
    monkeypatch.setattr(wh, "post", lambda *a, **k: 200)
    res = deliver(
        _record(auth={"mode": "header", "header": "Authorization",
                      "value": "Bearer \nX-Evil: 1"}),
        json_bytes=b"{}", pdf_bytes=None, pdf_filename="r.pdf")
    assert res["kind"] == "config"


@pytest.mark.parametrize("record,label", [
    (None, "record ist None"),
    ([], "record ist Liste"),
    ({"url": 12345, "auth": {"mode": "none"}}, "url ist Zahl"),
    ({"url": "https://a.example/h", "auth": "oops"}, "auth ist String"),
    ({"url": "https://a.example/h",
      "auth": {"mode": "header", "header": 123, "value": "x"}},
     "Header-Name ist Zahl"),
])
def test_deliver_survives_malformed_records(monkeypatch, record, label):
    """Der „wirft nie"-Vertrag gilt auch für Müll-Typen.

    Genau die Bedrohung, die schon die URL-Nachprüfung begründet: eine von
    Hand editierte webhooks.json kann in jedem Feld jeden Typ tragen. Ohne
    diese Absicherung entkäme ein AttributeError/TypeError aus dem
    Worker-Thread, `on_done` käme nie, und der Sende-Dialog bliebe dauerhaft
    auf „Sende…" stehen.
    """
    monkeypatch.setattr(wh, "post", lambda *a, **k: 200)
    res = deliver(record, json_bytes=b"{}", pdf_bytes=None,
                  pdf_filename="r.pdf")
    assert res["ok"] is False, label
    assert res["kind"] == "config", label


def test_deliver_signs_the_exact_body_sent(monkeypatch):
    seen = {}
    monkeypatch.setattr(
        wh, "post",
        lambda url, headers, body, timeout=30: seen.update(headers=headers, body=body) or 200)
    deliver(
        _record(auth={"mode": "hmac", "header": "X-Sig", "prefix": "",
                      "secret": "Jefe"}),
        json_bytes=b"what do ya want for nothing?", pdf_bytes=None,
        pdf_filename="r.pdf")
    assert seen["headers"]["X-Sig"] == wh.sign_hmac("Jefe", seen["body"])


def test_payload_without_vacation_has_null_fields():
    payload = build_json_payload(
        date_from=datetime.date(2026, 7, 1), date_to=datetime.date(2026, 7, 31),
        entries={}, name="", sender="", categories=None,
        generated_at="2026-08-30T10:00:00Z")
    assert payload["vacation"] is None
    assert payload["vacation_minutes"] == 0


def test_payload_carries_vacation_days_in_period():
    payload = build_json_payload(
        date_from=datetime.date(2026, 12, 1), date_to=datetime.date(2026, 12, 31),
        entries={}, name="", sender="", categories=None,
        generated_at="2026-08-30T10:00:00Z",
        vacation_days={
            "2026-12-28": 480, "2026-12-29": 480, "2026-12-30": 480,
            "2026-12-31": 240, "2027-01-04": 480,
        })
    assert payload["vacation"] == {
        "2026-12-28": 480, "2026-12-29": 480,
        "2026-12-30": 480, "2026-12-31": 240,
    }
    assert payload["vacation_minutes"] == 1680


def test_payload_vacation_matches_report_slice():
    """Webhook und Report müssen exakt denselben Ausschnitt behaupten —
    beide gehen über filter_period."""
    from src.report import filter_period
    snapshot = {"2026-12-31": 240, "2027-01-04": 480}
    payload = build_json_payload(
        date_from=datetime.date(2026, 12, 1), date_to=datetime.date(2026, 12, 31),
        entries={}, name="", sender="", categories=None,
        vacation_days=snapshot)
    assert payload["vacation"] == filter_period(
        datetime.date(2026, 12, 1), datetime.date(2026, 12, 31), snapshot)


def test_payload_caps_vacation_against_worktime_on_the_same_day():
    """Xveyn#97: derselbe Kalendertag darf nicht Urlaub UND Ist-Zeit voll
    ausweisen — sonst summiert ein Empfänger mehr Stunden, als der Tag hat.
    Gekappt wie in Mail-HTML und PDF, damit alle drei Wege dieselbe Zahl
    behaupten."""
    payload = build_json_payload(
        date_from=datetime.date(2026, 9, 1), date_to=datetime.date(2026, 9, 30),
        entries={"2026-09-01": {"slots": [_slot("08:00", "12:00")]}},
        name="", sender="", categories=None,
        vacation_days={"2026-09-01": 480})
    assert payload["vacation"] == {"2026-09-01": 240}
    assert payload["vacation_minutes"] == 240
    assert payload["total_minutes"] == 240  # Ist-Zeit unveraendert
