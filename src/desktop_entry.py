# src/desktop_entry.py
"""Freedesktop-`.desktop`-Dateien: Menüeintrag und das gemeinsame Format.

Besitzer des Formats — `autostart.py` schreibt seine Autostart-Datei über das
`exec_line` von hier, statt eine zweite Quoting-Regel zu pflegen (Audit N17:
kein Modul benutzt den privaten Namen eines anderen). Richtung stimmt so:
Autostart ist ein Sonderfall einer .desktop-Datei, nicht umgekehrt.

Tk-frei und stdlib-only, damit ohne Display testbar.
"""

import logging
import os
import shlex
import shutil

logger = logging.getLogger(__name__)

ICON_FILENAME = "icon.png"
BUNDLED_ICON = os.path.join("assets", "margenheld-icon.png")


def exec_line(target, arguments):
    """Baut die `Exec=`-Zeile mit shell-korrektem Quoting (Audit N12): ein Pfad
    mit Leerzeichen o.ä. zerbricht die .desktop-Datei sonst. `shlex.quote`
    deckt sich mit GLibs Exec-Parsing (`g_shell_parse_argv`). Werte ohne
    Sonderzeichen bleiben unverändert."""
    parts = [shlex.quote(target)]
    if arguments:
        parts.extend(shlex.quote(a) for a in arguments.split())
    return " ".join(parts)


def menu_entry_path():
    return os.path.join(
        os.path.expanduser("~"),
        ".local", "share", "applications", "Zeiterfassung.desktop",
    )


def ensure_icon(resource_path, data_path):
    """Kopiert das gebündelte PNG einmalig ins Datenverzeichnis und liefert den
    Zielpfad (oder `None`).

    Nötig, weil `Icon=` den AppImage-Mount ÜBERLEBEN muss: ein Pfad in
    `sys._MEIPASS` ist tot, sobald die App beendet ist, und das Menü zeigte
    dann ein leeres Icon.

    Idempotent über einen Dateigrößen-Vergleich — bewusst ohne Hash: das Icon
    ändert sich praktisch nie, und ein Hash pro Start wäre Aufwand ohne
    Gegenwert.
    """
    source = os.path.join(resource_path, BUNDLED_ICON)
    if not os.path.exists(source):
        logger.warning("Gebündeltes Icon %s fehlt — Menüeintrag ohne Icon", source)
        return None
    target = os.path.join(data_path, ICON_FILENAME)
    try:
        if (os.path.exists(target)
                and os.path.getsize(target) == os.path.getsize(source)):
            return target
        shutil.copyfile(source, target)
        return target
    except OSError:
        logger.warning("Icon konnte nicht ins Datenverzeichnis kopiert werden",
                       exc_info=True)
        return None


def write_menu_entry(target, icon_path):
    """Schreibt `~/.local/share/applications/Zeiterfassung.desktop`.

    Wird bei jedem Start überschrieben, damit `Exec=` nach einem Update von
    selbst auf die neue AppImage zeigt — dieselbe Selbstheilung wie beim
    Autostart.

    `StartupWMClass` ist eine begründete Annahme (Tk leitet die WM-Klasse vom
    Basisnamen der Exe ab), nicht verifiziert. Stimmt sie nicht, gruppiert der
    Desktop das Fenster nur nicht unter dem Menüeintrag — kosmetisch.
    """
    path = menu_entry_path()
    lines = [
        "[Desktop Entry]",
        "Type=Application",
        "Name=Zeiterfassung",
        "Comment=Arbeitszeiten erfassen, berichten und versenden",
        f"Exec={exec_line(target, '')}",
    ]
    if icon_path:
        lines.append(f"Icon={icon_path}")
    lines.extend([
        "Terminal=false",
        "Categories=Office;",
        "StartupWMClass=Zeiterfassung",
    ])
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
