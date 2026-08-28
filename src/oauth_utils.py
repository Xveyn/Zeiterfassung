"""Gemeinsame OAuth-Helfer für die Google-API-Wrapper (mail/drive/gcal).

Zentralisiert den zuvor mehrfach kopierten Boilerplate (Issue #47):
Token-Persistenz mit restriktiven Permissions und die Scope-Upgrade-Erkennung.

Reine stdlib — **keine** Google-Imports auf Modulebene. Damit bleibt die
Lazy-Import-Konvention der Wrapper erhalten (CI installiert kein
`requirements.txt`, siehe CLAUDE.md); `creds` wird nur über `creds.to_json()`
angefasst, was die aufrufende Seite ohnehin schon hält.
"""

from __future__ import annotations

import json
from typing import Any, Collection
import os
import stat
import tempfile
import time

from src.secure_file import harden_windows_acl


def write_token(creds: Any, token_path: str) -> None:
    """Persistiere Credentials atomar und setze restriktive Permissions.

    Geschrieben wird in eine Temp-Datei im selben Verzeichnis, dann via
    `os.replace` atomar an die Zielstelle bewegt — so kann ein abgebrochener
    Schreibvorgang nie eine halbe Token-Datei hinterlassen.

    Die Permissions werden auf `0o600` gesetzt. Auf Windows ist das chmod ein
    No-op (keine POSIX-Permissions); `try/except OSError` deckt zusätzlich
    exotische Filesystems (sshfs, FAT32) ab, wo chmod fehlschlagen kann. Dort
    übernimmt stattdessen `secure_file.harden_windows_acl` (Audit M8).

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
        harden_windows_acl(tmp_path)
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


def read_granted_scopes(token_path: str) -> list[str] | None:
    """Die im `token.json` tatsächlich gewährten OAuth-Scopes.

    Liefert die Liste, oder `None`, wenn die Datei fehlt, nicht lesbar ist,
    kaputtes JSON enthält oder ein `scopes`-Feld trägt, das keine Liste ist.
    Eine leere Liste heißt dagegen: Datei war lesbar, es sind keine Scopes
    vermerkt. Die Unterscheidung braucht die Anzeige im Google-Tab, um
    „noch nicht angemeldet" von „nicht lesbar" zu trennen (#120).

    Konservativ wie der ganze Token-Pfad: bei Zweifeln lieber `None` als eine
    falsche Behauptung über die gewährten Rechte.
    """
    try:
        with open(token_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    # json.load wirft nicht ValueError für non-dict-Wurzeln — z.B. [] oder "x"
    # sind syntaktisch gültig und zurückgegeben (plausibel bei
    # Teilschreibvorgängen, Plattenfehlern oder manueller Bearbeitung).
    # .get() wirft auf ihnen AttributeError; das konservativ abfangen.
    if not isinstance(data, dict):
        return None
    scopes = data.get("scopes")
    if scopes is None:
        return []
    if not isinstance(scopes, list):
        return None
    return scopes


def discard_token_for_scope_upgrade(token_path: str,
                                    scopes: Collection[str]) -> bool:
    """Erzwinge einen frischen OAuth-Flow, wenn der gespeicherte Token nicht
    alle angeforderten `scopes` abdeckt (typisch nach einem Feature-Update).

    Deckt der Token die Scopes nicht ab, wird die Token-Datei gelöscht und
    `True` geliefert — die aufrufende Seite setzt dann `creds = None` und
    durchläuft den vollen Consent. Andernfalls `False`.

    Bei Lesefehlern (kein/defektes JSON) konservativ `False`: der Token bleibt
    unangetastet, statt einen womöglich gültigen Token wegzuwerfen. Spiegelt
    das frühere `except Exception: pass` in den Wrappern.
    """
    granted = read_granted_scopes(token_path)
    if granted is None:
        # Nicht lesbar → konservativ: Token unangetastet lassen, statt einen
        # womöglich gültigen wegzuwerfen.
        return False

    if set(scopes).issubset(set(granted)):
        return False

    try:
        os.remove(token_path)
    except OSError:
        pass
    return True
