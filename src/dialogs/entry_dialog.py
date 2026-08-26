import datetime
import tkinter as tk
from typing import Callable

from src.category_defaults import resolve_slot_defaults
from src.holidays_de import get_holidays
from src.settings import WEEKDAY_KEYS, parse_reminder_minutes
from src.theme import (
    BG, CELL_BG, FONT, FONT_BOLD, FONT_SMALL, PAUSE_VALUES,
    STRAY_CLICK_GUARD_S, TEXT, TEXT_MUTED,
    TIME_VALUES, apply_combobox_style, attach_unfocus_on_click,
    center_dialog_on_parent, create_dialog, dark_combo,
    primary_button, secondary_button,
    set_primary_button_enabled, themed_askyesno, themed_showinfo,
)
from src.pause_requirement import check_day_pause
from src.time_utils import (
    format_date, format_hours_hm, format_iso_weekday_date, get_week_label,
    validate_slots,
)
from src.weekly_limit import check_week_limit

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


def suggest_ist_category(reservation_slots):
    """Kategorie-Vorschlag für die neu vorbelegte Ist-Zeit-Zeile aus einer
    bestehenden Reservierung (noch keine Ist-Zeit gespeichert). Nur bei GENAU
    EINEM Reservierungs-Slot — bei mehreren wäre unklar, welcher Slot die
    Kategorie der einen vorgeschlagenen Zeile bestimmen sollte (die
    Zeit-Vorbelegung nimmt ohnehin nur den ersten Slot, s. open_entry_dialog)."""
    if len(reservation_slots) != 1:
        return ""
    return reservation_slots[0].get("kategorie", "")


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


def plan_entry_save(ist_slots, res_slots, show_reservation):
    """Entscheidungslogik für den einen kombinierten Speichern-Button im
    Tages-Dialog: validiert Ist-Zeit- und (falls sichtbar) Reservierungs-
    Slots, bevor irgendetwas persistiert wird. Alles-oder-nichts — ist einer
    der beiden Blöcke ungültig, wird auch der andere, gültige Block nicht
    gespeichert (sonst müsste ein einzelner Klick teils leise scheitern,
    teils leise gelingen). Tk-frei, daher ohne UI testbar.

    Liefert `{"error": str|None, "save_ist": bool, "save_reservation": bool}`.
    Ein leerer Slot-Block (Block ungenutzt oder nicht sichtbar) wird einfach
    übersprungen, nicht als Fehler gewertet."""
    if ist_slots:
        ok, msg = validate_slots(ist_slots, with_pause=True)
        if not ok:
            return {
                "error": f"Arbeitszeit: {msg}" if show_reservation else msg,
                "save_ist": False,
                "save_reservation": False,
            }
    if show_reservation and res_slots:
        ok, msg = validate_slots(res_slots, with_pause=False)
        if not ok:
            return {
                "error": f"Reservierung: {msg}",
                "save_ist": False,
                "save_reservation": False,
            }
    return {
        "error": None,
        "save_ist": bool(ist_slots),
        "save_reservation": show_reservation and bool(res_slots),
    }


def reservation_block_visible(day, today, *, has_reservation=False):
    """Ob der Reservierungs-Block im Tages-Dialog erscheint.

    Regel: nur an heutigen/zukünftigen Tagen. An vergangenen Tagen wird KEIN
    Block gezeigt — bewusst auch dann nicht, wenn dort bereits eine Reservierung
    existiert (`has_reservation`): Per Linksklick lässt sich in der Vergangenheit
    keine (zusätzliche) Reservierung anlegen, der Dialog zeigt dort nur die
    Arbeitszeit. Eine alte Reservierung aufräumen läuft über den Rechtsklick im
    Kalender. Reservierungen sind per Definition zukünftige Soll-Zeiten.
    """
    return day >= today


def reminder_block_visible(settings, show_reservation):
    """Ob der Erinnerungs-Block im Tages-Dialog erscheint: nur wenn die
    Sende-Erinnerung überhaupt an ist, die Kopplung an Reservierungen aktiviert
    wurde und der Reservierungs-Block selbst sichtbar ist (der liefert die
    Slots, an denen die Erinnerung hängt)."""
    return bool(
        show_reservation
        and settings.get("send_reminder_enabled")
        and settings.get("send_reminder_reservations_enabled")
    )


