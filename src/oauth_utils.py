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
import logging
import uuid
from typing import Any, Collection
import os
import stat
import tempfile
import threading
import time

from src.secure_file import harden_windows_acl
from src import keyring_store

log = logging.getLogger(__name__)

# Speichern, Umzug und Verwerfen sind Lesen-Prüfen-Schreiben an token.json;
# beim Start erneuern Refresh, Absender-Abruf, Sync-Pull und Kalender-Abgleich
# parallel. Liegt hier und nicht in `token_store`, weil `forget_token` ihn
# braucht und `token_store` dieses Modul importiert (andersherum ein Zyklus);
# `token_store.TOKEN_LOCK` ist derselbe Lock.
TOKEN_LOCK = threading.RLock()


def write_token_json(json_text: str, token_path: str) -> None:
    """Persistiere fertigen JSON-Text atomar und setze restriktive Permissions.

    Schreibt fertigen JSON-Text; `write_token` und `token_store.save_credentials`
    liefern ihn.

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
            f.write(json_text)
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


def write_token(creds: Any, token_path: str) -> None:
    """Persistiere Credentials vollständig (inkl. Refresh-Token) als Datei —
    der Datei-Modus, byte-gleich zum Verhalten vor #101."""
    write_token_json(creds.to_json(), token_path)


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


REAUTH_REQUIRED_MSG = "Kein gültiger Google-Token — Anmeldung erforderlich."
"""Fehlertext der Service-Builder, wenn sie ohne Klick keinen Consent starten
dürfen (Xveyn#129). Ein Wert für beide Builder, weil die Sync-Flows den Fehler
teils nur als `str(e)` weiterreichen — `sync_orchestrator.classify_sync_error`
erkennt den Auth-Fall dann allein an diesem Text."""

KEYRING_UNAVAILABLE_MSG = (
    "Der Schlüsselbund des Betriebssystems ist nicht erreichbar — dort liegt "
    "die Google-Anmeldung.")
"""Fehlertext, wenn der Refresh-Token im Schlüsselbund liegt, dieser aber
nicht antwortet. Wie `REAUTH_REQUIRED_MSG` als Text erkennbar, weil
Sync-Flows Fehler teils nur als `str(e)` weiterreichen."""

REFRESH_TOKEN_LOCATION = "refresh_token_location"
"""Feld in token.json: `"keyring"`, wenn der Refresh-Token im Schlüsselbund
liegt. Fehlt es (Alt-Format), liegt er in der Datei (#101)."""

REFRESH_TOKEN_KEY = "refresh_token_key"
"""Feld in token.json: Schlüssel des Eintrags im Schlüsselbund. In der Datei
statt aus dem Pfad abgeleitet — ein verschobener Datenordner (Junction,
8.3-Name, Backup) behält so seinen Token."""


class TokenKeyringUnavailable(Exception):
    """Der Refresh-Token liegt im Schlüsselbund, der aber nicht antwortet.

    Kein Auth-Fehler: der Token ist nicht ungültig, nur gerade nicht lesbar.
    Aufrufer starten deshalb KEINEN Consent-Flow (Xveyn#129) und fassen
    token.json nicht an."""

    def __init__(self) -> None:
        super().__init__(KEYRING_UNAVAILABLE_MSG)


KEYRING_UNAVAILABLE_TITLE = "Schlüsselbund nicht erreichbar"
KEYRING_UNAVAILABLE_HINT = (
    "Die Google-Anmeldung liegt im Schlüsselbund des Betriebssystems, und der "
    "antwortet gerade nicht (gesperrt oder nicht gestartet).\n\nBitte "
    "entsperre ihn und versuche es erneut.")
"""Titel und Text der themed Meldung für `TokenKeyringUnavailable` — ein
bekannter Fehler, also kurz und ohne Traceback (Konvention „bekannt-themed /
unerwartet-nativ"). Eine Quelle für Sync-Meldungen und Einstellungsdialog."""


def is_keyring_unavailable(error: object) -> bool:
    """Ist `error` (Exception oder deren Text) der Schlüsselbund-Ausfall?

    Auch am Text erkennbar, weil die Kompaktierung und Sync-Flows Fehler nur
    als `str(e)` weiterreichen."""
    return (isinstance(error, TokenKeyringUnavailable)
            or (error is not None and KEYRING_UNAVAILABLE_MSG in str(error)))


