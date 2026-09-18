"""OAuth-Credentials laden und speichern — Refresh-Token im Schlüsselbund (#101).

Einzige Stelle, die OAuth-Credentials lädt und speichert. token.json bleibt
bestehen und behält alles außer dem Refresh-Token (Access-Token, Scopes,
Client, Ablauf): die rund zehn Datei-Prüfungen der App (existiert? welche
Scopes? mtime-Poll im Google-Tab) laufen unverändert weiter.

**Speichern behält den Ort bei.** Eine token.json im Datei-Modus bleibt eine
Datei; in den Schlüsselbund kommt der Token nur, wenn er schon dort liegt
oder es noch keine Datei gibt (frische Anmeldung). Umziehen darf allein
`secret_migration` — mit Zurücklesen und Hinweis.

Nur der Refresh-Token, weil der Windows Credential Manager höchstens 1280
Zeichen (UTF-16) fasst, Google Access-Tokens aber bis 2048 Byte reserviert
(Spec, R1). Tk-frei; die Credentials-Klasse kommt vom Aufrufer, damit dessen
lazy/optional gebundene Klasse und die Test-Patches daran greifen.
"""

from __future__ import annotations

import json
import os
import threading
from typing import Any

from src import keyring_store
from src.oauth_utils import (
    REFRESH_TOKEN_KEY, REFRESH_TOKEN_LOCATION, TokenKeyringUnavailable,
    new_token_keyring_key, read_token_meta, token_in_keyring, write_token,
    write_token_json,
)

# Speichern und Umzug sind Lesen-Prüfen-Schreiben an token.json; beim Start
# erneuern Refresh, Absender-Abruf, Sync-Pull und Kalender-Abgleich parallel.
TOKEN_LOCK = threading.RLock()


def load_credentials(token_path: str, scopes: list[str],
                     credentials_cls: Any) -> Any | None:
    """Lädt die Credentials aus token.json (+ Schlüsselbund).

    - Alt-Format / Datei-Modus / unlesbar: exakt wie bisher
      `credentials_cls.from_authorized_user_file`.
    - Schlüsselbund-Modus: Refresh-Token einsetzen, dann
      `from_authorized_user_info`.
      - Schlüsselbund antwortet nicht → `TokenKeyringUnavailable` (Datei
        unangetastet, kein Consent — Xveyn#129).
      - Eintrag oder Schlüssel fehlt → `None`; der Aufrufer behandelt das wie
        „kein Token" (vorab geprüft: google-auth würfe sonst `ValueError`
        „missing fields refresh_token", Spec R3).
    """
    meta = read_token_meta(token_path)
    if meta is None or not token_in_keyring(meta):
        return credentials_cls.from_authorized_user_file(token_path, scopes)
    key = meta.get(REFRESH_TOKEN_KEY)
    if not isinstance(key, str) or not key:
        return None
    refresh = keyring_store.fetch(key)
    if refresh is None:
        raise TokenKeyringUnavailable()
    if not refresh:
        return None
    info = dict(meta)
    info.pop(REFRESH_TOKEN_LOCATION, None)
    info.pop(REFRESH_TOKEN_KEY, None)
    info["refresh_token"] = refresh
    return credentials_cls.from_authorized_user_info(info, scopes)


def save_credentials(creds: Any, token_path: str) -> None:
    """Speichert die Credentials am bisherigen Ort (s. Modul-Docstring)."""
    with TOKEN_LOCK:
        exists = os.path.exists(token_path)
        meta = read_token_meta(token_path) if exists else None
        refresh = getattr(creds, "refresh_token", None)
        if ((exists and not token_in_keyring(meta))
                or not (isinstance(refresh, str) and refresh)):
            # Datei-Modus (Ort beibehalten) oder nichts für den Schlüsselbund
            # (MagicMock-/Fake-Creds in Tests, Flow ohne Refresh-Token).
            write_token(creds, token_path)
            return
        key = meta.get(REFRESH_TOKEN_KEY) if meta is not None else None
        if not isinstance(key, str) or not key:
            key = new_token_keyring_key()
        if keyring_store.put(key, refresh):
            data = json.loads(creds.to_json(strip=["refresh_token"]))
            data[REFRESH_TOKEN_LOCATION] = "keyring"
            data[REFRESH_TOKEN_KEY] = key
            write_token_json(json.dumps(data), token_path)
            return
        # Schlüsselbund fällt aus: vollständig in die Datei — ein (rotierter)
        # Refresh-Token geht nie verloren; der nächste Start zieht ihn um.
        write_token(creds, token_path)
