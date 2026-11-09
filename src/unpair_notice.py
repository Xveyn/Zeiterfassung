# pyright: reportOptionalMemberAccess=true
"""Der Hinweis an den Nutzer, wenn sich ein Handy selbst getrennt hat (#499), Tk-frei.

Kanalwahl und Texte als reine Funktionen, damit die Plattform-Lagen (Windows und Linux mit Tray,
macOS ohne, Fenster versteckt) ohne Tk testbar sind. Die Texte nennen nur den Gerätenamen."""
from __future__ import annotations

from typing import Final

_NAME_LIMIT: Final = 40
_FALLBACK_NAME: Final = "Ein Handy"


def unpair_notice_channel(*, window_visible: bool, tray_available: bool) -> str:
    """`"dialog"` bei sichtbarem Fenster, sonst `"toast"` mit Tray, sonst `"log"`."""
    if window_visible:
        return "dialog"
    return "toast" if tray_available else "log"


def _clean(name: str | None, limit: int) -> str:
    """Name in einer Zeile, gekürzt; leer wird zum Platzhalter. Der Name stammt vom Handy."""
    text = " ".join(str(name or "").split())
    if not text:
        return _FALLBACK_NAME
    return text if len(text) <= limit else text[:limit - 1] + "…"


def unpair_notice_text(name: str | None) -> tuple[str, str]:
    """(Titel, Text) des Dialogs."""
    who = _clean(name, 80)
    return ("Handy getrennt",
            f"{who} hat sich vom Desktop getrennt. Das Gerät wurde widerrufen; "
            "zum erneuten Verbinden muss es neu gekoppelt werden.")


def unpair_toast_text(name: str | None) -> str:
    return f"{_clean(name, _NAME_LIMIT)} hat sich vom Desktop getrennt."
