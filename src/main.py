# src/main.py
import logging
import os
import sys
import tkinter as tk
import uuid

from src.logging_setup import setup_logging
from src.paths import get_base_path
from src.settings import Settings
from src.storage import Storage
from src.ui import App
from src.version import VERSION


def _ensure_device_id(settings):
    """Bei Erststart oder fehlendem device_id: UUID generieren und persistieren."""
    if not settings.get("device_id"):
        settings.set("device_id", str(uuid.uuid4()))


def main():
    base = get_base_path()
    try:
        setup_logging(base)
        logging.getLogger(__name__).info("Zeiterfassung v%s gestartet", VERSION)
    except Exception:
        pass

    settings = Settings(os.path.join(base, "settings.json"))
    _ensure_device_id(settings)
    device_id = settings.get("device_id")
    settings.device_id_for_sync = device_id

    storage = Storage(os.path.join(base, "zeiterfassung.json"), device_id=device_id)

    root = tk.Tk()
    app = App(root, storage, settings, base_path=base)

    if "--minimized" in sys.argv:
        root.iconify()

    root.mainloop()


if __name__ == "__main__":
    main()
