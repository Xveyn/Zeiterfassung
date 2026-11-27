"""Krankheit eintragen und verwalten: Anlege-/Bearbeiten-Dialog und Übersicht.

Planung, Sperren und Speichern liegen Tk-frei in `sick_plan.py`; hier ist nur
das Wiring — dieselbe Aufteilung wie in `vacation_dialog.py`.
"""

import contextlib
import datetime
import logging
import tkinter as tk
import traceback
from tkinter import messagebox

from src.absence import format_day_list
from src.dialogs.date_row import build_date_row
from src.dialogs.vacation_dialog import (
    format_hours, parse_hours, prune_overrides,
)
from src.holidays_de import get_holidays
from src.reservations import reservations_active
from src.sick_plan import (
    BASES, BASIS_LABELS, HINT_AU, HINT_SICK_ON_VACATION, MAX_BLOCK_DAYS,
    ReservationDeleteError, basis_changed, block_hints, commit_sick_block,
    edit_overrides, normalize_basis, plan_sick_save, prefill,
    reservation_check_text, reservation_dates_to_offer, resulting_block_days,
    stored_overrides, touches_vacation, work_blocking_days,
)
from src.sick_view import block_label, manager_rows, ordered_blocks
from src.theme import (
    ACCENT, BG, CELL_BG, FONT, FONT_BOLD, FONT_SMALL, STRAY_CLICK_GUARD_S,
    TEXT, TEXT_MUTED, Form, apply_combobox_style, center_dialog_on_parent,
    create_dialog, dark_entry, primary_button, secondary_button,
    set_button_text, set_primary_button_enabled, themed_askyesno,
    themed_showerror, themed_showinfo, themed_showwarning,
)
from src.time_utils import format_iso_weekday_date, format_minutes_hm
from src.vacation_plan import hours_to_minutes_exact

log = logging.getLogger(__name__)

NO_STATE_HINT = ("Kein Bundesland gewählt — Feiertage werden als "
                 "Krankheitstage mit Stunden gezählt.")
SAVE_TITLE = "Krankheit nicht gespeichert"
PARTIAL_TITLE = "Teilweise gespeichert"
PARTIAL_TEXT = ("Krankheit gespeichert, aber nicht alle Reservierungen "
                "ließen sich löschen.\n\nBitte prüf die Reservierungen in "
                "diesem Zeitraum im Kalender.")
GONE_TITLE = "Zeitraum geändert"
GONE_TEXT = ("Dieser Krankheitszeitraum wurde inzwischen geändert oder "
             "gelöscht. Die Liste ist neu geladen.")


def _active_reservations(reservation_store, settings):
    """Alle Reservierungen, wenn sie aktiv sind, sonst `None`."""
    if reservation_store is not None and reservations_active(
            reservation_store, settings):
        return reservation_store.get_all()
    return None


