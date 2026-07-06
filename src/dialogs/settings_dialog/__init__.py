"""Einstellungen-Dialog als Paket (Audit H4): dialog.py trägt Chrome +
zentrales save_settings, die vier Tabs sind eigene Klassen-Module.
Öffentliche API unverändert re-exportiert."""

from src.dialogs.settings_dialog.dialog import open_settings_dialog
from src.dialogs.settings_dialog.oauth_task import build_oauth_enable_task

__all__ = ["open_settings_dialog", "build_oauth_enable_task"]
