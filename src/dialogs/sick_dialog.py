"""Krankheit eintragen und verwalten: Anlege-/Bearbeiten-Dialog und Übersicht.

Planung, Sperren und Speichern liegen Tk-frei in `sick_plan.py`; hier ist nur
das Wiring — dieselbe Aufteilung wie in `vacation_dialog.py`.
"""

import contextlib
import datetime
import logging
import tkinter as tk
import traceback
from tkinter import messagebox, ttk

from src.absence import format_day_list
from src.dialogs.date_row import build_date_row
from src.dialogs.vacation_dialog import (
    _format_hours, parse_hours, prune_overrides,
)
from src.holidays_de import get_holidays
from src.reservations import reservations_active
from src.sick_plan import (
    BASES, BASIS_LABELS, HINT_AU, HINT_SICK_ON_VACATION, MAX_BLOCK_DAYS,
    block_hints, commit_sick_block, normalize_basis, plan_sick_save, prefill,
    reservation_dates_in, sick_blocking_vacation, work_blocking_days,
)
from src.sick_view import block_label, manager_rows
from src.theme import (
    ACCENT, BG, CELL_BG, FONT, FONT_BOLD, FONT_SMALL, TEXT, TEXT_MUTED,
    apply_combobox_style, center_dialog_on_parent, create_dialog, dark_entry,
    primary_button, px, secondary_button, set_button_text, themed_askyesno,
    themed_showerror,
)
from src.time_utils import format_iso_weekday_date, format_minutes_hm
from src.vacation_plan import hours_to_minutes_exact

log = logging.getLogger(__name__)

NO_STATE_HINT = ("Kein Bundesland gewählt — Feiertage werden als "
                 "Krankheitstage mit Stunden gezählt.")
RESERVATION_CHECK_TEXT = "Reservierungen in diesem Zeitraum löschen"
SAVE_TITLE = "Krankheit nicht gespeichert"


def _active_reservations(reservation_store, settings):
    """Alle Reservierungen, wenn sie aktiv sind, sonst `None`."""
    if reservation_store is not None and reservations_active(
            reservation_store, settings):
        return reservation_store.get_all()
    return None


def _check_button(parent, text, var):
    return tk.Checkbutton(
        parent, text=text, variable=var, font=FONT, bg=BG,
        fg=TEXT, selectcolor=CELL_BG, activebackground=BG,
        activeforeground=TEXT, highlightthickness=0, bd=0, anchor="w")