def open_sick_dialog(parent, *, sick_store, storage, settings,
                     date_from, date_to=None, edit_block=None,
                     reservation_store=None, vacation_store=None,
                     on_change=None, on_reservations_deleted=None,
                     data_lock=None):
    """Krankheit eintragen. Ohne `edit_block` legt der Dialog an (`date_from`/
    `date_to` sind die Vorbelegung); mit einem `SickBlock` bearbeitet er
    diesen (Von/Bis aus dem Block, seine Tage als Überschreibungen). Wer
    bearbeiten will, übergibt den Block ausdrücklich — erkannt wird nichts."""
    old_dates = list(edit_block.days) if edit_block else []
    old_set = set(old_dates)
    dialog = create_dialog(
        parent, "Krankheit bearbeiten" if edit_block else "Krankheit eintragen")
    apply_combobox_style(dialog)
    state = settings.get("state") or ""

    if edit_block:
        from_default = datetime.date.fromisoformat(edit_block.date_from)
        to_default = datetime.date.fromisoformat(edit_block.date_to)
    else:
        from_default = datetime.date.fromisoformat(date_from)
        to_default = datetime.date.fromisoformat(date_to or date_from)

    buttons = tk.Frame(dialog, bg=BG)
    buttons.pack(side=tk.BOTTOM, fill=tk.X, padx=12, pady=12)
    form = Form(dialog, scroll=True)
    form.frame.pack(fill=tk.BOTH, expand=True)
    body = form.body

    # --- Zeitraum ---
    form.section("Zeitraum")
    from_row = build_date_row(body, None, from_default,
                              on_change=lambda: _recalc(), year_to_offset=3)
    to_row = build_date_row(body, None, to_default,
                            on_change=lambda: _recalc(), year_to_offset=3)
    form.row("Von", from_row.frame)
    form.row("Bis", to_row.frame)

    # --- Stunden ---
    form.section("Stunden")
    basis_var = tk.StringVar(value=normalize_basis(
        settings.get("sick_hours_basis")))
    basis_frame = tk.Frame(body, bg=BG)
    for basis in BASES:
        tk.Radiobutton(
            basis_frame, text=BASIS_LABELS[basis], variable=basis_var,
            value=basis, command=lambda: _recalc(), font=FONT, bg=BG, fg=TEXT,
            selectcolor=CELL_BG, activebackground=BG, activeforeground=TEXT,
            highlightthickness=0, bd=0, anchor="w").pack(anchor="w")
    form.block(basis_frame)

    # stored: die gespeicherten Krankheitstage im Zeitraum (`_refresh_stored`);
    # edited: die in dieser Sitzung von Hand geänderten. Ein Wechsel der
    # Grundlage verwirft stored.
    stored = {}
    edited = {}
    initial_basis = normalize_basis(settings.get("sick_hours_basis"))
    day_vars = {}
    expanded = {"on": False}
    current: dict = {"prefill": None, "res_shown": False}

    toggle = form.buttons(
        ("▸ Einzelne Tage anpassen", lambda: _toggle_days()))[0]
    day_rows_frame = tk.Frame(body, bg=BG)
    form.block(day_rows_frame)
    day_rows_frame.grid_remove()

    total_label = tk.Label(body, text="", font=FONT_BOLD, bg=BG, fg=TEXT)
    form.block(total_label)

    # --- Hinweise ---
    form.section("Hinweise")
    hints_label = form.hint("")

    # --- Reservierungen ---
    res_head = form.section("Reservierungen")
    delete_res_var = tk.BooleanVar(value=True)
    res_check = form.check("", delete_res_var)
    res_head.grid_remove()
    res_check.grid_remove()

    def _range():
        try:
            df = datetime.date(int(from_row.vars[2].get()),
                               int(from_row.vars[1].get()),
                               int(from_row.vars[0].get()))
            dt = datetime.date(int(to_row.vars[2].get()),
                               int(to_row.vars[1].get()),
                               int(to_row.vars[0].get()))
        except ValueError:
            return None, None
        return df, dt

    def _other_sick_days():
        """Lebende Krankheitstage ohne die des bearbeiteten Blocks: die
        schreibt das Speichern neu oder macht sie zu Tombstones."""
        return {d: m for d, m in sick_store.day_minutes().items()
                if d not in old_set}

    def _compute_prefill():
        """Vorbelegung, nur bei gültigem Zeitraum bis `MAX_BLOCK_DAYS`."""
        df, dt = _range()
        if df is None or dt is None or dt < df:
            return None
        if (dt - df).days + 1 > MAX_BLOCK_DAYS:
            return None
        return prefill(
            df.isoformat(), dt.isoformat(), basis=basis_var.get(),
            entries=storage.get_all(),
            reservations=_active_reservations(reservation_store, settings),
            vacation_days=(vacation_store.day_minutes()
                           if vacation_store is not None else {}),
            sick_days=_other_sick_days(), settings=settings)

    def _refresh_stored():
        """Gespeicherte Tage für den aktuellen Zeitraum neu lesen; bei
        ungültigem Zeitraum bleibt der Stand (wie `prune_overrides` bei einem
        Fehler-Plan), damit ein Tippfehler im Datum nichts verwirft."""
        df, dt = _range()
        if df is None or dt is None or dt < df:
            return
        fresh = stored_overrides(
            df.isoformat(), dt.isoformat(), sick_store.day_minutes(),
            edit_block.days if edit_block else None)
        stored.clear()
        stored.update(fresh)

    def _overrides():
        return edit_overrides(
            stored, edited,
            basis_changed=basis_changed(basis_var.get(), initial_basis))

    def _current_plan():
        df, dt = _range()
        if df is None or dt is None:
            return {"error": "Ungültiges Datum.", "days": {}}
        pf = current["prefill"]
        return plan_sick_save(df.isoformat(), dt.isoformat(),
                              pf.days if pf else {}, _overrides())

    def _rebuild_day_rows(days):
        for child in day_rows_frame.winfo_children():
            child.destroy()
        day_vars.clear()
        holidays = {}
        for year in {d[:4] for d in days}:
            holidays.update(get_holidays(state, int(year)))
        for day in sorted(days):
            row = tk.Frame(day_rows_frame, bg=BG)
            row.pack(anchor="w", pady=1)
            tk.Label(row, text=format_iso_weekday_date(day), font=FONT_SMALL,
                     bg=BG, fg=TEXT, width=24, anchor="w").pack(side=tk.LEFT)
            var = tk.StringVar(value=format_hours(days[day]))
            day_vars[day] = var
            dark_entry(row, var, width=6).pack(side=tk.LEFT)
            name = holidays.get(datetime.date.fromisoformat(day))
            if name:
                tk.Label(row, text=name, font=FONT_SMALL, bg=BG,
                         fg=TEXT_MUTED).pack(side=tk.LEFT, padx=(6, 0))
            var.trace_add("write", lambda *_, d=day: _override(d))

    def _override(day):
        hours = parse_hours(day_vars[day].get())
        if hours is None:
            return
        edited[day] = max(0, hours_to_minutes_exact(hours))
        _update_summary()

    def _update_summary():
        plan = _current_plan()
        days = plan["days"]
        if plan["error"] and not days:
            total_label.config(text="Krankheit gesamt: —")
        else:
            total_label.config(
                text=f"Krankheit gesamt: {format_minutes_hm(sum(days.values()))}")
        hints = list(current["prefill"].hints) if current["prefill"] else []
        if days:
            hints += block_hints(resulting_block_days(days, _other_sick_days()))
        hints.append(HINT_AU)
        if not state:
            hints.append(NO_STATE_HINT)
        if vacation_store is not None and touches_vacation(
                days, vacation_store.day_minutes()):
            hints.append(HINT_SICK_ON_VACATION)
        hints_label.config(text="\n\n".join(hints))
        # Wie in `commit_sick_block`: die alten Tage des Blocks zählen als
        # krank, auch wenn sie inzwischen anderswo gelöscht wurden.
        sick_before = set(sick_store.day_minutes()) | old_set
        shown = bool(reservation_dates_to_offer(
            days, _active_reservations(reservation_store, settings),
            sick_before))
        current["res_shown"] = shown
        if shown:
            res_check.config(text=reservation_check_text(days, sick_before))
            res_head.grid()
            res_check.grid()
        else:
            res_head.grid_remove()
            res_check.grid_remove()

    def _recalc():
        """Neu vorbelegen; gespeicherte und von Hand geänderte Tage bleiben,
        soweit sie im Zeitraum liegen."""
        current["prefill"] = _compute_prefill()
        _refresh_stored()
        plan = _current_plan()
        kept = prune_overrides(edited, plan)
        edited.clear()
        edited.update(kept)
        if expanded["on"]:
            _rebuild_day_rows(plan["days"])
        _update_summary()

    def _toggle_days():
        expanded["on"] = not expanded["on"]
        if expanded["on"]:
            _rebuild_day_rows(_current_plan()["days"])
            day_rows_frame.grid()
            set_button_text(toggle, "▾ Einzelne Tage anpassen")
        else:
            day_rows_frame.grid_remove()
            set_button_text(toggle, "▸ Einzelne Tage anpassen")

    def _finish(deleted):
        """Nach dem geschriebenen Block: Grundlage merken, schließen und die
        Aufrufer informieren — auch wenn Reservierungen hängen blieben.
        Geschrieben wird die Grundlage nur, wenn sie im Dialog gegenüber dem
        Öffnen geändert wurde; sonst überschriebe der Dialog einen inzwischen
        per Sync geänderten Wert mit dem, mit dem er bloß gerechnet hat."""
        basis = normalize_basis(basis_var.get())
        if basis_changed(basis, initial_basis):
            try:
                settings.set_synced("sick_hours_basis", basis)
            except Exception:
                # Der Block ist schon gespeichert; scheitert nur das Merken
                # der Grundlage, ist das folgenlos. Schließen und Neuzeichnen
                # dürfen daran nicht hängen.
                log.exception("Vorbelegung sick_hours_basis nicht gespeichert")
        dialog.destroy()
        if on_change is not None:
            on_change()
        if deleted and on_reservations_deleted is not None:
            on_reservations_deleted()

    def _show_blocked(blocked):
        themed_showerror(
            dialog, SAVE_TITLE,
            "An diesen Tagen ist bereits Arbeitszeit erfasst:\n\n"
            + format_day_list(blocked)
            + "\n\nKrankheit und Arbeitszeit schließen sich am selben "
              "Tag aus; zuerst die Einträge löschen oder einen anderen "
              "Zeitraum wählen.")

    def _save():
        if save_locked["value"]:
            return
        plan = _current_plan()
        if plan["error"]:
            themed_showerror(dialog, SAVE_TITLE, plan["error"])
            return
        days = plan["days"]
        # Nur löschen, was das Häkchen gerade zeigt und der Nutzer gesetzt hat.
        want_delete = bool(current["res_shown"] and delete_res_var.get())
        lock = data_lock if data_lock is not None else contextlib.nullcontext()
        blocked = []
        deleted = []
        try:
            # Prüfen und Schreiben unter einem Lock: dazwischen trägt kein
            # Sync und keine API Ist-Zeit auf einen der Tage ein.
            with lock:
                blocked = work_blocking_days(days, storage.get_all())
                if not blocked:
                    deleted = commit_sick_block(
                        sick_store, reservation_store, old_dates=old_dates,
                        days=days, delete_reservations=want_delete)
        except ReservationDeleteError as e:
            # Der Block steht schon: erst schließen und neu zeichnen, dann
            # melden. Das Log nennt nur den Typ des Grunds, nie Tage.
            log.warning("Reservierungen nach Krankmeldung nicht alle "
                        "gelöscht: %s", type(e.__cause__).__name__)
            _finish(e.deleted)
            if isinstance(e.__cause__, OSError):
                themed_showwarning(parent, PARTIAL_TITLE, PARTIAL_TEXT)
            else:
                messagebox.showerror(PARTIAL_TITLE, traceback.format_exc(),
                                     parent=parent)
            return
        except (OSError, ValueError) as e:
            themed_showerror(
                dialog, SAVE_TITLE,
                f"Die Krankheitsdatei konnte nicht geschrieben werden:\n\n{e}")
            return
        except Exception as exc:
            # Unerwartet und vor dem Schreiben des Blocks: nativ mit
            # Traceback, der Dialog bleibt offen. Das Log nennt nur den
            # Fehlertyp, nie Meldung, Tage oder Minuten.
            log.error("Krankheit speichern fehlgeschlagen: %s",
                      type(exc).__name__)
            messagebox.showerror(SAVE_TITLE, traceback.format_exc(),
                                 parent=dialog)
            return
        if blocked:
            _show_blocked(blocked)
            return
        _finish(deleted)

    secondary_button(buttons, "Abbrechen", dialog.destroy).pack(side=tk.RIGHT)
    save_btn = primary_button(buttons, "Speichern", _save)
    save_btn.pack(side=tk.RIGHT, padx=(0, 8))
    # Kurz nach dem Öffnen gesperrt: der Dialog öffnet vorbelegt aus einem
    # Kalenderklick, und `label_button` löst schon beim Drücken aus — der
    # zweite Klick eines Doppelklicks landete sonst auf „Speichern“. Flag
    # statt Optik allein, `set_primary_button_enabled` blockt keinen Klick.
    save_locked = {"value": True}
    set_primary_button_enabled(save_btn, False)

    def _unlock_save():
        if dialog.winfo_exists():
            save_locked["value"] = False
            set_primary_button_enabled(save_btn, True)
    dialog.after(int(STRAY_CLICK_GUARD_S * 1000), _unlock_save)

    current["prefill"] = _compute_prefill()
    _refresh_stored()
    _update_summary()
    center_dialog_on_parent(dialog, parent)


