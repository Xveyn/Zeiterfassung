# src/secure_file.py
"""Zugriffsschutz für lokal abgelegte Secrets (Audit M8).

Die App schreibt fünf sensible Dateien neben die Nutzerdaten: `token.json`
(OAuth-Refresh-Token, `oauth_utils.write_token`), `instance-secret`
(Shared Secret des Single-Instance-Handshakes, `single_instance`),
`webhooks.json` (Webhook-Konfiguration inkl. Auth-Token/HMAC-Secrets,
`webhook_store`), `smtp.json` (SMTP-Kontokonfiguration inkl. Passwort im
Datei-Fallback ohne Schlüsselbund, `smtp_store`) und `api-token` (Bearer-Token
der lokalen HTTP-API, `api_auth`). Alle fünf werden atomar
über Temp-Datei + `os.replace` geschrieben und mit `chmod 0600` abgesichert —
unter Windows ist das chmod allerdings ein No-op.

Dieses Modul liefert das Windows-Gegenstück. Es ist bewusst ein eigenes,
stdlib-only Modul und hängt an keinem der Aufrufer: `oauth_utils`,
`single_instance`, `webhook_store` und `smtp_store` sollen nichts
voneinander importieren müssen, und private Namen modulübergreifend zu
nutzen ist im Projekt ausdrücklich unerwünscht (Audit N17).
"""

from __future__ import annotations

import json
import logging
import os
import platform
import stat
import subprocess
import tempfile
import time
from typing import Any

_log = logging.getLogger(__name__)


def _windows_principal() -> str | None:
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


def harden_windows_acl(path: str) -> None:
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


def write_secret_json(path: str, obj: Any, *, prefix: str) -> None:
    """Schreibt `obj` als JSON atomar und gehärtet (#249): Temp-Datei im Zielordner →
    `flush` + `fsync` → `chmod 0600` → `harden_windows_acl` (Windows) → `os.replace`.

    Derselbe Ablauf wie `smtp_store._save_to_disk` und `oauth_utils.write_token`; chmod und
    icacls laufen auf der **Temp-Datei**, damit die Datei nie kurz mit geerbten Rechten am
    Zielpfad liegt. Der Rename wird bei `PermissionError` fünfmal wiederholt (ein Virenscanner
    auf der frisch ge-ACLten Datei, #135/#117). Bei **jedem** Fehler — auch schon im
    `json.dump` — wird die Temp-Datei entfernt und der Fehler weitergereicht; die alte Datei
    bleibt unberührt."""
    directory = os.path.dirname(os.path.abspath(path))
    fd, tmp_path = tempfile.mkstemp(dir=directory, prefix=prefix, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(obj, handle, indent=2, ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.chmod(tmp_path, stat.S_IRUSR | stat.S_IWUSR)         # 0o600
        except OSError:
            _log.debug("chmod 0600 nicht möglich (%s)", tmp_path, exc_info=True)
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
            _log.debug("Temp-Datei nicht entfernbar (%s)", tmp_path, exc_info=True)
        raise
