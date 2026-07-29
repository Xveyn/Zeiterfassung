"""_setup_window_icon darf einen Start nie verhindern (Review-Finding 1,
2026-07-29). Getestet ohne echtes Tk-Display über einen Stub mit den
relevanten Attributen — analog test_ui_navigate.py."""

import tkinter as tk

from src.ui import App


class _RootStub:
    """Minimaler Stand-in für root: zeichnet Aufrufe auf, wirft nichts."""

    def __init__(self):
        self.iconbitmap_calls = []
        self.iconphoto_calls = []

    def iconbitmap(self, default=None):
        self.iconbitmap_calls.append(default)

    def iconphoto(self, default, icon):
        self.iconphoto_calls.append((default, icon))


class _Stub:
    def __init__(self, root):
        self.root = root


def test_broken_png_does_not_raise(tmp_path, monkeypatch):
    """Ein PhotoImage, das TclError wirft (z.B. defektes/fehlendes PNG im
    gebündelten Ressourcen-Verzeichnis), darf App.__init__ nicht crashen
    lassen — genau das würde sonst auf macOS/Linux den kompletten Start
    verhindern, seit dieser Pfad über get_resource_path() erstmals
    erreichbar ist."""
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "margenheld-icon.png").write_bytes(b"not a real png")

    def _raise(*args, **kwargs):
        raise tk.TclError("couldn't recognize data in image file")

    monkeypatch.setattr("src.ui.tk.PhotoImage", _raise)

    stub = _Stub(_RootStub())
    App._setup_window_icon(stub, str(tmp_path))

    assert stub.root.iconphoto_calls == []
    assert not hasattr(stub, "_icon_ref")


def test_valid_png_sets_iconphoto(tmp_path, monkeypatch):
    """Gegenprobe: ein erfolgreich geladenes PNG setzt weiterhin das
    Fenster-Icon. Kein echtes Tk-Display nötig (Projektkonvention, siehe
    docs/known-limitations.md) — tk.PhotoImage wird durch ein Fake ersetzt,
    das statt zu rendern nur ein Sentinel-Objekt liefert."""
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "margenheld-icon.png").write_bytes(b"PNGDATA")

    sentinel = object()
    monkeypatch.setattr("src.ui.tk.PhotoImage", lambda file: sentinel)

    stub = _Stub(_RootStub())
    App._setup_window_icon(stub, str(tmp_path))

    assert len(stub.root.iconphoto_calls) == 1
    assert stub.root.iconphoto_calls[0] == (True, sentinel)
    assert stub._icon_ref is sentinel
