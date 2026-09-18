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
from typing import Any

from src import keyring_store
from src.oauth_utils import (
    REFRESH_TOKEN_KEY, REFRESH_TOKEN_LOCATION, TOKEN_LOCK,
    TokenKeyringUnavailable, new_token_keyring_key, read_token_meta,
    token_in_keyring, write_token, write_token_json,
)

# Speichern und Umzug sind Lesen-Prüfen-Schreiben an token.json. Der Lock
# liegt in `oauth_utils` (auch `forget_token` nimmt ihn) und wird hier für die
# bisherigen Importeure (`secret_migration`) re-exportiert.
__all__ = ["TOKEN_LOCK", "load_credentials", "save_credentials"]


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

    Bewusst ohne `TOKEN_LOCK` (alle Schreiber tauschen die Datei atomar). Zieht
    der Umzug zwischen `read_token_meta` und `from_authorized_user_file` um,
    fehlt der Datei plötzlich `refresh_token` → `ValueError`. Dann genau einmal
    neu lesen: steht sie jetzt im Schlüsselbund-Modus, von dort laden, sonst
    den Fehler weiterreichen.
    """
    meta = read_token_meta(token_path)
    if meta is None or not token_in_keyring(meta):
        try:
            return credentials_cls.from_authorized_user_file(token_path, scopes)
        except ValueError:
            meta = read_token_meta(token_path)
            if meta is None or not token_in_keyring(meta):
                raise
    return _load_from_keyring(meta, scopes, credentials_cls)


def _load_from_keyring(meta: dict[str, Any], scopes: list[str],
                       credentials_cls: Any) -> Any | None:
    """Schlüsselbund-Zweig von `load_credentials` (s. dort)."""
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
        key = meta.get(REFRESH_TOKEN_KEY) if meta is not None else None
        if not isinstance(key, str) or not key:
            key = None
        if exists and not token_in_keyring(meta):
            # Datei-Modus: Ort beibehalten — und einen bekannten Schlüssel
            # (aus einem früheren Datei-Fallback) mit.
            _write_file_mode(creds, key, token_path)
            return
        refresh = getattr(creds, "refresh_token", None)
        if not (isinstance(refresh, str) and refresh):
            if key is not None:
                # Schlüsselbund-Modus ohne neuen Refresh-Token: der dort
                # liegende bleibt gültig. Ohne Markierung fehlte der Datei
                # sonst `refresh_token`, und das nächste Laden bräche ab.
                _write_keyring_mode(creds.to_json(), key, token_path)
                return
            # Nichts für den Schlüsselbund (MagicMock-/Fake-Creds in Tests,
            # Flow ohne Refresh-Token).
            write_token(creds, token_path)
            return
        meta_key = key
        key = key or new_token_keyring_key()
        if keyring_store.put(key, refresh):
            _write_keyring_mode(creds.to_json(strip=["refresh_token"]), key, token_path)
            return
        # Schlüsselbund fällt aus: vollständig in die Datei — ein (rotierter)
        # Refresh-Token geht nie verloren; der nächste Start zieht ihn um.
        # Der Schlüssel bleibt stehen, sofern die Datei schon einen hatte:
        # unter ihm liegt womöglich noch der alte Eintrag, und nur so finden
        # ihn Umzug (derselbe Eintrag statt eines neuen), `forget_token` und
        # der Uninstaller. Ein frisch erzeugter Schlüssel kommt dagegen nicht
        # in die Datei — ohne Schlüsselbund bleibt sie byte-gleich zu vorher.
        _write_file_mode(creds, meta_key, token_path)


def _write_file_mode(creds: Any, key: str | None, token_path: str) -> None:
    """Schreibt token.json im Datei-Modus. Ohne Schlüssel exakt
    `write_token` (byte-gleich zum Verhalten vor #101); mit Schlüssel
    zusätzlich `refresh_token_key`, aber ohne Markierung — der Refresh-Token
    steht in der Datei, geladen wird wie bisher (google-auth ignoriert das
    Feld)."""
    if key is None:
        write_token(creds, token_path)
        return
    data = json.loads(creds.to_json())
    data[REFRESH_TOKEN_KEY] = key
    write_token_json(json.dumps(data), token_path)


def _write_keyring_mode(json_text: str, key: str, token_path: str) -> None:
    """Schreibt token.json im Schlüsselbund-Modus: ohne Refresh-Token, mit
    Markierung und Schlüssel."""
    data = json.loads(json_text)
    data.pop("refresh_token", None)
    data[REFRESH_TOKEN_LOCATION] = "keyring"
    data[REFRESH_TOKEN_KEY] = key
    write_token_json(json.dumps(data), token_path)
