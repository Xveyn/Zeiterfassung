# src/dialogs/conflicts_dialog.py
import tkinter as tk

from src import sync
from src.theme import (
    ACCENT, BG, ENTRY_BG, FONT, FONT_BOLD, TEXT,
    center_dialog_on_parent, create_dialog, secondary_button,
    set_secondary_button_enabled, themed_showerror,
)
from src.time_utils import format_iso_date, format_iso_datetime


def _fmt_slot(slot):
    kat = f" {slot['kategorie']}" if slot.get("kategorie") else ""
    return f"{slot.get('start', '')}—{slot.get('end', '')} (P{slot.get('pause', 0)}){kat}"


def _entry_chosen(cand):
    """Baut den chosen-Wert für sync.resolve_conflict aus einem Entry-Kandidaten:
    die Slot-Liste + das deleted-Flag (kein Top-Level start/end/pause mehr)."""
    return {"slots": cand.get("slots", []), "deleted": cand.get("deleted", False)}


def _fmt_entry_candidate(cand):
    when = format_iso_datetime(cand.get("modified_at", ""), fallback="")
    dev = cand.get("device_id", "?")[:8]
    if cand.get("deleted"):
        return f"GELÖSCHT (von {dev}…, {when})"
    slots = cand.get("slots", [])
    body = ", ".join(_fmt_slot(s) for s in slots) if slots else "(leer)"
    return f"{body} (von {dev}…, {when})"


def _fmt_setting_candidate(cand):
    when = format_iso_datetime(cand.get("modified_at", ""), fallback="")
    return f"{cand.get('value', '')!r} (von {cand.get('device_id', '?')[:8]}…, {when})"


