"""Dev-Konsole: Tk-Toplevel mit Live-Log-Viewer und Aktions-Buttons.

Nur im Dev-Mode aus App erzeugt. Der Logging-Handler schiebt Records
thread-sicher per root.after ins Text-Widget (Logs kommen aus Worker-Threads).
"""

import logging
import tkinter as tk

from src.theme import BG, TEXT


class _TkLogHandler(logging.Handler):
    def __init__(self, widget, root):
        super().__init__()
        self._widget = widget
        self._root = root
        self.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%H:%M:%S",
        ))

    def emit(self, record):
        try:
            msg = self.format(record)
        except Exception:
            return
        self._root.after(0, self._append, msg)

    def _append(self, msg):
        try:
            self._widget.config(state="normal")
            self._widget.insert("end", msg + "\n")
            self._widget.see("end")
            self._widget.config(state="disabled")
        except tk.TclError:
            pass  # Fenster wurde geschlossen


class DevConsole:
    def __init__(self, root, app):
        self.app = app
        self.win = tk.Toplevel(root)
        self.win.title("Dev-Konsole")
        self.win.configure(bg=BG)
        self.win.geometry("760x460")

        btns = tk.Frame(self.win, bg=BG)
        btns.pack(side="top", fill="x", padx=6, pady=6)
        actions = (
            ("Sync Pull", self.app.dev_sync_pull),
            ("Sync Push", self.app.dev_sync_push),
            ("Token-Fehler simulieren", self._simulate_auth_error),
            ("Sample-Daten neu laden", self.app.dev_reload_sample_data),
            ("Daten-Ordner öffnen", self._open_data_dir),
            ("Log leeren", self._clear),
            ("Kopieren", self._copy),
        )
        for label, cmd in actions:
            tk.Button(btns, text=label, command=cmd).pack(side="left", padx=3)

        self.text = tk.Text(self.win, bg="#101010", fg=TEXT,
                            insertbackground=TEXT, font=("Consolas", 9),
                            state="disabled", wrap="none")
        scroll = tk.Scrollbar(self.win, command=self.text.yview)
        self.text.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.text.pack(side="left", fill="both", expand=True, padx=(6, 0), pady=(0, 6))

        self._handler = _TkLogHandler(self.text, root)
        root_logger = logging.getLogger()
        root_logger.setLevel(logging.DEBUG)
        root_logger.addHandler(self._handler)
        logging.getLogger("zeiterfassung.dev").info("Dev-Konsole geöffnet")

    def _simulate_auth_error(self):
        from src.dev import fakes
        fakes.simulate_auth_error_once()
        logging.getLogger("zeiterfassung.dev").info(
            "Nächster Google-Aufruf wirft TokenAuthError")

    def _open_data_dir(self):
        from src.platform_open import open_folder
        open_folder(self.app.base_path)

    def _clear(self):
        self.text.config(state="normal")
        self.text.delete("1.0", "end")
        self.text.config(state="disabled")

    def _copy(self):
        content = self.text.get("1.0", "end-1c")
        self.win.clipboard_clear()
        self.win.clipboard_append(content)
