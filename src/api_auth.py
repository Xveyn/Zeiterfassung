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

import hmac
import logging
import os
import re
import secrets
import stat
import tempfile
import time
from dataclasses import dataclass
from typing import Callable, Mapping

from src.secure_file import harden_windows_acl

_log = logging.getLogger(__name__)

TOKEN_FILENAME = "api-token"
_TOKEN_BYTES = 32
# token_urlsafe(32) liefert genau 43 Zeichen. Alles andere ist kein Token dieser
# App (leer, abgeschnitten, von Hand gesetzt) und wird ersetzt: ein kürzerer,
# selbst gewählter Wert wäre kein 256-Bit-Geheimnis mehr.
_TOKEN_RE = re.compile(r"[A-Za-z0-9_-]{43}")
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


def _harden_existing(path: str) -> None:
    """Zieht eine vorhandene Token-Datei auf Besitzer-only nach (0600, unter
    Windows die ACL). Eine von Hand angelegte oder kopierte Datei trägt sonst
    die Rechte ihres Erzeugers (typisch 0644) — und der Loopback-Port steht
    jedem lokalen Nutzer offen. Best-effort wie `secure_file`: scheitert das
    (fremder Besitzer), ist der Zustand der von vorher, nie ein Startabbruch."""
    try:
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        _log.debug("chmod 0600 auf %s fehlgeschlagen", path, exc_info=True)
    harden_windows_acl(path)


def load_or_create_token(base_path: str) -> str | None:
    """Lädt das Token aus `<base_path>/api-token` oder erzeugt es.

    **Blockiert** (Windows: `icacls`-Subprozess bis 15 s, dazu der Retry von
    `os.replace`) — nie im UI-Thread aufrufen, nur über
    `BackgroundTaskRunner.run`.

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
            _harden_existing(path)
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
    das alte Token bleibt dann gültig.

    **Blockiert** wie `load_or_create_token` — nur über
    `BackgroundTaskRunner.run`, nie im UI-Thread."""
    token = generate_token()
    _write_token_atomic(os.path.join(base_path, TOKEN_FILENAME), token)
    return token


SCOPE_LOCAL = "local"
ALLOWED_METHODS = frozenset({"GET", "PUT", "POST", "DELETE"})
_BODY_METHODS = frozenset({"POST", "PUT"})   # tragen einen Body → JSON Pflicht
_MAX_BEARER_LEN = 512


@dataclass(frozen=True)
class Principal:
    """Wer da anfragt und was er darf. Stufe 1 kennt nur `local`; #221
    ergänzt `mobile-sync` mit eingeschränkten Routen."""
    name: str
    scopes: frozenset[str]


TokenVerifier = Callable[[str], "Principal | None"]


def single_token_verifier(token: str) -> TokenVerifier:
    """Prüfer für das eine Stufe-1-Token. #221 liefert einen Prüfer über
    gespeicherte Geräte-Token-Hashes — `authorize` merkt den Unterschied nicht."""
    if not token:
        raise ValueError("leeres Token: der Prüfer würde jeden leeren Wert zulassen")
    expected = token.encode("utf-8")
    principal = Principal("local", frozenset({SCOPE_LOCAL}))

    def verify(candidate: str) -> Principal | None:
        # errors="replace": Zeichen außerhalb von UTF-8 (lone surrogates) dürfen
        # hier nicht werfen; das Token-Alphabet enthält kein "?".
        if hmac.compare_digest(candidate.encode("utf-8", errors="replace"), expected):
            return principal
        return None

    return verify


@dataclass(frozen=True)
class Policy:
    """Was `authorize` zulässt. Stufe 1: nur Loopback, keine Browser-Origin.
    #221 füllt `allowed_hosts`/`allowed_origins` und setzt `bind_host`."""
    allowed_hosts: frozenset[str]
    allowed_origins: frozenset[str] = frozenset()
    bind_host: str = "127.0.0.1"

    @classmethod
    def loopback(cls, port: int) -> Policy:
        return cls(allowed_hosts=frozenset({f"127.0.0.1:{port}", f"localhost:{port}"}))


@dataclass(frozen=True)
class AuthResult:
    status: int
    code: str
    principal: Principal | None = None

    @property
    def ok(self) -> bool:
        return self.status == 200


def _bearer_principal(value: str | None, verifier: TokenVerifier) -> Principal | None:
    if not value:
        return None
    scheme, _, token = value.strip().partition(" ")
    token = token.strip()
    if scheme.lower() != "bearer" or not token or len(token) > _MAX_BEARER_LEN:
        return None
    return verifier(token)


def _is_json(content_type: str | None) -> bool:
    if not content_type:
        return False
    return content_type.split(";", 1)[0].strip().lower() == "application/json"


def authorize(method: str, headers: Mapping[str, str], policy: Policy,
              verifier: TokenVerifier) -> AuthResult:
    """Die vier Tore, in dieser Reihenfolge — ein Browser-Angriff scheitert
    an Host/Origin/Sec-Fetch-Site, bevor der Token überhaupt verglichen wird,
    und ein unauthentifizierter Aufrufer erfährt nichts über Content-Types.

    `headers` darf beliebige Schreibweise der Namen haben. Doppelte Host-/
    Authorization-Header kann ein Mapping nicht darstellen; die Server-Schicht
    lehnt sie vorher ab.

    `Sec-Fetch-Site` hilft nur auf Loopback: über `http://<LAN-IP>` sendet
    Chrome es nicht (Spike #221). Es ist ein zweiter Marker, nie der
    tragende Schutz — Origin und Token tragen."""
    method = method.upper()
    if method not in ALLOWED_METHODS:
        return AuthResult(405, "method_not_allowed")
    h = {name.lower(): value for name, value in headers.items()}
    if h.get("host", "").strip().lower() not in policy.allowed_hosts:
        return AuthResult(403, "bad_host")
    origin = h.get("origin")
    if origin is not None and origin not in policy.allowed_origins:
        return AuthResult(403, "bad_origin")
    if "sec-fetch-site" in h:
        return AuthResult(403, "browser_request")
    principal = _bearer_principal(h.get("authorization"), verifier)
    if principal is None:
        return AuthResult(401, "unauthorized")
    if method in _BODY_METHODS and not _is_json(h.get("content-type")):
        return AuthResult(415, "unsupported_media_type")
    return AuthResult(200, "ok", principal)


def require_scope(principal: Principal, scope: str) -> AuthResult:
    """Scope-Prüfung pro Route (nach dem Routing, das die Server-Schicht macht)."""
    if scope in principal.scopes:
        return AuthResult(200, "ok", principal)
    return AuthResult(403, "insufficient_scope")