class ConflictsDialog:
    def __init__(self, parent, storage, settings, conflicts_store, data_lock=None,
                 filter_key=None, on_resolved=None):
        self.parent = parent
        self.storage = storage
        self.settings = settings
        self.conflicts_store = conflicts_store
        # Geteilter Store-RLock (Review-Finding), durchgereicht bis zu
        # sync.resolve_conflict — siehe dort für die Begründung.
        self._data_lock = data_lock
        self._selected = None
        # Nach jedem erfolgreichen Resolve aufgerufen (z.B. App._refresh) —
        # sonst zeigt der Kalender hinter dem Dialog weiter den alten
        # Konflikt-Hinweis/die alte Ist-Zeit, obwohl schon aufgelöst wurde.
        self._on_resolved = on_resolved
        # Linksklick auf einen konfliktbehafteten Kalendertag (App._open_dialog)
        # öffnet diesen Dialog auf genau den Konflikt DIESES Tages gefiltert
        # (statt der vollen Liste aller offenen Konflikte) — die Listbox bleibt
        # dabei unsichtbar (s. _build), da es normalerweise ohnehin nur den
        # einen Eintrag gibt. Der Einstieg über Einstellungen → Google (volle
        # Liste, auch 'setting'-Konflikte ohne Kalendertag) setzt filter_key
        # nicht.
        self._filter_key = filter_key

        # Chrome komplett über den Konventions-Helfer (Audit H3): bringt
        # NEU dunkle Titelleiste, BG, disable_min_max, resizable(False).
        # transient übernimmt center_dialog_on_parent (gated, Tray-sicher).
        title = ("Konflikte auflösen" if filter_key is None
                 else f"Konflikt auflösen — {format_iso_date(filter_key)}")
        self.top = create_dialog(parent, title)

        self._build()
        self._refresh_list()
        center_dialog_on_parent(self.top, parent)

    def _build(self):
        # Gefiltert (Linksklick auf einen Tag) gibt es nur den einen Konflikt
        # dieses Tages — die Listbox (Navigation zwischen mehreren Konflikten)
        # entfällt dann, self.right nimmt die volle Dialogbreite ein.
        if self._filter_key is None:
            left = tk.Frame(self.top, bg=BG)
            left.pack(side="left", fill="y", padx=8, pady=8)
            tk.Label(left, text="Offene Konflikte", font=FONT_BOLD,
                     bg=BG, fg=TEXT).pack(anchor="w")
        else:
            left = self.top

        # Eine von zwei Listboxen der App (die andere: der Webhooks-Tab in
        # den Einstellungen, `tab_webhooks.py`) — beide dunkel über dieselbe
        # Palette (ENTRY_BG wie Eingabefelder, ACCENT-Selektion), flach ohne
        # Fokusrahmen. Bleibt im gefilterten Fall ungepackt (unsichtbar) —
        # _refresh_list/_on_select arbeiten unverändert auf ihr weiter, nur
        # ohne UI dafür.
        self.listbox = tk.Listbox(
            left, width=40, height=15, font=FONT,
            bg=ENTRY_BG, fg=TEXT,
            selectbackground=ACCENT, selectforeground="#ffffff",
            relief="flat", highlightthickness=0,
        )
        if self._filter_key is None:
            self.listbox.pack(fill="y", expand=True)
        self.listbox.bind("<<ListboxSelect>>", lambda _e: self._on_select())

        self.right = tk.Frame(self.top, bg=BG)
        right_side = "right" if self._filter_key is None else "left"
        self.right.pack(side=right_side, fill="both", expand=True, padx=8, pady=8)

        initial_text = ("Wähle einen Konflikt links." if self._filter_key is None
                       else "Kein offener Konflikt mehr für diesen Tag.")
        self.detail_label = tk.Label(self.right, text=initial_text,
                                      wraplength=400, justify="left",
                                      font=FONT, bg=BG, fg=TEXT)
        self.detail_label.pack(anchor="nw")

        button_row = tk.Frame(self.right, bg=BG)
        button_row.pack(side="bottom", fill="x", pady=(8, 0))
        self.btn_a = secondary_button(
            button_row, "Version A übernehmen",
            lambda: self._resolve_with_candidate(0))
        self.btn_b = secondary_button(
            button_row, "Version B übernehmen",
            lambda: self._resolve_with_candidate(1))
        self.btn_a.pack(side="left", padx=4)
        self.btn_b.pack(side="left", padx=4)
        # Optik-only-Disable (Muster set_primary_button_enabled) — der
        # No-op bei disabled läuft über den _selected-Guard im Callback.
        set_secondary_button_enabled(self.btn_a, False)
        set_secondary_button_enabled(self.btn_b, False)
        secondary_button(button_row, "Schließen",
                         self.top.destroy).pack(side="right")

    def _refresh_list(self):
        self.listbox.delete(0, "end")
        unresolved = [c for c in self.conflicts_store.get_all() if not c.get("resolved")]
        if self._filter_key is not None:
            unresolved = [c for c in unresolved if c["key"] == self._filter_key]
        self._unresolved = unresolved
        for c in self._unresolved:
            self.listbox.insert("end", f"{c['kind']}: {c['key']}")
        if self._filter_key is not None and self._unresolved:
            self.listbox.selection_set(0)
            self._on_select(0)

    def _on_select(self, idx=None):
        if idx is None:
            sel = self.listbox.curselection()
            if not sel:
                return
            idx = sel[0]
        c = self._unresolved[idx]
        if c["kind"] == "entry":
            cand_a = _fmt_entry_candidate(c["candidates"][0])
            cand_b = _fmt_entry_candidate(c["candidates"][1])
        else:
            cand_a = _fmt_setting_candidate(c["candidates"][0])
            cand_b = _fmt_setting_candidate(c["candidates"][1])
        self.detail_label.config(text=f"Konflikt für {c['key']}\n\nA: {cand_a}\n\nB: {cand_b}")
        set_secondary_button_enabled(self.btn_a, True)
        set_secondary_button_enabled(self.btn_b, True)
        self._selected = c

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
            themed_showerror(self.top, "Konflikt-Resolution fehlgeschlagen", str(e))
            return
        # Guard-Reset ist PFLICHT: die gedimmten Buttons sind Optik-only —
        # ohne _selected=None würde ein Klick den alten Konflikt erneut
        # auflösen (die frühere state="disabled"-Sperre entfällt).
        self._selected = None
        if self._on_resolved is not None:
            self._on_resolved()
        if self._filter_key is not None:
            # Gefiltert (Linksklick auf einen Tag) gibt es nach dem Auflösen
            # nichts mehr zu tun — kein "nächster Konflikt" in dieser Ansicht,
            # der Dialog schließt sich daher selbst statt die jetzt leere
            # Liste zu zeigen.
            self.top.destroy()
            return
        self._refresh_list()
        set_secondary_button_enabled(self.btn_a, False)
        set_secondary_button_enabled(self.btn_b, False)
        self.detail_label.config(text="Konflikt aufgelöst. Wähle den nächsten.")
