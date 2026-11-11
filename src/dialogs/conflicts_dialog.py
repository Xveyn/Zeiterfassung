# src/dialogs/conflicts_dialog.py
"""Konfliktdialog: zwei Stände nebeneinander, links die Liste der Konflikte.

Was auf den Karten steht und was sich unterscheidet, entscheidet das
Tk-freie `src/conflict_view.py`; hier werden nur Widgets gebaut.
"""

import tkinter as tk

from src import conflict_view, sync
from src.i18n import t
from src.theme import (
    ACCENT, BG, CELL_BG, ENTRY_BG, ENTRY_BG_HOVER, FONT, FONT_BOLD, FONT_HEADER_SMALL, SEPARATOR,
    STATUS_OK, STATUS_WARN, TEXT, TEXT_MUTED, TODAY_ACCENT, center_dialog_on_parent,
    create_dialog, label_button, px, secondary_button, themed_showerror,
)
from src.time_utils import format_iso_date


def done_text():
    return t("konflikt_dialog.alle_geloest")


def pick_text():
    return t("konflikt_dialog.waehle")


def none_for_day_text():
    return t("konflikt_dialog.keiner_fuer_tag")


def _entry_chosen(cand):
    """Baut den chosen-Wert für sync.resolve_conflict aus einem Entry-Kandidaten:
    die Slot-Liste + das deleted-Flag (kein Top-Level start/end/pause mehr)."""
    return {"slots": cand.get("slots", []), "deleted": cand.get("deleted", False)}


