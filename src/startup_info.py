# src/startup_info.py
"""Die Startzeilen des Logs (Xveyn#401): welcher Build läuft wo, und welche
Funktionen sind an.

Tk-frei und ohne I/O: alles kommt als Argument herein, damit es ohne echte
Plattform testbar ist. Es steht nur drin, was für die Fehlersuche gebraucht
wird — Build-Kennung, Betriebssystem, Python/Tk, Schalter. Nie Namen, Pfade,
Adressen oder Zugangsdaten.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping

# Schalter, die im Log als an/aus erscheinen (Settings-Schlüssel -> Kurzname).
FEATURE_FLAGS: tuple[tuple[str, str], ...] = (
    ("sync_enabled", "sync"),
    ("gcal_enabled", "kalender"),
    ("reservations_enabled", "reservierungen"),
    ("vacation_gcal_enabled", "urlaub-push"),
    ("mobile_enabled", "mobil"),
    ("mobile_push_enabled", "mobil-push"),
    ("api_enabled", "api"),
    ("minimize_to_tray", "tray"),
    ("reminders_enabled", "erinnerungen"),
    ("send_reminder_enabled", "sende-erinnerung"),
    ("auto_update_enabled", "auto-update"),
    ("prerelease_updates_enabled", "vorabversionen"),
)

# Nur auf Linux aussagekräftig (Tray, Skalierung und Schlüsselbund hängen daran).
_LINUX_ENV_KEYS: tuple[str, ...] = (
    "XDG_SESSION_TYPE", "XDG_CURRENT_DESKTOP")


def describe_environment(*, label: str, channel: str, frozen: bool,
                         system: str, platform_text: str, machine: str,
                         python: str, tk: float | str,
                         env: Mapping[str, str]) -> str:
    """Eine Zeile: Build, Kanal, Plattform, Python/Tk (+ Sitzung unter Linux)."""
    parts = [
        f"Zeiterfassung {label} gestartet",
        f"Kanal {channel}",
        "gebaut" if frozen else "Quellcode",
        f"{platform_text} ({machine})",
        f"Python {python}",
        f"Tk {tk}",
    ]
    if system == "Linux":
        session = ", ".join(
            f"{key}={env[key]}" for key in _LINUX_ENV_KEYS if env.get(key))
        if session:
            parts.append(session)
    return " · ".join(parts)


def describe_features(get: Callable[[str], object]) -> str:
    """Eine Zeile: welche Schalter an sind, dazu die UI-Skalierung."""
    on = [name for key, name in FEATURE_FLAGS if get(key)]
    off = [name for key, name in FEATURE_FLAGS if not get(key)]
    text = "Funktionen an: " + (", ".join(on) if on else "keine")
    if off:
        text += " · aus: " + ", ".join(off)
    scale = get("ui_scale")
    if scale:
        text += f" · UI-Skalierung {scale} %"
    return text
