# src/logging_setup.py
"""Logging-Setup mit Logfile + globalem Excepthook.

Single Purpose: einmal in main() aufrufen, danach landen alle uncaught
Exceptions und alle expliziten log.*-Calls im Logfile. Tkinter-Callback-
Crashes bekommen zusätzlich eine kurze Messagebox; der volle Traceback
geht ins Log.
"""

import logging
import os
import sys
import tkinter as tk
from logging.handlers import RotatingFileHandler


LOGFILE_NAME = "zeiterfassung.log"
LOG_SUBDIR = "logs"
MAX_BYTES = 1_000_000
BACKUP_COUNT = 3
DEFAULT_LEVEL = logging.INFO


def get_log_path(base_path: str) -> str:
    """Pfad zum Logfile, ohne das Verzeichnis anzulegen."""
    return os.path.join(base_path, LOG_SUBDIR, LOGFILE_NAME)


def _console_wanted() -> bool:
    """Konsolenausgabe nur im Quellcode-Betrieb (`python -m src.main`).

    Der gebaute Build ist `--noconsole`, dort gibt es keinen sinnvollen stderr
    (unter Windows ist `sys.stderr` dann `None`); er bleibt beim Logfile.
    """
    return not getattr(sys, "frozen", False) and sys.stderr is not None


def setup_logging(base_path: str, console: bool | None = None) -> str:
    """Konfiguriert Root-Logger und Excepthooks. Returns Logfile-Pfad.

    `console`: zusätzlich nach stderr loggen. `None` = automatisch (nur wenn
    die App aus dem Quellcode läuft, s. `_console_wanted`).

    Idempotent: ein zweiter Aufruf addiert keinen weiteren Handler.
    """
    log_dir = os.path.join(base_path, LOG_SUBDIR)
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, LOGFILE_NAME)

    root = logging.getLogger()
    root.setLevel(DEFAULT_LEVEL)
    if not any(isinstance(h, RotatingFileHandler) for h in root.handlers):
        handler = RotatingFileHandler(
            log_path,
            maxBytes=MAX_BYTES,
            backupCount=BACKUP_COUNT,
            encoding="utf-8",
        )
        handler.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        ))
        root.addHandler(handler)

    # `type(h) is`, nicht isinstance: RotatingFileHandler ist selbst ein
    # StreamHandler und würde den Konsolen-Handler sonst vortäuschen.
    if (_console_wanted() if console is None else console) and not any(
            type(h) is logging.StreamHandler for h in root.handlers):
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        ))
        root.addHandler(console_handler)

    _install_excepthooks()
    return log_path


def _install_excepthooks() -> None:
    log = logging.getLogger("zeiterfassung.uncaught")

    def _hook(exc_type, exc, tb):
        log.error("Uncaught exception", exc_info=(exc_type, exc, tb))

    sys.excepthook = _hook

    def _tk_hook(self, exc_type, exc, tb):
        log.error("Tk callback exception", exc_info=(exc_type, exc, tb))
        try:
            from tkinter import messagebox
            messagebox.showerror(
                "Unerwarteter Fehler",
                f"{exc_type.__name__}: {exc}\n\nDetails im Logfile.",
            )
        except Exception:
            log.exception(
                "Messagebox für uncaught Tk exception konnte nicht angezeigt werden",
            )

    tk.Tk.report_callback_exception = _tk_hook  # pyright: ignore[reportAttributeAccessIssue]
