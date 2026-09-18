# src/theme/form_logic.py
"""Tk-freie Entscheidungen der Formular-Bausteine (`theme/form.py`, #132).

Was hier liegt, braucht kein Fenster und ist deshalb getestet
(`tests/test_form_logic.py`): welche abhängigen Optionen aktiv sind, wohin ein
Mausrad-Schritt geht und wie hoch ein scrollbarer Tab-Körper werden darf.
`form.py` ruft nur noch hierher und setzt das Ergebnis in Tk um.

Unterste Schicht neben `palette`: reine stdlib, hängt an nichts.
"""

from collections.abc import Mapping
from typing import Literal

# Höhe eines scrollbaren Formular-Körpers bei 100 % Skalierung. 600 px
# entsprechen in etwa dem heutigen Tab-Körper des App-Tabs — der Dialog wird
# durch den Umbau also nie höher als vorher.
BODY_MAX_HEIGHT = 600
# Abstand, den der Körper zum Bildschirmrand lassen muss: Titelleiste,
# Reiterleiste, Knopfreihe und Taskleiste.
SCREEN_MARGIN = 160
# Untergrenze auf winzigen Bildschirmen — darunter wäre der Körper nicht
# mehr bedienbar, selbst mit Scrollleiste.
MIN_BODY_HEIGHT = 200

WheelRoute = Literal["widget", "form", "form_block"]

# Widgets, die das Mausrad selbst auswerten (eigene Klassen-Bindings).
_SELF_SCROLLING = frozenset({"Text", "Listbox"})
# Widgets, die beim Rad ihren WERT ändern — beim Scrollen des Formulars
# verstellte man sie sonst versehentlich. Spinbox/TSpinbox ändern ihren Wert
# beim Rad genau wie die Combobox, auch wenn `form.py` heute keine Spinbox
# baut — die Falle träfe den nächsten, der eine ergänzt.
_VALUE_ON_WHEEL = frozenset({"TCombobox", "TSpinbox", "Spinbox"})


def enabled_states(
    parents: Mapping[str, str | None], values: Mapping[str, bool],
) -> dict[str, bool]:
    """Welche Gruppen abhängiger Optionen aktiv sind.

    `parents` ordnet jeder Gruppe ihre übergeordnete Gruppe zu (None = oberste
    Ebene), `values` den Zustand ihres Schalters. Aktiv ist eine Gruppe genau
    dann, wenn ihr eigener Schalter UND alle Schalter darüber an sind — ein
    eingeschalteter Unterpunkt unter einem ausgeschalteten Hauptpunkt bleibt
    grau. Fehlt ein Schalterwert, gilt er als aus. Ein Zyklus ist ein
    Programmierfehler und wirft ValueError."""
    result: dict[str, bool] = {}

    def resolve(group: str, seen: frozenset[str]) -> bool:
        if group in result:
            return result[group]
        if group in seen:
            raise ValueError(f"Zyklus in den Abhängigkeiten bei {group!r}")
        parent = parents.get(group)
        active = bool(values.get(group, False))
        if parent is not None:
            active = resolve(parent, seen | {group}) and active
        result[group] = active
        return active

    for group in parents:
        resolve(group, frozenset())
    return {group: result[group] for group in parents}


def wheel_units(system: str, delta: int, num: int | None) -> int:
    """Scrollschritte (`yview_scroll`-Einheiten, positiv = nach unten) aus
    einem Mausrad-Event.

    X11 meldet das Rad als Taste 4 (hoch) / 5 (runter), Windows als `delta`
    in Vielfachen von 120, macOS als kleine Rohwerte. Touchpads unter Windows
    liefern Bruchteile von 120 — die zählen als ein Schritt statt als null,
    sonst stünde das Formular beim sanften Wischen still."""
    if num == 4:
        return -1
    if num == 5:
        return 1
    if delta == 0:
        return 0
    if system == "Darwin":
        return -delta
    steps = int(delta / 120)
    if steps == 0:
        steps = 1 if delta > 0 else -1
    return -steps


def wheel_route(widget_class: str) -> WheelRoute:
    """Wohin ein Mausrad-Schritt über einem Widget dieser Klasse geht:
    `"widget"` — das Widget scrollt selbst, das Formular bleibt stehen;
    `"form_block"` — das Formular scrollt, das Widget darf den Schritt NICHT
    sehen; `"form"` — das Formular scrollt."""
    if widget_class in _SELF_SCROLLING:
        return "widget"
    if widget_class in _VALUE_ON_WHEEL:
        return "form_block"
    return "form"


def is_descendant(path: str, ancestor: str) -> bool:
    """True, wenn der Tk-Pfad `path` das Widget `ancestor` selbst oder eines
    seiner Kinder bezeichnet. Verglichen wird komponentenweise — `.!canvas2`
    ist kein Kind von `.!canvas`, auch wenn der String so beginnt."""
    if ancestor == ".":
        return path.startswith(".")
    return path == ancestor or path.startswith(ancestor + ".")


def body_height(natural: int, scale: float, screen_height: int) -> int:
    """Sichtbare Höhe eines scrollbaren Formular-Körpers.

    Höchstens `BODY_MAX_HEIGHT` (mitskaliert) und höchstens so viel, wie der
    Bildschirm abzüglich `SCREEN_MARGIN` hergibt — aber nie weniger als
    `MIN_BODY_HEIGHT`. Kurze Formulare behalten ihre natürliche Höhe; die
    Untergrenze polstert sie nicht auf."""
    cap = round(BODY_MAX_HEIGHT * scale)
    room = screen_height - round(SCREEN_MARGIN * scale)
    limit = max(MIN_BODY_HEIGHT, min(cap, room))
    return min(natural, limit)
