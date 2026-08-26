# Webhook-Versand Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Der Zeiterfassungs-Bericht kann zusätzlich zur Gmail-Zustellung an mehrere benannte HTTP-Endpunkte gepostet werden — als JSON, als PDF oder beides, wahlweise ohne Auth, mit Header-Token oder HMAC-signiert.

**Architecture:** Der bestehende Gmail-Pfad bleibt inhaltlich unverändert und bekommt einen Dispatcher davor: `send_task.perform_send` baut die Payloads einmal, feuert jeden Kanal unabhängig und sammelt ein Ergebnis pro Kanal. Die gesamte Webhook-Logik liegt Tk-frei in `src/webhook.py` (pure) und `src/webhooks.py` (Store), damit sie testbar ist; Tk-Code kommt nur in Sende-Dialog, Webhook-Dialog und Settings-Tab hinzu.

**Tech Stack:** Python 3.10+, ausschließlich stdlib (`urllib`, `hmac`, `hashlib`, `ipaddress`, `uuid`, `json`, `tempfile`), Tkinter, pytest.

**Spec:** [`docs/superpowers/specs/2026-08-26-webhook-versand-design.md`](../specs/2026-08-26-webhook-versand-design.md)

## Global Constraints

Diese Regeln gelten für **jede** Aufgabe unten und werden dort nicht wiederholt.

