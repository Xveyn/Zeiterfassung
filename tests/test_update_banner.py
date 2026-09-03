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


def _release(version="1.2.0", html_url="https://example/r", assets=None,
             release_id=None, is_prerelease=False):
    r = MagicMock()
    r.version = version
    r.release_id = release_id if release_id is not None else version
    r.is_prerelease = is_prerelease
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
    b._show.assert_called_once_with(rel, ready_to_install=False)


def test_open_download_uses_asset_url(monkeypatch):
    opened = []
    monkeypatch.setattr(ub.webbrowser, "open", lambda url: opened.append(url))
    monkeypatch.setattr(ub, "pick_asset_url",
                        lambda assets, sysname, ver, machine: "https://asset/dl")
    b = UpdateBanner(root=object(), settings=_FakeSettings(),
                     get_anchor=lambda: object())
    b._open_download(_release())
    assert opened == ["https://asset/dl"]


def test_open_download_falls_back_to_html_url(monkeypatch):
    opened = []
    monkeypatch.setattr(ub.webbrowser, "open", lambda url: opened.append(url))
    monkeypatch.setattr(ub, "pick_asset_url", lambda assets, sysname, ver, machine: None)
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
    b._show(_release(), ready_to_install=False)
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


def test_show_if_newer_compares_release_id_for_prereleases():
    # pre.1 wurde ausgeblendet, pre.2 ist ein neuer Build -> anzeigen.
    b = _banner(_FakeSettings(dismissed_version="1.2.0-pre.1"))
    rel = _release(version="1.2.0", release_id="1.2.0-pre.2", is_prerelease=True)
    b.show_if_newer(rel)
    b._show.assert_called_once_with(rel, ready_to_install=False)


def test_show_if_newer_dismissed_prerelease_does_not_show():
    b = _banner(_FakeSettings(dismissed_version="1.2.0-pre.2"))
    rel = _release(version="1.2.0", release_id="1.2.0-pre.2", is_prerelease=True)
    b.show_if_newer(rel)
    b._show.assert_not_called()


def test_repo_mode_cannot_self_update():
    # Gegenprobe zur "tragenden Entscheidung": im Repo-Modus (kein Frozen-
    # Build) ist supports_self_update() immer False, unabhängig von der
    # Plattform (sys.frozen fehlt bzw. ist False) — der Banner muss also
    # weiterhin den Browser-Download-Pfad nehmen.
    b = UpdateBanner(root=object(), settings=_FakeSettings(),
                     get_anchor=lambda: object())
    assert b._can_self_update is False


def test_install_or_download_delegates_to_updates_tab_when_self_update_possible():
    # Bewusst KEIN zweiter Ablaufpfad im Banner: kann die App sich selbst
    # aktualisieren, schickt der Klick nur zum Updates-Tab, statt Download/
    # Prüfung/Installation hier zu duplizieren.
    opened_tab = []
    opened_download = []
    b = UpdateBanner(root=object(), settings=_FakeSettings(),
                     get_anchor=lambda: object(),
                     on_open_updates_tab=lambda: opened_tab.append(True))
    b._can_self_update = True
    b._open_download = lambda release: opened_download.append(release)
    rel = _release()
    b._install_or_download(rel)
    assert opened_tab == [True]
    assert opened_download == []


def test_install_or_download_falls_back_to_browser_download():
    # Ohne Selbst-Update-Fähigkeit (macOS, falsche Architektur, Repo-Modus)
    # bleibt es beim bisherigen Browser-Download.
    opened_tab = []
    opened_download = []
    b = UpdateBanner(root=object(), settings=_FakeSettings(),
                     get_anchor=lambda: object(),
                     on_open_updates_tab=lambda: opened_tab.append(True))
    b._can_self_update = False
    b._open_download = lambda release: opened_download.append(release)
    rel = _release()
    b._install_or_download(rel)
    assert opened_download == [rel]
    assert opened_tab == []


