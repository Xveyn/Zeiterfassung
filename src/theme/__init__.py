# src/theme/__init__.py
"""Dark-Theme der App — Palette, Fonts, Widget-Fabriken, Fenster-Chrome,
themed Messageboxen und Dialog-Geometrie.

Bis Issue #51 (R3) war das eine Datei mit 1075 Zeilen und fünf inhaltlich
zusammenhanglosen Blöcken. Der Schnitt ist eine reine Umsortierung: dieses
`__init__` re-exportiert die bisherige Oberfläche, alle 25 Aufrufstellen
(`from src.theme import ...`) bleiben unverändert.

Schichtung — zyklenfrei und in dieser Reihenfolge importierbar:

    palette      nur Konstanten, hängt an nichts
      └ fonts        benannte Tk-Fonts + Skalierung
          └ widgets      Widget-Fabriken, ttk-Styles
    geometry     Zentrierung + zwei Tk-freie Prädikate
    chrome       Win32-Fensterchrome, create_dialog
      └ messagebox   themed Drop-ins (nutzt chrome, widgets, geometry)

Wer etwas ergänzt, legt es in das passende Teilmodul und trägt es unten nach —
hier wird nichts definiert.

Re-exportiert werden die öffentlichen Namen plus **genau drei** private, die
echte externe Aufrufer haben: `_stray_click_suppressed` (ui.py),
`_should_show_delete_button` (grid_renderer.py) und `_click_keeps_focus`
(Test). Die übrigen `_`-Namen bleiben bewusst in ihrem Teilmodul — allen voran
`chrome._app_icon_ref`: ein hier gebundener Alias auf ein Modul-Global, das
`apply_app_icon` per `global` neu setzt, würde stillschweigend veralten.
"""

from src.theme.palette import (  # noqa: F401
    ACCENT,
    ACCENT_DISABLED,
    ACCENT_HOVER,
    BG,
    CELL_BG,
    CELL_BG_HOVER,
    ENTRY_BG,
    ENTRY_BG_HOVER,
    HOLIDAY_ACCENT,
    HOLIDAY_BG,
    HOLIDAY_BG_HOVER,
    PAUSE_VALUES,
    RESERVATION_ACCENT,
    STATUS_OK,
    TEXT,
    TEXT_MUTED,
    TIME_VALUES,
    TODAY_ACCENT,
    WEEKEND_BG,
    WEEKEND_BG_HOVER,
    WEEKEND_ENTRY_BG,
    WEEKEND_ENTRY_BG_HOVER,
    WEEKEND_FG,
)
from src.theme.fonts import (  # noqa: F401
    FONT,
    FONT_BOLD,
    FONT_FAMILY,
    FONT_FOOTER,
    FONT_HEADER,
    FONT_HEADER_SMALL,
    FONT_SMALL,
    FONT_TINY,
    init_fonts,
    scaled_size,
)
from src.theme.widgets import (  # noqa: F401
    _click_keeps_focus,
    apply_combobox_style,
    apply_notebook_style,
    attach_unfocus_on_click,
    dark_combo,
    dark_entry,
    dark_text,
    icon_button,
    label_button,
    primary_button,
    secondary_button,
    set_button_text,
    set_icon_button_enabled,
    set_primary_button_enabled,
    set_secondary_button_enabled,
    set_toggle_active,
    toggle_button,
)
from src.theme.geometry import (  # noqa: F401
    _should_show_delete_button,
    _stray_click_suppressed,
    STRAY_CLICK_GUARD_S,
    center_dialog_on_parent,
)
from src.theme.chrome import (  # noqa: F401
    apply_app_icon,
    apply_dark_titlebar,
    create_dialog,
    disable_min_max,
)
from src.theme.messagebox import (  # noqa: F401
    themed_ask_delete_choice,
    themed_askyesno,
    themed_showerror,
    themed_showinfo,
    themed_showwarning,
)

__all__ = [
    # palette
    "ACCENT", "ACCENT_DISABLED", "ACCENT_HOVER", "BG", "CELL_BG", "CELL_BG_HOVER",
    "ENTRY_BG", "ENTRY_BG_HOVER", "HOLIDAY_ACCENT", "HOLIDAY_BG", "HOLIDAY_BG_HOVER",
    "PAUSE_VALUES", "RESERVATION_ACCENT", "STATUS_OK", "TEXT", "TEXT_MUTED",
    "TIME_VALUES", "TODAY_ACCENT", "WEEKEND_BG", "WEEKEND_BG_HOVER",
    "WEEKEND_ENTRY_BG", "WEEKEND_ENTRY_BG_HOVER", "WEEKEND_FG",
    # fonts
    "FONT", "FONT_BOLD", "FONT_FAMILY", "FONT_FOOTER", "FONT_HEADER",
    "FONT_HEADER_SMALL", "FONT_SMALL", "FONT_TINY", "init_fonts", "scaled_size",
    # widgets
    "apply_combobox_style", "apply_notebook_style", "attach_unfocus_on_click",
    "dark_combo", "dark_entry", "dark_text", "icon_button", "label_button",
    "primary_button", "secondary_button", "set_button_text", "set_icon_button_enabled",
    "set_primary_button_enabled", "set_secondary_button_enabled", "set_toggle_active",
    "toggle_button", "_click_keeps_focus",
    # geometry
    "STRAY_CLICK_GUARD_S", "center_dialog_on_parent", "_should_show_delete_button",
    "_stray_click_suppressed",
    # chrome
    "apply_app_icon", "apply_dark_titlebar", "create_dialog", "disable_min_max",
    # messagebox
    "themed_ask_delete_choice", "themed_askyesno", "themed_showerror",
    "themed_showinfo", "themed_showwarning",
]
