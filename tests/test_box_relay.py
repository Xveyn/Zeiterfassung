"""Die Box am Relay löschen (#358): best effort, wirft nie, loggt das Geheimnis nie."""
import logging
import socket
import urllib.error
import urllib.request

import pytest

from src import box_relay, push_relay

SECRET = "Q" * 43


class FakeResponse:
    def __init__(self, status=204):
        self.status = status

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


def delete(result=None, secret=SECRET, **kwargs):
    opener = FakeOpener(FakeResponse() if result is None else result)
    return box_relay.delete_box(secret, opener=opener, **kwargs), opener


def http_error(status, message="x"):
    return urllib.error.HTTPError("u", status, message, {}, None)


def test_a_204_is_success():
    assert delete(FakeResponse(204))[0] is True
    assert delete(FakeResponse(200))[0] is True


def test_a_401_counts_as_gone():
    assert delete(http_error(401))[0] is True


@pytest.mark.parametrize("status", [429, 500, 503, 404, 400, 301])
def test_other_statuses_and_429_are_failures(status):
    assert delete(http_error(status))[0] is False


@pytest.mark.parametrize("error", [
    urllib.error.URLError("kein Netz"), TimeoutError("zu langsam"), socket.timeout("zu langsam"),
    ConnectionResetError("weg"), OSError("kaputt"), ValueError("komisch")])
def test_a_network_error_returns_false_and_never_raises(error):
    assert delete(error)[0] is False


@pytest.mark.parametrize("secret", [
    "Q" * 42, "Q" * 44, "", "Q" * 42 + "!", "Q" * 42 + " ", "Q" * 42 + "\n", "ä" * 43, None, 12345])
def test_a_malformed_secret_makes_no_request(secret):
    ok, opener = delete(secret=secret)
    assert ok is False
    assert opener.requests == []


def test_the_request_is_a_delete_to_v1_box_with_the_bearer_header_and_no_body():
    ok, opener = delete()
    request, timeout = opener.requests[0]
    assert ok is True
    assert request.get_method() == "DELETE"
    assert request.full_url.endswith("/v1/box")
    assert request.get_header("Authorization") == f"Bearer {SECRET}"
    assert request.get_header("User-agent") == "Zeiterfassung (Box-Relay)"
    assert request.data is None
    assert timeout == push_relay.TIMEOUT_S


def test_the_url_is_built_from_the_push_relay_url():
    _, opener = delete()
    assert opener.requests[0][0].full_url == f"{push_relay.RELAY_URL}/v1/box"
    _, opener = delete(base_url="https://relay.example")
    assert opener.requests[0][0].full_url == "https://relay.example/v1/box"


def test_redirects_are_not_followed():
    opener = box_relay._build_opener()
    request = box_relay._request(SECRET, push_relay.RELAY_URL)
    handler = next(h for h in opener.handlers if isinstance(h, urllib.request.HTTPRedirectHandler))
    with pytest.raises(urllib.error.HTTPError):
        handler.redirect_request(request, None, 301, "x", {}, "https://anders.example/")
    assert delete(http_error(301))[0] is False


def test_the_secret_never_reaches_the_log(caplog):
    with caplog.at_level(logging.DEBUG):
        delete(FakeResponse(204))
        delete(http_error(401, f"Nein {SECRET}"))
        delete(http_error(500, f"Boom {SECRET}"))
        delete(urllib.error.URLError(f"Fehler bei {SECRET}"))
        delete(TimeoutError(f"zu langsam {SECRET}"))
    assert SECRET not in caplog.text
