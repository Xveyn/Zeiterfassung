# src/secure_file.py
"""Zugriffsschutz für lokal abgelegte Secrets (Audit M8).

Die App schreibt zwei sensible Dateien neben die Nutzerdaten: `token.json`
(OAuth-Refresh-Token, `oauth_utils.write_token`) und `instance-secret`
(Shared Secret des Single-Instance-Handshakes, `single_instance`). Beide werden
atomar über Temp-Datei + `os.replace` geschrieben und mit `chmod 0600`
abgesichert — unter Windows ist das chmod allerdings ein No-op.

Dieses Modul liefert das Windows-Gegenstück. Es ist bewusst ein eigenes,
stdlib-only Modul und hängt an keinem der beiden Aufrufer: `single_instance`
soll nichts aus dem OAuth-Umfeld importieren müssen (und umgekehrt), und
private Namen modulübergreifend zu nutzen ist im Projekt ausdrücklich
unerwünscht (Audit N17).
"""

import logging
import os
import platform
import subprocess

_log = logging.getLogger(__name__)


def _windows_principal():
    """`DOMAIN\\user` für icacls, ersatzweise der nackte Benutzername.

    `None`, wenn sich der Benutzer nicht aus der Umgebung benennen lässt — dann
    wird nicht geraten: ein falscher Principal härtete entweder nichts oder
    sperrte den eigenen Prozess aus.
    """
    user = os.environ.get("USERNAME")
    if not user:
        return None
    domain = os.environ.get("USERDOMAIN")
    return f"{domain}\\{user}" if domain else user


def harden_windows_acl(path):
    """Beschränkt die ACL von `path` unter Windows auf den aktuellen Benutzer.

    `icacls /inheritance:r /grant:r <user>:(F)` entfernt die geerbten ACEs (bei
    der per-User-Installation u.a. SYSTEM und die lokale Administratorengruppe)
    und lässt genau einen Berechtigten übrig. **Vollzugriff**, nicht nur R/W:
    ein späteres `os.replace` auf diese Datei braucht DELETE, sonst scheitert
    der nächste Schreibvorgang.

    Aufrufen auf der **Temp-Datei**, bevor `os.replace` sie unter dem
    Zielnamen sichtbar macht — sonst liegt die Datei kurzzeitig mit geerbten
    Rechten am Zielpfad.

    Best-effort und **nie** fatal: fehlt `icacls` oder scheitert es, wird
    geloggt und weitergemacht. Eine ungehärtete Datei ist der Status quo, ein
    fehlgeschlagener Schreibvorgang wäre eine Regression. Auf Nicht-Windows ein
    No-op (dort greift `chmod 0600`).
    """
    if platform.system() != "Windows":
        return
    principal = _windows_principal()
    if not principal:
        _log.warning("ACL nicht gehärtet (%s): kein Benutzername in der Umgebung", path)
        return
    try:
        proc = subprocess.run(
            ["icacls", path, "/inheritance:r", "/grant:r", f"{principal}:(F)"],
            capture_output=True, text=True, timeout=15,
            # Ohne das blitzt in den --noconsole-Builds ein Konsolenfenster auf.
            # getattr, weil das Flag nur unter Windows existiert — die Tests
            # patchen platform.system() auch auf der Linux-CI auf "Windows".
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError):
        _log.warning("ACL nicht gehärtet (%s): icacls nicht ausführbar", path,
                     exc_info=True)
        return
    if proc.returncode != 0:
        _log.warning("ACL nicht gehärtet (%s): icacls endete mit %s (%s)",
                     path, proc.returncode, (proc.stderr or "").strip())