- **Keine neue Dependency.** `requirements.txt` und `requirements-test.txt` bleiben unangetastet. Alles Nötige ist stdlib. Grund: die Test-CI installiert `requirements.txt` bewusst nicht.
- **Python 3.10 ist die Untergrenze.** Die CI-Matrix läuft 3.10–3.13; kein `match`, kein `X | Y` in `isinstance`, keine 3.11+-stdlib-API.
- **Logik Tk-frei.** `src/webhook.py` und `src/webhooks.py` importieren **kein** `tkinter`. Tests gibt es nur für diese Module — Dialog-, Tab- und Widget-Code wird nicht automatisiert getestet (`docs/known-limitations.md`, entschiedene Scope-Grenze).
- **Alle UI-Texte auf Deutsch.**
- **Datumsformat:** intern ISO (`YYYY-MM-DD`), in der UI deutsch über `time_utils.format_iso_date`.
- **Summen über Minuten**, nie über Dezimalstunden (`CLAUDE.md`, Abschnitt „Stunden").
- **Fehlerdialoge:** kuratierte Meldungen über `theme.themed_showerror`/`themed_showinfo`, Traceback-Ausgabe über rohes `tkinter.messagebox.showerror`.
- **Secrets:** Jeder Schreibvorgang auf `webhooks.json` läuft Temp-Datei → `chmod 0600` → `secure_file.harden_windows_acl` → `os.replace`, und zwar in dieser Reihenfolge, mit der Härtung auf der **Temp-Datei**.
- **Kein Webhook-Key in `SYNCED_SETTING_KEYS`.** Webhooks sind gerätelokal und tauchen im Sync-Doc nicht auf.
- **Vor jedem Commit:** `pytest`, `ruff check .` und `pyright` müssen grün sein.
- **Commit-Messages** ohne `&&`-Verkettung ausführen (PowerShell 5.1); mehrzeilige Messages über `git commit -F <datei>`.

---

### Task 1: URL-Regel — https außerhalb, http innerhalb

Entscheidet allein anhand der Adresse in der URL, ob unverschlüsseltes HTTP erlaubt ist. Keine DNS-Auflösung: die müsste online sein, wäre langsam und könnte später still anders ausgehen.

**Files:**
- Create: `src/webhook.py`
- Test: `tests/test_webhook.py`

**Interfaces:**
- Consumes: nichts
- Produces:
  - `is_private_host(host: str) -> bool`
  - `validate_url(url: str) -> tuple[bool, str]` — `(True, "")` oder `(False, "<deutsche Begründung>")`

- [ ] **Step 1: Write the failing test**

`tests/test_webhook.py`:

```python
"""Pure Webhook-Logik: URL-Regel, Auth, Payload, Transport, Fehler-Mapping."""

import pytest

from src.webhook import is_private_host, validate_url


@pytest.mark.parametrize("host", [
    "localhost", "127.0.0.1", "127.1.2.3", "::1",
    "10.0.0.5", "172.16.0.1", "172.31.255.254", "192.168.1.10",
    "100.64.0.1",                      # CGNAT (Tailscale u.ä.)
    "169.254.1.1", "fe80::1",          # Link-Local
    "fd00::1",                         # IPv6 ULA
    "nas.local", "server.lan", "printer.home.arpa", "api.internal",
    "nas",                             # Single-Label, nur lokal auflösbar
])
def test_private_hosts(host):
    assert is_private_host(host) is True


@pytest.mark.parametrize("host", [
    "example.com", "erp.example.com",
    "8.8.8.8",
    "172.32.0.1",                      # knapp außerhalb von 172.16/12
    "2606:4700::1111",
])
def test_public_hosts(host):
    assert is_private_host(host) is False


def test_http_allowed_inside_local_network():
    assert validate_url("http://192.168.1.10:5678/hook") == (True, "")


def test_http_rejected_for_public_host():
    ok, msg = validate_url("http://erp.example.com/hook")
    assert ok is False
    assert "https" in msg


def test_https_always_allowed():
    assert validate_url("https://erp.example.com/hook") == (True, "")


def test_unsupported_scheme_rejected():
    ok, msg = validate_url("ftp://example.com/x")
    assert ok is False
    assert msg


def test_missing_host_rejected():
    ok, msg = validate_url("https:///hook")
    assert ok is False
    assert msg


def test_ipv6_url_brackets_are_handled():
    assert validate_url("http://[::1]:8080/hook") == (True, "")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_webhook.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.webhook'`

- [ ] **Step 3: Write minimal implementation**

`src/webhook.py`:

```python
"""Pure Logik des Webhook-Versands (Tk-frei, stdlib-only).

Kein tkinter, keine Google-Imports, keine dritte Dependency — dieses Modul
ist die getestete Schicht des Features (siehe docs/known-limitations.md:
getestet wird Logik, nicht UI).
"""

import ipaddress
from urllib.parse import urlsplit

# Explizit ausgeschriebene Netzliste statt ip_address(...).is_private:
# CPython hat die Einordnung von 100.64.0.0/10 (RFC 6598, CGNAT) zwischen
# 3.10 und 3.13 geändert. Die CI-Matrix deckt beide ab — mit is_private wäre
# derselbe Test auf einer Python-Version grün und auf der anderen rot.
_PRIVATE_NETWORKS = tuple(
    ipaddress.ip_network(cidr)
    for cidr in (
        "127.0.0.0/8",      # Loopback
        "10.0.0.0/8",       # RFC 1918
        "172.16.0.0/12",    # RFC 1918
        "192.168.0.0/16",   # RFC 1918
        "100.64.0.0/10",    # RFC 6598 CGNAT (Tailscale u.ä.)
        "169.254.0.0/16",   # Link-Local
        "::1/128",          # Loopback v6
        "fc00::/7",         # ULA
        "fe80::/10",        # Link-Local v6
    )
)

_PRIVATE_SUFFIXES = (".local", ".lan", ".home.arpa", ".internal", ".localhost")


def is_private_host(host):
    """True, wenn `host` im lokalen Netz liegt und http damit erlaubt ist.

    Rein syntaktisch, ohne DNS-Auflösung. Ein öffentlicher Name, der per
    Split-Horizon-DNS intern auf eine private Adresse zeigt, gilt deshalb als
    öffentlich — bewusst, siehe docs/known-limitations.md.
    """
    if not host:
        return False
    host = host.strip().lower().rstrip(".")
    if host == "localhost":
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        # Kein IP-Literal, also ein Name.
        if host.endswith(_PRIVATE_SUFFIXES):
            return True
        # Single-Label-Name (»nas«, »fritzbox«): nur im lokalen Netz auflösbar.
        return "." not in host
    return any(ip in net for net in _PRIVATE_NETWORKS)


def validate_url(url):
    """Prüft Schema und Host. Liefert (ok, deutsche Begründung)."""
    parts = urlsplit((url or "").strip())
    if parts.scheme not in ("http", "https"):
        return False, "Die Adresse muss mit http:// oder https:// beginnen."
    try:
        host = parts.hostname
    except ValueError:
        # z.B. kaputte IPv6-Klammern
        host = None
    if not host:
        return False, "Die Adresse enthält keinen Server-Namen."
    if parts.scheme == "http" and not is_private_host(host):
        return False, (
            "Für Adressen außerhalb des lokalen Netzes ist https erforderlich."
        )
    return True, ""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_webhook.py -v`
Expected: PASS (alle Fälle, inklusive der parametrisierten)

- [ ] **Step 5: Commit**

```
git add src/webhook.py tests/test_webhook.py
git commit -m "feat(webhook): URL-Regel - https ausserhalb, http innerhalb"
```

---

### Task 2: Auth-Header und HMAC-Signatur

Drei Verfahren: `none`, `header` (Bearer/API-Key), `hmac` (SHA-256 über den Body). Steuerzeichen in Header-Werten werden **abgewiesen, nicht bereinigt** — dieselbe Entscheidung wie bei der Empfängeradresse in `mail.send_email` (Audit N11 / #133): still gestrippte Zeichen ergeben einen falschen Request, den niemand bemerkt.

**Files:**
- Modify: `src/webhook.py`
- Test: `tests/test_webhook.py`

**Interfaces:**
- Consumes: nichts aus Task 1
- Produces:
  - `sign_hmac(secret: str, body: bytes) -> str` — Hex-Digest, kleingeschrieben
  - `auth_headers(auth: dict, body: bytes) -> dict[str, str]` — wirft `ValueError` bei Steuerzeichen oder unbekanntem `mode`

- [ ] **Step 1: Write the failing test**

Anhängen an `tests/test_webhook.py`:

```python
from src.webhook import auth_headers, sign_hmac


def test_sign_hmac_matches_rfc4231_test_case_2():
    """RFC 4231, Test Case 2 — veröffentlichter Vektor, kein selbstgerechnetes
    Ergebnis (das wäre tautologisch)."""
    digest = sign_hmac("Jefe", b"what do ya want for nothing?")
    assert digest == (
        "5bdcc146bf60754e6a042426089575c75a003f089d2739839dec58b964ec3843"
    )


def test_auth_none_sends_no_header():
    assert auth_headers({"mode": "none"}, b"body") == {}


def test_auth_header_mode_passes_value_through():
    headers = auth_headers(
        {"mode": "header", "header": "Authorization", "value": "Bearer abc123"},
        b"body",
    )
    assert headers == {"Authorization": "Bearer abc123"}


def test_auth_header_mode_supports_custom_header_name():
    headers = auth_headers(
        {"mode": "header", "header": "X-API-Key", "value": "k"}, b"body")
    assert headers == {"X-API-Key": "k"}


def test_auth_hmac_signs_body_with_prefix():
    headers = auth_headers(
        {"mode": "hmac", "header": "X-Hub-Signature-256",
         "prefix": "sha256=", "secret": "Jefe"},
        b"what do ya want for nothing?",
    )
    assert headers == {
        "X-Hub-Signature-256":
            "sha256=5bdcc146bf60754e6a042426089575c75a003f089d2739839dec58b964ec3843"
    }


def test_auth_hmac_prefix_may_be_empty():
    headers = auth_headers(
        {"mode": "hmac", "header": "X-Sig", "prefix": "", "secret": "Jefe"},
        b"what do ya want for nothing?",
    )
    assert headers["X-Sig"].startswith("5bdcc146")


@pytest.mark.parametrize("bad", ["a\rb", "a\nb", "a\x00b"])
def test_control_characters_in_header_value_are_rejected(bad):
    with pytest.raises(ValueError):
        auth_headers({"mode": "header", "header": "Authorization", "value": bad},
                     b"body")


@pytest.mark.parametrize("bad", ["X\rY", "X\nY", "X\x00Y"])
def test_control_characters_in_header_name_are_rejected(bad):
    with pytest.raises(ValueError):
        auth_headers({"mode": "header", "header": bad, "value": "v"}, b"body")


def test_unknown_auth_mode_is_rejected():
    with pytest.raises(ValueError):
        auth_headers({"mode": "oauth"}, b"body")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_webhook.py -v -k "hmac or auth or control"`
Expected: FAIL — `ImportError: cannot import name 'auth_headers'`

- [ ] **Step 3: Write minimal implementation**

An `src/webhook.py` anhängen (Imports oben ergänzen: `import hashlib`, `import hmac`):

```python
_CONTROL_CHARS = ("\r", "\n", "\x00")


def _check_header_part(kind, value):
    """Wirft ValueError, wenn `value` Steuerzeichen enthält.

    Abweisen statt strippen: ein still bereinigtes "Bearer a\\nX-Foo: b"
    ergäbe einen Request, den der Nutzer nie so gemeint hat, und der Fehler
    fiele erst beim Empfänger auf (Muster wie mail.send_email, Audit N11).
    """
    if any(c in value for c in _CONTROL_CHARS):
        raise ValueError(
            f"Der {kind} enthält unzulässige Steuerzeichen "
            "(Zeilenumbruch oder Nullbyte)."
        )


def sign_hmac(secret, body):
    """HMAC-SHA256 über die rohen Body-Bytes, Hex, kleingeschrieben."""
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def auth_headers(auth, body):
    """Baut die Auth-Header für einen Webhook-Request.

    `auth` ist das `auth`-Objekt aus webhooks.json. Signiert wird bei `hmac`
    über die rohen Body-Bytes — exakt die Bytes, die über die Leitung gehen,
    sonst kann der Empfänger nicht verifizieren.
    """
    mode = (auth or {}).get("mode", "none")
    if mode == "none":
        return {}
    if mode == "header":
        name = auth.get("header") or "Authorization"
        value = auth.get("value") or ""
        _check_header_part("Header-Name", name)
        _check_header_part("Header-Wert", value)
        return {name: value}
    if mode == "hmac":
        name = auth.get("header") or "X-Hub-Signature-256"
        prefix = auth.get("prefix") or ""
        _check_header_part("Header-Name", name)
        _check_header_part("Signatur-Präfix", prefix)
        return {name: prefix + sign_hmac(auth.get("secret") or "", body)}
    raise ValueError(f"Unbekanntes Auth-Verfahren: {mode!r}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_webhook.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```
git add src/webhook.py tests/test_webhook.py
git commit -m "feat(webhook): Auth-Header und HMAC-Signatur"
```

---

### Task 3: Zeitraum-/Kategorie-Filter in `report.py` öffentlich machen

Vorbereitung für Task 4: die JSON-Payload muss auf **exakt denselben** Zeitraum und dieselben Kategorien gefiltert sein wie PDF und Mail-HTML — sonst behaupten zwei Anhänge derselben Sendung verschiedene Zeiträume. Die Filter liegen heute privat in `report.py`; nachbauen wäre eine Dublette, und den privaten Namen von außen zu benutzen ist im Projekt unerwünscht (Audit N17). Also: umbenennen, Verhalten unverändert.

**Files:**
- Modify: `src/report.py:103` (`_filter_entries`), `src/report.py:112` (`_apply_category_filter`) und die sechs Call-Sites in Zeilen 131, 133, 293, 295, 339, 341
- Test: `tests/test_report.py` (bestehende Tests müssen unverändert grün bleiben)

**Interfaces:**
- Consumes: nichts
- Produces:
  - `report.filter_period(date_from: date, date_to: date, all_entries: dict) -> dict | None` — `None`, wenn im Zeitraum nichts liegt (unverändertes Verhalten von `_filter_entries`)
  - `report.filter_categories(entries: dict, categories: list | None) -> dict` — `categories=None` liefert dasselbe Dict zurück

- [ ] **Step 1: Write the failing test**

An `tests/test_report.py` anhängen:

```python
from src.report import filter_categories, filter_period


def test_filter_period_public_name_keeps_range_only():
    entries = {
        "2026-06-30": {"slots": [_slot("08:00", "16:00")]},
        "2026-07-01": {"slots": [_slot("08:00", "16:00")]},
        "2026-08-01": {"slots": [_slot("08:00", "16:00")]},
    }
    got = filter_period(datetime.date(2026, 7, 1), datetime.date(2026, 7, 31), entries)
    assert list(got) == ["2026-07-01"]


def test_filter_period_returns_none_when_empty():
    assert filter_period(
        datetime.date(2026, 7, 1), datetime.date(2026, 7, 31), {}) is None


def test_filter_categories_none_returns_same_object():
    entries = {"2026-07-01": {"slots": [_slot("08:00", "16:00")]}}
    assert filter_categories(entries, None) is entries


def test_filter_categories_drops_days_without_matching_slots():
    entries = {
        "2026-07-01": {"slots": [_slot("08:00", "16:00", kategorie="A")]},
        "2026-07-02": {"slots": [_slot("08:00", "16:00", kategorie="B")]},
    }
    got = filter_categories(entries, ["A"])
    assert list(got) == ["2026-07-01"]
```

> Hinweis: `tests/test_report.py` importiert `_slot` bereits als
> `from tests.conftest import ist_slot as _slot` und `datetime`. Prüfe das oben
> in der Datei und ergänze nur, was fehlt.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_report.py -v -k "filter_period or filter_categories"`
Expected: FAIL — `ImportError: cannot import name 'filter_period' from 'src.report'`

- [ ] **Step 3: Write minimal implementation**

In `src/report.py` die beiden Funktionen umbenennen (Rumpf unverändert lassen, nur `def`-Zeile und Docstring-Anfang anpassen):

```python
def filter_period(date_from, date_to, all_entries):
    """Einträge im Zeitraum [date_from, date_to], oder None wenn keiner drin
    liegt. Öffentlich, weil neben Mail-HTML und PDF auch die Webhook-Payload
    exakt denselben Ausschnitt braucht — zwei Filter-Implementierungen würden
    beim nächsten Detail auseinanderlaufen."""
```

```python
def filter_categories(entries, categories):
    """categories=None → unverändert. Sonst werden je Tag nur Slots behalten,
    deren Kategorie (oder "" für ohne) in `categories` liegt; Tage ohne
    verbleibende Slots fallen weg. Liefert ein neues Dict."""
```

Danach alle sechs Call-Sites in `report.py` mitziehen:

```
_filter_entries(         →  filter_period(
_apply_category_filter(  →  filter_categories(
```

Prüfen, dass kein alter Name übrig ist:

```
grep -rn "_filter_entries\|_apply_category_filter" src/ tests/
```

Erwartet: keine Treffer (die `.pyc`-Dateien im `__pycache__` ignorieren).

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_report.py tests/test_period_picker.py -v`
Expected: PASS — die neuen Tests **und** alle bestehenden Report-Tests. Diese Aufgabe darf sich nirgends im Verhalten auswirken.

- [ ] **Step 5: Commit**

```
git add src/report.py tests/test_report.py
git commit -m "refactor(report): Zeitraum- und Kategorie-Filter oeffentlich machen"
```

---

### Task 4: JSON-Dokument und Request-Body

Das Wire-Format, das der Empfänger bekommt, plus die Wahl des Content-Type je nach Payload-Kombination.

**Files:**
- Modify: `src/webhook.py`
- Test: `tests/test_webhook.py`

**Interfaces:**
- Consumes: `report.filter_period`, `report.filter_categories` (Task 3)
- Produces:
  - `PAYLOAD_SCHEMA_VERSION = 1`, `PAYLOAD_KIND = "zeiterfassung-report"`
  - `total_minutes(entries: dict) -> int`
  - `build_json_payload(*, date_from, date_to, entries, name, sender, categories, generated_at=None) -> dict` — `generated_at=None` stempelt `utc_now_iso()`; Tests reichen einen festen Wert herein
  - `build_body(*, json_bytes: bytes | None, pdf_bytes: bytes | None, pdf_filename: str, boundary: str) -> tuple[str, bytes]` — `(content_type, body)`

- [ ] **Step 1: Write the failing test**

Anhängen an `tests/test_webhook.py`:

```python
import datetime
import json

from tests.conftest import ist_slot as _slot

from src.webhook import build_body, build_json_payload, total_minutes


def _entries():
    return {
        "2026-06-30": {"slots": [_slot("08:00", "16:00")]},          # außerhalb
        "2026-07-01": {"slots": [_slot("08:00", "16:00", pause=30, kategorie="A")]},
        "2026-07-02": {"slots": [_slot("09:00", "12:15", kategorie="B")]},
    }


def _payload(**over):
    base = dict(
        date_from=datetime.date(2026, 7, 1), date_to=datetime.date(2026, 7, 31),
        entries=_entries(), name="Sven", sender="sven@example.com",
        categories=None, generated_at="2026-08-26T09:14:00Z",
    )
    base.update(over)
    return build_json_payload(**base)


def test_payload_has_kind_and_version():
    doc = _payload()
    assert doc["kind"] == "zeiterfassung-report"
    assert doc["schema_version"] == 1
    assert doc["generated_at"] == "2026-08-26T09:14:00Z"
    assert doc["sender"] == "sven@example.com"
    assert doc["name"] == "Sven"
    assert doc["period"] == {"from": "2026-07-01", "to": "2026-07-31"}


def test_payload_drops_days_outside_the_period():
    assert list(_payload()["entries"]) == ["2026-07-01", "2026-07-02"]


def test_payload_slots_use_share_v3_shape():
    slot = _payload()["entries"]["2026-07-01"]["slots"][0]
    assert set(slot) == {"start", "end", "pause", "kategorie"}


def test_payload_categories_none_when_unfiltered():
    assert _payload()["categories"] is None


def test_payload_applies_category_filter():
    doc = _payload(categories=["A"])
    assert list(doc["entries"]) == ["2026-07-01"]
    assert doc["categories"] == ["A"]


def test_payload_empty_period_yields_empty_entries():
    doc = _payload(date_from=datetime.date(2030, 1, 1),
                   date_to=datetime.date(2030, 1, 31))
    assert doc["entries"] == {}
    assert doc["total_minutes"] == 0


def test_total_minutes_sums_minutes_not_decimal_hours():
    """CLAUDE.md: angezeigte Summen laufen über hours_to_minutes, nie über
    Dezimalstunden. 08:00-16:00 abzgl. 30 min = 450, 09:00-12:15 = 195."""
    entries = {
        "2026-07-01": {"slots": [_slot("08:00", "16:00", pause=30)]},
        "2026-07-02": {"slots": [_slot("09:00", "12:15")]},
    }
    assert total_minutes(entries) == 645


def test_body_json_only():
    ct, body = build_body(json_bytes=b'{"a":1}', pdf_bytes=None,
                          pdf_filename="r.pdf", boundary="B")
    assert ct == "application/json; charset=utf-8"
    assert body == b'{"a":1}'


def test_body_pdf_only():
    ct, body = build_body(json_bytes=None, pdf_bytes=b"%PDF-1.4",
                          pdf_filename="r.pdf", boundary="B")
    assert ct == "application/pdf"
    assert body == b"%PDF-1.4"


def test_body_multipart_contains_both_parts():
    ct, body = build_body(json_bytes=b'{"a":1}', pdf_bytes=b"%PDF-1.4",
                          pdf_filename="Zeiterfassung_20260701_20260731.pdf",
                          boundary="BOUNDARY")
    assert ct == 'multipart/form-data; boundary="BOUNDARY"'
    text = body.decode("latin-1")
    assert '--BOUNDARY\r\n' in text
    assert 'name="data"' in text
    assert "application/json" in text
    assert 'name="report"' in text
    assert 'filename="Zeiterfassung_20260701_20260731.pdf"' in text
    assert "application/pdf" in text
    assert text.endswith("--BOUNDARY--\r\n")
    assert b"%PDF-1.4" in body


def test_body_requires_at_least_one_payload():
    with pytest.raises(ValueError):
        build_body(json_bytes=None, pdf_bytes=None, pdf_filename="r.pdf",
                   boundary="B")


def test_payload_serializes_to_json():
    json.dumps(_payload())  # wirft nicht
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_webhook.py -v -k "payload or body or total_minutes"`
Expected: FAIL — `ImportError: cannot import name 'build_json_payload'`

- [ ] **Step 3: Write minimal implementation**

An `src/webhook.py` anhängen (oben ergänzen: `from src.report import filter_categories, filter_period`, `from src.time_utils import calculate_hours, hours_to_minutes, utc_now_iso`):

```python
PAYLOAD_SCHEMA_VERSION = 1
PAYLOAD_KIND = "zeiterfassung-report"


def total_minutes(entries):
    """Summe der Arbeitsminuten über alle Slots.

    Summiert wird über hours_to_minutes je Slot, NICHT über die
    Dezimalstunden — calculate_hours rundet pro Slot auf 2 Nachkommastellen
    (gröber als eine Minute), zweimal unabhängig zu runden ließe die Summe
    von den Einzelposten abweichen (CLAUDE.md, Abschnitt „Stunden").
    """
    return sum(
        hours_to_minutes(
            calculate_hours(slot.get("start"), slot.get("end"), slot.get("pause", 0)))
        for record in entries.values()
        for slot in record.get("slots", [])
    )


def build_json_payload(*, date_from, date_to, entries, name, sender,
                       categories, generated_at=None):
    """Das JSON-Dokument für den Webhook.

    `entries` ist der Snapshot aus `Storage.get_all()` (bereits durch
    `workweek.filter_for_report` gelaufen); Zeitraum und Kategorien filtert
    diese Funktion über dieselben Helfer wie Mail-HTML und PDF, damit alle
    drei denselben Ausschnitt behaupten.

    Eigenes `kind` statt `zeiterfassung-share`: das Dokument trägt
    Report-Metadaten, die der Share-Validator als unbekannte Felder ablehnt.
    Die Slot-Shape ist trotzdem identisch zu Share v3, damit ein Empfänger
    seinen Parser wiederverwenden kann.
    """
    ranged = filter_period(date_from, date_to, entries) or {}
    if ranged:
        ranged = filter_categories(ranged, categories)
    return {
        "schema_version": PAYLOAD_SCHEMA_VERSION,
        "kind": PAYLOAD_KIND,
        "generated_at": generated_at or utc_now_iso(),
        "sender": sender or "",
        "name": name or "",
        "period": {"from": date_from.isoformat(), "to": date_to.isoformat()},
        "categories": list(categories) if categories is not None else None,
        "total_minutes": total_minutes(ranged),
        "entries": ranged,
    }


def build_body(*, json_bytes, pdf_bytes, pdf_filename, boundary):
    """Wählt Content-Type und baut den Request-Body.

    JSON allein → application/json, PDF allein → application/pdf,
    beides → multipart/form-data mit den Teilen `data` und `report`.
    Multipart statt base64-im-JSON: Empfänger wie n8n/Make erwarten es so,
    und base64 bläht die Payload um ein Drittel auf.

    `boundary` wird hereingereicht (statt hier gewürfelt), damit Tests
    deterministisch bleiben.
    """
    if json_bytes is not None and pdf_bytes is None:
        return "application/json; charset=utf-8", json_bytes
    if pdf_bytes is not None and json_bytes is None:
        return "application/pdf", pdf_bytes
    if json_bytes is None and pdf_bytes is None:
        raise ValueError("Weder JSON noch PDF zum Senden vorhanden.")

    sep = f"--{boundary}\r\n".encode("latin-1")
    parts = [
        sep,
        b'Content-Disposition: form-data; name="data"; filename="report.json"\r\n',
        b"Content-Type: application/json; charset=utf-8\r\n\r\n",
        json_bytes, b"\r\n",
        sep,
        f'Content-Disposition: form-data; name="report"; '
        f'filename="{pdf_filename}"\r\n'.encode("utf-8"),
        b"Content-Type: application/pdf\r\n\r\n",
        pdf_bytes, b"\r\n",
        f"--{boundary}--\r\n".encode("latin-1"),
    ]
    return f'multipart/form-data; boundary="{boundary}"', b"".join(parts)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_webhook.py tests/test_report.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```
git add src/webhook.py tests/test_webhook.py
git commit -m "feat(webhook): JSON-Dokument und Request-Body"
```

---

### Task 5: HTTP-POST, Redirect-Schutz, Fehlerklassifikation

Die Netz-Schicht. Zwei Details entscheiden hier über Sicherheit bzw. Verständlichkeit und sind der eigentliche Grund für diese Aufgabe:

1. **`urllib.error.HTTPError` erbt von `URLError`**, und `URLError` steht in `mail._OFFLINE_EXC_NAMES`. Würde man `mail_task.classify_mail_error` wiederverwenden, meldete ein sauberes HTTP 500 „keine Internetverbindung". `HTTPError` wird deshalb **vor** der Offline-Prüfung abgefangen.
2. **Redirects dürfen das Schema nicht verschlechtern.** Ein `301` von https auf http lieferte sonst den Bearer-Token im Klartext aus und hebelte die URL-Regel aus Task 1 aus.

**Files:**
- Modify: `src/webhook.py`
- Test: `tests/test_webhook.py`

**Interfaces:**
- Consumes: nichts
- Produces:
  - `REQUEST_TIMEOUT_S = 30`
  - `post(url: str, headers: dict, body: bytes, timeout: int = REQUEST_TIMEOUT_S) -> int` — liefert den HTTP-Status, wirft bei Fehlern
  - `classify_error(exc: BaseException) -> dict` — `{"ok": False, "kind": ..., "detail": str, "error": exc, "tb": str | None}`
  - `_NoDowngradeRedirectHandler` (intern, aber im Test benannt)

- [ ] **Step 1: Write the failing test**

Anhängen an `tests/test_webhook.py`:

```python
import io
import socket
import urllib.error
import urllib.request

import src.webhook as wh
from src.webhook import classify_error, post


class _Resp(io.BytesIO):
    def __init__(self, status=200, body=b"ok"):
        super().__init__(body)
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_post_sends_headers_and_body(monkeypatch):
    seen = {}

    def fake_open(self, req, timeout=None):
        seen["url"] = req.full_url
        seen["data"] = req.data
        seen["ct"] = req.get_header("Content-type")
        seen["auth"] = req.get_header("Authorization")
        seen["timeout"] = timeout
        return _Resp(202)

    monkeypatch.setattr(urllib.request.OpenerDirector, "open", fake_open)
    status = post("https://example.com/hook",
                  {"Content-Type": "application/json", "Authorization": "Bearer x"},
                  b"{}")
    assert status == 202
    assert seen["url"] == "https://example.com/hook"
    assert seen["data"] == b"{}"
    assert seen["auth"] == "Bearer x"
    assert seen["timeout"] == 30


def test_redirect_handler_allows_https_to_https():
    handler = wh._NoDowngradeRedirectHandler()
    req = urllib.request.Request("https://a.example/hook", data=b"{}")
    new = handler.redirect_request(
        req, io.BytesIO(b""), 301, "Moved", {}, "https://b.example/hook")
    assert new is not None


def test_redirect_handler_blocks_https_to_http():
    """Sonst ginge der Bearer-Token im Klartext raus."""
    handler = wh._NoDowngradeRedirectHandler()
    req = urllib.request.Request("https://a.example/hook", data=b"{}")
    with pytest.raises(urllib.error.HTTPError):
        handler.redirect_request(
            req, io.BytesIO(b""), 301, "Moved", {}, "http://b.example/hook")


def _http_error(code, body=b""):
    return urllib.error.HTTPError(
        "https://example.com/hook", code, "Err", {}, io.BytesIO(body))


@pytest.mark.parametrize("code,kind", [
    (401, "auth"), (403, "auth"), (404, "notfound"),
    (400, "client"), (422, "client"),
    (500, "server"), (503, "server"),
])
def test_classify_http_status_codes(code, kind):
    res = classify_error(_http_error(code))
    assert res["ok"] is False
    assert res["kind"] == kind
    assert str(code) in res["detail"]


def test_classify_http_error_is_not_mistaken_for_offline():
    """HTTPError ist Unterklasse von URLError, und URLError gilt in mail.py als
    Offline-Symptom. Ohne die explizite Vorab-Prüfung meldete ein 500 hier
    „keine Internetverbindung"."""
    assert classify_error(_http_error(500))["kind"] == "server"


def test_classify_server_error_includes_truncated_body():
    res = classify_error(_http_error(500, b"x" * 2000))
    assert "xxx" in res["detail"]
    assert len(res["detail"]) < 700


def test_classify_urlerror_is_offline():
    res = classify_error(urllib.error.URLError(socket.gaierror("no dns")))
    assert res["kind"] == "offline"
    assert res["tb"] is None


def test_classify_timeout_is_offline():
    assert classify_error(TimeoutError("timed out"))["kind"] == "offline"


def test_classify_unexpected_error_carries_traceback():
    try:
        raise RuntimeError("boom")
    except RuntimeError as e:
        res = classify_error(e)
    assert res["kind"] == "error"
    assert "RuntimeError" in res["tb"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_webhook.py -v -k "post or redirect or classify"`
Expected: FAIL — `ImportError: cannot import name 'classify_error'`

- [ ] **Step 3: Write minimal implementation**

An `src/webhook.py` anhängen (oben ergänzen: `import traceback`, `import urllib.error`, `import urllib.request`, `from src.mail import is_offline_error`, `from src.version import VERSION`):

```python
REQUEST_TIMEOUT_S = 30
_MAX_RESPONSE_BYTES = 8192
_MAX_DETAIL_CHARS = 500

USER_AGENT = f"Zeiterfassung/{VERSION}"


class _NoDowngradeRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Folgt Redirects, aber nie von https auf http.

    Ohne das könnte ein 301 den Auth-Header (Bearer-Token) im Klartext
    ausliefern und die https-Pflicht aus validate_url aushebeln.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if req.type == "https" and urlsplit(newurl).scheme != "https":
            raise urllib.error.HTTPError(
                newurl, code,
                "Weiterleitung von https auf http abgelehnt (der "
                "Auth-Header ginge unverschlüsselt raus).",
                headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def post(url, headers, body, timeout=REQUEST_TIMEOUT_S):
    """POST an `url`. Liefert den HTTP-Status; wirft bei Fehlern."""
    req = urllib.request.Request(url, data=body, method="POST")
    for name, value in headers.items():
        req.add_header(name, value)
    req.add_header("User-Agent", USER_AGENT)
    opener = urllib.request.build_opener(_NoDowngradeRedirectHandler())
    with opener.open(req, timeout=timeout) as resp:
        resp.read(_MAX_RESPONSE_BYTES)
        return getattr(resp, "status", None) or resp.getcode()


def _response_snippet(exc):
    try:
        raw = exc.read(_MAX_RESPONSE_BYTES)
    except Exception:
        return ""
    text = raw.decode("utf-8", "replace").strip()
    return text[:_MAX_DETAIL_CHARS]


def classify_error(exc):
    """Mappt eine Versand-Exception auf ein Fehler-Result-Dict.

    HTTPError wird bewusst ZUERST geprüft: es ist eine Unterklasse von
    URLError, und URLError zählt in mail.is_offline_error als Offline-Symptom
    — ein sauberes HTTP 500 würde sonst als „keine Internetverbindung"
    gemeldet. Deshalb auch ein eigener Klassifikator statt
    mail_task.classify_mail_error.
    """
    if isinstance(exc, urllib.error.HTTPError):
        code = exc.code
        snippet = _response_snippet(exc)
        detail = f"HTTP {code}" + (f": {snippet}" if snippet else "")
        if code in (401, 403):
            kind = "auth"
        elif code == 404:
            kind = "notfound"
        elif 400 <= code < 500:
            kind = "client"
        else:
            kind = "server"
        return {"ok": False, "kind": kind, "detail": detail,
                "error": exc, "tb": None}
    if is_offline_error(exc):
        return {"ok": False, "kind": "offline", "detail": "",
                "error": exc, "tb": None}
    return {"ok": False, "kind": "error", "detail": str(exc),
            "error": exc, "tb": traceback.format_exc()}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_webhook.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```
git add src/webhook.py tests/test_webhook.py
git commit -m "feat(webhook): POST mit Redirect-Schutz und Fehlerklassifikation"
```

---

### Task 6: `webhook.perform_send` — der Kern, der nie wirft

Setzt Task 1, 2, 4 und 5 zu einem Versand zusammen. Vertrag wie `send_task.perform_send` (Audit M10): **wirft nie**, liefert immer ein Result-Dict.

**Files:**
- Modify: `src/webhook.py`
- Test: `tests/test_webhook.py`

**Interfaces:**
- Consumes: `validate_url`, `auth_headers`, `build_body`, `post`, `classify_error`
- Produces:
  - `perform_send(record: dict, *, json_bytes: bytes | None, pdf_bytes: bytes | None, pdf_filename: str, boundary: str | None = None) -> dict` — `{"ok": True, "status": int}` oder das Fehler-Dict aus `classify_error`, ergänzt um `"kind": "config"` für ungültige Konfiguration

- [ ] **Step 1: Write the failing test**

Anhängen an `tests/test_webhook.py`:

```python
from src.webhook import perform_send


def _record(**over):
    base = {
        "id": "abc", "name": "Server", "url": "https://example.com/hook",
        "enabled": True, "payload": {"json": True, "pdf": False},
        "auth": {"mode": "none"},
    }
    base.update(over)
    return base


def test_perform_send_posts_and_reports_status(monkeypatch):
    seen = {}

    def fake_post(url, headers, body, timeout=30):
        seen.update(url=url, headers=headers, body=body)
        return 204

    monkeypatch.setattr(wh, "post", fake_post)
    res = perform_send(_record(), json_bytes=b'{"a":1}', pdf_bytes=None,
                       pdf_filename="r.pdf")
    assert res == {"ok": True, "status": 204}
    assert seen["headers"]["Content-Type"] == "application/json; charset=utf-8"
    assert seen["body"] == b'{"a":1}'


def test_perform_send_adds_auth_header(monkeypatch):
    seen = {}
    monkeypatch.setattr(wh, "post",
                        lambda url, headers, body, timeout=30: seen.update(headers=headers) or 200)
    perform_send(
        _record(auth={"mode": "header", "header": "Authorization", "value": "Bearer t"}),
        json_bytes=b"{}", pdf_bytes=None, pdf_filename="r.pdf")
    assert seen["headers"]["Authorization"] == "Bearer t"


def test_perform_send_rejects_http_to_public_host_before_posting(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("darf nicht gesendet werden")

    monkeypatch.setattr(wh, "post", boom)
    res = perform_send(_record(url="http://erp.example.com/hook"),
                       json_bytes=b"{}", pdf_bytes=None, pdf_filename="r.pdf")
    assert res["ok"] is False
    assert res["kind"] == "config"
    assert "https" in res["detail"]


def test_perform_send_maps_http_error(monkeypatch):
    def fake_post(*a, **k):
        raise _http_error(500, b"kaputt")

    monkeypatch.setattr(wh, "post", fake_post)
    res = perform_send(_record(), json_bytes=b"{}", pdf_bytes=None,
                       pdf_filename="r.pdf")
    assert res["ok"] is False
    assert res["kind"] == "server"


def test_perform_send_never_raises_on_unexpected_error(monkeypatch):
    def fake_post(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr(wh, "post", fake_post)
    res = perform_send(_record(), json_bytes=b"{}", pdf_bytes=None,
                       pdf_filename="r.pdf")
    assert res["ok"] is False
    assert res["kind"] == "error"
    assert res["tb"]


def test_perform_send_rejects_bad_auth_config_as_config_error(monkeypatch):
    monkeypatch.setattr(wh, "post", lambda *a, **k: 200)
    res = perform_send(
        _record(auth={"mode": "header", "header": "Authorization",
                      "value": "Bearer \nX-Evil: 1"}),
        json_bytes=b"{}", pdf_bytes=None, pdf_filename="r.pdf")
    assert res["kind"] == "config"


def test_perform_send_signs_the_exact_body_sent(monkeypatch):
    seen = {}
    monkeypatch.setattr(
        wh, "post",
        lambda url, headers, body, timeout=30: seen.update(headers=headers, body=body) or 200)
    perform_send(
        _record(auth={"mode": "hmac", "header": "X-Sig", "prefix": "",
                      "secret": "Jefe"}),
        json_bytes=b"what do ya want for nothing?", pdf_bytes=None,
        pdf_filename="r.pdf")
    assert seen["headers"]["X-Sig"] == wh.sign_hmac("Jefe", seen["body"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_webhook.py -v -k perform_send`
Expected: FAIL — `ImportError: cannot import name 'perform_send'`

- [ ] **Step 3: Write minimal implementation**

An `src/webhook.py` anhängen (oben ergänzen: `import logging`, `import uuid`; `log = logging.getLogger(__name__)`):

```python
def perform_send(record, *, json_bytes, pdf_bytes, pdf_filename, boundary=None):
    """Sendet eine Payload an einen konfigurierten Webhook.

    Wirft nie — Fehler kommen als Result-Dict zurück (Vertrag wie
    send_task.perform_send, Audit M10). `kind == "config"` heißt: die
    Konfiguration ist unbrauchbar, es wurde gar nicht erst gesendet.

    Die URL wird hier erneut geprüft, obwohl der Dialog das beim Speichern
    schon tut: eine von Hand editierte webhooks.json soll die https-Pflicht
    nicht umgehen können.
    """
    try:
        ok, msg = validate_url(record.get("url", ""))
        if not ok:
            return {"ok": False, "kind": "config", "detail": msg,
                    "error": None, "tb": None}

        content_type, body = build_body(
            json_bytes=json_bytes, pdf_bytes=pdf_bytes,
            pdf_filename=pdf_filename,
            boundary=boundary or uuid.uuid4().hex)

        headers = {"Content-Type": content_type}
        headers.update(auth_headers(record.get("auth"), body))
    except ValueError as e:
        return {"ok": False, "kind": "config", "detail": str(e),
                "error": e, "tb": None}

    try:
        status = post(record["url"], headers, body)
    except Exception as e:  # noqa: BLE001 — bewusst alles, der Vertrag ist „wirft nie"
        log.exception("Webhook-Versand an %r fehlgeschlagen", record.get("name"))
        return classify_error(e)
    return {"ok": True, "status": status}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_webhook.py -v`
Expected: PASS (alle Tests aus Task 1–6)

- [ ] **Step 5: Commit**

```
git add src/webhook.py tests/test_webhook.py
git commit -m "feat(webhook): perform_send als nie werfender Versand-Kern"
```

---

### Task 7: `WebhookStore` — gerätelokale, gehärtete Persistenz

Dritter Secret-Schreibpfad neben `token.json` und `instance-secret`. Deshalb Pflicht: `harden_windows_acl` auf der **Temp-Datei**, vor dem `os.replace`.

**Files:**
- Create: `src/webhooks.py`
- Test: `tests/test_webhooks_store.py`

**Interfaces:**
- Consumes: `webhook.validate_url` (Task 1)
- Produces:
  - `SCHEMA_VERSION = 1`
  - `WebhookStore(filepath="webhooks.json", lock=None)`
  - `.get_all() -> list[dict]` (Kopien), `.enabled() -> list[dict]`, `.get(id) -> dict | None`
  - `.save(record: dict) -> None` (legt an oder ersetzt nach `id`), `.delete(id: str) -> None`
  - `new_id() -> str`
  - `validate_record(record: dict, existing: list[dict]) -> tuple[bool, str]`

- [ ] **Step 1: Write the failing test**

`tests/test_webhooks_store.py`:

```python
"""WebhookStore: gerätelokale, gehärtete Persistenz der Webhook-Liste."""

import json

import pytest

import src.webhooks as whs
from src.webhooks import WebhookStore, new_id, validate_record


def _record(**over):
    base = {
        "id": "id-1", "name": "Server", "url": "https://example.com/hook",
        "enabled": True, "payload": {"json": True, "pdf": False},
        "auth": {"mode": "none"},
    }
    base.update(over)
    return base


def _store(tmp_path):
    return WebhookStore(str(tmp_path / "webhooks.json"))


def test_starts_empty_without_file(tmp_path):
    assert _store(tmp_path).get_all() == []


def test_save_and_reload_round_trip(tmp_path):
    path = str(tmp_path / "webhooks.json")
    WebhookStore(path).save(_record())
    assert WebhookStore(path).get_all() == [_record()]


def test_save_replaces_by_id(tmp_path):
    store = _store(tmp_path)
    store.save(_record())
    store.save(_record(name="Neu"))
    assert [w["name"] for w in store.get_all()] == ["Neu"]


def test_delete_removes_only_the_named_one(tmp_path):
    store = _store(tmp_path)
    store.save(_record(id="a"))
    store.save(_record(id="b", name="B"))
    store.delete("a")
    assert [w["id"] for w in store.get_all()] == ["b"]


def test_enabled_skips_disabled(tmp_path):
    store = _store(tmp_path)
    store.save(_record(id="a"))
    store.save(_record(id="b", name="B", enabled=False))
    assert [w["id"] for w in store.enabled()] == ["a"]


def test_get_all_returns_copies(tmp_path):
    store = _store(tmp_path)
    store.save(_record())
    store.get_all()[0]["name"] = "mutiert"
    assert store.get_all()[0]["name"] == "Server"


def test_corrupt_file_is_quarantined(tmp_path, caplog):
    path = tmp_path / "webhooks.json"
    path.write_text("{kaputt", encoding="utf-8")
    store = WebhookStore(str(path))
    assert store.get_all() == []
    assert list(tmp_path.glob("webhooks.json.corrupt-*"))
    assert not path.exists()


def test_invalid_record_is_skipped_rest_survives(tmp_path, caplog):
    path = tmp_path / "webhooks.json"
    path.write_text(json.dumps({
        "schema_version": 1,
        "webhooks": [
            {"id": "kaputt"},                       # Pflichtfelder fehlen
            _record(id="gut"),
        ],
    }), encoding="utf-8")
    store = WebhookStore(str(path))
    assert [w["id"] for w in store.get_all()] == ["gut"]


def test_newer_schema_version_is_left_alone(tmp_path):
    """Ein älterer Build darf eine neuere Datei nicht überschreiben."""
    path = tmp_path / "webhooks.json"
    original = json.dumps({"schema_version": 99, "webhooks": [_record()]})
    path.write_text(original, encoding="utf-8")
    store = WebhookStore(str(path))
    assert store.get_all() == []
    assert path.read_text(encoding="utf-8") == original


def test_hardening_runs_on_the_temp_file(tmp_path, monkeypatch):
    """Auf der Temp-Datei, VOR os.replace — sonst läge die Datei kurz mit
    geerbten Rechten am Zielpfad (Muster wie oauth_utils.write_token)."""
    hardened = []
    monkeypatch.setattr(whs, "harden_windows_acl", hardened.append)
    path = tmp_path / "webhooks.json"
    WebhookStore(str(path)).save(_record())
    assert hardened, "harden_windows_acl wurde nicht aufgerufen"
    assert hardened[0] != str(path)
    assert not any(p.name.endswith(".tmp") for p in tmp_path.iterdir())


def test_new_id_is_unique():
    assert new_id() != new_id()


def test_validate_record_requires_name():
    ok, msg = validate_record(_record(name="  "), [])
    assert ok is False
    assert msg


def test_validate_record_rejects_duplicate_name_case_insensitive():
    ok, msg = validate_record(_record(id="b", name="SERVER"), [_record(id="a")])
    assert ok is False
    assert msg


def test_validate_record_allows_renaming_itself():
    ok, _ = validate_record(_record(id="a", name="Server"), [_record(id="a")])
    assert ok is True


def test_validate_record_rejects_http_to_public_host():
    ok, msg = validate_record(_record(url="http://erp.example.com/x"), [])
    assert ok is False
    assert "https" in msg


def test_validate_record_requires_a_payload():
    ok, msg = validate_record(_record(payload={"json": False, "pdf": False}), [])
    assert ok is False
    assert msg


@pytest.mark.parametrize("auth", [
    {"mode": "header", "header": "Authorization", "value": ""},
    {"mode": "hmac", "header": "X-Sig", "prefix": "sha256=", "secret": ""},
])
def test_validate_record_requires_secret_for_auth_modes(auth):
    ok, msg = validate_record(_record(auth=auth), [])
    assert ok is False
    assert msg


def test_uses_the_injected_lock(tmp_path):
    """Alle Stores teilen sich den in main() erzeugten RLock (Audit H1/H2)."""
    import threading
    lock = threading.RLock()
    store = WebhookStore(str(tmp_path / "webhooks.json"), lock=lock)
    assert store._lock is lock


def test_creates_own_lock_without_injection(tmp_path):
    assert _store(tmp_path)._lock is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_webhooks_store.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.webhooks'`

- [ ] **Step 3: Write minimal implementation**

`src/webhooks.py`:

```python
"""Gerätelokale Persistenz der Webhook-Konfiguration (Tk-frei, stdlib-only).

`webhooks.json` liegt neben `token.json` im Datenverzeichnis und enthält
Konfiguration UND Secrets. Sie wird deshalb wie `token.json` gehärtet
geschrieben (chmod 0600 + icacls auf der Temp-Datei, dann os.replace) — der
dritte Secret-Schreibpfad der App, siehe src/CLAUDE.md.

Nichts hiervon reist per Drive-Sync: Webhooks sind bewusst gerätelokal, damit
kein Secret im Sync-Doc landet.
"""

from __future__ import annotations

import datetime
import json
import logging
import os
import stat
import tempfile
import threading
import uuid
from typing import Any

from src.secure_file import harden_windows_acl
from src.webhook import validate_url

log = logging.getLogger(__name__)

SCHEMA_VERSION = 1

Webhook = dict[str, Any]

_REQUIRED_KEYS = ("id", "name", "url", "enabled", "payload", "auth")
_AUTH_MODES = ("none", "header", "hmac")


def new_id() -> str:
    """Stabile Kennung eines Webhooks. Trägt die Zuordnung, wenn der Nutzer
    den Namen ändert."""
    return uuid.uuid4().hex


def _is_wellformed(record: Any) -> bool:
    """Strukturprüfung fürs Laden — absichtlich schwächer als validate_record.
    Hier geht es nur darum, ob mit dem Datensatz überhaupt zu arbeiten ist."""
    if not isinstance(record, dict):
        return False
    if any(k not in record for k in _REQUIRED_KEYS):
        return False
    if not isinstance(record.get("payload"), dict):
        return False
    auth = record.get("auth")
    return isinstance(auth, dict) and auth.get("mode") in _AUTH_MODES


def validate_record(record: Webhook, existing: list[Webhook]) -> tuple[bool, str]:
    """Prüft einen im Dialog bearbeiteten Datensatz. (ok, deutsche Begründung).

    `existing` ist die aktuelle Liste; der Datensatz selbst (gleiche `id`) wird
    beim Namens-Vergleich ausgenommen, sonst könnte man einen Webhook nicht
    speichern, ohne ihn umzubenennen.
    """
    name = (record.get("name") or "").strip()
    if not name:
        return False, "Bitte einen Namen angeben."
    for other in existing:
        if other.get("id") != record.get("id") and \
                (other.get("name") or "").strip().lower() == name.lower():
            return False, f"Es gibt bereits einen Webhook namens „{name}“."

    ok, msg = validate_url(record.get("url", ""))
    if not ok:
        return False, msg

    payload = record.get("payload") or {}
    if not payload.get("json") and not payload.get("pdf"):
        return False, "Bitte mindestens JSON oder PDF auswählen."

    auth = record.get("auth") or {}
    mode = auth.get("mode")
    if mode == "header":
        if not (auth.get("header") or "").strip():
            return False, "Bitte einen Header-Namen angeben."
        if not (auth.get("value") or "").strip():
            return False, "Bitte einen Header-Wert (Token) angeben."
    elif mode == "hmac":
        if not (auth.get("header") or "").strip():
            return False, "Bitte einen Header-Namen angeben."
        if not (auth.get("secret") or "").strip():
            return False, "Bitte ein Secret für die Signatur angeben."
    elif mode != "none":
        return False, "Unbekanntes Auth-Verfahren."
    return True, ""


class WebhookStore:
    def __init__(self, filepath: str = "webhooks.json",
                 lock: threading.RLock | None = None) -> None:
        self.filepath = filepath
        # Geteilter Daten-Lock (Audit H1/H2) — siehe storage.py.
        self._lock = lock if lock is not None else threading.RLock()
        self._webhooks: list[Webhook] = []
        self._readonly = False
        self._load()

    def _load(self) -> None:
        if not os.path.exists(self.filepath):
            return
        try:
            with open(self.filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError, ValueError):
            self._quarantine("JSON nicht parsebar")
            return
        if not isinstance(data, dict):
            self._quarantine(f"unerwartetes Toplevel-Format ({type(data).__name__})")
            return

        version = data.get("schema_version")
        if isinstance(version, int) and not isinstance(version, bool) \
                and version > SCHEMA_VERSION:
            # Nicht anfassen: ein älterer Build darf eine neuere Datei nicht
            # überschreiben. Lieber ohne Webhooks laufen.
            self._readonly = True
            log.warning(
                "webhooks.json hat schema_version %s (bekannt: %s) — die Datei "
                "wird nicht gelesen und nicht überschrieben.",
                version, SCHEMA_VERSION)
            return

        raw = data.get("webhooks")
        if not isinstance(raw, list):
            return
        for record in raw:
            if _is_wellformed(record):
                self._webhooks.append(record)
            else:
                log.warning("webhooks.json: Datensatz übersprungen (%r)", record)

    def _quarantine(self, reason: str) -> None:
        """Verschiebt die kaputte Datei nach `.corrupt-<stamp>` statt sie
        kommentarlos zu verwerfen (Muster wie settings/conflicts_store)."""
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        target = f"{self.filepath}.corrupt-{stamp}"
        try:
            os.replace(self.filepath, target)
        except OSError:
            log.warning("webhooks.json korrupt (%s); Quarantäne-Rename "
                        "fehlgeschlagen — starte ohne Webhooks", reason,
                        exc_info=True)
            return
        log.warning("webhooks.json korrupt (%s) — nach %s in Quarantäne "
                    "verschoben, starte ohne Webhooks",
                    reason, os.path.basename(target))

    def _save_to_disk(self) -> None:
        """Atomar und gehärtet — derselbe Ablauf wie oauth_utils.write_token.

        chmod und icacls laufen auf der TEMP-Datei: sonst gäbe es ein Fenster,
        in dem webhooks.json schon am Zielpfad steht, aber noch die geerbten
        Rechte trägt.
        """
        if self._readonly:
            log.warning("webhooks.json wird wegen neuerer schema_version "
                        "nicht geschrieben.")
            return
        payload = {"schema_version": SCHEMA_VERSION, "webhooks": self._webhooks}
        directory = os.path.dirname(os.path.abspath(self.filepath))
        fd, tmp_path = tempfile.mkstemp(
            dir=directory, prefix=".webhooks-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            try:
                os.chmod(tmp_path, stat.S_IRUSR | stat.S_IWUSR)  # 0o600
            except OSError:
                pass
            harden_windows_acl(tmp_path)
            os.replace(tmp_path, self.filepath)
        except BaseException:
            try:
                os.remove(tmp_path)
            except OSError:
                pass
            raise

    def get_all(self) -> list[Webhook]:
        with self._lock:
            return [dict(w) for w in self._webhooks]

    def enabled(self) -> list[Webhook]:
        with self._lock:
            return [dict(w) for w in self._webhooks if w.get("enabled")]

    def get(self, webhook_id: str) -> Webhook | None:
        with self._lock:
            for w in self._webhooks:
                if w.get("id") == webhook_id:
                    return dict(w)
            return None

    def save(self, record: Webhook) -> None:
        """Legt an oder ersetzt nach `id`."""
        with self._lock:
            for i, existing in enumerate(self._webhooks):
                if existing.get("id") == record.get("id"):
                    self._webhooks[i] = dict(record)
                    break
            else:
                self._webhooks.append(dict(record))
            self._save_to_disk()

    def delete(self, webhook_id: str) -> None:
        with self._lock:
            self._webhooks = [
                w for w in self._webhooks if w.get("id") != webhook_id]
            self._save_to_disk()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_webhooks_store.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```
git add src/webhooks.py tests/test_webhooks_store.py
git commit -m "feat(webhooks): geraetelokaler, gehaerteter Store"
```

---

### Task 8: `send_task` wird zum Multi-Kanal-Dispatcher

Der heutige Gmail-Block wandert unverändert nach `_send_mail`; `perform_send` baut die Payloads einmal und feuert jeden Kanal unabhängig.

**Achtung:** `tests/test_send_task.py` prüft die alte Signatur und muss in dieser Aufgabe mit angepasst werden — die Mail-Zusicherungen bleiben inhaltlich erhalten.

**Files:**
- Modify: `src/dialogs/send_task.py` (komplett neu strukturiert)
- Modify: `tests/test_send_task.py` (an die neue Signatur angepasst)
- Test: `tests/test_send_task_dispatch.py` (neu)

**Interfaces:**
- Consumes: `webhook.perform_send`, `webhook.build_json_payload` (Task 4/6)
- Produces:
  - `perform_send(*, date_from, date_to, entries, name, categories, category_breakdown, send_mail: bool, mail: dict | None, webhooks: list[dict], pdf_filename, settings) -> dict`
    — `mail` ist `{"credentials_path", "token_path", "recipient", "subject", "html", "sync_enabled", "gcal_enabled"}`;
    jeder Eintrag in `webhooks` ist `{"record": <webhook-dict>, "json": bool, "pdf": bool}` (die im Dialog übersteuerte Format-Wahl).
    Rückgabe: `{"results": [ … ]}` mit je `{"channel", "name", "ok"}` und im Fehlerfall zusätzlich `{"kind", "detail", "error", "tb"}`.
  - `needs_pdf(send_mail: bool, webhooks: list[dict]) -> bool`
  - `needs_json(webhooks: list[dict]) -> bool`
  - `format_result_summary(results: list[dict]) -> str`

- [ ] **Step 1: Write the failing test**

`tests/test_send_task_dispatch.py`:

```python
"""Multi-Kanal-Dispatch: Mail und Webhooks feuern unabhängig voneinander."""

import datetime

import src.dialogs.send_task as st
from src.dialogs.send_task import (
    format_result_summary, needs_json, needs_pdf, perform_send,
)
from tests.conftest import ist_slot as _slot


class _FakeSettings:
    def __init__(self):
        self._d = {"sender_email": ""}
        self.sets = []

    def get(self, k):
        return self._d.get(k)

    def set(self, k, v):
        self.sets.append((k, v))
        self._d[k] = v


def _hook(name="Server", json_=True, pdf=False):
    return {
        "record": {"id": name, "name": name, "url": "https://x.example/h",
                   "enabled": True, "payload": {"json": json_, "pdf": pdf},
                   "auth": {"mode": "none"}},
        "json": json_, "pdf": pdf,
    }


def _mail():
    return {
        "credentials_path": "c.json", "token_path": "t.json",
        "recipient": "to@example.com", "subject": "Subj", "html": "<p>x</p>",
        "sync_enabled": False, "gcal_enabled": False,
    }


def _kwargs(**over):
    base = dict(
        date_from=datetime.date(2026, 7, 1), date_to=datetime.date(2026, 7, 31),
        entries={"2026-07-01": {"slots": [_slot("08:00", "16:00")]}},
        name="Sven", categories=None, category_breakdown=False,
        send_mail=True, mail=_mail(), webhooks=[],
        pdf_filename="r.pdf", settings=_FakeSettings(),
    )
    base.update(over)
    return base


def _patch_mail_ok(monkeypatch, calls=None):
    monkeypatch.setattr(st, "generate_pdf",
                        lambda *a, **k: (calls.append("pdf") if calls is not None else None) or b"PDF")
    monkeypatch.setattr(st, "get_gmail_service", lambda *a, **k: "svc")
    monkeypatch.setattr(st, "send_email", lambda *a, **k: "mid")
    monkeypatch.setattr(st, "fetch_user_email", lambda *a, **k: "me@example.com")


def test_mail_only_matches_previous_behaviour(monkeypatch):
    _patch_mail_ok(monkeypatch)
    res = perform_send(**_kwargs())
    assert res["results"] == [
        {"channel": "mail", "name": "to@example.com", "ok": True}]


def test_webhook_result_is_reported_per_channel(monkeypatch):
    _patch_mail_ok(monkeypatch)
    monkeypatch.setattr(st.webhook, "perform_send",
                        lambda *a, **k: {"ok": True, "status": 200})
    res = perform_send(**_kwargs(webhooks=[_hook("Buchhaltung")]))
    assert [r["name"] for r in res["results"]] == ["to@example.com", "Buchhaltung"]
    assert all(r["ok"] for r in res["results"])


def test_failing_webhook_does_not_stop_mail(monkeypatch):
    _patch_mail_ok(monkeypatch)
    monkeypatch.setattr(
        st.webhook, "perform_send",
        lambda *a, **k: {"ok": False, "kind": "server", "detail": "HTTP 500",
                         "error": None, "tb": None})
    res = perform_send(**_kwargs(webhooks=[_hook("Buchhaltung")]))
    mail_res, hook_res = res["results"]
    assert mail_res["ok"] is True
    assert hook_res["ok"] is False
    assert hook_res["kind"] == "server"


def test_failing_mail_does_not_stop_webhooks(monkeypatch):
    monkeypatch.setattr(st, "generate_pdf", lambda *a, **k: b"PDF")

    def boom(*a, **k):
        raise RuntimeError("gmail kaputt")

    monkeypatch.setattr(st, "get_gmail_service", boom)
    monkeypatch.setattr(st.webhook, "perform_send",
                        lambda *a, **k: {"ok": True, "status": 200})
    res = perform_send(**_kwargs(webhooks=[_hook("Buchhaltung")]))
    assert res["results"][0]["ok"] is False
    assert res["results"][1]["ok"] is True


def test_pdf_is_generated_once_for_all_channels(monkeypatch):
    calls = []
    _patch_mail_ok(monkeypatch, calls)
    monkeypatch.setattr(st.webhook, "perform_send",
                        lambda *a, **k: {"ok": True, "status": 200})
    perform_send(**_kwargs(webhooks=[_hook("A", json_=False, pdf=True),
                                     _hook("B", json_=False, pdf=True)]))
    assert calls.count("pdf") == 1


def test_pdf_is_not_generated_when_nobody_wants_it(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("generate_pdf darf nicht laufen")

    monkeypatch.setattr(st, "generate_pdf", boom)
    monkeypatch.setattr(st.webhook, "perform_send",
                        lambda *a, **k: {"ok": True, "status": 200})
    res = perform_send(**_kwargs(send_mail=False, mail=None,
                                 webhooks=[_hook("A", json_=True, pdf=False)]))
    assert res["results"][0]["ok"] is True


def test_unexpected_webhook_error_never_escapes(monkeypatch):
    _patch_mail_ok(monkeypatch)

    def boom(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr(st.webhook, "perform_send", boom)
    res = perform_send(**_kwargs(webhooks=[_hook("A")]))
    assert res["results"][1]["ok"] is False
    assert res["results"][1]["kind"] == "error"


def test_needs_pdf_and_needs_json():
    assert needs_pdf(True, []) is True
    assert needs_pdf(False, [_hook("A", json_=True, pdf=False)]) is False
    assert needs_pdf(False, [_hook("A", json_=False, pdf=True)]) is True
    assert needs_json([_hook("A", json_=True, pdf=False)]) is True
    assert needs_json([_hook("A", json_=False, pdf=True)]) is False


def test_summary_lists_every_channel():
    text = format_result_summary([
        {"channel": "mail", "name": "to@example.com", "ok": True},
        {"channel": "webhook", "name": "Buchhaltung", "ok": False,
         "kind": "server", "detail": "HTTP 500"},
    ])
    assert "to@example.com" in text
    assert "Buchhaltung" in text
    assert "HTTP 500" in text
    assert "✓" in text and "✗" in text
```

Zusätzlich `tests/test_send_task.py` an die neue Signatur anpassen: `_kwargs()` dort um `send_mail=True`, `mail={...}` und `webhooks=[]` umbauen und die Assertions von `res == {"ok": True}` auf `res["results"][0]["ok"] is True` bzw. auf `res["results"][0]["kind"]` umstellen. Die inhaltlichen Zusicherungen (Empfänger, Anhang-Bytes, `attachment_subtype`, `sender_email`-Cache, Delegation an `classify_mail_error`) bleiben erhalten.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_send_task_dispatch.py -v`
Expected: FAIL — `ImportError: cannot import name 'needs_pdf'`

- [ ] **Step 3: Write minimal implementation**

`src/dialogs/send_task.py` ersetzen durch:

```python
"""Worker-Kern des Sende-Dialogs (Audit M10): Tk-frei, wirft nie.

Dispatcher über zwei Kanaltypen: Gmail und beliebig viele Webhooks. Die
Payloads (PDF, JSON) entstehen genau einmal und nur, wenn sie ein Kanal
braucht — generate_pdf ist der teuerste Schritt im Pfad. Jeder Kanal läuft
unabhängig; ein Fehler bricht die übrigen nicht ab. Persistenz
(settings.set) passiert hier im Worker und überlebt damit einen
Dialog-Close.
"""

import json as _json
import logging
import traceback

from src import webhook
from src.dialogs.mail_task import classify_mail_error
from src.mail import fetch_user_email, get_gmail_service, send_email
from src.report import generate_pdf

log = logging.getLogger(__name__)


def needs_pdf(send_mail, webhooks):
    """True, wenn irgendein Kanal die PDF braucht (Mail hängt sie immer an)."""
    return bool(send_mail) or any(w.get("pdf") for w in webhooks)


def needs_json(webhooks):
    return any(w.get("json") for w in webhooks)


def _send_mail(*, mail, pdf_bytes, pdf_filename, settings):
    """Der bisherige Gmail-Pfad, unverändert im Verhalten."""
    try:
        service = get_gmail_service(
            mail["credentials_path"], mail["token_path"],
            sync_enabled=mail["sync_enabled"], gcal_enabled=mail["gcal_enabled"])
        send_email(service, mail["recipient"], mail["subject"], mail["html"],
                   attachment_bytes=pdf_bytes,
                   attachment_filename=pdf_filename,
                   attachment_subtype="pdf")
    except FileNotFoundError as e:
        return classify_mail_error(e)
    except Exception as e:
        log.exception("Mailversand fehlgeschlagen")
        return classify_mail_error(e)

    # Nach erfolgreichem Send ist der Token frisch — Absender-Adresse cachen.
    try:
        email = fetch_user_email(
            mail["token_path"], sync_enabled=mail["sync_enabled"],
            gcal_enabled=mail["gcal_enabled"])
        if email and email != settings.get("sender_email"):
            settings.set("sender_email", email)
    except Exception:
        log.exception("sender_email fetch after send failed")

    return {"ok": True}


def perform_send(*, date_from, date_to, entries, name, categories,
                 category_breakdown, send_mail, mail, webhooks,
                 pdf_filename, settings):
    """Feuert alle gewählten Kanäle und sammelt ein Ergebnis je Kanal.

    Wirft nie. `webhooks` ist eine Liste von
    {"record": <webhook>, "json": bool, "pdf": bool} — die im Sende-Dialog
    ggf. übersteuerte Format-Wahl.
    """
    results = []

    pdf_bytes = None
    if needs_pdf(send_mail, webhooks):
        try:
            pdf_bytes = generate_pdf(
                date_from, date_to, entries, name=name,
                categories=categories, category_breakdown=category_breakdown)
        except Exception as e:
            log.exception("PDF-Erzeugung fehlgeschlagen")
            failure = {"ok": False, "kind": "error", "detail": str(e),
                       "error": e, "tb": traceback.format_exc()}
            # Ohne PDF kann weder die Mail noch ein PDF-Webhook raus. Die
            # JSON-Webhooks laufen trotzdem weiter — sie brauchen sie nicht.
            if send_mail:
                results.append({"channel": "mail",
                                "name": mail["recipient"], **failure})
                send_mail = False
            for entry in [w for w in webhooks if w.get("pdf")]:
                results.append({"channel": "webhook",
                                "name": entry["record"].get("name", ""),
                                **failure})
            webhooks = [w for w in webhooks if not w.get("pdf")]

    if send_mail:
        res = _send_mail(mail=mail, pdf_bytes=pdf_bytes,
                         pdf_filename=pdf_filename, settings=settings)
        results.append({"channel": "mail", "name": mail["recipient"], **res})

    json_bytes = None
    if needs_json(webhooks):
        payload = webhook.build_json_payload(
            date_from=date_from, date_to=date_to, entries=entries,
            name=name, sender=settings.get("sender_email"),
            categories=categories)
        json_bytes = _json.dumps(
            payload, ensure_ascii=False, sort_keys=True).encode("utf-8")

    for entry in webhooks:
        record = entry["record"]
        try:
            res = webhook.perform_send(
                record,
                json_bytes=json_bytes if entry.get("json") else None,
                pdf_bytes=pdf_bytes if entry.get("pdf") else None,
                pdf_filename=pdf_filename)
        except Exception as e:  # noqa: BLE001 — Vertrag: der Dispatcher wirft nie
            log.exception("Webhook %r: unerwarteter Fehler",
                          record.get("name"))
            res = {"ok": False, "kind": "error", "detail": str(e),
                   "error": e, "tb": traceback.format_exc()}
        results.append({"channel": "webhook",
                        "name": record.get("name", ""), **res})

    return {"results": results}


_KIND_TEXTS = {
    "filenotfound": "Zugangsdaten fehlen",
    "offline": "keine Internetverbindung",
    "auth": "Zugangsdaten wurden abgelehnt",
    "notfound": "Adresse nicht gefunden",
    "client": "Anfrage abgelehnt",
    "server": "Server-Fehler",
    "config": "Konfiguration ungültig",
    "error": "unerwarteter Fehler",
}


def format_result_summary(results):
    """Mehrzeilige Zusammenfassung für den Ergebnis-Dialog."""
    lines = []
    for res in results:
        if res.get("ok"):
            lines.append(f"✓  {res['name']}")
            continue
        reason = _KIND_TEXTS.get(res.get("kind"), "Fehler")
        detail = (res.get("detail") or "").strip()
        lines.append(f"✗  {res['name']} — {reason}"
                     + (f" ({detail})" if detail else ""))
    return "\n".join(lines)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_send_task_dispatch.py tests/test_send_task.py -v`
Expected: PASS — beide Dateien

- [ ] **Step 5: Commit**

```
git add src/dialogs/send_task.py tests/test_send_task.py tests/test_send_task_dispatch.py
git commit -m "feat(send-task): Multi-Kanal-Dispatcher fuer Mail und Webhooks"
```

---

### Task 9: `WebhookStore` verdrahten

Store erzeugen und dorthin reichen, wo er gebraucht wird. Kein neues Verhalten — danach ist der Store vorhanden, aber noch von keiner UI benutzt.

**Files:**
- Modify: `src/main.py` (dort, wo `Storage`/`Settings`/`ConflictsStore` mit `lock=data_lock` erzeugt werden)
- Modify: `src/ui.py` (`App.__init__`-Signatur + Attribut)

**Interfaces:**
- Consumes: `WebhookStore` (Task 7)
- Produces: `App._webhook_store` — der von den Dialogen genutzte Store

> **Kein Test-Schritt.** Diese Aufgabe verdrahtet nur; das Verhalten des Stores
> ist in Task 7 abgedeckt (inklusive `lock=`-Injektion). Die Schranke hier ist,
> dass die **gesamte** Suite grün bleibt und die App startet.

- [ ] **Step 1: Write the implementation**

In `src/main.py` neben den anderen Stores anlegen (Import ergänzen: `from src.webhooks import WebhookStore`):

```python
webhook_store = WebhookStore(
    os.path.join(base_path, "webhooks.json"), lock=data_lock)
```

und an `App(...)` durchreichen. In `src/ui.py`:

```python
def __init__(self, root, storage, settings, ..., webhook_store=None):
    ...
    # Gerätelokale Webhook-Konfiguration; None bedeutet „Feature nicht
    # verfügbar" und wird von den Dialogen wie eine leere Liste behandelt.
    self._webhook_store = webhook_store
```

Den exakten Aufruf in `main.py` an die dort vorhandene Parameterliste anpassen (die anderen Stores werden direkt daneben übergeben).

- [ ] **Step 2: Verify**

Run: `pytest -q ; ruff check .`
Expected: PASS — die gesamte Suite. Diese Aufgabe darf nichts brechen.

Zusätzlich manuell: `python -m src.main` startet ohne Fehler; es entsteht (noch) keine `webhooks.json`, weil noch nichts schreibt.

- [ ] **Step 3: Commit**

```
git add src/main.py src/ui.py
git commit -m "feat(app): WebhookStore erzeugen und durchreichen"
```

---

### Task 10: Webhook-Dialog (Anlegen / Bearbeiten / Testen)

Erster sichtbarer Teil. Reine Tk-Schicht — die Validierung kommt aus `webhooks.validate_record` (Task 7), der Testversand aus `webhook.perform_send` (Task 6).

**Files:**
- Create: `src/dialogs/webhook_dialog.py`

**Interfaces:**
- Consumes: `webhooks.new_id`, `webhooks.validate_record`, `webhook.perform_send`, `theme.create_dialog`
- Produces: `open_webhook_dialog(parent, store, runner, record=None, on_saved=None) -> None` — `record=None` legt neu an

- [ ] **Step 1: Write the implementation**

> Kein Test-Schritt: Tk-gebundener Dialogaufbau wird im Projekt bewusst nicht
> automatisiert getestet (`docs/known-limitations.md`). Die Logik, die er
> aufruft, ist in Task 6 und 7 vollständig abgedeckt.

`src/dialogs/webhook_dialog.py`:

```python
"""Anlegen und Bearbeiten eines Webhooks, inklusive Testversand.

Reine Tk-Schicht: Validierung (webhooks.validate_record) und Versand
(webhook.perform_send) liegen Tk-frei in den pure Modulen und sind dort
getestet.
"""

import json
import tkinter as tk

from src import webhook, webhooks
from src.theme import (
    BG, CELL_BG, FONT, FONT_SMALL, TEXT, TEXT_MUTED,
    apply_combobox_style, attach_unfocus_on_click, center_dialog_on_parent,
    create_dialog, dark_combo, dark_entry, primary_button, secondary_button,
    set_secondary_button_enabled, themed_showerror, themed_showinfo,
)

AUTH_LABELS = [
    ("none", "Keine"),
    ("header", "Token im Header (Bearer / API-Key)"),
    ("hmac", "HMAC-Signatur (SHA-256)"),
]


def _mode_for_label(label):
    return next((m for m, lbl in AUTH_LABELS if lbl == label), "none")


def _label_for_mode(mode):
    return next((lbl for m, lbl in AUTH_LABELS if m == mode), AUTH_LABELS[0][1])


def open_webhook_dialog(parent, store, runner, record=None, on_saved=None):
    is_new = record is None
    record = dict(record or {
        "id": webhooks.new_id(), "name": "", "url": "", "enabled": True,
        "payload": {"json": True, "pdf": False}, "auth": {"mode": "none"},
    })
    auth = dict(record.get("auth") or {"mode": "none"})

    dialog = create_dialog(
        parent, "Webhook hinzufügen" if is_new else "Webhook bearbeiten")
    apply_combobox_style(dialog)
    attach_unfocus_on_click(dialog)

    name_var = tk.StringVar(value=record.get("name", ""))
    url_var = tk.StringVar(value=record.get("url", ""))
    enabled_var = tk.BooleanVar(value=bool(record.get("enabled", True)))
    json_var = tk.BooleanVar(value=bool(record.get("payload", {}).get("json")))
    pdf_var = tk.BooleanVar(value=bool(record.get("payload", {}).get("pdf")))
    mode_var = tk.StringVar(value=_label_for_mode(auth.get("mode", "none")))
    header_var = tk.StringVar(value=auth.get("header") or "Authorization")
    value_var = tk.StringVar(value=auth.get("value") or "Bearer ")
    prefix_var = tk.StringVar(value=auth.get("prefix", "sha256="))
    secret_var = tk.StringVar(value=auth.get("secret", ""))

    def _label(text, row, **kw):
        opts = dict(padx=10, pady=6, sticky="w")
        opts.update(kw)
        tk.Label(dialog, text=text, font=FONT, bg=BG, fg=TEXT).grid(
            row=row, column=0, **opts)

    _label("Name:", 0, pady=(14, 6))
    dark_entry(dialog, name_var, width=32).grid(
        row=0, column=1, padx=10, pady=(14, 6), sticky="w")

    _label("URL:", 1)
    dark_entry(dialog, url_var, width=32).grid(
        row=1, column=1, padx=10, pady=6, sticky="w")

    opts_frame = tk.Frame(dialog, bg=BG)
    opts_frame.grid(row=2, column=0, columnspan=2, padx=10, pady=(2, 4), sticky="w")

    def _check(parent_frame, text, var):
        cb = tk.Checkbutton(
            parent_frame, text=text, variable=var, font=FONT,
            bg=BG, fg=TEXT, selectcolor=CELL_BG,
            activebackground=BG, activeforeground=TEXT, cursor="hand2")
        cb.pack(anchor="w")
        return cb

    _check(opts_frame, "Aktiv", enabled_var)
    _check(opts_frame, "Arbeitszeiten als JSON senden", json_var)
    _check(opts_frame, "Bericht als PDF senden", pdf_var)

    _label("Authentifizierung:", 3)
    dark_combo(dialog, mode_var, [lbl for _, lbl in AUTH_LABELS], width=32).grid(
        row=3, column=1, padx=10, pady=6, sticky="w")

    auth_frame = tk.Frame(dialog, bg=BG)
    auth_frame.grid(row=4, column=0, columnspan=2, padx=10, pady=(0, 4), sticky="we")

    def _rebuild_auth_fields(*_a):
        for child in auth_frame.winfo_children():
            child.destroy()
        mode = _mode_for_label(mode_var.get())
        if mode == "none":
            tk.Label(auth_frame,
                     text="Der Endpunkt wird ohne zusätzlichen Header aufgerufen.",
                     font=FONT_SMALL, bg=BG, fg=TEXT_MUTED).grid(
                row=0, column=0, columnspan=2, sticky="w", pady=(0, 4))
            return
        rows = [("Header:", header_var, False)]
        if mode == "header":
            rows.append(("Wert:", value_var, True))
        else:
            rows.append(("Präfix:", prefix_var, False))
            rows.append(("Secret:", secret_var, True))
        for i, (text, var, masked) in enumerate(rows):
            tk.Label(auth_frame, text=text, font=FONT, bg=BG, fg=TEXT).grid(
                row=i, column=0, sticky="w", pady=4)
            entry = dark_entry(auth_frame, var, width=30)
            if masked:
                entry.config(show="•")
            entry.grid(row=i, column=1, padx=(8, 0), pady=4, sticky="w")

    mode_var.trace_add("write", _rebuild_auth_fields)
    _rebuild_auth_fields()

    def _collect():
        mode = _mode_for_label(mode_var.get())
        new_auth = {"mode": mode}
        if mode == "header":
            new_auth.update(header=header_var.get().strip(), value=value_var.get())
        elif mode == "hmac":
            new_auth.update(header=header_var.get().strip(),
                            prefix=prefix_var.get(), secret=secret_var.get())
        return {
            "id": record["id"],
            "name": name_var.get().strip(),
            "url": url_var.get().strip(),
            "enabled": bool(enabled_var.get()),
            "payload": {"json": bool(json_var.get()), "pdf": bool(pdf_var.get())},
            "auth": new_auth,
        }

    def _validated():
        candidate = _collect()
        ok, msg = webhooks.validate_record(candidate, store.get_all())
        if not ok:
            themed_showerror(dialog, "Eingabe unvollständig", msg)
            return None
        return candidate

    def do_save():
        candidate = _validated()
        if candidate is None:
            return
        store.save(candidate)
        dialog.destroy()
        if on_saved:
            on_saved()

    def do_test():
        candidate = _validated()
        if candidate is None:
            return
        set_secondary_button_enabled(test_btn, False)

        sample = {
            "schema_version": webhook.PAYLOAD_SCHEMA_VERSION,
            "kind": "zeiterfassung-report-test",
            "period": {"from": "2026-07-01", "to": "2026-07-01"},
            "total_minutes": 450,
            "entries": {"2026-07-01": {"slots": [
                {"start": "08:00", "end": "16:00", "pause": 30, "kategorie": ""}]}},
        }
        body = json.dumps(sample, ensure_ascii=False).encode("utf-8")

        def fn():
            return webhook.perform_send(
                candidate,
                json_bytes=body if candidate["payload"]["json"] else None,
                pdf_bytes=b"%PDF-1.4\n% Testversand\n"
                if candidate["payload"]["pdf"] else None,
                pdf_filename="Zeiterfassung_Test.pdf")

        def on_done(res):
            if not dialog.winfo_exists():
                return
            set_secondary_button_enabled(test_btn, True)
            if res.get("ok"):
                themed_showinfo(
                    dialog, "Test erfolgreich",
                    f"Der Endpunkt hat mit HTTP {res['status']} geantwortet.")
                return
            from src.dialogs.send_task import format_result_summary
            themed_showerror(
                dialog, "Test fehlgeschlagen",
                format_result_summary(
                    [{"name": candidate["name"], "ok": False,
                      "kind": res.get("kind"), "detail": res.get("detail")}]))

        runner.run(fn, on_done)

    btn_frame = tk.Frame(dialog, bg=BG)
    btn_frame.grid(row=5, column=0, columnspan=2, pady=14)
    primary_button(btn_frame, "Speichern", do_save).pack(side=tk.LEFT, padx=5)
    test_btn = secondary_button(btn_frame, "Testen", do_test)
    test_btn.pack(side=tk.LEFT, padx=5)
    secondary_button(btn_frame, "Abbrechen", dialog.destroy).pack(side=tk.LEFT, padx=5)

    dialog.bind("<Escape>", lambda _e: dialog.destroy())
    center_dialog_on_parent(dialog, parent)
```

- [ ] **Step 2: Verify manually**

`ruff check .` und `pyright` müssen grün sein. Der Dialog ist erst nach Task 11 erreichbar; hier nur die statische Prüfung.

- [ ] **Step 3: Commit**

```
git add src/dialogs/webhook_dialog.py
git commit -m "feat(webhook-dialog): Anlegen, Bearbeiten und Testversand"
```

---

### Task 11: Settings-Tab „Webhooks"

**Files:**
- Create: `src/dialogs/settings_dialog/tab_webhooks.py`
- Modify: `src/dialogs/settings_dialog/dialog.py` (Notebook + `tabs`-Dict)
- Modify: `src/ui.py` (`open_settings_dialog(...)`-Aufruf um `webhook_store=` erweitern)

**Interfaces:**
- Consumes: `WebhookStore` (Task 7), `open_webhook_dialog` (Task 10)
- Produces: `WebhooksTab(frame, dialog, store, runner)` mit Attribut `.frame`

> **Wichtig:** Dieser Tab exponiert **keine** Variablen für `save_settings` — er
> ist der erste Tab ohne diesen Vertrag. Webhooks werden vom Unterdialog direkt
> im Store gespeichert; der zentrale Settings-Save-Pfad ist auf skalare
> Tk-Variablen ausgelegt.

- [ ] **Step 1: Write the implementation**

`src/dialogs/settings_dialog/tab_webhooks.py`:

```python
"""Tab „Webhooks": Liste der konfigurierten HTTP-Ziele.

Anders als die übrigen Tabs exponiert dieser KEINE Variablen für
save_settings — Webhooks liegen in ihrem eigenen, gerätelokalen Store und
werden vom Unterdialog direkt gespeichert.
"""

import tkinter as tk
from urllib.parse import urlsplit

from src.dialogs.webhook_dialog import open_webhook_dialog
from src.theme import (
    BG, CELL_BG, FONT, FONT_SMALL, TEXT, TEXT_MUTED,
    primary_button, secondary_button, themed_askyesno,
)


class WebhooksTab:
    def __init__(self, frame, dialog, store, runner):
        self.frame = frame
        self._dialog = dialog
        self._store = store
        self._runner = runner

        tk.Label(
            frame,
            text=("Der Bericht kann zusätzlich zur E-Mail an HTTP-Endpunkte "
                  "gesendet werden.\nWebhooks gelten nur auf diesem Gerät."),
            font=FONT_SMALL, bg=BG, fg=TEXT_MUTED, justify="left",
        ).grid(row=0, column=0, padx=10, pady=(10, 6), sticky="w")

        self._listbox = tk.Listbox(
            frame, height=8, width=48, font=FONT,
            bg=CELL_BG, fg=TEXT, selectbackground=TEXT_MUTED,
            highlightthickness=0, borderwidth=0, activestyle="none",
        )
        self._listbox.grid(row=1, column=0, padx=10, pady=(0, 8), sticky="we")
        self._listbox.bind("<Double-Button-1>", lambda _e: self._edit())

        btns = tk.Frame(frame, bg=BG)
        btns.grid(row=2, column=0, padx=10, pady=(0, 10), sticky="w")
        primary_button(btns, "Hinzufügen", self._add).pack(side=tk.LEFT, padx=(0, 6))
        secondary_button(btns, "Bearbeiten", self._edit).pack(side=tk.LEFT, padx=6)
        secondary_button(btns, "Entfernen", self._remove).pack(side=tk.LEFT, padx=6)

        self._records = []
        self.refresh()

    def refresh(self):
        self._records = self._store.get_all() if self._store else []
        self._listbox.delete(0, tk.END)
        for record in self._records:
            host = urlsplit(record.get("url", "")).hostname or "?"
            mark = "✓" if record.get("enabled") else "○"
            self._listbox.insert(tk.END, f"  {mark}  {record.get('name', '')}  —  {host}")

    def _selected(self):
        selection = self._listbox.curselection()
        return self._records[selection[0]] if selection else None

    def _add(self):
        if not self._store:
            return
        open_webhook_dialog(self._dialog, self._store, self._runner,
                            on_saved=self.refresh)

    def _edit(self):
        record = self._selected()
        if record is None:
            return
        open_webhook_dialog(self._dialog, self._store, self._runner,
                            record=record, on_saved=self.refresh)

    def _remove(self):
        record = self._selected()
        if record is None:
            return
        if not themed_askyesno(
                self._dialog, "Webhook entfernen",
                f"„{record.get('name', '')}“ wirklich entfernen?"):
            return
        self._store.delete(record["id"])
        self.refresh()
```

In `src/dialogs/settings_dialog/dialog.py`:

```python
from src.dialogs.settings_dialog.tab_webhooks import WebhooksTab
```

Signatur um `webhook_store=None` erweitern, Frame und Notebook-Eintrag neben den übrigen anlegen:

```python
tab_webhooks = tk.Frame(notebook, bg=BG)
notebook.add(tab_webhooks, text="Webhooks")
```

(direkt **nach** `notebook.add(tab_mail, …)`), dann:

```python
hooks = WebhooksTab(tab_webhooks, dialog, webhook_store, runner)
```

und in das `tabs`-Dict `"webhooks": hooks.frame` aufnehmen. In `save_settings`
wird der Tab **nicht** angefasst.

In `src/ui.py` beim Öffnen des Settings-Dialogs `webhook_store=self._webhook_store` mitgeben.

- [ ] **Step 2: Verify manually**

- `pytest -q` — insbesondere `tests/test_settings_dialog.py` muss grün bleiben.
- `ruff check .`, `pyright`
- `python -m src.main` → Einstellungen öffnen: Tab „Webhooks" ist da; Hinzufügen legt einen Eintrag an, `webhooks.json` entsteht im Repo-Verzeichnis; Bearbeiten und Entfernen funktionieren; ein Neustart zeigt den Eintrag wieder.
- Gegenprobe URL-Regel: `http://example.com/x` speichern → Fehlermeldung mit https-Hinweis; `http://192.168.1.10/x` → speichert kommentarlos.

- [ ] **Step 3: Commit**

```
git add src/dialogs/settings_dialog/tab_webhooks.py src/dialogs/settings_dialog/dialog.py src/ui.py
git commit -m "feat(settings): Tab fuer Webhooks"
```

---

### Task 12: Ziel-Auswahl und Ergebnis-Anzeige im Sende-Dialog

Der letzte funktionale Baustein. Zwei Verhaltensänderungen im bestehenden Dialog, die leicht zu übersehen sind:

1. **Der Empfänger-Check darf nicht mehr blind abbrechen.** Heute beendet ein leerer `recipient` den Dialog, bevor er aufgeht. Mit konfigurierten Webhooks muss er stattdessen aufgehen — mit deaktivierter Mail-Zeile.
2. **Die „Keine Einträge"-Prüfung wandert.** Sie fällt heute als Nebenwirkung davon an, dass `generate_report` `None` liefert. Ohne Mail-Kanal gäbe es dieses Signal nicht, und ein Webhook bekäme ein Dokument mit leerem `entries`.

**Files:**
- Modify: `src/dialogs/send_dialog.py`
- Modify: `src/ui.py` (`open_send_dialog(...)` um `webhook_store=` erweitern)

**Interfaces:**
- Consumes: `send_task.perform_send`, `send_task.format_result_summary` (Task 8), `report.filter_period`/`filter_categories` (Task 3)
- Produces: nichts für spätere Tasks

- [ ] **Step 1: Write the implementation**

In `src/dialogs/send_dialog.py`:

1. Signatur um `webhook_store=None` erweitern.
2. Den frühen Abbruch bei leerem Empfänger ersetzen:

```python
    hooks = webhook_store.enabled() if webhook_store else []
    recipient = settings.get("recipient")
    if not recipient and not hooks:
        themed_showinfo(
            parent, "Kein Empfänger",
            "Bitte zuerst einen Empfänger in den Einstellungen angeben.")
        return
```

Der `credentials.json`-Check bleibt, wird aber ebenfalls nur wirksam, wenn Mail überhaupt möglich ist:

```python
    mail_possible = bool(recipient) and os.path.exists(credentials_path)
    if not mail_possible and not hooks:
        show_missing_credentials_dialog(parent, base_path)
        return
```

3. Ziel-Block bauen (nur wenn `hooks` nicht leer ist — sonst bleibt der Dialog optisch identisch zu heute):

```python
    FORMAT_LABELS = {(True, False): "JSON", (False, True): "PDF",
                     (True, True): "JSON + PDF"}
    _FORMAT_BY_LABEL = {v: k for k, v in FORMAT_LABELS.items()}

    mail_var = tk.BooleanVar(value=mail_possible)
    hook_vars = []

    if hooks:
        targets = tk.LabelFrame(dialog, text="Ziele", font=FONT, bg=BG, fg=TEXT_MUTED)
        targets.grid(row=1, column=0, padx=10, pady=(4, 0), sticky="we")

        mail_cb = tk.Checkbutton(
            targets, text=f"E-Mail an {recipient}" if recipient else "E-Mail (kein Empfänger)",
            variable=mail_var, font=FONT, bg=BG, fg=TEXT, selectcolor=CELL_BG,
            activebackground=BG, activeforeground=TEXT, cursor="hand2")
        mail_cb.grid(row=0, column=0, sticky="w", padx=6, pady=2)
        if not mail_possible:
            mail_var.set(False)
            mail_cb.config(state="disabled")

        for i, record in enumerate(hooks, start=1):
            var = tk.BooleanVar(value=True)
            tk.Checkbutton(
                targets, text=record.get("name", ""), variable=var, font=FONT,
                bg=BG, fg=TEXT, selectcolor=CELL_BG, activebackground=BG,
                activeforeground=TEXT, cursor="hand2",
            ).grid(row=i, column=0, sticky="w", padx=6, pady=2)

            payload = record.get("payload") or {}
            current = (bool(payload.get("json")), bool(payload.get("pdf")))
            fmt_var = tk.StringVar(value=FORMAT_LABELS.get(current, "JSON"))
            dark_combo(targets, fmt_var, list(_FORMAT_BY_LABEL), width=12).grid(
                row=i, column=1, sticky="w", padx=(12, 6), pady=2)
            hook_vars.append((record, var, fmt_var))
```

(Der Button-Frame rutscht dadurch von `row=1` auf `row=2`.)

4. In `do_send` die Leer-Prüfung kanalunabhängig **vor** allem anderen machen:

```python
        from src.report import filter_categories, filter_period

        ranged = filter_period(date_from, date_to, entries)
        if ranged is not None:
            ranged = filter_categories(ranged, categories)
        if not ranged:
            themed_showinfo(
                dialog, "Keine Einträge",
                f"Keine Einträge für {format_date(date_from)} – "
                f"{format_date(date_to)} vorhanden.")
            return
```

Danach `generate_report` **nur** noch aufrufen, wenn Mail gewählt ist; sein
`None`-Zweig bleibt als Sicherheitsnetz erhalten.

5. Ziele einsammeln und an den Dispatcher geben:

```python
        selected_hooks = []
        for record, var, fmt_var in hook_vars:
            if not var.get():
                continue
            want_json, want_pdf = _FORMAT_BY_LABEL[fmt_var.get()]
            selected_hooks.append(
                {"record": record, "json": want_json, "pdf": want_pdf})

        send_mail = bool(mail_var.get())
        if not send_mail and not selected_hooks:
            themed_showerror(dialog, "Kein Ziel gewählt",
                             "Bitte mindestens ein Ziel auswählen.")
            return

        def fn():
            return perform_send(
                date_from=date_from, date_to=date_to, entries=entries,
                name=settings.get("name"), categories=categories,
                category_breakdown=category_breakdown,
                send_mail=send_mail,
                mail={
                    "credentials_path": credentials_path,
                    "token_path": token_path,
                    "recipient": recipient, "subject": subject, "html": html,
                    "sync_enabled": settings.get("sync_enabled"),
                    "gcal_enabled": settings.get("gcal_enabled"),
                } if send_mail else None,
                webhooks=selected_hooks,
                pdf_filename=pdf_filename, settings=settings)
```

6. `on_done` auf die Ergebnisliste umstellen:

```python
        def on_done(res):
            results = res["results"]
            if all(r["ok"] for r in results):
                if dialog.winfo_exists():
                    dialog.destroy()
                themed_showinfo(
                    parent, "Gesendet",
                    f"Bericht für {label} gesendet:\n\n"
                    + format_result_summary(results))
                return

            busy["running"] = False
            alive = dialog.winfo_exists()
            target = dialog if alive else parent
            if alive:
                set_primary_button_enabled(send_btn, True)
                set_button_text(send_btn, "Senden")

            themed_showerror(
                target, "Nicht alles konnte gesendet werden",
                format_result_summary(results))

            # Unerwartete Fehler zusätzlich roh mit Traceback — themed Dialoge
            # bauen selbst Tk-Widgets auf und sind im gestörten Zustand die
            # unzuverlässigere Schicht (CLAUDE.md).
            for r in results:
                if r.get("kind") == "error" and r.get("tb"):
                    messagebox.showerror(
                        "Senden fehlgeschlagen",
                        f"{r['name']}: {type(r['error']).__name__}: "
                        f"{r['error']}\n\n{r['tb']}",
                        parent=target)
```

7. Imports ergänzen: `CELL_BG`, `TEXT_MUTED`, `dark_combo` aus `src.theme`; `format_result_summary` aus `src.dialogs.send_task`.

In `src/ui.py` beim Aufruf `open_send_dialog(...)` ein `webhook_store=self._webhook_store` mitgeben.

- [ ] **Step 2: Verify manually**

- `pytest -q`, `ruff check .`, `pyright` — alles grün.
- `python -m src.main`, ohne konfigurierten Webhook: Sende-Dialog sieht aus wie zuvor, kein Ziel-Block.
- Mit einem Webhook (Testendpunkt, z.B. `http://127.0.0.1:8000/hook` und ein `python -m http.server`-Ersatz, der POSTs annimmt): Ziel-Block erscheint, Format-Combobox ist vorbelegt, Versand meldet beide Kanäle.
- Webhook auf eine tote Adresse zeigen lassen: Mail geht raus, Zusammenfassung zeigt ✓ für Mail und ✗ mit Begründung für den Webhook, der Dialog bleibt offen.
- Zeitraum ohne Einträge wählen: „Keine Einträge", auch wenn nur ein Webhook angehakt ist.

- [ ] **Step 3: Commit**

```
git add src/dialogs/send_dialog.py src/ui.py
git commit -m "feat(send-dialog): Ziel-Auswahl und Ergebnis-Zusammenfassung"
```

---

### Task 13: Dokumentation

**Files:**
- Modify: `CLAUDE.md` (Modul-Liste im Abschnitt „Struktur")
- Modify: `src/CLAUDE.md` (Persistenz-Schicht, `secure_file`-Absatz, Dialoge, Dispatcher-Vertrag)
- Modify: `docs/known-limitations.md` (neuer Abschnitt)
- Modify: `README.md` (Versandwege)

- [ ] **Step 1: `docs/known-limitations.md` ergänzen**

Neuer Abschnitt am Ende, im Stil der vorhandenen:

```markdown
## Webhooks: Split-Horizon-DNS gilt als öffentliche Adresse

Der Webhook-Versand erlaubt unverschlüsseltes `http://` nur für Adressen im
lokalen Netz (Loopback, RFC 1918, CGNAT, Link-Local, IPv6-ULA, die Suffixe
`.local`/`.lan`/`.home.arpa`/`.internal` und Single-Label-Namen). Für alles
andere ist `https://` Pflicht — sonst gingen Arbeitszeiten und, je nach
Konfiguration, ein Bearer-Token im Klartext durchs Netz.

Entschieden wird **allein an der Adresse in der URL**, ohne DNS-Auflösung.
Ein öffentlicher Name, der per Split-Horizon-DNS intern auf eine private
Adresse zeigt (`erp.firma.de` → `10.0.0.5`), gilt deshalb als öffentlich und
verlangt https, obwohl der Verkehr das lokale Netz nie verlässt.

**Warum nicht auflösen:** ein DNS-Lookup beim Speichern wäre langsam, offline
unmöglich und könnte später still anders ausgehen, ohne dass die App es
bemerkt — die Adresse wäre dann nach der einmaligen Prüfung dauerhaft als
„privat" eingestuft, auch wenn sie längst nach außen zeigt.

**Umgehung:** die interne Adresse direkt eintragen (`http://10.0.0.5/hook`).

Design: [`superpowers/specs/2026-08-26-webhook-versand-design.md`](superpowers/specs/2026-08-26-webhook-versand-design.md)
```

- [ ] **Step 2: `CLAUDE.md` ergänzen**

In der Modul-Liste, alphabetisch/thematisch passend neben `src/share.py`:

```markdown
- `src/webhook.py` — pure Logik des Webhook-Versands (Tk-frei, stdlib-only):
  URL-Regel (https außerhalb des lokalen Netzes), Auth-Header, HMAC-Signatur,
  JSON-Dokument (`kind: zeiterfassung-report`, Slot-Shape wie Share v3),
  Request-Body (JSON / PDF / multipart), POST mit Redirect-Schema-Schutz und
  eigener Fehlerklassifikation. **Eigener** Klassifikator statt
  `mail_task.classify_mail_error`, weil `urllib.error.HTTPError` von
  `URLError` erbt und dort als Offline-Symptom gilt — ein HTTP 500 würde sonst
  als „keine Internetverbindung" gemeldet.
- `src/webhooks.py` — gerätelokaler Store der Webhook-Konfiguration
  (`webhooks.json`). Enthält Konfiguration **und** Secrets und wird deshalb wie
  `token.json` gehärtet geschrieben; reist bewusst **nicht** per Drive-Sync.
```

Beim Abschnitt „UTF-8 im Mail-Pipeline" bzw. in der Nähe der Versand-Beschreibung ein Hinweis, dass `send_task.perform_send` ein Dispatcher über Mail und Webhooks ist.

- [ ] **Step 3: `src/CLAUDE.md` ergänzen**

- In der Daten-/Persistenz-Schicht `webhooks.py` aufnehmen (gerätelokal, gehärtet, nicht im Sync-Doc).
- Im `secure_file.py`-Absatz „zwei lokal abgelegte Secrets" auf **drei** korrigieren und `webhooks.json` als dritten Schreibpfad nennen.
- Im Threading-/Dialog-Absatz ergänzen, dass `send_dialog` seinen Worker über einen Dispatcher fährt, der pro Kanal ein Result liefert und nie wirft.
- Bei den Dialogen `webhook_dialog` und den Tab `tab_webhooks` nennen — mit dem Hinweis, dass Letzterer als einziger Tab **keine** Variablen an `save_settings` exponiert.

- [ ] **Step 4: `README.md` ergänzen**

Bei den Versandwegen einen Satz: der Bericht lässt sich zusätzlich zur E-Mail an konfigurierbare HTTP-Endpunkte senden (JSON und/oder PDF, optional mit Token oder HMAC-Signatur; gerätelokal konfiguriert).

- [ ] **Step 5: Verify**

Run: `pytest -q ; ruff check .`
Expected: PASS

- [ ] **Step 6: Commit**

```
git add CLAUDE.md src/CLAUDE.md docs/known-limitations.md README.md
git commit -m "docs: Webhook-Versand dokumentieren"
```

---

## Abschluss

Nach Task 13:

- `pytest`, `ruff check .` und `pyright` grün.
- Manuelle Gegenprobe des kompletten Pfads laut Task 12.
- Für den Release-PR: `src/version.py` bumpen, `CHANGELOG.md` ergänzen, `release:minor` als Label setzen (neues Feature, keine Breaking Change).
- **Kein** Pre-Release nötig: der Code ist plattformneutral (stdlib-`urllib`), es gibt keinen macOS-/Linux-spezifischen Zweig. Einzige plattformabhängige Stelle ist `harden_windows_acl`, das bereits durch die bestehenden `secure_file`-Tests und den Token-Pfad abgedeckt ist.
