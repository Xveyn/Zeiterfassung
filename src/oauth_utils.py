"""Gemeinsame OAuth-Helfer für die Google-API-Wrapper (mail/drive/gcal).

Zentralisiert den zuvor mehrfach kopierten Boilerplate (Issue #47):
Token-Persistenz mit restriktiven Permissions und die Scope-Upgrade-Erkennung.

Reine stdlib — **keine** Google-Imports auf Modulebene. Damit bleibt die
Lazy-Import-Konvention der Wrapper erhalten (CI installiert kein
`requirements.txt`, siehe CLAUDE.md); `creds` wird nur über `creds.to_json()`
angefasst, was die aufrufende Seite ohnehin schon hält.
"""

import json
import os
import stat
import tempfile


def write_token(creds, token_path):
    """Persistiere Credentials atomar und setze restriktive Permissions.

    Geschrieben wird in eine Temp-Datei im selben Verzeichnis, dann via
    `os.replace` atomar an die Zielstelle bewegt — so kann ein abgebrochener
    Schreibvorgang nie eine halbe Token-Datei hinterlassen.

    Die Permissions werden auf `0o600` gesetzt. Auf Windows ist das chmod ein
    No-op (keine POSIX-Permissions); `try/except OSError` deckt zusätzlich
    exotische Filesystems (sshfs, FAT32) ab, wo chmod fehlschlagen kann.
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
        os.replace(tmp_path, token_path)
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