def reminder_slot_labels(rows):
    """Anzeige-Labels der Reservierungs-Zeilen fürs Slot-Dropdown.

    `rows`: Liste von {start, end, kategorie}. Die führende Nummer hält die
    Labels eindeutig — zwei Zeilen dürfen dieselbe Zeit und Kategorie haben,
    und der Dialog liest die Auswahl über den Listen-Index zurück.
    """
    out = []
    for i, row in enumerate(rows):
        kategorie = (row.get("kategorie") or "").strip()
        label = f"{i + 1}. {row.get('start')}–{row.get('end')}"
        out.append(f"{label}  {kategorie}" if kategorie else label)
    return out


def apply_reminder_to_slots(res_slots, slot_index, minutes, enabled):
    """Setzt `send_reminder_minutes` am gewählten Slot und None an allen
    anderen — die Invariante „höchstens ein markierter Slot pro Tag".

    Mutiert `res_slots` in-place. enabled=False, ein Index außerhalb der Liste
    oder ungültige Minuten → alle Slots None.
    """
    valid = (
        enabled
        and isinstance(slot_index, int)
        and not isinstance(slot_index, bool)
        and 0 <= slot_index < len(res_slots)
        and isinstance(minutes, int)
        and not isinstance(minutes, bool)
        and 0 <= minutes <= 120
    )
    for i, slot in enumerate(res_slots):
        slot["send_reminder_minutes"] = minutes if valid and i == slot_index else None


