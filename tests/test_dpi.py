"""Systemskalierung (#157 Windows, Xveyn#167 Linux): Awareness bzw.
`Xft.dpi` und Systemfaktor.

Die Win32-Aufrufe selbst sind nicht Teil dieser Tests — sie kommen als
Funktionen herein. Geprüft wird die Entscheidung darum herum, vor allem die
beiden Zusagen, an denen der Umbau hängt: außerhalb von Windows passiert
**nichts** (macOS ist nicht testbar, der Weg muss dort ein No-op sein), und
ohne gesetzte Awareness bleibt der Faktor 1,0 — sonst streckte Windows das
Fenster und die App skalierte obendrauf.
"""

import os

import pytest

from src import dpi


def _fail():
    raise AssertionError("darf außerhalb von Windows nicht aufgerufen werden")


@pytest.mark.parametrize("value,expected", [
    (96, 1.0),
    (120, 1.25),
    (144, 1.5),
    (168, 1.75),
    (192, 2.0),
])
def test_scale_from_dpi(value, expected):
    assert dpi.scale_from_dpi(value) == expected


@pytest.mark.parametrize("value", [None, 0, -96])
def test_scale_from_dpi_without_usable_value_is_neutral(value):
    assert dpi.scale_from_dpi(value) == 1.0


def test_init_system_scale_is_a_noop_on_macos():
    assert dpi.init_system_scale("Darwin", set_aware=_fail, get_dpi=_fail,
                                 get_xft_dpi=_fail) == 1.0


def test_init_system_scale_never_touches_win32_on_linux():
    assert dpi.init_system_scale("Linux", set_aware=_fail, get_dpi=_fail,
                                 get_xft_dpi=lambda: None, tk_version=8.6) == 1.0


def test_init_system_scale_uses_system_dpi_once_aware():
    calls = []
    factor = dpi.init_system_scale(
        "Windows", set_aware=lambda: calls.append("aware") or True,
        get_dpi=lambda: 144)
    assert factor == 1.5
    assert calls == ["aware"]


def test_init_system_scale_stays_neutral_when_awareness_fails():
    """Ohne Awareness streckt Windows das Fenster selbst — ein zusätzlicher
    Faktor skalierte doppelt."""
    factor = dpi.init_system_scale(
        "Windows", set_aware=lambda: False, get_dpi=lambda: 144)
    assert factor == 1.0


def test_init_system_scale_remembers_the_factor(monkeypatch):
    monkeypatch.setattr(dpi, "_system_scale", 1.0)
    dpi.init_system_scale("Windows", set_aware=lambda: True, get_dpi=lambda: 120)
    assert dpi.system_scale() == 1.25


class _FakeRoot:
    def __init__(self):
        self.calls = []

        class _Tk:
            def call(_self, *args):
                self.calls.append(args)

        self.tk = _Tk()


def test_pin_tk_scaling_sets_the_96_dpi_value_on_windows():
    """Tk leitet `tk scaling` in einem DPI-aware Prozess aus der echten
    Auflösung ab und vergrößerte Punkt-Schriften damit selbst — zusätzlich zu
    `init_fonts`. Festgenagelt auf 96 dpi bleibt `init_fonts` der eine Hebel."""
    root = _FakeRoot()
    dpi.pin_tk_scaling(root, "Windows")
    assert root.calls == [("tk", "scaling", 96 / 72)]


def test_pin_tk_scaling_leaves_macos_alone(monkeypatch):
    """Auf macOS wirkt `tk scaling` auf Pixel- statt Punkt-Schriften — ein
    Festnageln veränderte dort die Schriftgrößen."""
    monkeypatch.setattr(dpi, "_xft_found", True)
    root = _FakeRoot()
    dpi.pin_tk_scaling(root, "Darwin")
    assert root.calls == []


def test_scale_hint_is_silent_at_100_percent():
    assert dpi.scale_hint(1.0) is None


def test_scale_hint_names_the_percentage():
    hint = dpi.scale_hint(1.5)
    assert hint is not None
    assert "150 %" in hint