def open_sick_manager(parent, *, sick_store, storage, settings,
                      reservation_store=None, vacation_store=None,
                      on_change=None, on_reservations_deleted=None,
                      data_lock=None):
    """Übersicht aller Krankheitszeiträume mit Neu / Bearbeiten / Löschen."""
    dialog = create_dialog(parent, "Krankheit verwalten")
    tk.Label(dialog, text="Krankheitszeiträume", font=FONT_BOLD, bg=BG,
             fg=TEXT).pack(anchor="w", padx=12, pady=(12, 4))
    listbox = tk.Listbox(
        dialog, font=FONT, bg=CELL_BG, fg=TEXT, selectbackground=ACCENT,
        selectforeground="#ffffff", highlightthickness=0, relief=tk.FLAT,
        width=40, height=10, activestyle="none")
    listbox.bind("<Double-Button-1>", lambda e: _edit())
    listbox.pack(fill=tk.BOTH, expand=True, padx=12)
    tk.Label(dialog, text="Löschen geht auch per Rechtsklick im Kalender.",
             font=FONT_SMALL, bg=BG, fg=TEXT_MUTED).pack(
                 anchor="w", padx=12, pady=(4, 0))

    order = []

    def _reload():
        """Ordnet die Blöcke einmal; Zeilen und Auswahl lesen dieselbe Liste."""
        listbox.delete(0, tk.END)
        order.clear()
        order.extend(ordered_blocks(sick_store.blocks()))
        for span, total in manager_rows(order):
            listbox.insert(tk.END, f"{span}   {total}")

    def _selected():
        sel = listbox.curselection()
        return order[sel[0]] if sel else None

    def _changed():
        _reload()
        if on_change is not None:
            on_change()

    def _open(edit_block, date_from):
        open_sick_dialog(
            dialog, sick_store=sick_store, storage=storage, settings=settings,
            date_from=date_from, edit_block=edit_block,
            reservation_store=reservation_store, vacation_store=vacation_store,
            on_change=_changed, on_reservations_deleted=on_reservations_deleted,
            data_lock=data_lock)

    def _new():
        _open(None, datetime.date.today().isoformat())

    def _edit():
        block = _selected()
        if block is None:
            themed_showerror(dialog, "Kein Zeitraum gewählt",
                             "Bitte zuerst einen Krankheitszeitraum auswählen.")
            return
        # Frisch lesen wie beim Löschen: bearbeitet wird der Block, wie er
        # jetzt im Store steht, nicht das Abbild der Liste.
        fresh = sick_store.block_for(block.date_from)
        if fresh is None:
            themed_showinfo(dialog, GONE_TITLE, GONE_TEXT)
            _changed()
            return
        _open(fresh, fresh.date_from)

    def _delete():
        block = _selected()
        if block is None:
            themed_showerror(dialog, "Kein Zeitraum gewählt",
                             "Bitte zuerst einen Krankheitszeitraum auswählen.")
            return
        # Die Liste ist nur ein Abbild des Stores; frisch lesen, damit ein
        # inzwischen geänderter Block nicht mit veralteten Tagen gelöscht wird.
        fresh = sick_store.block_for(block.date_from)
        if fresh is None:
            _changed()
            return
        if not themed_askyesno(
                dialog, "Krankheit löschen",
                f"{block_label(fresh)} komplett löschen?", lock_ms=600):
            return
        try:
            sick_store.delete_days(list(fresh.days))
        except OSError as e:
            themed_showerror(
                dialog, "Krankheit nicht gelöscht",
                f"Die Krankheitsdatei konnte nicht geschrieben werden:\n\n{e}")
            return
        except Exception as exc:
            # Unerwartet: nativ mit Traceback; das Log nennt nur den Typ.
            log.error("Krankheit löschen fehlgeschlagen: %s",
                      type(exc).__name__)
            messagebox.showerror("Krankheit nicht gelöscht",
                                 traceback.format_exc(), parent=dialog)
            return
        _changed()

    buttons = tk.Frame(dialog, bg=BG)
    buttons.pack(fill=tk.X, padx=12, pady=12)
    secondary_button(buttons, "Neu", _new).pack(side=tk.LEFT)
    secondary_button(buttons, "Bearbeiten", _edit).pack(side=tk.LEFT,
                                                        padx=(8, 0))
    secondary_button(buttons, "Löschen", _delete).pack(side=tk.LEFT,
                                                       padx=(8, 0))
    primary_button(buttons, "Schließen", dialog.destroy).pack(side=tk.RIGHT)

    _reload()
    center_dialog_on_parent(dialog, parent)
