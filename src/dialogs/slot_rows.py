"""Editierbare Slot-Zeilenliste des Tages-Dialogs (R5, #51).

Ist-Zeiten und Reservierungen führten im Tages-Dialog dieselbe Zeilenliste
zweimal von Hand: Start–Ende (bei Ist-Zeiten zusätzlich Pause), Kategorie-Combo
mit Override-Marker, ein × nur an neuen Zeilen, Kollabieren des leeren Frames
beim Entfernen der letzten Zeile. Der einzige echte Unterschied ist die
Pause-Spalte — plus, bei Reservierungen, ein Änderungs-Hook für den
Erinnerungs-Block.

**Teil des dokumentierten Klick-Modells (`CLAUDE.md`), nicht aufweichen:** das
× erscheint **nur** an neu hinzugefügten, noch nicht gespeicherten Zeilen
(`removable=True`). Bereits gespeicherte Slots lassen sich hier editieren, aber
nicht löschen — Löschen läuft ausschließlich über den Rechtsklick im Kalender
(auf macOS über das ✕ in der Tageszelle). `removable` steuert außerdem, ob eine
Kategorie-Auswahl die hinterlegten Standardzeiten in die Zeile zieht: bei
gespeicherten Slots sind die Zeiten bewusst gesetzt und bleiben unangetastet.

Die Anzeige-Helfer (`category_*`, `slot_category_display`) liegen mit hier,
weil sie ausschließlich beschreiben, wie eine Slot-Zeile ihre Kategorie zeigt.
Sie sind Tk-frei und in `tests/test_entry_dialog.py` getestet.
"""

import tkinter as tk

from src.category_defaults import resolve_slot_defaults
from src.theme import (
    BG, FONT, PAUSE_VALUES, TEXT_MUTED, TIME_VALUES, dark_combo, secondary_button,
)

# Kategorie am Slot: "" = keine Kategorie. Das Dropdown ist readonly (Anlegen/
# Bearbeiten von Kategorien läuft über die Einstellungen, nicht per Freitext),
# darum wird "" als eigener Eintrag "(ohne Kategorie)" gezeigt und beim Speichern
# wieder auf "" abgebildet. Label konsistent mit report.py/period_picker/share.
NO_CATEGORY_LABEL = "(ohne Kategorie)"

# Angehängt ans Kategorie-Label, wenn die Slot-Zeiten manuell von den für
# diese Kategorie hinterlegten Standardzeiten abweichen (z.B. "Office*") —
# reine Anzeige, s. slot_category_display/category_from_display.
OVERRIDE_MARKER = "*"


def category_choices(categories):
    """Werte fürs readonly-Kategorie-Dropdown: '(ohne Kategorie)' zuerst, dann
    die in den Einstellungen gepflegten Kategorien."""
    return [NO_CATEGORY_LABEL, *categories]


def category_to_display(value):
    """Gespeicherter Kategoriewert ('' = keine) → Dropdown-Anzeige."""
    return value if value else NO_CATEGORY_LABEL


def category_from_display(display):
    """Dropdown-Anzeige → gespeicherter Kategoriewert: '(ohne Kategorie)' → '',
    ein angehängtes Override-Sternchen ('Office*' → 'Office') wird mit
    gestrippt — es ist reine Anzeige (s. slot_category_display) und darf nie
    im persistierten Kategoriewert landen."""
    if display == NO_CATEGORY_LABEL:
        return ""
    if display.endswith(OVERRIDE_MARKER):
        return display[:-len(OVERRIDE_MARKER)]
    return display


def slot_category_display(kategorie, start, end, pause, category_times, weekday_key,
                          default_start, default_end, default_pause):
    """Anzeige-Label fürs Kategorie-Dropdown eines Slots: Kategorie-Name, mit
    angehängtem `OVERRIDE_MARKER`, wenn Start/Ende (und bei Ist-Zeit-Slots
    auch Pause) manuell von den für diese Kategorie hinterlegten Standard-
    zeiten abweichen. `pause=None` für Reservierungs-Slots (keine Pause-
    Komponente dort) — dann zählt nur Start/Ende für den Abgleich. Reine
    Anzeige: der persistierte Kategoriewert bleibt der Klarname, ohne
    Sternchen (s. category_from_display). Tk-frei, daher ohne UI testbar."""
    if not kategorie:
        return NO_CATEGORY_LABEL
    t_start, t_end, t_pause = resolve_slot_defaults(
        category_times, kategorie, weekday_key,
        default_start, default_end, default_pause,
    )
    overridden = start != t_start or end != t_end
    if pause is not None:
        overridden = overridden or str(pause) != str(t_pause)
    return kategorie + OVERRIDE_MARKER if overridden else kategorie


