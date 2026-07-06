import datetime
import tkinter as tk

from src.category_defaults import resolve_slot_defaults
from src.holidays_de import get_holidays
from src.settings import WEEKDAY_KEYS
from src.theme import (
    BG, FONT, FONT_BOLD, PAUSE_VALUES, STRAY_CLICK_GUARD_S, TEXT, TEXT_MUTED,
    TIME_VALUES, apply_combobox_style, attach_unfocus_on_click,
    center_dialog_on_parent, create_dialog, dark_combo,
    primary_button, secondary_button,
    set_primary_button_enabled, themed_askyesno, themed_showinfo,
)
from src.time_utils import format_iso_weekday_date, get_week_label, validate_slots
from src.weekly_limit import check_week_limit

# Kategorie am Slot: "" = keine Kategorie. Das Dropdown ist readonly (Anlegen/
# Bearbeiten von Kategorien läuft über die Einstellungen, nicht per Freitext),
# darum wird "" als eigener Eintrag "(ohne Kategorie)" gezeigt und beim Speichern
# wieder auf "" abgebildet. Label konsistent mit report.py/period_picker/share.
NO_CATEGORY_LABEL = "(ohne Kategorie)"


def category_choices(categories):
    """Werte fürs readonly-Kategorie-Dropdown: '(ohne Kategorie)' zuerst, dann
    die in den Einstellungen gepflegten Kategorien."""
    return [NO_CATEGORY_LABEL, *categories]


def category_to_display(value):
    """Gespeicherter Kategoriewert ('' = keine) → Dropdown-Anzeige."""
    return value if value else NO_CATEGORY_LABEL


def category_from_display(display):
    """Dropdown-Anzeige → gespeicherter Kategoriewert ('(ohne Kategorie)' → '')."""
    return "" if display == NO_CATEGORY_LABEL else display


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