def test_scale_hint_is_platform_neutral():
    assert "Windows" not in dpi.scale_hint(1.5)


# --- Linux: Xft.dpi (Xveyn#167) ---------------------------------------------

@pytest.mark.parametrize("text,expected", [
    ("Xft.dpi:\t144\n", 144.0),
    ("Xft.antialias:\t1\nXft.dpi:\t96\nXft.hinting:\t1\n", 96.0),
    ("Xft.dpi: 120.5", 120.5),
    ("Xft.dpi:\t144\n*.dpi:\t96\n", 144.0),
])
def test_xft_dpi_from_resources(text, expected):
    assert dpi.xft_dpi_from_resources(text) == expected


@pytest.mark.parametrize("text", [
    None, "", "Xft.antialias:\t1\n", "Xft.dpi:\tabc\n", "Xft.dpi:\t0\n",
    "Xft.dpi:\t-96\n", "Xft.dpiX:\t144\n", "MyXft.dpi:\t144\n",
])
def test_xft_dpi_from_resources_without_usable_value(text):
    assert dpi.xft_dpi_from_resources(text) is None


def _linux(monkeypatch, xft, tk_version=8.6):
    monkeypatch.setattr(dpi, "_system_scale", 1.0)
    monkeypatch.setattr(dpi, "_xft_found", False)
    return dpi.init_system_scale("Linux", get_xft_dpi=lambda: xft,
                                 tk_version=tk_version)


@pytest.mark.parametrize("xft,expected", [(96, 1.0), (144, 1.5), (192, 2.0)])
def test_linux_factor_follows_xft_dpi(monkeypatch, xft, expected):
    assert _linux(monkeypatch, xft) == expected
    assert dpi.system_scale() == expected


def test_linux_without_xft_dpi_stays_neutral(monkeypatch):
    """Kein Display, keine libX11, kein Eintrag: die App startet wie bisher."""
    assert _linux(monkeypatch, None) == 1.0


def test_linux_never_shrinks_below_96_dpi(monkeypatch):
    """Ein `Xft.dpi` unter 96 (etwa 90) machte die App kleiner als bisher."""
    assert _linux(monkeypatch, 90) == 1.0


def test_linux_leaves_scaling_to_tk_9(monkeypatch):
    """Tk 9 wertet `Xft.dpi` selbst aus — ein Faktor obendrauf skalierte doppelt."""
    calls = []
    monkeypatch.setattr(dpi, "_system_scale", 1.0)
    monkeypatch.setattr(dpi, "_xft_found", False)
    factor = dpi.init_system_scale(
        "Linux", get_xft_dpi=lambda: calls.append("xft") or 144, tk_version=9.0)
    assert factor == 1.0
    assert calls == []
    root = _FakeRoot()
    dpi.pin_tk_scaling(root, "Linux")
    assert root.calls == []


def test_linux_survives_a_failing_lookup(monkeypatch):
    def boom():
        raise OSError("kein X")
    monkeypatch.setattr(dpi, "_xft_found", False)
    assert dpi.init_system_scale("Linux", get_xft_dpi=boom, tk_version=8.6) == 1.0


def test_pin_tk_scaling_on_linux_once_xft_dpi_was_found(monkeypatch):
    """Mit `Xft.dpi` ist die Desktop-Angabe maßgeblich; aus den Bildschirmmaßen
    des X-Servers abgeleitet, vergrößerte `tk scaling` die Punkt-Schriften
    sonst ein zweites Mal."""
    _linux(monkeypatch, 144)
    root = _FakeRoot()
    dpi.pin_tk_scaling(root, "Linux")
    assert root.calls == [("tk", "scaling", 96 / 72)]


def test_pin_tk_scaling_on_linux_also_at_96_dpi(monkeypatch):
    """Auch ein gefundenes 96 ist eine Aussage: die Desktop-Skalierung liegt
    beim Compositor, Tk soll keine eigene aus den Bildschirmmaßen ableiten."""
    _linux(monkeypatch, 96)
    root = _FakeRoot()
    dpi.pin_tk_scaling(root, "Linux")
    assert root.calls == [("tk", "scaling", 96 / 72)]


