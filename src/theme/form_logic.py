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
# Scroll-Schrittweite eines Formulars bei 100 % (`yscrollincrement`, px,
# mitskaliert). Ohne feste Schrittweite rechnet der Canvas in Zehnteln der
# sichtbaren Höhe — auf einem macOS-Trackpad, das viele kleine Deltas
# schickt, sprang die Seite dadurch.
WHEEL_STEP = 20
# Schritte je Raste eines klassischen Mausrads (Windows, X11): drei mal
# `WHEEL_STEP` fühlt sich an wie in anderen Anwendungen.
NOTCH_UNITS = 3

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


def scroll_units(system: str, delta: int, num: int | None) -> int:
    """`yview_scroll`-Einheiten (à `WHEEL_STEP`) aus einem Mausrad-Event.

    Eine Raste (Windows, X11) zählt `NOTCH_UNITS` Einheiten. macOS liefert
    Rohwerte, die schon fein genug sind — die bleiben, wie `wheel_units` sie
    liest."""
    units = wheel_units(system, delta, num)
    if system == "Darwin" and num is None:
        return units
    return units * NOTCH_UNITS


def scroll_target(item_top: int, item_height: int, first: float, last: float,
                  total: int) -> float | None:
    """Wohin gescrollt werden muss, damit ein Feld sichtbar ist.

    `item_top`/`item_height` in px relativ zum Formularkörper, `first`/`last`
    der sichtbare Bereich als Anteil (`canvas.yview()`), `total` die volle
    Körperhöhe. Liefert den neuen `yview_moveto`-Wert oder `None`, wenn das
    Feld schon ganz sichtbar ist. Liegt es darüber (oder ist es höher als der
    Sichtbereich), kommt seine Oberkante an den oberen Rand, sonst seine
    Unterkante an den unteren."""
    if total <= 0:
        return None
    view_top = first * total
    view_height = (last - first) * total
    item_bottom = item_top + item_height
    if item_top >= view_top and item_bottom <= view_top + view_height:
        return None
    if item_top < view_top or item_height >= view_height:
        return max(0.0, item_top / total)
    # Gerundet gegen Fließkomma-Reste wie 0.33000000000000007.
    return round(max(0.0, (item_bottom - view_height) / total), 6)


def wheel_route(widget_class: str, can_scroll: bool = True) -> WheelRoute:
    """Wohin ein Mausrad-Schritt über einem Widget dieser Klasse geht:
    `"widget"` — das Widget scrollt selbst, das Formular bleibt stehen;
    `"form_block"` — das Formular scrollt, das Widget darf den Schritt NICHT
    sehen; `"form"` — das Formular scrollt.

    `can_scroll=False` meldet ein Text/eine Listbox ohne Überlauf: das Rad
    ginge dort ins Leere, das Formular stünde still. Dann scrollt es."""
    if widget_class in _SELF_SCROLLING:
        return "widget" if can_scroll else "form"
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