def open_entry_dialog(parent, date_str, storage, settings, on_change,
                      reservation_store=None, trigger_reconcile=None):
    """Modaler Dialog zum Bearbeiten von Ist-Zeit und Reservierung eines Tages.

    Beide Blöcke führen eine Liste von Slot-Zeilen (Start/Ende/Pause/Kategorie
    bzw. Start/Ende/Kategorie). Speichern sammelt die Zeilen, validiert sie
    (validate_slots: pro Slot + Überlappungsfreiheit) und schreibt die Slot-
    Liste. Entfernt man alle Zeilen eines Blocks und speichert, wird der Block
    gelöscht — der Dialog hat keinen Lösch-Button (Löschen läuft im Kalender:
    Rechtsklick auf Win/Linux, ✕-Button in der Zelle auf macOS).

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
                date_de = day.strftime("%d.%m.%Y")
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
    ist_save_btn = None  # wird nach dem Button-Bau gesetzt (s. unten)
    # "locked" = Button vorübergehend nicht klickbar: (1) kurzer Cooldown direkt
    # nach dem Öffnen (unten via dialog.after freigegeben), damit ein Doppelklick
    # auf die Kalenderzelle nicht durchschlägt und bei vorbefüllten Einträgen
    # sofort speichert; (2) während eines laufenden Speicherns. Flag statt
    # -state, weil label_button keine -state-Option hat und
    # set_primary_button_enabled nur die Optik ändert (blockt den Klick nicht).
    ist_save_locked = {"value": True}

    def refresh_ist_save_state():
        # Einzige Stelle, die den Enabled-Zustand entscheidet: aktiv, wenn Slots
        # vorhanden sind UND der Button nicht (Cooldown/Speichern) gesperrt ist.
        if ist_save_btn is not None:
            set_primary_button_enabled(
                ist_save_btn, bool(ist_rows) and not ist_save_locked["value"])

    def unlock_ist_save():
        # Ende des Öffnen-Cooldowns; Dialog kann zwischenzeitlich zu sein.
        if dialog.winfo_exists():
            ist_save_locked["value"] = False
            refresh_ist_save_state()

    def add_ist_row(start, end, pause, kategorie, removable=True):
        row = tk.Frame(ist_rows_frame, bg=BG)
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

        # Standardzeiten der Kategorie ziehen nur bei NEUEN (entfernbaren) Zeilen
        # und nur bei echter Auswahl aus der Vorschlagsliste (<<ComboboxSelected>>)
        # — nicht pro Tastendruck (Freitext würde sonst auf globale Defaults
        # zurücksetzen) und nicht für bereits gespeicherte Slots (deren Zeiten
        # sind bewusst gesetzt und bleiben unangetastet).
        if removable:
            cat_combo.bind("<<ComboboxSelected>>", on_cat_change)

        def remove():
            row.destroy()
            ist_rows.remove(record)
            # Ein leeres Tk-Frame behält sonst die Höhe seiner letzten Zeile als
            # Lücke — beim Entfernen der letzten Zeile explizit kollabieren,
            # damit der Dialog passend schrumpft (pack_propagate baut die Höhe
            # beim nächsten "+ Slot" wieder auf).
            if not ist_rows:
                ist_rows_frame.configure(height=1)
            refresh_ist_save_state()

        # Bereits gespeicherte Slots tragen kein ×: Löschen läuft ausschließlich
        # über den Rechtsklick im Kalender (Design-Entscheidung — der Dialog
        # speichert nur). Das × erscheint nur an neu hinzugefügten, noch nicht
        # persistierten Zeilen.
        if removable:
            secondary_button(row, "×", remove, padx=8, pady=0).pack(side=tk.LEFT, padx=2)
        ist_rows.append(record)
        refresh_ist_save_state()

    # Vorbelegung: vorhandene Ist-Slots → bestehende Reservierung (erste Slot-
    # Zeit). Gibt es weder Ist-Zeit noch Reservierung, bleibt der Block leer —
    # nur der „+ Slot"-Button erscheint, keine Default-Zeile.
    if entry and entry["slots"]:
        for s in entry["slots"]:
            add_ist_row(s["start"], s["end"], s.get("pause", 0),
                        s.get("kategorie", ""), removable=False)
    elif existing_reservation and existing_reservation["slots"]:
        # Vorschlag aus der Reservierung (noch nicht als Ist-Zeit gespeichert)
        # → entfernbar.
        first = existing_reservation["slots"][0]
        add_ist_row(first["start"], first["end"], default_pause, "")

    ist_btns = tk.Frame(outer, bg=BG)
    ist_btns.pack(fill="x", pady=(2, 8))
    secondary_button(
        ist_btns, "+ Slot",
        lambda: add_ist_row(default_start, default_end, default_pause, ""),
    ).pack(side=tk.LEFT, padx=2)

    def save_ist():
        # Ohne Slot deaktiviert; während Cooldown/Speichern geblockt.
        if not ist_rows or ist_save_locked["value"]:
            return
        ist_save_locked["value"] = True
        refresh_ist_save_state()  # sofort sperren gegen Doppelklick
        slots = [{
            "start": r["start"].get(),
            "end": r["end"].get(),
            "pause": int(r["pause"].get() or 0),
            "kategorie": category_from_display(r["kategorie"].get()),
        } for r in ist_rows]
        ok, msg = validate_slots(slots, with_pause=True)
        if not ok:
            themed_showinfo(dialog, "Hinweis", msg)
            ist_save_locked["value"] = False
            refresh_ist_save_state()  # Fehler → wieder freigeben
            return

        # Werkstudenten-Wochenlimit: prüft die ISO-Woche MIT den neuen Slots
        # (simulierter Post-Save-Stand), nicht den aktuellen Storage-Stand —
        # sonst würde eine Verlängerung, die erst über das Limit treibt,
        # nicht erkannt. Reine Warnung: der User kann trotzdem speichern.
        simulated_entries = storage.get_all()
        simulated_entries[date_str] = {"slots": slots}
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
                ist_save_locked["value"] = False
                refresh_ist_save_state()  # Abbruch → wieder freigeben
                return

        storage.save(date_str, slots)
        dialog.destroy()
        on_change()

    ist_save = tk.Frame(outer, bg=BG)
    ist_save.pack(fill="x")
    ist_save_btn = primary_button(ist_save, "Speichern", save_ist)
    ist_save_btn.pack(side=tk.LEFT, padx=2)
    refresh_ist_save_state()  # startet gesperrt (Cooldown)
    dialog.after(int(STRAY_CLICK_GUARD_S * 1000), unlock_ist_save)

    # ---------- Reservierung ----------
    if show_reservation:
        tk.Label(
            outer, text="— Reservierung —", font=FONT_BOLD, bg=BG, fg=TEXT_MUTED,
        ).pack(anchor="w", pady=(12, 2))
        res_rows_frame = tk.Frame(outer, bg=BG)
        res_rows_frame.pack(fill="x")
        res_rows = []  # Liste von {frame, start, end, kategorie}
        res_save_btn = None  # wird nach dem Button-Bau gesetzt (s. unten)
        res_save_locked = {"value": True}  # Cooldown + Speicher-Sperre (s. ist_save_locked)

        def refresh_res_save_state():
            if res_save_btn is not None:
                set_primary_button_enabled(
                    res_save_btn, bool(res_rows) and not res_save_locked["value"])

        def unlock_res_save():
            if dialog.winfo_exists():
                res_save_locked["value"] = False
                refresh_res_save_state()

        def add_res_row(start, end, kategorie, removable=True):
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
            record = {"frame": row, "start": sv, "end": ev, "kategorie": kv}

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

            # Nur bei neuen Zeilen + echter Auswahl ziehen (siehe add_ist_row).
            if removable:
                cat_combo.bind("<<ComboboxSelected>>", on_cat_change)

            def remove():
                row.destroy()
                res_rows.remove(record)
                if not res_rows:
                    res_rows_frame.configure(height=1)
                refresh_res_save_state()

            # Gespeicherte Reservierungs-Slots tragen kein × (Löschen per
            # Rechtsklick im Kalender); nur neue, ungespeicherte Zeilen.
            if removable:
                secondary_button(row, "×", remove, padx=8, pady=0).pack(
                    side=tk.LEFT, padx=2)
            res_rows.append(record)
            refresh_res_save_state()

        # Bestehende Reservierung → Zeilen. Sonst leer: nur der „+ Slot"-Button
        # (an der Stelle, wo sonst die Default-Zeile stünde), keine Vorbelegung.
        if existing_reservation and existing_reservation["slots"]:
            for s in existing_reservation["slots"]:
                add_res_row(s["start"], s["end"], s.get("kategorie", ""),
                            removable=False)

        res_btns = tk.Frame(outer, bg=BG)
        res_btns.pack(fill="x", pady=(2, 8))
        secondary_button(
            res_btns, "+ Slot",
            lambda: add_res_row(default_start, default_end, ""),
        ).pack(side=tk.LEFT, padx=2)

        def save_reservation():
            # Ohne Slot deaktiviert; während Cooldown/Speichern geblockt.
            if not res_rows or res_save_locked["value"]:
                return
            res_save_locked["value"] = True
            refresh_res_save_state()  # sofort sperren gegen Doppelklick
            slots = [{
                "start": r["start"].get(),
                "end": r["end"].get(),
                "kategorie": category_from_display(r["kategorie"].get()),
            } for r in res_rows]
            ok, msg = validate_slots(slots, with_pause=False)
            if not ok:
                themed_showinfo(dialog, "Hinweis", msg)
                res_save_locked["value"] = False
                refresh_res_save_state()  # Fehler → wieder freigeben
                return
            reservation_store.save(date_str, slots)
            dialog.destroy()
            on_change()
            if trigger_reconcile is not None:
                trigger_reconcile()

        res_save = tk.Frame(outer, bg=BG)
        res_save.pack(fill="x")
        res_save_btn = primary_button(res_save, "Reservierung speichern",
                                      save_reservation)
        res_save_btn.pack(side=tk.LEFT, padx=2)
        refresh_res_save_state()  # startet gesperrt (Cooldown)
        dialog.after(int(STRAY_CLICK_GUARD_S * 1000), unlock_res_save)

    center_dialog_on_parent(dialog, parent)
