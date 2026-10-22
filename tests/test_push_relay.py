"""Das Relay-Objekt eines Handys abräumen (#331)."""
import logging
import pathlib
import re
import socket
import urllib.error
import urllib.request

import pytest

from src import push_relay

SECRET = "Q" * 43
ROOT = pathlib.Path(__file__).resolve().parent.parent


class FakeResponse:
    def __init__(self, status=204):
        self.status = status

    def read(self, *_):
        return b""

    def getcode(self):
        return self.status

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


class FakeOpener:
    def __init__(self, result):
        self.result, self.requests = result, []

    def open(self, request, timeout=None):
        self.requests.append((request, timeout))
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result


def delete(result=None, **kwargs):
    opener = FakeOpener(FakeResponse() if result is None else result)
    return push_relay.delete_device(SECRET, opener=opener, **kwargs), opener


def test_the_request_is_a_delete_with_the_secret_as_bearer():
    ok, opener = delete()
    request, timeout = opener.requests[0]
    assert ok is True
    assert request.get_method() == "DELETE"
    assert request.full_url == f"{push_relay.RELAY_URL}/v1/device"
    assert request.get_header("Authorization") == f"Bearer {SECRET}"
    assert request.data is None
    assert timeout == push_relay.TIMEOUT_S


@pytest.mark.parametrize("status", [200, 204])
def test_a_success_status_is_true(status):
    assert delete(FakeResponse(status))[0] is True


@pytest.mark.parametrize("error", [
    urllib.error.HTTPError("u", 401, "x", {}, None), urllib.error.HTTPError("u", 429, "x", {}, None),
    urllib.error.HTTPError("u", 500, "x", {}, None), urllib.error.HTTPError("u", 301, "x", {}, None),
    urllib.error.URLError("kein Netz"), TimeoutError("zu langsam"), socket.timeout("zu langsam"),
    ConnectionResetError("weg"), OSError("kaputt"), ValueError("komisch")])
def test_every_failure_is_false_and_never_raises(error):
    assert delete(error)[0] is False


def test_a_redirect_is_not_followed_and_counts_as_failure():
    opener = push_relay._build_opener()
    request = push_relay._request(SECRET, push_relay.RELAY_URL)
    handler = next(h for h in opener.handlers if isinstance(h, urllib.request.HTTPRedirectHandler))
    with pytest.raises(urllib.error.HTTPError):
        handler.redirect_request(request, None, 301, "x", {}, "https://anders.example/")


def test_nothing_in_the_log_carries_the_secret(caplog):
    with caplog.at_level(logging.DEBUG):
        delete(urllib.error.URLError(f"Fehler bei {SECRET}"))
        delete(urllib.error.HTTPError("u", 500, f"Boom {SECRET}", {}, None))
    assert SECRET not in caplog.text


def test_the_relay_url_matches_the_one_in_the_pwa():
    source = (ROOT / "pwa" / "relay-client.js").read_text(encoding="utf-8")
    match = re.search(r"export const RELAY_URL = '([^']+)'", source)
    assert match is not None
    assert push_relay.RELAY_URL == match.group(1)
