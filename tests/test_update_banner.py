"""UpdateBanner: Entscheidungslogik (show_if_newer) und Download-URL-Wahl
ohne Tk — _show wird gemockt, webbrowser/pick_asset_url gepatcht."""

from unittest.mock import MagicMock

import src.update_banner as ub
from src.update_banner import UpdateBanner


class _FakeSettings:
    def __init__(self, dismissed_version=None):
        self._d = {"dismissed_version": dismissed_version}

    def get(self, key, default=None):
        return self._d.get(key, default)

    def set(self, key, value):
        self._d[key] = value


def _release(version="1.2.0", html_url="https://example/r", assets=None):
    r = MagicMock()
    r.version = version
    r.html_url = html_url
    r.assets = assets if assets is not None else []
    return r


def _banner(settings):
    b = UpdateBanner(root=object(), settings=settings, get_anchor=lambda: object())
    b._show = MagicMock()
    return b


def test_show_if_newer_dismissed_version_does_not_show():
    b = _banner(_FakeSettings(dismissed_version="1.2.0"))
    b.show_if_newer(_release(version="1.2.0"))
    b._show.assert_not_called()


def test_show_if_newer_new_version_shows():
    b = _banner(_FakeSettings(dismissed_version="1.1.0"))
    rel = _release(version="1.2.0")
    b.show_if_newer(rel)
    b._show.assert_called_once_with(rel)


def test_open_download_uses_asset_url(monkeypatch):
    opened = []
    monkeypatch.setattr(ub.webbrowser, "open", lambda url: opened.append(url))
    monkeypatch.setattr(ub, "pick_asset_url",
                        lambda assets, sysname, ver: "https://asset/dl")
    b = UpdateBanner(root=object(), settings=_FakeSettings(),
                     get_anchor=lambda: object())
    b._open_download(_release())
    assert opened == ["https://asset/dl"]


def test_open_download_falls_back_to_html_url(monkeypatch):
    opened = []
    monkeypatch.setattr(ub.webbrowser, "open", lambda url: opened.append(url))
    monkeypatch.setattr(ub, "pick_asset_url", lambda assets, sysname, ver: None)
    b = UpdateBanner(root=object(), settings=_FakeSettings(),
                     get_anchor=lambda: object())
    b._open_download(_release(html_url="https://example/r"))
    assert opened == ["https://example/r"]


def test_show_triggers_resize(monkeypatch):
    # Banner einblenden muss die Fenstergeometrie neu pinnen, sonst wächst das
    # fixe Fenster (resizable(False, False)) nicht und der zuletzt gepackte
    # Footer (Summen-Zeile) wird abgeschnitten (#92).
    monkeypatch.setattr(ub.tk, "Frame", lambda *a, **k: MagicMock())
    monkeypatch.setattr(ub.tk, "Label", lambda *a, **k: MagicMock())
    monkeypatch.setattr(ub, "label_button", lambda *a, **k: MagicMock())
    monkeypatch.setattr(ub, "attach_tooltip", lambda *a, **k: None)
    resized = []
    b = UpdateBanner(root=object(), settings=_FakeSettings(),
                     get_anchor=lambda: object(),
                     on_resize=lambda: resized.append(True))
    b._show(_release())
    assert resized == [True]


def test_dismiss_triggers_resize():
    # Banner ausblenden muss die Geometrie zurückpinnen, damit das Fenster
    # wieder auf die Höhe ohne Banner schrumpft (Gegenstück zu _show).
    resized = []
    b = UpdateBanner(root=object(), settings=_FakeSettings(),
                     get_anchor=lambda: object(),
                     on_resize=lambda: resized.append(True))
    b._banner = MagicMock()
    b._dismiss("1.2.0")
    assert b._banner is None
    assert resized == [True]
