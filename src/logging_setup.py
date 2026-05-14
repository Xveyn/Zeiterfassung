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


def setup_logging(base_path: str) -> str:
    """Konfiguriert Root-Logger und Excepthooks. Returns Logfile-Pfad.

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