def test_pin_tk_scaling_leaves_linux_alone_without_xft_dpi(monkeypatch):
    """Ohne `Xft.dpi` bleibt Linux exakt wie vor Xveyn#167."""
    _linux(monkeypatch, None)
    root = _FakeRoot()
    dpi.pin_tk_scaling(root, "Linux")
    assert root.calls == []


# --- Einmalige Umrechnung von ui_scale (Xveyn#167) --------------------------
# Wer die winzige App bisher mit ui_scale ausgeglichen hat, sähe sie mit dem
# Systemfaktor obendrauf doppelt so groß — auf 1080p mit abgeschnittener
# Fußzeile. Einmal umgerechnet, liegt sie wieder, wo sie war.

@pytest.mark.parametrize("value,factor,expected", [
    (1.5, 1.5, 1.0),
    (2.0, 2.0, 1.0),
    (2.0, 1.5, 1.25),   # 1,33 → nächster Rasterwert
    (1.25, 1.5, 0.75),  # 0,83 → 0,75
    (1.0, 1.0, 1.0),
])
def test_migrated_ui_scale(value, factor, expected):
    assert dpi.migrated_ui_scale(value, factor) == expected


@pytest.mark.parametrize("value", [1.0, 0.75, "kaputt"])
def test_migrated_ui_scale_keeps_values_up_to_100_percent(value):
    """Nur ein Wert über 100 % war ein Ausgleich für die winzige App. Wer nie
    etwas eingestellt hat, bekommt ab jetzt die Systemskalierung; wer
    verkleinert hat, wollte kleiner als Tk 8.6 zeichnete."""
    assert dpi.migrated_ui_scale(value, 1.5) == (1.0 if value == "kaputt" else value)


def _settings(tmp_path, **values):
    from src.settings import Settings
    s = Settings(str(tmp_path / "settings.json"))
    if values:
        s.set_many(values)
    return s


def test_migrate_ui_scale_divides_once(tmp_path, monkeypatch):
    _linux(monkeypatch, 144)
    settings = _settings(tmp_path, ui_scale=1.5)
    dpi.migrate_ui_scale(settings, "Linux")
    assert settings.get("ui_scale") == 1.0
    assert settings.get(dpi.MIGRATED_KEY) is True
    # Ein danach bewusst gesetzter Wert wird nie wieder geteilt.
    settings.set("ui_scale", 1.5)
    dpi.migrate_ui_scale(settings, "Linux")
    assert settings.get("ui_scale") == 1.5


def test_migrate_ui_scale_marks_done_at_96_dpi(tmp_path, monkeypatch):
    """Auch ohne Umrechnung ist die Migration erledigt — sonst teilte ein
    späterer Wechsel in eine skalierte X11-Sitzung einen längst
    selbst gewählten Wert."""
    _linux(monkeypatch, 96)
    settings = _settings(tmp_path, ui_scale=1.25)
    dpi.migrate_ui_scale(settings, "Linux")
    assert settings.get("ui_scale") == 1.25
    assert settings.get(dpi.MIGRATED_KEY) is True


def test_migrate_ui_scale_waits_for_xft_dpi(tmp_path, monkeypatch):
    """Ohne gefundenes Xft.dpi hat sich nichts geändert — nichts umrechnen,
    nichts als erledigt markieren."""
    _linux(monkeypatch, None)
    settings = _settings(tmp_path, ui_scale=1.5)
    dpi.migrate_ui_scale(settings, "Linux")
    assert settings.get("ui_scale") == 1.5
    assert not settings.get(dpi.MIGRATED_KEY)