class SlotRowList:
    """Besitzt den Zeilen-Frame und die Liste der Zeilen-Records eines Blocks.

    `rows` ist die echte Liste (kein Snapshot) — der Dialog liest sie direkt
    für Vorschau, Erinnerungs-Block und Speichern.

    Hooks:
      * `on_rows_changed()` — nach jedem Hinzufügen/Entfernen einer Zeile.
      * `on_value_changed()` — optional, zusätzlich bei jeder Änderung von
        Start/Ende und bei jeder Kategorie-Auswahl. Der Reservierungs-Block
        hängt daran seinen Erinnerungs-Teil; der Ist-Zeit-Block braucht es
        nicht und übergibt None.
    """

    def __init__(self, frame, *, with_pause, categories, category_times,
                 weekday_key, default_start, default_end, default_pause,
                 on_rows_changed, on_value_changed=None):
        self.rows = []
        self._frame = frame
        self._with_pause = with_pause
        self._categories = categories
        self._category_times = category_times
        self._weekday_key = weekday_key
        self._default_start = default_start
        self._default_end = default_end
        self._default_pause = default_pause
        self._on_rows_changed = on_rows_changed
        self._on_value_changed = on_value_changed

    def add(self, start, end, kategorie, *, pause=None, removable=True,
            parent=None, extra=None):
        """Hängt eine Zeile an und liefert ihren Record.

        `parent` überschreibt den Ziel-Frame — gebraucht für die Breiten-Probe
        des Dialogs, die eine Zeile in einem nie gepackten Holder misst.
        `extra` ergänzt den Record um blockspezifische Felder (Reservierungen
        führen dort `send_reminder_minutes` mit).
        """
        row = tk.Frame(parent if parent is not None else self._frame, bg=BG)
        row.pack(fill="x", pady=2)

        sv = tk.StringVar(value=start)
        ev = tk.StringVar(value=end)
        pv = tk.StringVar(value=str(pause)) if self._with_pause else None
        kv = tk.StringVar(value=category_to_display(kategorie))

        # Basis = die Werte, mit denen die Zeile angelegt wurde. Wählt man für
        # eine NEUE Zeile eine Kategorie, überschreibt das ein Feld NUR, solange
        # es noch der Basis entspricht (= nicht manuell geändert), und zieht die
        # Basis nach.
        base = {"start": start, "end": end}
        if pv is not None:
            base["pause"] = str(pause)

        dark_combo(row, sv, TIME_VALUES, width=6).pack(side=tk.LEFT, padx=2)
        tk.Label(row, text="–", font=FONT, bg=BG, fg=TEXT_MUTED).pack(side=tk.LEFT)
        dark_combo(row, ev, TIME_VALUES, width=6).pack(side=tk.LEFT, padx=2)
        if pv is not None:
            dark_combo(row, pv, PAUSE_VALUES, width=4).pack(side=tk.LEFT, padx=2)
        cat_combo = dark_combo(row, kv, category_choices(self._categories), width=18)
        cat_combo.pack(side=tk.LEFT, padx=2)

        record = {"frame": row, "start": sv, "end": ev, "kategorie": kv}
        if pv is not None:
            record["pause"] = pv
        if extra:
            record.update(extra)

        # Manuelles Anpassen der Zeit ändert NIE die zugeordnete Kategorie —
        # nur das Anzeige-Label bekommt dann ein Override-Sternchen ("Office*",
        # s. slot_category_display); rein optisch, kv bleibt die einzige
        # Quelle für den beim Speichern persistierten Kategoriewert.
        def refresh_cat_display(*_a):
            kategorie_value = category_from_display(kv.get())
            display = slot_category_display(
                kategorie_value, sv.get(), ev.get(),
                pv.get() if pv is not None else None,
                self._category_times, self._weekday_key,
                self._default_start, self._default_end, self._default_pause,
            )
            if kv.get() != display:
                kv.set(display)

        sv.trace_add("write", refresh_cat_display)
        ev.trace_add("write", refresh_cat_display)
        if pv is not None:
            pv.trace_add("write", refresh_cat_display)
        if self._on_value_changed is not None:
            sv.trace_add("write", self._on_value_changed)
            ev.trace_add("write", self._on_value_changed)

        def on_cat_change(*_a):
            # Reservierungen haben keine Pause → dort nur Start/Ende anwenden.
            t_start, t_end, t_pause = resolve_slot_defaults(
                self._category_times, category_from_display(kv.get()),
                self._weekday_key,
                self._default_start, self._default_end, self._default_pause,
            )
            if sv.get() == base["start"]:
                sv.set(t_start)
                base["start"] = t_start
            if ev.get() == base["end"]:
                ev.set(t_end)
                base["end"] = t_end
            if pv is not None:
                t_pause = str(t_pause)
                if pv.get() == base["pause"]:
                    pv.set(t_pause)
                    base["pause"] = t_pause

        # Marker-Anzeige bei jeder Kategorie-Wahl neu berechnen (alle Zeilen);
        # Standardzeiten der Kategorie ziehen nur bei NEUEN (entfernbaren)
        # Zeilen und nur bei echter Auswahl aus der Vorschlagsliste
        # (<<ComboboxSelected>>) — nicht pro Tastendruck (Freitext würde sonst
        # auf globale Defaults zurücksetzen) und nicht für bereits gespeicherte
        # Slots (deren Zeiten sind bewusst gesetzt und bleiben unangetastet).
        cat_combo.bind("<<ComboboxSelected>>", refresh_cat_display, add="+")
        if removable:
            cat_combo.bind("<<ComboboxSelected>>", on_cat_change, add="+")
        refresh_cat_display()  # initialer Marker-Zustand beim Dialog-Öffnen
        if self._on_value_changed is not None:
            cat_combo.bind("<<ComboboxSelected>>", self._on_value_changed, add="+")

        def remove():
            row.destroy()
            self.rows.remove(record)
            # Ein leeres Tk-Frame behält sonst die Höhe seiner letzten Zeile als
            # Lücke — beim Entfernen der letzten Zeile explizit kollabieren,
            # damit der Dialog passend schrumpft (pack_propagate baut die Höhe
            # beim nächsten "+ Slot" wieder auf).
            if not self.rows:
                self._frame.configure(height=1)
            self._on_rows_changed()

        # Bereits gespeicherte Slots tragen kein ×: Löschen läuft ausschließlich
        # über den Rechtsklick im Kalender (Design-Entscheidung — der Dialog
        # speichert nur). Das × erscheint nur an neu hinzugefügten, noch nicht
        # persistierten Zeilen.
        if removable:
            secondary_button(row, "×", remove, padx=8, pady=0).pack(
                side=tk.LEFT, padx=2)

        self.rows.append(record)
        self._on_rows_changed()
        return record
