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