class ConflictsDialog:
    def __init__(self, parent, storage, settings, conflicts_store, data_lock=None,
                 filter_key=None, on_resolved=None):
        self.parent = parent
        self.storage = storage
        self.settings = settings
        self.conflicts_store = conflicts_store
        # Geteilter Store-RLock, durchgereicht bis zu sync.resolve_conflict.
        self._data_lock = data_lock
        self._selected = None
        self._unresolved = []
        self._rows = []
        # Nach jedem erfolgreichen Resolve aufgerufen (z.B. App._refresh) —
        # sonst zeigt der Kalender hinter dem Dialog weiter den alten
        # Konflikt-Hinweis/die alte Ist-Zeit.
        self._on_resolved = on_resolved
        # Linksklick auf einen konfliktbehafteten Kalendertag (App._open_dialog)
        # öffnet den Dialog auf genau den Konflikt DIESES Tages gefiltert;
        # die Liste bleibt dann unsichtbar (s. _build). Der Einstieg über
        # Einstellungen → Google (volle Liste, auch Einstellungs-Konflikte)
        # setzt filter_key nicht.
        self._filter_key = filter_key

        title = (t("konflikt_dialog.titel") if filter_key is None
                 else t("konflikt_dialog.titel_tag", datum=format_iso_date(filter_key)))
        self.top = create_dialog(parent, title)

        self._build()
        self._refresh_list()
        center_dialog_on_parent(self.top, parent)

    def _build(self):
        if self._filter_key is None:
            left = tk.Frame(self.top, bg=BG)
            left.pack(side="left", fill="y", padx=8, pady=8)
        else:
            left = self.top

        # Dieselbe Listbox-Palette wie die Listen-Tabs Webhooks/SMTP in den
        # Einstellungen (`_record_list_tab.py`). Die Gruppenüberschriften sind
        # Zeilen derselben Liste, aber nicht wählbar (s. _on_select). Bleibt
        # im gefilterten Fall ungepackt.
        self.listbox = tk.Listbox(
            left, width=30, height=15, font=FONT,
            bg=ENTRY_BG, fg=TEXT, activestyle="none", exportselection=False,
            selectbackground=ACCENT, selectforeground="#ffffff",
            relief="flat", highlightthickness=0,
        )
        if self._filter_key is None:
            self.listbox.pack(fill="y", expand=True)
        self.listbox.bind("<<ListboxSelect>>", lambda _e: self._on_select())

        self.right = tk.Frame(self.top, bg=BG)
        right_side = "right" if self._filter_key is None else "left"
        self.right.pack(side=right_side, fill="both", expand=True, padx=8, pady=8)

        self.title_label = tk.Label(
            self.right, text="", font=FONT_HEADER_SMALL, bg=BG, fg=TEXT,
            anchor="w", justify="left")
        self.title_label.pack(fill="x")
        self.sub_label = tk.Label(
            self.right, text="", font=FONT, bg=BG, fg=TEXT_MUTED,
            wraplength=px(480), anchor="w", justify="left")
        self.sub_label.pack(fill="x", pady=(2, 10))

        self.cards_frame = tk.Frame(self.right, bg=BG)
        self.cards_frame.pack(fill="both", expand=True)

        button_row = tk.Frame(self.right, bg=BG)
        button_row.pack(side="bottom", fill="x", pady=(10, 0))
        secondary_button(button_row, t("knopf.schliessen"),
                         self.top.destroy).pack(side="right")

    # --- Liste ---------------------------------------------------------------

    def _refresh_list(self, keep_pos=None):
        """Baut die Liste neu. `keep_pos`: Position des eben aufgelösten
        Konflikts — der Konflikt, der nachrückt, wird gleich ausgewählt."""
        self.listbox.delete(0, "end")
        unresolved = [c for c in self.conflicts_store.get_all() if not c.get("resolved")]
        if self._filter_key is not None:
            unresolved = [c for c in unresolved if c["key"] == self._filter_key]
        entries, settings = conflict_view.group_conflicts(unresolved)
        self._unresolved = entries + settings
        self._rows = []
        for header, group in ((t("konflikt_dialog.kopf_zeiten", anzahl=len(entries)), entries),
                              (t("konflikt_dialog.kopf_einstellungen", anzahl=len(settings)),
                               settings)):
            if not group:
                continue
            self._rows.append(("header", header))
            for c in group:
                self._rows.append(("conflict", c))
        for kind, payload in self._rows:
            if kind == "header":
                self.listbox.insert("end", payload)
                last = self.listbox.size() - 1
                # Eine Listbox kennt keine Schrift pro Zeile: Versalien, die
                # volle Textfarbe und der dunklere Grund setzen die Überschrift
                # ab (TEXT_MUTED war auf BG kaum zu lesen).
                self.listbox.itemconfig(
                    last, fg=TEXT, bg=BG, selectbackground=BG,
                    selectforeground=TEXT)
            else:
                self.listbox.insert("end", "  " + conflict_view.list_label(payload))

        if not self._unresolved:
            self._selected = None
            self._show_message(none_for_day_text() if self._filter_key is not None
                               else (done_text() if keep_pos is not None else pick_text()))
            return
        if self._filter_key is not None:
            self.listbox.selection_set(0)
            self._on_select(0)
        elif keep_pos is not None:
            pos = min(keep_pos, len(self._unresolved) - 1)
            self._select_pos(pos)
        else:
            self._selected = None
            self._show_message(pick_text())

    def _row_of(self, pos):
        """Listenzeile des Konflikts an Position `pos` von `_unresolved`."""
        conflict = self._unresolved[pos]
        for row, (kind, payload) in enumerate(self._rows):
            if kind == "conflict" and payload is conflict:
                return row
        return None

    def _select_pos(self, pos):
        row = self._row_of(pos)
        if row is not None:
            self.listbox.selection_clear(0, "end")
            self.listbox.selection_set(row)
            self.listbox.see(row)
        self._on_select(pos)

    def _on_select(self, pos=None):
        """`pos`: Index in `_unresolved`; ohne Angabe die Auswahl der Liste."""
        if pos is None:
            sel = self.listbox.curselection()
            if not sel:
                return
            kind, payload = self._rows[sel[0]]
            if kind == "header":
                # Überschriften sind nicht wählbar: Auswahl zurück auf den
                # angezeigten Konflikt.
                self.listbox.selection_clear(0, "end")
                if self._selected is not None and self._selected in self._unresolved:
                    row = self._row_of(self._unresolved.index(self._selected))
                    if row is not None:
                        self.listbox.selection_set(row)
                return
            pos = self._unresolved.index(payload)
        self._selected = self._unresolved[pos]
        self._show_conflict(self._selected)

    # --- Rechte Seite --------------------------------------------------------

    def _clear_cards(self):
        for child in self.cards_frame.winfo_children():
            child.destroy()

    def _show_message(self, text):
        self.title_label.config(text=text)
        self.sub_label.config(text="")
        self._clear_cards()

    def _show_conflict(self, conflict):
        registry = self.settings.get("known_devices")
        cards = conflict_view.build_cards(
            conflict, registry, self.settings.get("device_id"),
            self.settings.get("device_name") or "")
        subtitle = (t("konflikt_dialog.untertitel_einstellung")
                    if conflict.get("kind") == "setting"
                    else t("konflikt_dialog.untertitel_tag"))
        self.title_label.config(text=conflict_view.conflict_title(conflict))
        self.sub_label.config(text=subtitle)
        self._clear_cards()
        self.cards_frame.rowconfigure(0, minsize=px(230))
        for col, card in enumerate(cards):
            # Feste Mindestgröße, damit der Dialog beim Blättern nicht in
            # Breite und Höhe springt (Fenster ist nicht skalierbar).
            self.cards_frame.columnconfigure(
                col, weight=1, uniform="card", minsize=px(270))
            self._build_card(card, col)

    def _build_card(self, card, col):
        border = TODAY_ACCENT if card.is_own else SEPARATOR
        frame = tk.Frame(self.cards_frame, bg=CELL_BG, highlightthickness=1,
                         highlightbackground=border, highlightcolor=border)
        frame.grid(row=0, column=col, sticky="nsew",
                   padx=(0, 6) if col == 0 else (6, 0))

        head = tk.Frame(frame, bg=CELL_BG)
        head.pack(fill="x", padx=10, pady=(10, 0))
        tk.Label(head, text=card.title, font=FONT_BOLD, bg=CELL_BG, fg=TEXT,
                 anchor="w").pack(side="left")
        if card.newer:
            tk.Label(head, text=t("konflikt_dialog.neuer"), font=FONT, bg=CELL_BG,
                     fg=STATUS_OK).pack(side="left")
        for text in (card.device_line, card.modified):
            if text:
                tk.Label(frame, text=text, font=FONT, bg=CELL_BG, fg=TEXT_MUTED,
                         anchor="w").pack(fill="x", padx=10)

        body = tk.Frame(frame, bg=CELL_BG)
        body.pack(fill="both", expand=True, padx=10, pady=(10, 0))
        if card.deleted is not None:
            self._field(body, card.deleted, FONT_HEADER_SMALL).pack(anchor="w")
        elif card.value is not None:
            tk.Label(body, text=card.value.text, font=FONT_HEADER_SMALL,
                     bg=CELL_BG, fg=STATUS_WARN if card.value.differs else TEXT,
                     wraplength=px(220), justify="left", anchor="w").pack(anchor="w")
        for slot in card.slots:
            self._build_slot(body, slot)

        # ENTRY_BG statt des Secondary-Looks: CELL_BG wäre auf der Karte
        # unsichtbar.
        btn = label_button(
            frame, t("konflikt_dialog.behalten"),
            lambda i=card.index: self._resolve_with_candidate(i),
            bg=ENTRY_BG, fg=TEXT, hover_bg=ENTRY_BG_HOVER, hover_fg=TEXT,
            font=FONT, label_padx=16, label_pady=4)
        btn.pack(anchor="w", padx=10, pady=10)

    def _build_slot(self, parent, slot):
        box = tk.Frame(parent, bg=CELL_BG)
        box.pack(anchor="w", pady=(0, 6))
        times = tk.Frame(box, bg=CELL_BG)
        times.pack(anchor="w")
        self._field(times, slot.start, FONT_HEADER_SMALL).pack(side="left")
        tk.Label(times, text=" – ", font=FONT_HEADER_SMALL, bg=CELL_BG,
                 fg=TEXT).pack(side="left")
        self._field(times, slot.end, FONT_HEADER_SMALL).pack(side="left")
        details = tk.Frame(box, bg=CELL_BG)
        details.pack(anchor="w")
        self._field(details, slot.category, FONT).pack(side="left")
        tk.Label(details, text=" · ", font=FONT, bg=CELL_BG,
                 fg=TEXT_MUTED).pack(side="left")
        self._field(details, slot.pause, FONT).pack(side="left")

    @staticmethod
    def _field(parent, field, font):
        return tk.Label(parent, text=field.text, font=font, bg=CELL_BG,
                        fg=STATUS_WARN if field.differs else TEXT)

    # --- Auflösen ------------------------------------------------------------

    def _resolve_with_candidate(self, idx):
        if self._selected is None:
            return
        c = self._selected
        cand = c["candidates"][idx]
        if c["kind"] == "entry":
            chosen = _entry_chosen(cand)
        else:
            chosen = {"value": cand.get("value")}
        device_id = self.settings.get("device_id") or ""
        try:
            sync.resolve_conflict(c["id"], chosen, self.conflicts_store,
                                  self.storage, self.settings, device_id,
                                  data_lock=self._data_lock)
        except Exception as e:
            themed_showerror(self.top, t("konflikt_dialog.fehler_titel"), str(e))
            return
        # Guard-Reset ist PFLICHT: die Buttons der Karten bleiben bis zum
        # Neuaufbau klickbar — ohne _selected=None würde ein zweiter Klick den
        # alten Konflikt erneut auflösen.
        pos = self._unresolved.index(c) if c in self._unresolved else 0
        self._selected = None
        if self._on_resolved is not None:
            self._on_resolved()
        if self._filter_key is not None:
            # Gefiltert (Linksklick auf einen Tag) gibt es nach dem Auflösen
            # nichts mehr zu tun — der Dialog schließt sich selbst.
            self.top.destroy()
            return
        self._refresh_list(keep_pos=pos)
