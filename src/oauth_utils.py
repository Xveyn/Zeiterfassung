"""Gemeinsame OAuth-Helfer für die Google-API-Wrapper (mail/drive/gcal).

Zentralisiert den zuvor mehrfach kopierten Boilerplate (Issue #47):
Token-Persistenz mit restriktiven Permissions und die Scope-Upgrade-Erkennung.

Reine stdlib — **keine** Google-Imports auf Modulebene. Damit bleibt die
Lazy-Import-Konvention der Wrapper erhalten (CI installiert kein
`requirements.txt`, siehe CLAUDE.md); `creds` wird nur über `creds.to_json()`
angefasst, was die aufrufende Seite ohnehin schon hält.
"""

import json
import logging
import os
import platform
import stat
import subprocess
import tempfile
import time

_log = logging.getLogger(__name__)


def _windows_principal():
    """`DOMAIN\\user` für icacls, ersatzweise der nackte Benutzername.

    `None`, wenn sich der Benutzer nicht aus der Umgebung benennen lässt — dann
    wird nicht geraten (ein falscher Principal härtete entweder nichts oder
    sperrte den eigenen Prozess aus).
    """
    user = os.environ.get("USERNAME")
    if not user:
        return None
    domain = os.environ.get("USERDOMAIN")
    return f"{domain}\\{user}" if domain else user


def _harden_windows_acl(path):
    """Beschränkt die ACL von `path` auf den aktuellen Benutzer (Audit M8).

    `os.chmod` ist unter Windows ein No-op; der Refresh-Token wäre dort allein
    durch die geerbten Rechte des Datenverzeichnisses geschützt — bei der
    per-User-Installation zusätzlich für lokale Administratoren lesbar.
    `icacls /inheritance:r /grant:r <user>:(F)` entfernt die geerbten ACEs und
    lässt genau einen Berechtigten übrig. Vollzugriff (nicht nur R/W), weil das
    spätere `os.replace` auf der Zieldatei DELETE braucht.

    Best-effort und **nie** fatal: fehlt `icacls` oder scheitert es, wird
    geloggt und weitergemacht — eine nicht gehärtete Token-Datei ist der Status
    quo, eine fehlgeschlagene Token-Persistenz wäre eine Regression.
    """
    if platform.system() != "Windows":
        return
    principal = _windows_principal()
    if not principal:
        _log.warning("Token-ACL nicht gehärtet: kein Benutzername in der Umgebung")
        return
    try:
        proc = subprocess.run(
            ["icacls", path, "/inheritance:r", "/grant:r", f"{principal}:(F)"],
            capture_output=True, text=True, timeout=15,
            # Ohne das blitzt in den --noconsole-Builds ein Konsolenfenster auf.
            # getattr, weil das Flag nur unter Windows existiert — die Tests
            # patchen platform.system() auch auf Linux-CI auf "Windows".
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError):
        _log.warning("Token-ACL nicht gehärtet: icacls nicht ausführbar", exc_info=True)
        return
    if proc.returncode != 0:
        _log.warning("Token-ACL nicht gehärtet: icacls endete mit %s (%s)",
                     proc.returncode, (proc.stderr or "").strip())


def write_token(creds, token_path):
    """Persistiere Credentials atomar und setze restriktive Permissions.

    Geschrieben wird in eine Temp-Datei im selben Verzeichnis, dann via
    `os.replace` atomar an die Zielstelle bewegt — so kann ein abgebrochener
    Schreibvorgang nie eine halbe Token-Datei hinterlassen.

    Die Permissions werden auf `0o600` gesetzt. Auf Windows ist das chmod ein
    No-op (keine POSIX-Permissions); `try/except OSError` deckt zusätzlich
    exotische Filesystems (sshfs, FAT32) ab, wo chmod fehlschlagen kann. Dort
    übernimmt stattdessen `_harden_windows_acl` (Audit M8).

    Beide Härtungen greifen auf der **Temp-Datei**, also vor dem `os.replace`:
    sonst gäbe es ein Fenster, in dem `token.json` bereits am Zielpfad steht,
    aber noch die geerbten Rechte trägt.
    """
    token_path = os.fspath(token_path)
    directory = os.path.dirname(os.path.abspath(token_path))
    fd, tmp_path = tempfile.mkstemp(
        dir=directory, prefix=".token-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(creds.to_json())
        try:
            os.chmod(tmp_path, stat.S_IRUSR | stat.S_IWUSR)  # 0o600
        except OSError:
            pass
        _harden_windows_acl(tmp_path)
        # os.replace mit Retry gegen transiente Windows-PermissionError: ein
        # Virenscanner, der die frisch erzeugte .token-*.tmp scannt, oder ein
        # noch offenes Handle auf token.json blockiert den atomaren Rename kurz
        # (WinError 5/32 -> beide PermissionError). Kurzer Backoff überbrückt das;
        # bleibt es dabei, wird der Fehler durchgereicht (Issue #135, Muster wie
        # #117). Gezielt PermissionError, damit echte Fehler (fehlende tmp,
        # Zielverzeichnis) nicht maskiert werden.
        attempts = 5
        for attempt in range(attempts):
            try:
                os.replace(tmp_path, token_path)
                break
            except PermissionError:
                if attempt == attempts - 1:
                    raise
                time.sleep(0.2)
    except BaseException:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise


def discard_token_for_scope_upgrade(token_path, scopes):
    """Erzwinge einen frischen OAuth-Flow, wenn der gespeicherte Token nicht
    alle angeforderten `scopes` abdeckt (typisch nach einem Feature-Update).

    Deckt der Token die Scopes nicht ab, wird die Token-Datei gelöscht und
    `True` geliefert — die aufrufende Seite setzt dann `creds = None` und
    durchläuft den vollen Consent. Andernfalls `False`.

    Bei Lesefehlern (kein/defektes JSON) konservativ `False`: der Token bleibt
    unangetastet, statt einen womöglich gültigen Token wegzuwerfen. Spiegelt
    das frühere `except Exception: pass` in den Wrappern.
    """
    try:
        with open(token_path, "r", encoding="utf-8") as f:
            granted = set(json.load(f).get("scopes") or [])
    except (OSError, ValueError):
        return False

    if set(scopes).issubset(granted):
        return False

    try:
        os.remove(token_path)
    except OSError:
        pass
    return True
