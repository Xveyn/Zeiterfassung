"""Webhook-Secrets im Schlüsselbund (#101) — das SMTP-Muster für webhooks.json.

`auth.value` (Token im Header) bzw. `auth.secret` (HMAC) wandern in den
Schlüsselbund; im Datensatz bleibt `auth.secret_location = "keyring"`. Fehlt
das Feld (Alt-Format), steht das Secret wie bisher im Klartext im Datensatz.

`webhook_store` bleibt reine Dateipersistenz und fasst den Schlüsselbund
nicht an — dieselbe Trennung wie `smtp_store`/`keyring_store`. Alles hier
kann blockieren (Schlüsselbund-Watchdog) und läuft deshalb im Worker.
"""

from __future__ import annotations

import copy
from typing import Any

from src import keyring_store

SECRET_LOCATION = "secret_location"

_FIELDS = {"header": "value", "hmac": "secret"}


def secret_field(record: dict[str, Any]) -> str | None:
    """Das Secret-Feld des Auth-Verfahrens, oder None (`none`)."""
    return _FIELDS.get((record.get("auth") or {}).get("mode", "none"))


def keyring_key(webhook_id: str) -> str:
    """Schlüssel im Schlüsselbund (Service über keyring_store.service_for)."""
    return f"webhook:{webhook_id}"


def in_keyring(record: dict[str, Any]) -> bool:
    return (record.get("auth") or {}).get(SECRET_LOCATION) == "keyring"


def plaintext_secret(record: dict[str, Any]) -> str:
    """Das im Datensatz stehende Secret, oder "" (keins/im Schlüsselbund)."""
    field = secret_field(record)
    if field is None or in_keyring(record):
        return ""
    return str((record.get("auth") or {}).get(field) or "")


def stored_in_keyring(record: dict[str, Any]) -> dict[str, Any]:
    """Kopie in Schlüsselbund-Form: ohne Secret-Feld, mit Ort-Markierung."""
    out = copy.deepcopy(record)
    auth = out.setdefault("auth", {})
    field = secret_field(out)
    if field is not None:
        auth.pop(field, None)
    auth[SECRET_LOCATION] = "keyring"
    return out


def resolve(record: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    """Datensatz fürs Senden, Secret eingesetzt.

    `(record, None)` sendefertig (Alt-Format unverändert); `(None,
    "unavailable")` Schlüsselbund antwortet nicht; `(None, "missing")`
    Eintrag fehlt. Nie ohne Secret senden: der Endpunkt antwortete 401, und
    der Nutzer suchte beim Token, obwohl der Schlüsselbund das Problem war.
    """
    field = secret_field(record)
    if field is None or not in_keyring(record):
        return record, None
    value = keyring_store.fetch(keyring_key(record["id"]))
    if value is None:
        return None, "unavailable"
    if not value:
        return None, "missing"
    out = copy.deepcopy(record)
    out["auth"].pop(SECRET_LOCATION, None)
    out["auth"][field] = value
    return out, None


def persist(candidate: dict[str, Any], typed: str,
            stored: dict[str, Any] | None) -> tuple[dict[str, Any], str | None]:
    """Entscheidet, wo das Secret landet, legt es ab und liefert
    `(zu_speichernder_datensatz, abzuräumender_schlüssel)`.

    Abgeräumt wird NICHT hier, sondern vom Aufrufer NACH `store.save` —
    scheiterte das Schreiben, zeigte der Datensatz sonst auf einen gelöschten
    Eintrag (dieselbe Regel wie `remove_record`).

    - Verfahren ohne Secret (`none`): Datensatz ohne Secret; ein altes
      Schlüsselbund-Secret ist abzuräumen.
    - `typed` mit Inhalt: in den Schlüsselbund; klappt das nicht, in den
      Datensatz (Alt-Format), und ein älterer Schlüsselbund-Eintrag ist
      abzuräumen (sonst zweite, veraltete Quelle).
    - `typed` leer oder nur Leerzeichen: unverändert (Dialog: „leer lassen =
      unverändert"). Verändert `candidate` nicht.
    """
    stale = keyring_key(candidate["id"]) if stored is not None and in_keyring(stored) else None
    field = secret_field(candidate)
    if field is None:
        out = copy.deepcopy(candidate)
        out.get("auth", {}).pop(SECRET_LOCATION, None)
        return out, stale
    if typed.strip():
        with_secret = copy.deepcopy(candidate)
        with_secret["auth"][field] = typed
        with_secret["auth"].pop(SECRET_LOCATION, None)
        if keyring_store.put(keyring_key(candidate["id"]), typed):
            return stored_in_keyring(with_secret), None
        return with_secret, stale
    return copy.deepcopy(candidate), None


def forget_by_id(webhook_id: str) -> None:
    """Nach dem Löschen eines Webhooks den Eintrag abräumen (wie
    `tab_smtp._delete_secret` — ein fehlender Eintrag ist kein Fehler)."""
    keyring_store.remove(keyring_key(webhook_id))


def keyring_failure(problem: str) -> dict[str, Any]:
    """Ergebnis-Dict eines Webhook-Kanals, dessen Secret nicht lesbar war."""
    if problem == "unavailable":
        return {"ok": False, "kind": "keyring", "error": None, "tb": None,
                "detail": "Die Zugangsdaten konnten nicht aus dem "
                          "Schlüsselbund gelesen werden."}
    return {"ok": False, "kind": "keyring_missing", "error": None, "tb": None,
            "detail": "Webhook bearbeiten und die Zugangsdaten neu eingeben."}