def test_show_button_label_reflects_self_update_capability(monkeypatch):
    # Knopftext analog Task 7 (tab_updates.py): "Update installieren" nur,
    # wenn die App das Update auch selbst laden kann.
    monkeypatch.setattr(ub.tk, "Frame", lambda *a, **k: MagicMock())
    monkeypatch.setattr(ub.tk, "Label", lambda *a, **k: MagicMock())
    captured = []

    def _fake_label_button(parent, text, *a, **k):
        captured.append(text)
        return MagicMock()

    monkeypatch.setattr(ub, "label_button", _fake_label_button)
    monkeypatch.setattr(ub, "attach_tooltip", lambda *a, **k: None)
    b = UpdateBanner(root=object(), settings=_FakeSettings(),
                     get_anchor=lambda: object())
    b._can_self_update = True
    b._show(_release(), ready_to_install=False)
    assert ub._LABEL_INSTALL in captured
    assert ub._LABEL_DOWNLOAD not in captured


# --- show_ready_to_install (Task 9, Nachtrag: Automatik-Pfad) -------------


def _patch_widgets(monkeypatch, captured_labels=None, captured_buttons=None):
    """Gemeinsames Tk-Mocking fuer die show_ready_to_install-Tests."""
    monkeypatch.setattr(ub.tk, "Frame", lambda *a, **k: MagicMock())

    def _fake_label(parent, text, **k):
        if captured_labels is not None:
            captured_labels.append(text)
        return MagicMock()

    monkeypatch.setattr(ub.tk, "Label", _fake_label)

    def _fake_label_button(parent, text, *a, **k):
        if captured_buttons is not None:
            captured_buttons.append(text)
        return MagicMock()

    monkeypatch.setattr(ub, "label_button", _fake_label_button)
    monkeypatch.setattr(ub, "attach_tooltip", lambda *a, **k: None)


def test_show_ready_to_install_ignores_dismissed_version(monkeypatch):
    # Ein Update, das gleich automatisch installiert wird, ist wichtiger als
    # eine zuvor weggeklickte Verfuegbarkeits-Meldung (Design-Regel 3).
    labels = []
    _patch_widgets(monkeypatch, captured_labels=labels)
    rel = _release(version="1.2.0")
    b = UpdateBanner(root=object(), settings=_FakeSettings(dismissed_version="1.2.0"),
                     get_anchor=lambda: object())
    b.show_ready_to_install(rel)
    assert b._banner is not None
    assert any("Update bereit" in text for text in labels)


def test_show_ready_to_install_has_no_install_or_download_button(monkeypatch):
    buttons = []
    _patch_widgets(monkeypatch, captured_buttons=buttons)
    b = UpdateBanner(root=object(), settings=_FakeSettings(), get_anchor=lambda: object())
    b._can_self_update = True
    b.show_ready_to_install(_release())
    # Nur der Dismiss-Button ("✕") — es gibt nichts mehr zu klicken, das
    # Update laedt/installiert bereits automatisch.
    assert buttons == ["✕"]


def test_show_ready_to_install_replaces_an_already_shown_available_banner(monkeypatch):
    _patch_widgets(monkeypatch)
    b = UpdateBanner(root=object(), settings=_FakeSettings(), get_anchor=lambda: object())
    rel = _release()
    b.show_if_newer(rel)
    first_banner = b._banner
    assert b._ready_to_install is False

    b.show_ready_to_install(rel)

    assert b._ready_to_install is True
    assert b._banner is not first_banner


def test_show_ready_to_install_is_idempotent_once_shown(monkeypatch):
    # Ein zweiter Aufruf (z.B. vom naechsten taeglichen Check, solange noch
    # nicht beendet wurde) darf den Banner nicht unnoetig neu aufbauen.
    _patch_widgets(monkeypatch)
    b = UpdateBanner(root=object(), settings=_FakeSettings(), get_anchor=lambda: object())
    rel = _release()
    b.show_ready_to_install(rel)
    first_banner = b._banner

    b.show_ready_to_install(rel)

    assert b._banner is first_banner