def open_sick_dialog(parent, *, sick_store, storage, settings,
                     date_from, date_to=None, reservation_store=None,
                     vacation_store=None, on_change=None,
                     on_reservations_deleted=None, data_lock=None):
    """Krankheit eintragen. Liegt `date_from` in einem Block, wird dieser
    Block bearbeitet (Von/Bis aus dem Block, seine Tage als Überschreibungen).
    """
    existing = sick_store.block_for(date_from)
    old_dates = list(existing.days) if existing else []
    dialog = create_dialog(
        parent, "Krankheit bearbeiten" if existing else "Krankheit eintragen")
    apply_combobox_style(dialog)
    state = settings.get("state") or ""

    if existing:
        from_default = datetime.date.fromisoformat(existing.date_from)
        to_default = datetime.date.fromisoformat(existing.date_to)
    else:
        from_default = datetime.date.fromisoformat(date_from)
        to_default = datetime.date.fromisoformat(date_to or date_from)

    from_row = build_date_row(dialog, "Von:", from_default,
                              on_change=lambda: _recalc(), label_width=6,
                              year_to_offset=3)
    to_row = build_date_row(dialog, "Bis:", to_default,
                            on_change=lambda: _recalc(), label_width=6,
                            year_to_offset=3)
    from_row.frame.pack(anchor="w", padx=12, pady=(12, 4))
    to_row.frame.pack(anchor="w", padx=12, pady=4)

    basis_var = tk.StringVar(value=normalize_basis(
        settings.get("sick_hours_basis")))
    basis_frame = tk.Frame(dialog, bg=BG)
    basis_frame.pack(anchor="w", padx=12, pady=(8, 4))
    for basis in BASES:
        tk.Radiobutton(
            basis_frame, text=BASIS_LABELS[basis], variable=basis_var,
            value=basis, command=lambda: _recalc(), font=FONT, bg=BG, fg=TEXT,
            selectcolor=CELL_BG, activebackground=BG, activeforeground=TEXT,
            highlightthickness=0, bd=0, anchor="w").pack(anchor="w")

    overrides = dict(existing.days) if existing else {}
    day_vars = {}
    expanded = {"on": False}
    current: dict = {"prefill": None}

    toggle = secondary_button(
        dialog, "▸ Einzelne Tage anpassen", lambda: _toggle_days())
    toggle.pack(anchor="w", padx=12, pady=(8, 0))

    day_scroll = tk.Frame(dialog, bg=BG)
    day_canvas = tk.Canvas(day_scroll, bg=BG, highlightthickness=0,
                           height=px(220))
    day_bar = ttk.Scrollbar(day_scroll, orient="vertical",
                            command=day_canvas.yview,
                            style="Vertical.TScrollbar")
    day_canvas.configure(yscrollcommand=day_bar.set)
    day_canvas.pack(side="left", fill="both", expand=True)
    day_bar.pack(side="right", fill="y")
    day_rows_frame = tk.Frame(day_canvas, bg=BG)
    day_canvas.create_window((0, 0), window=day_rows_frame, anchor="nw")

    total_label = tk.Label(dialog, text="", font=FONT_BOLD, bg=BG, fg=TEXT)
    total_label.pack(anchor="w", padx=12, pady=(8, 4))

    delete_res_var = tk.BooleanVar(value=True)
    extras = tk.Frame(dialog, bg=BG)
    extras.pack(anchor="w", fill=tk.X, padx=12)
    hints_label = tk.Label(extras, text="", font=FONT_SMALL, bg=BG,
                           fg=TEXT_MUTED, wraplength=px(420), justify="left")
    hints_label.pack(anchor="w", pady=(0, 4))
    res_check = _check_button(extras, RESERVATION_CHECK_TEXT, delete_res_var)

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

    def _compute_prefill():
        """Vorbelegung, nur bei gültigem Zeitraum bis `MAX_BLOCK_DAYS`."""
        df, dt = _range()
        if df is None or dt is None or dt < df:
            return None
        if (dt - df).days + 1 > MAX_BLOCK_DAYS:
            return None
        sick_days = {d: m for d, m in sick_store.day_minutes().items()
                     if d not in old_dates}
        return prefill(
            df.isoformat(), dt.isoformat(), basis=basis_var.get(),
            entries=storage.get_all(),
            reservations=_active_reservations(reservation_store, settings),
            vacation_days=(vacation_store.day_minutes()
                           if vacation_store is not None else {}),
            sick_days=sick_days, settings=settings)

    def _current_plan():
        df, dt = _range()
        if df is None or dt is None:
            return {"error": "Ungültiges Datum.", "days": {}}
        pf = current["prefill"]
        return plan_sick_save(df.isoformat(), dt.isoformat(),
                              pf.days if pf else {}, overrides)

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
            var = tk.StringVar(value=_format_hours(days[day]))
            day_vars[day] = var
            dark_entry(row, var, width=6).pack(side=tk.LEFT)
            name = holidays.get(datetime.date.fromisoformat(day))
            if name:
                tk.Label(row, text=name, font=FONT_SMALL, bg=BG,
                         fg=TEXT_MUTED).pack(side=tk.LEFT, padx=(6, 0))
            var.trace_add("write", lambda *_, d=day: _override(d))
        day_rows_frame.update_idletasks()
        day_canvas.configure(scrollregion=day_canvas.bbox("all"))

    def _override(day):
        hours = parse_hours(day_vars[day].get())
        if hours is None:
            return
        overrides[day] = max(0, hours_to_minutes_exact(hours))
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
            hints += block_hints(days)
        hints.append(HINT_AU)
        if not state:
            hints.append(NO_STATE_HINT)
        if vacation_store is not None and sick_blocking_vacation(
                vacation_store.day_minutes(), days):
            hints.append(HINT_SICK_ON_VACATION)
        hints_label.config(text="\n\n".join(hints))
        reservations = _active_reservations(reservation_store, settings)
        if reservation_dates_in(days, reservations):
            res_check.pack(anchor="w", before=hints_label)
        else:
            res_check.pack_forget()

    def _recalc():
        """Neu vorbelegen; von Hand geänderte Tage bleiben, soweit sie noch im
        Zeitraum liegen."""
        current["prefill"] = _compute_prefill()
        plan = _current_plan()
        kept = prune_overrides(overrides, plan)
        overrides.clear()
        overrides.update(kept)
        if expanded["on"]:
            _rebuild_day_rows(plan["days"])
        _update_summary()

    def _toggle_days():
        expanded["on"] = not expanded["on"]
        if expanded["on"]:
            _rebuild_day_rows(_current_plan()["days"])
            day_scroll.pack(anchor="w", padx=24, fill=tk.X, before=total_label)
            set_button_text(toggle, "▾ Einzelne Tage anpassen")
        else:
            day_scroll.pack_forget()
            set_button_text(toggle, "▸ Einzelne Tage anpassen")

    def _save():
        plan = _current_plan()
        if plan["error"]:
            themed_showerror(dialog, SAVE_TITLE, plan["error"])
            return
        days = plan["days"]
        blocked = work_blocking_days(days, storage.get_all())
        if blocked:
            themed_showerror(
                dialog, SAVE_TITLE,
                "An diesen Tagen ist bereits Arbeitszeit erfasst:\n\n"
                + format_day_list(blocked)
                + "\n\nKrankheit und Arbeitszeit schließen sich am selben "
                  "Tag aus; zuerst die Einträge löschen oder einen anderen "
                  "Zeitraum wählen.")
            return
        want_delete = bool(delete_res_var.get() and reservation_dates_in(
            days, _active_reservations(reservation_store, settings)))
        lock = data_lock if data_lock is not None else contextlib.nullcontext()
        try:
            with lock:
                deleted = commit_sick_block(
                    sick_store, reservation_store, old_dates=old_dates,
                    days=days, delete_reservations=want_delete)
        except (OSError, ValueError) as e:
            themed_showerror(
                dialog, SAVE_TITLE,
                f"Die Krankheitsdatei konnte nicht geschrieben werden:\n\n{e}")
            return
        except Exception:
            # Unerwartet: nativ mit Traceback, der Dialog bleibt offen. Das
            # Log nennt nur den Fehlertyp, nie Tage oder Minuten.
            log.error("Krankheit speichern fehlgeschlagen")
            messagebox.showerror(SAVE_TITLE, traceback.format_exc(),
                                 parent=dialog)
            return
        basis = normalize_basis(basis_var.get())
        if basis != normalize_basis(settings.get("sick_hours_basis")):
            # Der Block ist schon gespeichert; scheitert nur die Vorbelegung,
            # ist das folgenlos.
            try:
                settings.set_synced("sick_hours_basis", basis)
            except OSError:
                log.exception("Vorbelegung sick_hours_basis nicht gespeichert")
        dialog.destroy()
        if on_change is not None:
            on_change()
        if deleted and on_reservations_deleted is not None:
            on_reservations_deleted()

    buttons = tk.Frame(dialog, bg=BG)
    buttons.pack(fill=tk.X, padx=12, pady=12)
    secondary_button(buttons, "Abbrechen", dialog.destroy).pack(side=tk.RIGHT)
    primary_button(buttons, "Speichern", _save).pack(side=tk.RIGHT,
                                                     padx=(0, 8))

    current["prefill"] = _compute_prefill()
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
        listbox.delete(0, tk.END)
        order.clear()
        blocks = sorted(sick_store.blocks(), key=lambda b: b.date_from,
                        reverse=True)
        order.extend(blocks)
        for span, total in manager_rows(blocks):
            listbox.insert(tk.END, f"{span}   {total}")

    def _selected():
        sel = listbox.curselection()
        return order[sel[0]] if sel else None

    def _changed():
        _reload()
        if on_change is not None:
            on_change()

    def _new():
        open_sick_dialog(
            dialog, sick_store=sick_store, storage=storage, settings=settings,
            date_from=datetime.date.today().isoformat(),
            reservation_store=reservation_store, vacation_store=vacation_store,
            on_change=_changed, on_reservations_deleted=on_reservations_deleted,
            data_lock=data_lock)

    def _edit():
        block = _selected()
        if block is None:
            themed_showerror(dialog, "Kein Zeitraum gewählt",
                             "Bitte zuerst einen Krankheitszeitraum auswählen.")
            return
        open_sick_dialog(
            dialog, sick_store=sick_store, storage=storage, settings=settings,
            date_from=block.date_from, reservation_store=reservation_store,
            vacation_store=vacation_store, on_change=_changed,
            on_reservations_deleted=on_reservations_deleted,
            data_lock=data_lock)

    def _delete():
        block = _selected()
        if block is None:
            themed_showerror(dialog, "Kein Zeitraum gewählt",
                             "Bitte zuerst einen Krankheitszeitraum auswählen.")
            return
        if not themed_askyesno(
                dialog, "Krankheit löschen",
                f"{block_label(block)} komplett löschen?", lock_ms=600):
            return
        sick_store.delete_days(list(block.days))
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