@pytest.mark.parametrize("system", ["Windows", "Darwin"])
def test_migrate_ui_scale_only_on_linux(tmp_path, monkeypatch, system):
    """Unter Windows hat das System dasselbe Produkt bisher gestreckt, dort
    bleibt ui_scale unverändert richtig (#157)."""
    monkeypatch.setattr(dpi, "_xft_found", True)
    monkeypatch.setattr(dpi, "_system_scale", 1.5)
    settings = _settings(tmp_path, ui_scale=1.5)
    dpi.migrate_ui_scale(settings, system)
    assert settings.get("ui_scale") == 1.5
    assert not settings.get(dpi.MIGRATED_KEY)


def test_linux_without_known_tk_version_stays_neutral(monkeypatch):
    """Ohne Tk-Version ist offen, ob Tk selbst skaliert (Tk 9) — lieber gar
    nicht als womöglich doppelt."""
    monkeypatch.setattr(dpi, "_xft_found", False)
    assert dpi.init_system_scale("Linux", get_xft_dpi=lambda: 144) == 1.0
    assert dpi._xft_found is False


# --- Tks Xft-Schriftbackend rechnet selbst mit Xft.dpi (Xveyn#199) -----------

def test_neutralize_xft_dpi_overrides_it_for_this_process(tmp_path, monkeypatch):
    """Tks Xft-Backend skaliert Schriften selbst mit `Xft.dpi` — auch Pixel-
    größen, `tk scaling` ändert daran nichts. Zusätzlich zu `init_fonts`
    wäre die Schrift doppelt skaliert (bei 240 dpi: 2,5 × 2,5). Die
    Prozess-Ressourcen (`XENVIRONMENT`) legen sich über die des Servers."""
    _linux(monkeypatch, 240)
    monkeypatch.delenv("XENVIRONMENT", raising=False)
    path = dpi.neutralize_xft_dpi("Linux", directory=str(tmp_path))
    assert path is not None
    assert os.environ["XENVIRONMENT"] == path
    assert "Xft.dpi: 96" in open(path, encoding="utf-8").read().splitlines()


def test_neutralize_xft_dpi_keeps_an_existing_xenvironment_file(tmp_path, monkeypatch):
    """Eine eigene `XENVIRONMENT`-Datei des Nutzers bleibt erhalten; unsere
    Zeile steht dahinter und gewinnt nur für `Xft.dpi`."""
    _linux(monkeypatch, 240)
    mine = tmp_path / "mine"
    mine.write_text("Xterm*foo: bar\nXft.dpi: 200\n", encoding="utf-8")
    monkeypatch.setenv("XENVIRONMENT", str(mine))
    path = dpi.neutralize_xft_dpi("Linux", directory=str(tmp_path))
    lines = open(path, encoding="utf-8").read().splitlines()
    assert lines[0] == "Xterm*foo: bar"
    assert lines[-1] == "Xft.dpi: 96"


def test_neutralize_xft_dpi_only_with_found_xft_dpi(tmp_path, monkeypatch):
    """Ohne `Xft.dpi` bleibt Linux exakt wie vorher."""
    _linux(monkeypatch, None)
    monkeypatch.delenv("XENVIRONMENT", raising=False)
    assert dpi.neutralize_xft_dpi("Linux", directory=str(tmp_path)) is None
    assert "XENVIRONMENT" not in os.environ


@pytest.mark.parametrize("system", ["Windows", "Darwin"])
def test_neutralize_xft_dpi_only_on_linux(tmp_path, monkeypatch, system):
    _linux(monkeypatch, 240)
    monkeypatch.delenv("XENVIRONMENT", raising=False)
    assert dpi.neutralize_xft_dpi(system, directory=str(tmp_path)) is None
    assert "XENVIRONMENT" not in os.environ


def test_neutralize_xft_dpi_survives_an_unwritable_directory(tmp_path, monkeypatch):
    """Best-Effort: scheitert das Schreiben, startet die App wie bisher."""
    _linux(monkeypatch, 240)
    monkeypatch.delenv("XENVIRONMENT", raising=False)
    missing = str(tmp_path / "gibt-es-nicht")
    assert dpi.neutralize_xft_dpi("Linux", directory=missing) is None
    assert "XENVIRONMENT" not in os.environ
