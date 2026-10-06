# src/api_auth.py
"""Authentifizierung der lokalen HTTP-API (#92, Stufe 1). Tk-frei, ohne Socket.

Dieses Modul kennt weder Server noch Routen: es erzeugt und speichert das
Token (Datei `api-token`, gehärtet wie `instance-secret`) und beantwortet
EINE Frage — darf diese Anfrage (Methode + Header) durch? `authorize` ist
die einzige Stelle dafür, damit später genau eine Stelle aufgeht (LAN,
mobile Tokens, #221).

Fail-closed: lässt sich das Token nicht lesen oder schreiben, gibt es keins,
und die API bleibt aus. Anders als `single_instance` (dort läuft der Handshake
im Zweifel unauthentifiziert weiter) wäre ein offener Schreibzugang auf
Arbeitszeitdaten der falsche Fallback.
"""
from __future__ import annotations

import logging
import os
import re
import secrets
import stat
import tempfile
import time

from src.secure_file import harden_windows_acl

_log = logging.getLogger(__name__)

TOKEN_FILENAME = "api-token"
_TOKEN_BYTES = 32
# token_urlsafe(32) liefert 43 Zeichen; großzügige Spanne für Handarbeit.
_TOKEN_RE = re.compile(r"[A-Za-z0-9_-]{32,128}")
_MAX_FILE_BYTES = 1024


def generate_token() -> str:
    return secrets.token_urlsafe(_TOKEN_BYTES)


def _write_token_atomic(path: str, token: str) -> None:
    """Schreibt das Token atomar (Temp + os.replace) mit 0600 und
    PermissionError-Retry — dasselbe Muster wie `single_instance.
    _write_secret_atomic` (Issue #135, Audit M8).

    Gehärtet wird die Temp-Datei, bevor `os.replace` sie unter dem Zielnamen
    sichtbar macht; unter Windows ist das chmod ein No-op, dort greift die
    ACL (`secure_file`). Das Präfix `.api-token-` erwartet
    `removal._credential_paths` für liegengebliebene Temp-Dateien."""
    directory = os.path.dirname(os.path.abspath(path))
    fd, tmp_path = tempfile.mkstemp(
        dir=directory, prefix=f".{TOKEN_FILENAME}-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="ascii") as f:
            f.write(token)
        try:
            os.chmod(tmp_path, stat.S_IRUSR | stat.S_IWUSR)  # 0o600; Win: No-op
        except OSError:
            _log.debug("chmod 0600 auf %s fehlgeschlagen", tmp_path, exc_info=True)
        harden_windows_acl(tmp_path)
        attempts = 5
        for attempt in range(attempts):
            try:
                os.replace(tmp_path, path)
                break
            except PermissionError:
                if attempt == attempts - 1:
                    raise
                time.sleep(0.2)
    except BaseException:
        try:
            os.remove(tmp_path)
        except OSError:
            _log.debug("Temp-Datei %s nicht entfernbar", tmp_path, exc_info=True)
        raise


def load_or_create_token(base_path: str) -> str | None:
    """Lädt das Token aus `<base_path>/api-token` oder erzeugt es.

    `None` heißt: kein Token, die API bleibt aus. Das gilt, wenn die Datei
    nicht lesbar ist (sie wird dann NICHT überschrieben — es könnte das Token
    sein, das ein Client gerade benutzt) oder das Schreiben scheitert.
    Eine vorhandene, aber ungültige Datei (leer, abgeschnitten, Müll) wird
    durch ein frisches Token ersetzt; ein Zeilenumbruch am Ende wird
    toleriert (Hand-Bearbeitung, Kopieren)."""
    path = os.path.join(base_path, TOKEN_FILENAME)
    try:
        with open(path, "rb") as f:
            data = f.read(_MAX_FILE_BYTES + 1)
    except FileNotFoundError:
        data = None
    except OSError:
        _log.warning("API-Token nicht lesbar — API bleibt aus", exc_info=True)
        return None
    if data is not None:
        candidate = data.strip().decode("ascii", errors="replace")
        if len(data) <= _MAX_FILE_BYTES and _TOKEN_RE.fullmatch(candidate):
            return candidate
        _log.warning("API-Token-Datei ungültig — wird neu erzeugt")
    token = generate_token()
    try:
        _write_token_atomic(path, token)
    except OSError:
        _log.warning("API-Token nicht schreibbar — API bleibt aus", exc_info=True)
        return None
    return token


def rotate_token(base_path: str) -> str:
    """Ersetzt das Token durch ein neues (Settings-Tab „Token neu erzeugen").
    Wirft `OSError`, wenn das Schreiben scheitert — der Aufrufer zeigt das an;
    das alte Token bleibt dann gültig."""
    token = generate_token()
    _write_token_atomic(os.path.join(base_path, TOKEN_FILENAME), token)
    return token