def open_entry_dialog(parent, date_str, storage, settings, on_change,
                      reservation_store=None, trigger_reconcile=None):
    """Modaler Dialog zum Bearbeiten von Ist-Zeit und Reservierung eines Tages.

    Beide Blöcke führen eine Liste von Slot-Zeilen (Start/Ende/Pause/Kategorie
    bzw. Start/Ende/Kategorie) und teilen sich EINEN „Speichern"-Button unten
    im Dialog (statt je einen eigenen): der sammelt und validiert beide
    Blöcke (validate_slots: pro Slot + Überlappungsfreiheit) und schreibt sie
    alles-oder-nichts — ist ein Block ungültig, wird auch der andere, gültige
    Block nicht gespeichert (siehe `plan_entry_save`). Entfernt man alle
    Zeilen eines Blocks und speichert, wird der Block gelöscht — der Dialog
    hat keinen Lösch-Button (Löschen läuft im Kalender: Rechtsklick auf
    Win/Linux, ✕-Button in der Zelle auf macOS).

    on_change wird nach erfolgreichem Speichern/Löschen aufgerufen.
    reservation_store / trigger_reconcile sind optional; ist der Tag
    heute/zukünftig (oder existiert bereits eine Reservierung), erscheint der
    Reservierungs-Block. trigger_reconcile() stößt den Kalender-Abgleich an.
    """
    entry = storage.get(date_str)
    day = datetime.date.fromisoformat(date_str)
    weekday_key = WEEKDAY_KEYS[day.weekday()]

    # Feiertags-Warnung beim Anlegen einer Ist-Zeit (nicht beim Edit).
    if entry is None:
        state = settings.get("state")
        if state:
            feiertage = get_holidays(state, day.year)
            if day in feiertage:
                date_de = format_date(day)
                confirm = themed_askyesno(
                    parent, "Feiertag",
                    f"Der {date_de} ist {feiertage[day]} (Feiertag).\n\n"
                    "Trotzdem Eintrag anlegen?",
                )
                if not confirm:
                    return

    existing_reservation = (
        reservation_store.get(date_str) if reservation_store is not None else None
    )
    show_reservation = reservation_store is not None and reservation_block_visible(
        day, datetime.date.today(), has_reservation=existing_reservation is not None
    )

    categories = settings.get("categories") or []
    category_times = settings.get("category_times") or {}
    default_start = settings.get(f"default_start_{weekday_key}")
    default_end = settings.get(f"default_end_{weekday_key}")
    default_pause = settings.get("default_pause")

    dialog = create_dialog(parent, format_iso_weekday_date(date_str))
    apply_combobox_style(dialog)
    attach_unfocus_on_click(dialog)

    outer = tk.Frame(dialog, bg=BG)
    outer.pack(padx=12, pady=12)

    # ---------- Ist-Zeit ----------
    tk.Label(outer, text="Arbeitszeit", font=FONT_BOLD, bg=BG, fg=TEXT).pack(anchor="w")
    ist_rows_frame = tk.Frame(outer, bg=BG)
    ist_rows_frame.pack(fill="x")
    ist_rows = []  # Liste von {frame, start, end, pause, kategorie}
    res_rows = []  # Liste von {frame, start, end, kategorie}; bleibt leer ohne Reservierungs-Block

    # Late-bound: der Erinnerungs-Block wird erst nach den Reservierungs-Zeilen
    # gebaut, muss aber von deren Änderungen erfahren.
    notify_reminder_block: dict[str, Callable[[], None] | None] = {"fn": None}

    def _reminder_changed(*_a):
        if notify_reminder_block["fn"] is not None:
            notify_reminder_block["fn"]()
    save_btn = None  # wird nach dem Button-Bau gesetzt (s. unten) — EIN Button für beide Blöcke
    # "locked" = Button vorübergehend nicht klickbar: (1) kurzer Cooldown direkt
    # nach dem Öffnen (unten via dialog.after freigegeben), damit ein Doppelklick
    # auf die Kalenderzelle nicht durchschlägt und bei vorbefüllten Einträgen
    # sofort speichert; (2) während eines laufenden Speicherns. Flag statt
    # -state, weil label_button keine -state-Option hat und
    # set_primary_button_enabled nur die Optik ändert (blockt den Klick nicht).
    save_locked = {"value": True}

    def refresh_save_state():
        # Einzige Stelle, die den Enabled-Zustand entscheidet: aktiv, wenn in
        # mindestens einem der beiden Blöcke Slots vorhanden sind UND der
        # Button nicht (Cooldown/Speichern) gesperrt ist.
        if save_btn is not None:
            has_content = bool(ist_rows) or (show_reservation and bool(res_rows))
            set_primary_button_enabled(save_btn, has_content and not save_locked["value"])

    def unlock_save():
        # Ende des Öffnen-Cooldowns; Dialog kann zwischenzeitlich zu sein.
        if dialog.winfo_exists():
            save_locked["value"] = False
            refresh_save_state()

    def add_ist_row(start, end, pause, kategorie, removable=True, parent=None):
        # parent nur für die Breiten-Probe unten (ungepackter Holder) — sonst
        # landet die Zeile im sichtbaren Ist-Zeit-Block.
        row = tk.Frame(parent if parent is not None else ist_rows_frame, bg=BG)
        row.pack(fill="x", pady=2)
        sv = tk.StringVar(value=start)
        ev = tk.StringVar(value=end)
        pv = tk.StringVar(value=str(pause))
        kv = tk.StringVar(value=category_to_display(kategorie))
        # Basis = die Werte, mit denen die Zeile angelegt wurde. Wählt man für
        # eine NEUE Zeile eine Kategorie, überschreibt das ein Feld NUR, solange
        # es noch der Basis entspricht (= nicht manuell geändert), und zieht die
        # Basis nach.
        base = {"start": start, "end": end, "pause": str(pause)}
        dark_combo(row, sv, TIME_VALUES, width=6).pack(side=tk.LEFT, padx=2)
        tk.Label(row, text="–", font=FONT, bg=BG, fg=TEXT_MUTED).pack(side=tk.LEFT)
        dark_combo(row, ev, TIME_VALUES, width=6).pack(side=tk.LEFT, padx=2)
        dark_combo(row, pv, PAUSE_VALUES, width=4).pack(side=tk.LEFT, padx=2)
        cat_combo = dark_combo(row, kv, category_choices(categories), width=18)
        cat_combo.pack(side=tk.LEFT, padx=2)
        record = {"frame": row, "start": sv, "end": ev, "pause": pv, "kategorie": kv}

        # Manuelles Anpassen der Zeit ändert NIE die zugeordnete Kategorie —
        # nur das Anzeige-Label bekommt dann ein Override-Sternchen ("Office*",
        # s. slot_category_display); rein optisch, kv bleibt die einzige
        # Quelle für den beim Speichern persistierten Kategoriewert.
        def refresh_cat_display(*_a):
            kategorie = category_from_display(kv.get())
            display = slot_category_display(
                kategorie, sv.get(), ev.get(), pv.get(), category_times,
                weekday_key, default_start, default_end, default_pause,
            )
            if kv.get() != display:
                kv.set(display)

        sv.trace_add("write", refresh_cat_display)
        ev.trace_add("write", refresh_cat_display)
        pv.trace_add("write", refresh_cat_display)

        def on_cat_change(*_a):
            t_start, t_end, t_pause = resolve_slot_defaults(
                category_times, category_from_display(kv.get()), weekday_key,
                default_start, default_end, default_pause,
            )
            t_pause = str(t_pause)
            if sv.get() == base["start"]:
                sv.set(t_start)
                base["start"] = t_start
            if ev.get() == base["end"]:
                ev.set(t_end)
                base["end"] = t_end
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

        def remove():
            row.destroy()
            ist_rows.remove(record)
            # Ein leeres Tk-Frame behält sonst die Höhe seiner letzten Zeile als
            # Lücke — beim Entfernen der letzten Zeile explizit kollabieren,
            # damit der Dialog passend schrumpft (pack_propagate baut die Höhe
            # beim nächsten "+ Slot" wieder auf).
            if not ist_rows:
                ist_rows_frame.configure(height=1)
            refresh_save_state()

        # Bereits gespeicherte Slots tragen kein ×: Löschen läuft ausschließlich
        # über den Rechtsklick im Kalender (Design-Entscheidung — der Dialog
        # speichert nur). Das × erscheint nur an neu hinzugefügten, noch nicht
        # persistierten Zeilen.
        if removable:
            secondary_button(row, "×", remove, padx=8, pady=0).pack(side=tk.LEFT, padx=2)
        ist_rows.append(record)
        refresh_save_state()

    # Vorbelegung: vorhandene Ist-Slots → bestehende Reservierung (erste Slot-
    # Zeit). Gibt es weder Ist-Zeit noch Reservierung, bleibt der Block leer —
    # nur der „+ Slot"-Button erscheint, keine Default-Zeile.
    if entry and entry["slots"]:
        for s in entry["slots"]:
            add_ist_row(s["start"], s["end"], s.get("pause", 0),
                        s.get("kategorie", ""), removable=False)
    elif existing_reservation and existing_reservation["slots"]:
        # Vorschlag aus der Reservierung (noch nicht als Ist-Zeit gespeichert)
        # → entfernbar. Kategorie wird mitvorgeschlagen (suggest_ist_category:
        # nur bei genau einem Reservierungs-Slot).
        first = existing_reservation["slots"][0]
        add_ist_row(first["start"], first["end"], default_pause,
                    suggest_ist_category(existing_reservation["slots"]))

    ist_btns = tk.Frame(outer, bg=BG)
    ist_btns.pack(fill="x", pady=(2, 8))
    secondary_button(
        ist_btns, "+ Slot",
        lambda: add_ist_row(default_start, default_end, default_pause, ""),
    ).pack(side=tk.LEFT, padx=2)

    # ---------- Reservierung ----------
    if show_reservation:
        tk.Label(
            outer, text="— Reservierung —", font=FONT_BOLD, bg=BG, fg=TEXT_MUTED,
        ).pack(anchor="w", pady=(12, 2))
        res_rows_frame = tk.Frame(outer, bg=BG)
        res_rows_frame.pack(fill="x")

        def add_res_row(start, end, kategorie, removable=True,
                        send_reminder_minutes=None):
            row = tk.Frame(res_rows_frame, bg=BG)
            row.pack(fill="x", pady=2)
            sv = tk.StringVar(value=start)
            ev = tk.StringVar(value=end)
            kv = tk.StringVar(value=category_to_display(kategorie))
            base = {"start": start, "end": end}
            dark_combo(row, sv, TIME_VALUES, width=6).pack(side=tk.LEFT, padx=2)
            tk.Label(row, text="–", font=FONT, bg=BG, fg=TEXT_MUTED).pack(side=tk.LEFT)
            dark_combo(row, ev, TIME_VALUES, width=6).pack(side=tk.LEFT, padx=2)
            cat_combo = dark_combo(row, kv, category_choices(categories), width=18)
            cat_combo.pack(side=tk.LEFT, padx=2)
            record = {"frame": row, "start": sv, "end": ev, "kategorie": kv,
                      # Nicht editierbar in der Zeile — nur mitgeführt, damit
                      # ein bestehender Marker das Speichern überlebt, auch
                      # wenn der Erinnerungs-Block gar nicht sichtbar ist.
                      "send_reminder_minutes": send_reminder_minutes}

            # Manuelles Anpassen der Zeit ändert nie die Kategorie — nur das
            # Anzeige-Label bekommt ein Override-Sternchen (s. add_ist_row).
            def refresh_cat_display(*_a):
                kategorie = category_from_display(kv.get())
                display = slot_category_display(
                    kategorie, sv.get(), ev.get(), None, category_times,
                    weekday_key, default_start, default_end, default_pause,
                )
                if kv.get() != display:
                    kv.set(display)

            sv.trace_add("write", refresh_cat_display)
            ev.trace_add("write", refresh_cat_display)
            sv.trace_add("write", _reminder_changed)
            ev.trace_add("write", _reminder_changed)

            def on_cat_change(*_a):
                # Reservierungen haben keine Pause → nur Start/Ende anwenden.
                t_start, t_end, _ = resolve_slot_defaults(
                    category_times, category_from_display(kv.get()), weekday_key,
                    default_start, default_end, default_pause,
                )
                if sv.get() == base["start"]:
                    sv.set(t_start)
                    base["start"] = t_start
                if ev.get() == base["end"]:
                    ev.set(t_end)
                    base["end"] = t_end

            # Marker-Anzeige bei jeder Kategorie-Wahl neu berechnen (alle
            # Zeilen); Standardzeiten ziehen nur bei neuen Zeilen + echter
            # Auswahl (siehe add_ist_row).
            cat_combo.bind("<<ComboboxSelected>>", refresh_cat_display, add="+")
            if removable:
                cat_combo.bind("<<ComboboxSelected>>", on_cat_change, add="+")
            refresh_cat_display()  # initialer Marker-Zustand beim Dialog-Öffnen
            cat_combo.bind("<<ComboboxSelected>>", _reminder_changed, add="+")

            def remove():
                row.destroy()
                res_rows.remove(record)
                if not res_rows:
                    res_rows_frame.configure(height=1)
                refresh_save_state()
                _reminder_changed()

            # Gespeicherte Reservierungs-Slots tragen kein × (Löschen per
            # Rechtsklick im Kalender); nur neue, ungespeicherte Zeilen.
            if removable:
                secondary_button(row, "×", remove, padx=8, pady=0).pack(
                    side=tk.LEFT, padx=2)
            res_rows.append(record)
            refresh_save_state()
            _reminder_changed()

        # Bestehende Reservierung → Zeilen. Sonst leer: nur der „+ Slot"-Button
        # (an der Stelle, wo sonst die Default-Zeile stünde), keine Vorbelegung.
        if existing_reservation and existing_reservation["slots"]:
            for s in existing_reservation["slots"]:
                add_res_row(s["start"], s["end"], s.get("kategorie", ""),
                            removable=False,
                            send_reminder_minutes=s.get("send_reminder_minutes"))

        res_btns = tk.Frame(outer, bg=BG)
        res_btns.pack(fill="x", pady=(2, 8))
        secondary_button(
            res_btns, "+ Slot",
            lambda: add_res_row(default_start, default_end, ""),
        ).pack(side=tk.LEFT, padx=2)

    # ---------- Erinnerung an eine Reservierung ----------
    # Bewusst auf Funktionsebene, NICHT im if show_reservation: — sonst waere
    # reminder_ui undefiniert, wenn kein Reservierungs-Block gezeigt wird, und
    # save_all liefe in einen NameError. reminder_block_visible verlangt
    # show_reservation ohnehin.
    reminder_ui = None
    if reminder_block_visible(settings, show_reservation):
        tk.Label(
            outer, text="— Erinnerung —", font=FONT_BOLD, bg=BG, fg=TEXT_MUTED,
        ).pack(anchor="w", pady=(12, 2))
        rem_frame = tk.Frame(outer, bg=BG)
        rem_frame.pack(fill="x")

        marked = next(
            (i for i, r in enumerate(res_rows)
             if r["send_reminder_minutes"] is not None), None)
        rem_enabled = tk.BooleanVar(value=marked is not None)
        rem_slot = tk.StringVar()
        rem_minutes = tk.StringVar(value=str(
            res_rows[marked]["send_reminder_minutes"] if marked is not None
            else settings.get("send_reminder_default_minutes")))
        # Ausgewählter Slot als Index — die Labels ändern sich mit den Zeiten,
        # der Index ist die stabile Auswahl.
        rem_index = {"value": marked if marked is not None else None}

        rem_cb = tk.Checkbutton(
            rem_frame, text="Ans Verschicken der Arbeitszeiten erinnern",
            variable=rem_enabled, font=FONT, bg=BG, fg=TEXT, selectcolor=CELL_BG,
            activebackground=BG, activeforeground=TEXT, cursor="hand2",
        )
        rem_cb.pack(anchor="w")

        rem_row = tk.Frame(rem_frame, bg=BG)
        rem_row.pack(anchor="w", pady=(2, 0))
        tk.Label(rem_row, text="Slot:", font=FONT, bg=BG, fg=TEXT).pack(
            side=tk.LEFT, padx=(24, 8))
        slot_combo = dark_combo(rem_row, rem_slot, [], width=26)
        slot_combo.pack(side=tk.LEFT, padx=(0, 8))
        dark_combo(rem_row, rem_minutes,
                   [str(m) for m in range(0, 121, 5)], width=4).pack(side=tk.LEFT)
        tk.Label(rem_row, text="Minuten vor Ende", font=FONT, bg=BG, fg=TEXT).pack(
            side=tk.LEFT, padx=(8, 0))
        rem_hint = tk.Label(
            rem_frame, text="Erst eine Reservierung anlegen.",
            font=FONT_SMALL, bg=BG, fg=TEXT_MUTED)

        def on_slot_selected(*_a):
            values = list(slot_combo.cget("values"))
            if rem_slot.get() in values:
                rem_index["value"] = values.index(rem_slot.get())

        slot_combo.bind("<<ComboboxSelected>>", on_slot_selected, add="+")

        def refresh_reminder_block(*_a):
            """Hält Slot-Liste und Bedienbarkeit an den Reservierungs-Zeilen.

            Wird bei jedem Hinzufügen/Entfernen einer Zeile und bei jeder
            Zeit-/Kategorie-Änderung aufgerufen; die Auswahl bleibt über den
            Index erhalten und wird auf die Listenlänge geklemmt.
            """
            rows = [{"start": r["start"].get(), "end": r["end"].get(),
                     "kategorie": category_from_display(r["kategorie"].get())}
                    for r in res_rows]
            labels = reminder_slot_labels(rows)
            slot_combo.config(values=labels)
            if not labels:
                rem_enabled.set(False)
                rem_index["value"] = None
                rem_slot.set("")
                rem_cb.config(state="disabled")
                slot_combo.config(state="disabled")
                rem_hint.pack(anchor="w", padx=(24, 0))
                return
            rem_cb.config(state="normal")
            slot_combo.config(state="readonly")
            rem_hint.pack_forget()
            index = rem_index["value"]
            if index is None or index >= len(labels):
                index = len(labels) - 1
                rem_index["value"] = index
            rem_slot.set(labels[index])

        reminder_ui = {
            "enabled": rem_enabled, "minutes": rem_minutes, "index": rem_index,
            "refresh": refresh_reminder_block,
        }
        notify_reminder_block["fn"] = refresh_reminder_block
        refresh_reminder_block()

    # ---------- Mindestbreite ohne Slot-Zeilen ----------
    # Hat der Tag weder Ist-Zeit noch Reservierung, bestimmen nur die schmalen
    # „+ Slot"-Buttons die Dialogbreite — das Fenster wird deutlich schmaler als
    # derselbe Dialog mit einer Zeile und schneidet den Titel ab. Ein
    # unsichtbarer Spacer hält die Breite, die eine Slot-Zeile hätte. Gemessen
    # statt hart kodiert, weil die Zeilenbreite an Font/UI-Skalierung hängt; die
    # Probe-Zeile entsteht in einem nie gepackten Holder, wird also nie sichtbar.
    if not ist_rows and not res_rows:
        holder = tk.Frame(outer, bg=BG)
        add_ist_row(default_start, default_end, default_pause, "", parent=holder)
        holder.update_idletasks()
        row_width = holder.winfo_reqwidth()
        holder.destroy()
        ist_rows.clear()
        tk.Frame(outer, bg=BG, height=1, width=row_width).pack()

    # ---------- Speichern (ein Button für beide Blöcke) ----------
    def save_all():
        # Ohne Inhalt deaktiviert; während Cooldown/Speichern geblockt.
        if save_locked["value"]:
            return
        ist_slots = [{
            "start": r["start"].get(),
            "end": r["end"].get(),
            "pause": int(r["pause"].get() or 0),
            "kategorie": category_from_display(r["kategorie"].get()),
        } for r in ist_rows]
        res_slots = [{
            "start": r["start"].get(),
            "end": r["end"].get(),
            "kategorie": category_from_display(r["kategorie"].get()),
            "send_reminder_minutes": r["send_reminder_minutes"],
        } for r in res_rows]
        if not ist_slots and not (show_reservation and res_slots):
            return

        if reminder_ui is not None:
            # Nur bei sichtbarem Block anfassen: sonst blieben die aus dem
            # Store mitgeführten Marker unangetastet, statt still gelöscht zu
            # werden, wenn die Option abgeschaltet wurde.
            apply_reminder_to_slots(
                res_slots, reminder_ui["index"]["value"],
                parse_reminder_minutes(reminder_ui["minutes"].get()),
                bool(reminder_ui["enabled"].get()),
            )

        plan = plan_entry_save(ist_slots, res_slots, show_reservation)
        if plan["error"]:
            themed_showinfo(dialog, "Hinweis", plan["error"])
            return

        save_locked["value"] = True
        refresh_save_state()  # sofort sperren gegen Doppelklick

        if plan["save_ist"]:
            # Werkstudenten-Wochenlimit: prüft die ISO-Woche MIT den neuen
            # Slots (simulierter Post-Save-Stand), nicht den aktuellen
            # Storage-Stand — sonst würde eine Verlängerung, die erst über
            # das Limit treibt, nicht erkannt. Reine Warnung: der User kann
            # trotzdem speichern.
            simulated_entries = storage.get_all()
            simulated_entries[date_str] = {"slots": ist_slots}
            overshoot = check_week_limit(settings, simulated_entries, date_str)
            if overshoot is not None:
                week_label = get_week_label(overshoot["iso_year"], overshoot["iso_week"])
                confirm = themed_askyesno(
                    dialog, "Wochenlimit überschritten",
                    f"{week_label}: {overshoot['total_hours']:.2f}h Ist-Zeit "
                    f"überschreiten das konfigurierte Werkstudenten-Limit von "
                    f"{overshoot['limit_hours']:.2f}h/Woche.\n\n"
                    "Grobe Näherung, keine rechtliche Bewertung.\n\nTrotzdem speichern?",
                )
                if not confirm:
                    save_locked["value"] = False
                    refresh_save_state()  # Abbruch → wieder freigeben
                    return

            # Pausenpflicht (§4 ArbZG): zählt nur die eingetragenen
            # pause-Felder der Zeitblöcke, keine Lücke ZWISCHEN zwei Blöcken
            # desselben Tages — das steht bewusst mit im Warntext, sonst
            # wirkt eine Warnung trotz real genommener Pause zwischen zwei
            # Einträgen wie ein Bug. Reine Warnung: der User kann trotzdem
            # speichern.
            pause_violation = check_day_pause(settings, ist_slots)
            if pause_violation is not None:
                confirm = themed_askyesno(
                    dialog, "Pausenpflicht unterschritten",
                    f"{format_hours_hm(pause_violation['worked_hours'])} Arbeitszeit "
                    f"mit nur {pause_violation['actual_pause_minutes']} min Pause "
                    f"eingetragen — §4 ArbZG schreibt ab dieser Arbeitszeit mindestens "
                    f"{pause_violation['required_pause_minutes']} min vor.\n\n"
                    "Gezählt werden nur die eingetragenen Pause-Minuten der Zeitblöcke, "
                    "keine Lücke zwischen mehreren Blöcken am selben Tag.\n\n"
                    "Grobe Näherung, keine rechtliche Bewertung.\n\nTrotzdem speichern?",
                )
                if not confirm:
                    save_locked["value"] = False
                    refresh_save_state()  # Abbruch → wieder freigeben
                    return

        if plan["save_ist"]:
            storage.save(date_str, ist_slots)
        if plan["save_reservation"]:
            reservation_store.save(date_str, res_slots)
        dialog.destroy()
        on_change()
        if plan["save_reservation"] and trigger_reconcile is not None:
            trigger_reconcile()

    save_frame = tk.Frame(outer, bg=BG)
    save_frame.pack(fill="x", pady=(12, 0))
    save_btn = primary_button(save_frame, "Speichern", save_all)
    save_btn.pack(side=tk.LEFT, padx=2)
    refresh_save_state()  # startet gesperrt (Cooldown)
    dialog.after(int(STRAY_CLICK_GUARD_S * 1000), unlock_save)

    center_dialog_on_parent(dialog, parent)
