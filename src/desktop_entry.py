# src/desktop_entry.py
"""Freedesktop-`.desktop`-Dateien: schreibt den Menüeintrag und besitzt die
`Exec=`-Quoting-Regel.

`autostart.py` schreibt weiterhin sein eigenes `[Desktop Entry]` — die beiden
Dateien tragen unterschiedliche Keys, ein gemeinsamer Renderer lohnt sich
nicht. Geteilt wird nur `exec_line` (Audit N17: kein Modul benutzt den
privaten Namen eines anderen); `autostart.py` importiert es von hier statt
eine zweite Quoting-Regel zu pflegen. Richtung stimmt so: Autostart ist ein
Sonderfall des Exec-Quotings, nicht umgekehrt.

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
    Sonderzeichen bleiben unverändert.

    `arguments` ist typischerweise ein Whitespace-getrennter String einfacher
    Flags (z.B. "" oder "--minimized"); im Nicht-Frozen-Modus kann es
    zusätzlich einen Skript-Pfad enthalten (`resolve_autostart_target`) — ein
    Leerzeichen darin würde fälschlich als Token-Grenze behandelt.
    Vorbestehendes Verhalten, nicht durch den Umzug hierher eingeführt.

    Quotet NICHT `%`: in einer `.desktop`-`Exec=`-Zeile leitet `%` einen
    Freedesktop-Feldcode ein (`%f`, `%u`, …), ein literales `%` müsste als
    `%%` verdoppelt werden. `shlex.quote` kennt nur Shell-Metazeichen, keine
    Freedesktop-Feldcodes — ein `%` im Pfad (z.B. einer AppImage) bliebe
    unverändert und würde die Zeile verstümmeln. Bislang nicht behoben,
    hier nur dokumentiert."""
    parts = [shlex.quote(target)]
    if arguments:
        parts.extend(shlex.quote(a) for a in arguments.split())
    return " ".join(parts)


def menu_entry_path():
    """Zielpfad des Menüeintrags, `<XDG_DATA_HOME>/applications/Zeiterfassung.desktop`.

    `XDG_DATA_HOME` respektiert, Fallback `~/.local/share` — spiegelt
    `paths.get_base_path()`. Ohne diesen Fallback-Abgleich würde die Datei bei
    gesetztem `XDG_DATA_HOME` an einem Ort geschrieben, den keine
    Desktop-Umgebung durchsucht: sie entstünde, erschiene aber nie im Menü —
    genau der Fehlerfall, den dieses Modul beheben soll."""
    xdg = os.environ.get("XDG_DATA_HOME") or os.path.join(
        os.path.expanduser("~"), ".local", "share"
    )
    return os.path.join(xdg, "applications", "Zeiterfassung.desktop")


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
    """Schreibt den Menüeintrag nach `menu_entry_path()`.

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
