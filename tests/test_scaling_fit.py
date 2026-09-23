"""Passt die gewählte UI-Skalierung noch auf den Bildschirm? (`scaled_window_fits`)

Das Hauptfenster ist `resizable(False, False)` und wird von
`grid_renderer.repin_geometry` stumpf auf seine angeforderte Größe gepinnt —
ohne die Bildschirmgröße je anzusehen. Bei 200 % wird es rund 1160 px hoch;
auf einem 1080p-Schirm (Arbeitsfläche ~1040 px) ist die Fußzeile mit
„Arbeitszeiten senden“/„Export“/„Teilen“ damit abgeschnitten.

Verhindert wird das nicht — gewarnt wird. Die Entscheidung bleibt beim Nutzer,
und der Zustand ist umkehrbar: das Zahnrad sitzt im Header, die Einstellungen
bleiben also erreichbar.
"""

import pytest

from src.theme.geometry import FIT_TOLERANCE, scaled_window_fits


def test_unveraenderte_skalierung_passt():
    est, fits = scaled_window_fits(602, 1.0, 1.0, 1040)
    assert (est, fits) == (602, True)


def test_verkleinern_passt_immer():
    _, fits = scaled_window_fits(1159, 2.0, 1.0, 1040)
    assert fits


def test_verdoppeln_sprengt_1080p():
    """Gemessen: 602 px bei 100 %, 1159 px bei 200 %. Die Schätzung liegt mit
    1204 px etwas darüber — beide Male deutlich über der Arbeitsfläche."""
    est, fits = scaled_window_fits(602, 1.0, 2.0, 1040)
    assert est == 1204
    assert not fits


def test_toleranz_verhindert_fehlalarm_bei_175_auf_1080p():
    """Der Grund für FIT_TOLERANCE: die proportionale Schätzung liegt hier bei
    1054 px, real sind es 1018 px — die Arbeitsfläche von 1040 px reicht also.
    Ohne Toleranz warnte die App bei einer ganz gewöhnlichen Kombination."""
    est, fits = scaled_window_fits(602, 1.0, 1.75, 1040)
    assert est == 1054
    assert fits


def test_toleranz_ist_kein_freibrief():
    """Knapp über der Toleranz wird weiterhin gewarnt — sie federt die
    Rundungsabweichung ab, nicht einen echten Überlauf."""
    limit = round(1040 * FIT_TOLERANCE)
    _, fits = scaled_window_fits(limit + 10, 1.0, 1.0, 1040)
    assert not fits


def test_schaetzung_skaliert_proportional():
    est, _ = scaled_window_fits(800, 1.25, 1.5, 4000)
    assert est == 960


@pytest.mark.parametrize("height,scale,workarea", [
    (0, 1.0, 1040),      # Fenster noch nicht gemappt
    (602, 0, 1040),      # kaputter ui_scale aus settings.json
    (602, -1.0, 1040),
    (602, 1.0, 0),       # Arbeitsfläche nicht ermittelbar
])
def test_unbrauchbare_eingaben_warnen_nicht(height, scale, workarea):
    """Ohne belastbare Zahlen gibt es keine Aussage — und eine Warnung ins
    Blaue wäre schlimmer als keine."""
    est, fits = scaled_window_fits(height, scale, 2.0, workarea)
    assert (est, fits) == (0, True)
