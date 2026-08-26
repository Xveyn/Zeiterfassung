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
    assert doc["schema_version"] == 1
    assert doc["generated_at"] == "2026-08-26T09:14:00Z"
    assert doc["sender"] == "sven@example.com"
    assert doc["name"] == "Sven"
    assert doc["period"] == {"from": "2026-07-01", "to": "2026-07-31"}


def test_payload_drops_days_outside_the_period():
    assert list(_payload()["entries"]) == ["2026-07-01", "2026-07-02"]


def test_payload_slots_use_share_v3_shape():
    slot = _payload()["entries"]["2026-07-01"]["slots"][0]
    assert set(slot) == {"start", "end", "pause", "kategorie"}


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


def test_total_minutes_sums_minutes_not_decimal_hours():
    """CLAUDE.md: angezeigte Summen laufen über hours_to_minutes, nie über
    Dezimalstunden. 08:00-16:00 abzgl. 30 min = 450, 09:00-12:15 = 195."""
    entries = {
        "2026-07-01": {"slots": [_slot("08:00", "16:00", pause=30)]},
        "2026-07-02": {"slots": [_slot("09:00", "12:15")]},
    }
    assert total_minutes(entries) == 645


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
