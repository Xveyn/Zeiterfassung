"""Einstellungen-Dialog als Paket (Audit H4): dialog.py trägt Chrome und
das Speichern je Tab (`form_model.SaveCoordinator`), die Tabs sind eigene
Klassen-Module.
Öffentliche API unverändert re-exportiert."""

from src.dialogs.settings_dialog.dialog import open_settings_dialog
from src.dialogs.settings_dialog.oauth_task import build_oauth_enable_task

__all__ = ["open_settings_dialog", "build_oauth_enable_task"]
