# src/dialogs/conflicts_dialog.py
import tkinter as tk
from tkinter import ttk, messagebox

from src import sync


def _fmt_entry_candidate(cand):
    if cand.get("deleted"):
        return f"GELÖSCHT (von {cand.get('device_id', '?')[:8]}…, {cand.get('modified_at', '')})"
    return (f"{cand.get('start', '')}—{cand.get('end', '')} "
            f"(Pause {cand.get('pause', 0)} min, von "
            f"{cand.get('device_id', '?')[:8]}…, {cand.get('modified_at', '')})")


def _fmt_setting_candidate(cand):
    return f"{cand.get('value', '')!r} (von {cand.get('device_id', '?')[:8]}…, {cand.get('modified_at', '')})"


class ConflictsDialog:
    def __init__(self, parent, storage, settings, conflicts_store):
        self.parent = parent
        self.storage = storage
        self.settings = settings
        self.conflicts_store = conflicts_store

        self.top = tk.Toplevel(parent)
        self.top.title("Konflikte auflösen")
        self.top.transient(parent)
        self.top.grab_set()

        self._build()
        self._refresh_list()

    def _build(self):
        left = tk.Frame(self.top)
        left.pack(side="left", fill="y", padx=8, pady=8)

        tk.Label(left, text="Offene Konflikte").pack(anchor="w")
        self.listbox = tk.Listbox(left, width=40, height=15)
        self.listbox.pack(fill="y", expand=True)
        self.listbox.bind("<<ListboxSelect>>", lambda _e: self._on_select())

        self.right = tk.Frame(self.top)
        self.right.pack(side="right", fill="both", expand=True, padx=8, pady=8)

        self.detail_label = tk.Label(self.right, text="Wähle einen Konflikt links.",
                                      wraplength=400, justify="left")
        self.detail_label.pack(anchor="nw")

        button_row = tk.Frame(self.right)
        button_row.pack(side="bottom", fill="x", pady=(8, 0))
        self.btn_a = tk.Button(button_row, text="Version A übernehmen",
                               command=lambda: self._resolve_with_candidate(0),
                               state="disabled")
        self.btn_b = tk.Button(button_row, text="Version B übernehmen",
                               command=lambda: self._resolve_with_candidate(1),
                               state="disabled")
        self.btn_a.pack(side="left", padx=4)
        self.btn_b.pack(side="left", padx=4)
        tk.Button(button_row, text="Schließen", command=self.top.destroy).pack(side="right")

    def _refresh_list(self):
        self.listbox.delete(0, "end")
        self._unresolved = [c for c in self.conflicts_store.get_all() if not c.get("resolved")]
        for c in self._unresolved:
            self.listbox.insert("end", f"{c['kind']}: {c['key']}")

    def _on_select(self):
        sel = self.listbox.curselection()
        if not sel:
            return
        c = self._unresolved[sel[0]]
        if c["kind"] == "entry":
            cand_a = _fmt_entry_candidate(c["candidates"][0])
            cand_b = _fmt_entry_candidate(c["candidates"][1])
        else:
            cand_a = _fmt_setting_candidate(c["candidates"][0])
            cand_b = _fmt_setting_candidate(c["candidates"][1])
        self.detail_label.config(text=f"Konflikt für {c['key']}\n\nA: {cand_a}\n\nB: {cand_b}")
        self.btn_a.config(state="normal")
        self.btn_b.config(state="normal")
        self._selected = c

    def _resolve_with_candidate(self, idx):
        c = self._selected
        cand = c["candidates"][idx]
        if c["kind"] == "entry":
            chosen = {
                "start": cand.get("start"),
                "end": cand.get("end"),
                "pause": cand.get("pause", 0),
                "deleted": cand.get("deleted", False),
            }
        else:
            chosen = {"value": cand.get("value")}
        device_id = self.settings.get("device_id") or ""
        try:
            sync.resolve_conflict(c["id"], chosen, self.conflicts_store,
                                  self.storage, self.settings, device_id)
        except Exception as e:
            messagebox.showerror("Konflikt-Resolution fehlgeschlagen", str(e))
            return
        self._refresh_list()
        self.btn_a.config(state="disabled")
        self.btn_b.config(state="disabled")
        self.detail_label.config(text="Konflikt aufgelöst. Wähle den nächsten.")