def new_token_keyring_key() -> str:
    """Neuer, eindeutiger Schlüssel für den Refresh-Token. Eindeutig statt
    fest: zwei Datenverzeichnisse desselben OS-Nutzers (Dev-Instanz neben
    der Installation) dürfen sich keinen Eintrag teilen."""
    return f"google-oauth:{uuid.uuid4().hex}"


def read_token_meta(token_path: str) -> dict[str, Any] | None:
    """Inhalt von token.json als Dict, oder None (fehlt/unlesbar/kein Dict)."""
    try:
        with open(token_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def token_in_keyring(meta: dict[str, Any] | None) -> bool:
    """Liegt der Refresh-Token laut `meta` im Schlüsselbund?"""
    return isinstance(meta, dict) and meta.get(REFRESH_TOKEN_LOCATION) == "keyring"


def forget_token(token_path: str) -> None:
    """Löscht token.json und — sobald die Datei einen `refresh_token_key`
    trägt — den Eintrag im Schlüsselbund. Ohne das zweite blieben nach
    „Google neu verbinden" oder einem Scope-Upgrade verwaiste Einträge stehen.

    Maßgeblich ist der Schlüssel, nicht `refresh_token_location`: nach einem
    Datei-Fallback (`token_store.save_credentials`, Schlüsselbund fiel beim
    Schreiben aus) steht der Token wieder in der Datei, unter dem Schlüssel
    liegt aber noch der alte Eintrag. Der Schlüssel ist eine App-eigene uuid —
    nur diese App schreibt ihn.

    Der Eintrag geht auch dann, wenn die Datei sich nicht löschen lässt
    (gesperrt): sie zeigt danach auf einen fehlenden Eintrag, was
    `token_store.load_credentials` als „neu anmelden" liest — genau das,
    was beide Aufrufer ohnehin wollen. Der Löschfehler selbst wird
    weitergereicht."""
    with TOKEN_LOCK:
        meta = read_token_meta(token_path)
        key = meta.get(REFRESH_TOKEN_KEY) if meta is not None else None
        try:
            os.remove(token_path)
        except FileNotFoundError:
            pass
        finally:
            if isinstance(key, str) and key:
                keyring_store.remove(key)


def token_lacks_scopes(token_path: str, scopes: Collection[str]) -> bool:
    """True, wenn `token.json` lesbar ist und nicht alle `scopes` gewährt.

    Bei Lesefehlern (kein/defektes JSON) konservativ `False`: ein womöglich
    gültiger Token gilt nicht als unzureichend."""
    granted = read_granted_scopes(token_path)
    if granted is None:
        return False
    return not set(scopes).issubset(set(granted))


def discard_token_for_scope_upgrade(token_path: str,
                                    scopes: Collection[str]) -> bool:
    """Erzwinge einen frischen OAuth-Flow, wenn der gespeicherte Token nicht
    alle angeforderten `scopes` abdeckt (typisch nach einem Feature-Update).

    Deckt der Token die Scopes nicht ab, wird die Token-Datei gelöscht und
    `True` geliefert — die aufrufende Seite setzt dann `creds = None` und
    durchläuft den vollen Consent. Andernfalls `False`.

    Nur aufrufen, wenn der Consent **unmittelbar** folgt: ohne ihn bliebe gar
    kein Token zurück (Xveyn#129). Nicht-interaktive Pfade fragen
    `token_lacks_scopes` und melden den Auth-Fall.

    Bei Lesefehlern (kein/defektes JSON) konservativ `False`: der Token bleibt
    unangetastet, statt einen womöglich gültigen Token wegzuwerfen. Spiegelt
    das frühere `except Exception: pass` in den Wrappern.
    """
    if not token_lacks_scopes(token_path, scopes):
        return False

    try:
        forget_token(token_path)
    except OSError:
        # Wie zuvor: ein Löschfehler (gesperrte Datei) darf den Consent, der
        # unmittelbar folgt, nicht verhindern — der schreibt token.json neu.
        log.debug("token.json ließ sich nicht löschen", exc_info=True)
    return True
