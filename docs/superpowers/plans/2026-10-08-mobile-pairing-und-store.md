# Mobile Erfassung, Teil 1: Pairing-Regeln und Gerätestore — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Die beiden reinen Grundbausteine der Handy-Erfassung (#221): der Einmalcode zum Koppeln samt Gerätetoken-Regeln (`mobile_pairing`) und die gerätelokale Datei der gekoppelten Handys (`mobile_store`). Noch kein Server, keine Oberfläche, kein Sync.

**Architecture:** `mobile_pairing.py` ist rein (kein I/O, Uhr als Parameter); `mobile_store.py` ist nur Dateimechanik über `json_store` (Muster `smtp_store`, eigener Lock). Die Datensätze tragen nur den SHA-256-Hash der Gerätetoken.

**Tech Stack:** Python 3.12, stdlib. Keine neue Abhängigkeit.

**Spec:** `docs/superpowers/specs/2026-10-08-mobile-pwa-design.md` (Abschnitte „Bausteine", „Pairing und Token"). Teil 1 von 8 des PR-Zuschnitts dort (Punkt 2).

**Voraussetzung:** Der API-Stack (#234–#247) ist gemergt. `mobile_store` nutzt `json_store.quarantine_corrupt(path, reason)` aus #247 und die Listen `removal.CREDENTIAL_FILES`/`installer.iss`/`.gitignore`, in denen `api-token` bereits steht (die Edits in Task 4 haken daran ein).

**Branching:** `feat/mobile-pairing` vom dann aktuellen `master`; der PR zielt auf `master`, trägt `Refs #221`, kein `Closes`. Kein Versionsbump.

## Entscheidungen (mit dem Nutzer abgestimmt, siehe Spec)

- Einmalcode: 8 Zeichen aus 31 (Ziffern 2–9, Buchstaben ohne I, L, O), 5 Minuten, einmal einlösbar, nach 5 Fehlversuchen gesperrt. Gerätetoken: 256 Bit, nur als SHA-256-Hash gespeichert, 30 Tage ab der letzten Nutzung, ein erneuertes Token lässt das alte 10 Minuten gelten. Widerruf: der Datensatz bleibt erhalten (Antwort `token_revoked` statt `unauthorized`).

## Rulings aus der Planung

- **Der Store schreibt ohne ACL-Härtung.** Die Datei enthält keine Geheimnisse im Klartext, nur Hashes von 256-Bit-Zufallstoken; ein `icacls`-Aufruf bei jedem Abgleich (`last_seen`, `last_pull_at`, Token-Erneuerung) wäre unnötige Last. Unter POSIX hat die Datei über `mkstemp` trotzdem 0600; sie steht in `removal`, `installer.iss` und `.gitignore`.
- **Der fünfte Fehlversuch ist noch `INVALID`,** danach antwortet die Sitzung `LOCKED`, bis `open()` einen neuen Code erzeugt. `close()` hebt die Sperre auf (ohne Code gilt wieder „kein Code aktiv" = `INVALID`).
- **`renew(..., keep_previous=True)`** bei einer Anfrage, die mit dem **vorherigen** Token kam: ginge die Antwort mit dem neuen Token ein zweites Mal verloren, sperrte sonst das noch nie übergebene aktuelle Token das alte aus.
- **Erneutes Koppeln** (`issue_device(..., existing=...)`) behält `created_at` und `last_pull_at` (die Identität im Sync ändert sich nicht) und hebt einen Widerruf auf.
- **Zeitstempel sind Text im festen Format** `YYYY-MM-DDTHH:MM:SSZ` (nur dann ist der String-Vergleich korrekt). Der Store überspringt beim Laden Datensätze mit anderem Format: ein handbearbeitetes `expires_at: "zzzz"` liefe sonst nie ab.
- **Geräte-ID und Name vom Handy sind Fremddaten** (`normalize_device_id`, `clean_device_name`); eine Obergrenze für die Zahl der Geräte gibt es nicht (Koppeln braucht einen Code am Desktop, YAGNI).
- **Die Uhr des Codes ist `time.monotonic`** (unempfindlich gegen Uhrsprünge), die der Gerätedatensätze der UTC-Text, den der Aufrufer mit `utc_now_iso()` liefert.

## Global Constraints

- Tk-frei, stdlib-only, vollständig annotiert (beide Module kommen in `ANNOTATED_MODULES`); `ruff check .` und `pyright 1.1.411` sauber.
- Weder Code noch Token noch Token-Hash stehen im Log; beim Überspringen eines Datensatzes nur `id` und Name.
- Jeder `except` ist eng (`OSError`) und begründet; `except BaseException` nur zum Zurückrollen mit `raise`.
- Die Datei `mobile_devices.json` gehört weder in `SYNCED_SETTING_KEYS` noch ins Sync- oder Share-Doc.

## Review Focus

1. **Code-Raum und Zeit:** Alphabet ohne Verwechselbares, genau 31 Zeichen; Ablauf exakt bei 300 s; ein Fehlversuch mit Müll (`None`, Zahl, Unicode-Ziffern) zählt wie ein falscher Code. Task 1.
2. **Nebenläufigkeit:** von vielen gleichzeitigen `redeem`-Aufrufen gewinnt genau einer. Task 1.
3. **Token-Zustände:** `ok`/`expired`/`revoked`/`unauthorized` sind scharf getrennt; die Karenz gilt nur für das *vorherige* Token, nie nach dem Widerruf, und bei zwei verlorenen Antworten in Folge sperrt sich das Handy nicht aus. Task 2.
4. **Fremddaten:** Token der Länge 0 oder 5000, Bytes, Listen, Lone Surrogates werfen nie; Geräte-ID und Name werden normalisiert. Task 2.
5. **Store gegen kaputte Dateien:** kein Absturz bei Müll in der Datei (Nicht-Objekt, falsche Typen, falsches Hash- oder Zeitformat), nie ein Hash im Log, eine neuere `schema_version` oder ein Lesefehler überschreibt die Datei nicht. Task 3.
6. **Keine Klartext-Token auf der Platte,** auch nicht beim erneuerten Token. Task 3.

---

### Task 1: Einmalcode: `generate_code`, `normalize_code`, `PairingSession`

**Interfaces:** Produces: `CODE_ALPHABET` (31 Zeichen), `generate_code() -> str`, `format_code(code) -> str`, `normalize_code(raw: object) -> str | None`, `RedeemResult` (`OK`/`INVALID`/`LOCKED`), `PairingSession(clock=time.monotonic, *, ttl_seconds=300, max_failures=5)` mit `open() -> str`, `close()`, `is_active()`, `seconds_left()`, `redeem(raw) -> RedeemResult`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_mobile_pairing.py`:

```python
# tests/test_mobile_pairing.py
import threading

import pytest

from src import mobile_pairing as mp
from src.mobile_pairing import PairingSession, RedeemResult


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


# --- Code -------------------------------------------------------------------------------

def test_the_alphabet_has_31_unambiguous_characters():
    assert len(mp.CODE_ALPHABET) == 31 and len(set(mp.CODE_ALPHABET)) == 31
    assert not set("01ILO") & set(mp.CODE_ALPHABET)


def test_a_generated_code_has_eight_characters_from_the_alphabet():
    for _ in range(200):
        code = mp.generate_code()
        assert len(code) == 8 and set(code) <= set(mp.CODE_ALPHABET)


def test_generated_codes_differ():
    assert len({mp.generate_code() for _ in range(200)}) == 200


def test_format_code_puts_a_dash_in_the_middle():
    assert mp.format_code("K7M29QXA") == "K7M2-9QXA"


@pytest.mark.parametrize("raw", ["K7M2-9QXA", "k7m2-9qxa", " K7M29QXA ", "K7M2 9QXA", "K7-M2-9Q-XA"])
def test_normalize_accepts_case_dashes_and_spaces(raw):
    assert mp.normalize_code(raw) == "K7M29QXA"


@pytest.mark.parametrize("raw", [
    None, 5, b"K7M29QXA", "", "K7M2-9QX", "K7M2-9QXAA", "K7M2-9QX0", "K7M2-9QXO", "K7M2-9QX1",
    "K7M2-9QXI", "K7M2-9QXL", "K7M2-9QXÄ", "٢" * 8, "A" * 5000, "K7M2-9QX\n",
])
def test_normalize_rejects_anything_that_cannot_be_a_code(raw):
    assert mp.normalize_code(raw) is None


# --- PairingSession ---------------------------------------------------------------------

def test_no_code_is_active_before_open():
    session = PairingSession(FakeClock())
    assert not session.is_active() and session.seconds_left() == 0
    assert session.redeem("K7M2-9QXA") is RedeemResult.INVALID


def test_open_returns_a_formatted_code_that_redeems_once():
    session = PairingSession(FakeClock())
    shown = session.open()

    assert len(shown) == 9 and shown[4] == "-"
    assert session.is_active()
    assert session.redeem(shown) is RedeemResult.OK
    assert not session.is_active()
    assert session.redeem(shown) is RedeemResult.INVALID                # verbraucht


def test_the_code_is_accepted_in_any_spelling():
    session = PairingSession(FakeClock())
    shown = session.open()
    assert session.redeem(shown.lower().replace("-", " ")) is RedeemResult.OK


def test_the_code_expires_after_five_minutes_exactly():
    clock = FakeClock()
    session = PairingSession(clock)
    shown = session.open()
    clock.advance(299)
    assert session.is_active() and session.seconds_left() == 1
    clock.advance(1)                                                     # 300 s: abgelaufen
    assert not session.is_active() and session.seconds_left() == 0
    assert session.redeem(shown) is RedeemResult.INVALID


def test_five_wrong_attempts_lock_the_session_until_the_next_open():
    session = PairingSession(FakeClock())
    shown = session.open()

    results = [session.redeem("AAAA-AAAA") for _ in range(5)]
    assert results == [RedeemResult.INVALID] * 5                          # der fünfte ist noch INVALID
    assert session.redeem("AAAA-AAAA") is RedeemResult.LOCKED
    assert session.redeem(shown) is RedeemResult.LOCKED                   # auch der richtige Code
    assert not session.is_active()

    fresh = session.open()                                                # neuer Code hebt die Sperre auf
    assert session.redeem(fresh) is RedeemResult.OK


def test_four_wrong_attempts_do_not_lock():
    session = PairingSession(FakeClock())
    shown = session.open()
    for _ in range(4):
        session.redeem("AAAA-AAAA")
    assert session.redeem(shown) is RedeemResult.OK


def test_malformed_input_counts_as_a_failed_attempt():
    session = PairingSession(FakeClock())
    session.open()
    for raw in (None, 5, "", "zu kurz", "٢" * 8):
        session.redeem(raw)
    assert session.redeem("AAAA-AAAA") is RedeemResult.LOCKED


def test_close_invalidates_the_code_and_clears_a_lock():
    session = PairingSession(FakeClock())
    shown = session.open()
    session.close()
    assert session.redeem(shown) is RedeemResult.INVALID
    for _ in range(5):
        session.open()
        session.redeem("AAAA-AAAA")
    session.close()
    assert session.redeem("AAAA-AAAA") is RedeemResult.INVALID            # nicht LOCKED


def test_reopening_replaces_the_old_code():
    session = PairingSession(FakeClock())
    first = session.open()
    second = session.open()
    assert first != second
    assert session.redeem(first) is RedeemResult.INVALID
    assert session.redeem(second) is RedeemResult.OK


def test_exactly_one_of_many_concurrent_redeems_wins():
    session = PairingSession()
    shown = session.open()
    results = []

    def attempt():
        results.append(session.redeem(shown))

    threads = [threading.Thread(target=attempt) for _ in range(40)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert results.count(RedeemResult.OK) == 1
```

- [ ] **Step 2: Run to verify they fail**

Run: `python3 -m pytest -q -p no:cacheprovider -x`
Expected: ERROR beim Sammeln: `ModuleNotFoundError: No module named 'src.mobile_pairing'`.

- [ ] **Step 3: Implement**

Create `src/mobile_pairing.py`:

```python
# src/mobile_pairing.py
"""Pairing-Code und Gerätetoken der Handy-Erfassung (#221), Tk-frei und stdlib-only.

Rein: kein Dateizugriff, kein Socket. Die Uhr kommt als Parameter herein
(`clock` für die Laufzeit des Codes, `now` als UTC-Text `YYYY-MM-DDTHH:MM:SSZ`
für die Gerätedatensätze), damit alles ohne `sleep` testbar ist. Persistiert
werden die Datensätze von `mobile_store`; der Server (`mobile_routes`) ruft hier
nur auf.

Zwei Dinge liegen hier:

- **Der Einmalcode** (`PairingSession`): 8 Zeichen aus 31, 5 Minuten gültig, einmal
  einlösbar, nach 5 Fehlversuchen gesperrt. Er steht nur im Hauptspeicher.
- **Das Gerätetoken** (`issue_device`, `renew`, `authenticate`): 256 Bit Zufall,
  im Datensatz nur als SHA-256-Hash. 30 Tage ab der letzten Nutzung (Sliding
  Expiration); jede Erneuerung lässt das alte Token noch 10 Minuten gelten, damit
  eine verlorene Antwort das Handy nicht aussperrt.

Geräte-ID, Name und Token kommen vom Handy — Fremddaten.
"""
from __future__ import annotations

import enum
import hmac
import secrets
import threading
import time
from collections.abc import Callable

# Ziffern 2–9 und Buchstaben ohne I, L, O: 31 Zeichen, keine Verwechslung 0/O, 1/I/L.
CODE_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"
CODE_LENGTH = 8
CODE_TTL_SECONDS = 300
MAX_CODE_FAILURES = 5
_MAX_RAW_CODE_LENGTH = 32



def generate_code() -> str:
    """Ein frischer Code in kanonischer Form (8 Zeichen, ohne Bindestrich)."""
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))


def format_code(code: str) -> str:
    """`K7M29QXA` → `K7M2-9QXA` (Anzeige und QR-Code)."""
    half = CODE_LENGTH // 2
    return f"{code[:half]}-{code[half:]}"


def normalize_code(raw: object) -> str | None:
    """Die kanonische Form einer Eingabe, oder `None`, wenn sie kein möglicher
    Code ist. Groß-/Kleinschreibung, Bindestriche und Leerzeichen sind egal; ein
    Zeichen außerhalb des Alphabets (auch `0`, `O`, `1`, `I`, `L`) ist ungültig."""
    if not isinstance(raw, str) or len(raw) > _MAX_RAW_CODE_LENGTH:
        return None
    code = raw.strip().upper().replace("-", "").replace(" ", "")
    if len(code) != CODE_LENGTH or any(ch not in CODE_ALPHABET for ch in code):
        return None
    return code


class RedeemResult(enum.Enum):
    OK = "ok"
    INVALID = "invalid"      # falsch, abgelaufen, verbraucht oder gar kein Code aktiv
    LOCKED = "locked"        # zu viele Fehlversuche, bis zum nächsten `open()`


class PairingSession:
    """Der eine aktive Einmalcode. Thread-sicher: `redeem` kommt aus
    Server-Threads, `open`/`close` aus dem UI-Thread."""

    def __init__(self, clock: Callable[[], float] = time.monotonic, *,
                 ttl_seconds: float = CODE_TTL_SECONDS,
                 max_failures: int = MAX_CODE_FAILURES) -> None:
        self._clock = clock
        self._ttl = ttl_seconds
        self._max_failures = max_failures
        self._lock = threading.Lock()
        self._code: str | None = None
        self._expires = 0.0
        self._failures = 0
        self._locked = False

    def open(self) -> str:
        """Erzeugt einen neuen Code (der alte verfällt, Sperre und Zähler werden
        zurückgesetzt) und liefert ihn formatiert."""
        with self._lock:
            self._code = generate_code()
            self._expires = self._clock() + self._ttl
            self._failures = 0
            self._locked = False
            return format_code(self._code)

    def close(self) -> None:
        """Macht den Code ungültig (Dialog geschlossen)."""
        with self._lock:
            self._code = None
            self._failures = 0
            self._locked = False

    def is_active(self) -> bool:
        with self._lock:
            return self._active_locked()

    def seconds_left(self) -> int:
        with self._lock:
            if not self._active_locked():
                return 0
            return max(0, int(self._expires - self._clock()))

    def _active_locked(self) -> bool:
        if self._code is None:
            return False
        if self._clock() >= self._expires:
            self._code = None
            return False
        return True

    def redeem(self, raw: object) -> RedeemResult:
        """Löst den Code ein. Bei Erfolg ist er verbraucht. Der Fehlversuch, der den
        Zähler erschöpft, ist selbst noch `INVALID`; danach antwortet die Sitzung
        `LOCKED`, bis ein neuer Code geöffnet wird."""
        with self._lock:
            if self._locked:
                return RedeemResult.LOCKED
            if not self._active_locked() or self._code is None:
                return RedeemResult.INVALID
            candidate = normalize_code(raw) or "-" * CODE_LENGTH
            # Immer vergleichen, auch bei einer Form, die nie passen kann: gleiche Laufzeit.
            if hmac.compare_digest(candidate.encode("ascii"), self._code.encode("ascii")):
                self._code = None
                self._failures = 0
                return RedeemResult.OK
            self._failures += 1
            if self._failures >= self._max_failures:
                self._code = None
                self._locked = True
            return RedeemResult.INVALID
```

In `tests/test_type_annotations.py` ersetze

```python
    "src/api_summary.py",
```

durch

```python
    "src/api_summary.py",
    "src/mobile_pairing.py",
```

- [ ] **Step 4: Run to verify they pass**

Run: `python3 -m pytest tests/test_mobile_pairing.py tests/test_type_annotations.py -q -p no:cacheprovider` und danach `python3 -m pytest -q -p no:cacheprovider && ruff check . && npx --yes pyright@1.1.411 src/mobile_pairing.py src/mobile_store.py`
Expected: PASS, `All checks passed!`, `0 errors`.

- [ ] **Step 5: Commit**

~~~bash
git add src/mobile_pairing.py tests/test_mobile_pairing.py tests/test_type_annotations.py
git commit -m "feat(mobile): Einmalcode für das Koppeln des Handys (#221)

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
~~~

### Task 2: Gerätetoken, Datensätze, Fremddaten

**Interfaces:** Produces: `Record`, `new_token()`, `hash_token(token)`, `normalize_device_id(raw)`, `clean_device_name(raw)`, `shift(now, delta)`, `issue_device(device_id, name, now, existing=None) -> (Record, token)`, `renew(record, now, *, keep_previous=False) -> (Record, token)`, `revoke(record) -> Record`, `AuthOutcome(status, record, via_previous)` mit `.ok`, `authenticate(records, token, now) -> AuthOutcome`, Konstanten `TOKEN_LIFETIME` (30 Tage), `PREVIOUS_TOKEN_GRACE` (10 Minuten).

- [ ] **Step 1: Write the failing tests**

In `tests/test_mobile_pairing.py` ersetze

```python
# tests/test_mobile_pairing.py
import threading

import pytest

from src import mobile_pairing as mp
from src.mobile_pairing import PairingSession, RedeemResult
```

durch

```python
# tests/test_mobile_pairing.py
import datetime
import threading

import pytest

from src import mobile_pairing as mp
from src.mobile_pairing import PairingSession, RedeemResult

NOW = "2026-10-08T12:00:00Z"
```

Hänge ans Ende von `tests/test_mobile_pairing.py` an:

```python
# --- Token --------------------------------------------------------------------------------

def test_tokens_are_long_unique_and_urlsafe():
    tokens = {mp.new_token() for _ in range(100)}
    assert len(tokens) == 100 and all(len(t) == 43 for t in tokens)


def test_the_hash_is_stable_hex_and_differs_per_token():
    assert mp.hash_token("abc") == mp.hash_token("abc")
    assert mp.hash_token("abc") != mp.hash_token("abd")
    assert len(mp.hash_token("abc")) == 64 and int(mp.hash_token("abc"), 16) >= 0


def test_a_lone_surrogate_hashes_without_raising():
    assert len(mp.hash_token("\ud800")) == 64
    assert mp.hash_token("\ud800") != mp.hash_token("\udc00")


# --- Fremddaten vom Handy ---------------------------------------------------------------------

@pytest.mark.parametrize("raw", ["6f1c2b9e-3d4a-4b5c-8d7e-9f0a1b2c3d4e", "ABCDEFGH", "a" * 64])
def test_a_plausible_device_id_is_kept(raw):
    assert mp.normalize_device_id(raw) == raw


@pytest.mark.parametrize("raw", [None, 5, "", "kurz", "a" * 65, "mit leerzeichen!", "ä" * 10,
                                 "٢" * 10, "id\n12345678"])
def test_an_implausible_device_id_is_rejected(raw):
    assert mp.normalize_device_id(raw) is None


def test_a_device_name_is_cleaned():
    assert mp.clean_device_name("  Pixel von Sven ") == "Pixel von Sven"
    assert mp.clean_device_name("Pi\nxel\x00\x07") == "Pixel"
    assert mp.clean_device_name("x" * 500) == "x" * mp.MAX_NAME_LENGTH
    for junk in (None, 5, "", "   ", "\n\x00"):
        assert mp.clean_device_name(junk) == mp.DEFAULT_DEVICE_NAME


# --- Zeit ----------------------------------------------------------------------------------------

def test_shift_adds_and_subtracts_in_the_fixed_format():
    assert mp.shift(NOW, datetime.timedelta(days=30)) == "2026-11-07T12:00:00Z"
    assert mp.shift(NOW, -datetime.timedelta(minutes=1)) == "2026-10-08T11:59:00Z"
    assert mp.shift("2026-12-31T23:59:59Z", datetime.timedelta(seconds=1)) == "2027-01-01T00:00:00Z"


# --- Geräte, Erneuerung, Widerruf ----------------------------------------------------------------

def test_issue_device_returns_a_record_without_the_token():
    record, token = mp.issue_device("device-0001", "Pixel", NOW)

    assert token not in repr(record)
    assert record["token_hash"] == mp.hash_token(token)
    assert (record["id"], record["name"], record["revoked"]) == ("device-0001", "Pixel", False)
    assert (record["created_at"], record["last_seen"], record["last_pull_at"]) == (NOW, NOW, "")
    assert record["expires_at"] == "2026-11-07T12:00:00Z"
    assert (record["previous_token_hash"], record["previous_valid_until"]) == ("", "")


def test_pairing_again_keeps_the_sync_identity_and_lifts_a_revocation():
    old, _ = mp.issue_device("device-0001", "Pixel", NOW)
    old["last_pull_at"] = "2026-10-07T09:00:00Z"
    old = mp.revoke(old)

    record, token = mp.issue_device("device-0001", "Pixel neu", "2026-10-09T08:00:00Z", existing=old)

    assert record["created_at"] == NOW and record["last_pull_at"] == "2026-10-07T09:00:00Z"
    assert record["revoked"] is False and record["name"] == "Pixel neu"
    assert mp.authenticate([record], token, "2026-10-09T08:00:00Z").ok


def test_a_valid_token_authenticates_and_an_unknown_one_does_not():
    record, token = mp.issue_device("device-0001", "Pixel", NOW)

    outcome = mp.authenticate([record], token, NOW)
    assert outcome.ok and outcome.record["id"] == "device-0001" and not outcome.via_previous
    assert mp.authenticate([record], token + "x", NOW).status == "unauthorized"
    assert mp.authenticate([], token, NOW).status == "unauthorized"


@pytest.mark.parametrize("junk", [None, 5, "", b"abc", "x" * 5000, ["a"], "\ud800"])
def test_a_junk_token_is_unauthorized_and_never_raises(junk):
    record, _ = mp.issue_device("device-0001", "Pixel", NOW)
    assert mp.authenticate([record], junk, NOW).status == "unauthorized"


def test_the_token_expires_exactly_at_expires_at():
    record, token = mp.issue_device("device-0001", "Pixel", NOW)
    before = mp.shift(record["expires_at"], -datetime.timedelta(seconds=1))

    assert mp.authenticate([record], token, before).ok
    assert mp.authenticate([record], token, record["expires_at"]).status == "expired"
    assert mp.authenticate([record], token, record["expires_at"]).record["id"] == "device-0001"


def test_a_revoked_device_is_reported_as_revoked_not_as_unknown():
    record, token = mp.issue_device("device-0001", "Pixel", NOW)
    assert mp.authenticate([mp.revoke(record)], token, NOW).status == "revoked"


def test_revoke_also_cuts_the_grace_of_the_previous_token():
    record, token = mp.issue_device("device-0001", "Pixel", NOW)
    renewed, _ = mp.renew(record, NOW)
    revoked = mp.revoke(renewed)

    assert mp.authenticate([revoked], token, NOW).status == "unauthorized"


def test_renew_issues_a_new_token_and_extends_the_expiry():
    record, token = mp.issue_device("device-0001", "Pixel", NOW)
    later = "2026-10-20T08:00:00Z"

    renewed, new_token = mp.renew(record, later)

    assert new_token != token and renewed["token_hash"] == mp.hash_token(new_token)
    assert renewed["expires_at"] == "2026-11-19T08:00:00Z" and renewed["last_seen"] == later
    assert mp.authenticate([renewed], new_token, later).ok
    assert record["token_hash"] == mp.hash_token(token)                    # das Original bleibt unverändert


def test_the_previous_token_works_for_ten_minutes_after_a_renewal():
    record, token = mp.issue_device("device-0001", "Pixel", NOW)
    renewed, _ = mp.renew(record, NOW)

    inside = mp.authenticate([renewed], token, "2026-10-08T12:10:00Z")
    outside = mp.authenticate([renewed], token, "2026-10-08T12:10:01Z")

    assert inside.ok and inside.via_previous
    assert outside.status == "unauthorized"


def test_a_lost_answer_twice_does_not_lock_the_phone_out():
    # T1 -> Antwort mit T2 geht verloren -> Handy sendet weiter mit T1 -> Antwort mit T3 geht verloren
    record, t1 = mp.issue_device("device-0001", "Pixel", NOW)
    second, _t2 = mp.renew(record, NOW)
    outcome = mp.authenticate([second], t1, "2026-10-08T12:05:00Z")
    assert outcome.ok and outcome.via_previous

    third, t3 = mp.renew(outcome.record, "2026-10-08T12:05:00Z", keep_previous=outcome.via_previous)

    assert mp.authenticate([third], t1, "2026-10-08T12:06:00Z").ok         # T1 gilt noch
    assert mp.authenticate([third], t3, "2026-10-08T12:06:00Z").ok


def test_renewing_with_the_current_token_replaces_the_previous_one():
    record, t1 = mp.issue_device("device-0001", "Pixel", NOW)
    second, t2 = mp.renew(record, NOW)
    third, _t3 = mp.renew(second, "2026-10-08T12:01:00Z")                  # normal: keep_previous=False

    assert mp.authenticate([third], t2, "2026-10-08T12:02:00Z").via_previous
    assert mp.authenticate([third], t1, "2026-10-08T12:02:00Z").status == "unauthorized"


def test_the_right_device_is_found_among_several():
    a, ta = mp.issue_device("device-aaaa", "A", NOW)
    b, tb = mp.issue_device("device-bbbb", "B", NOW)

    assert mp.authenticate([a, b], tb, NOW).record["id"] == "device-bbbb"
    assert mp.authenticate([a, b], ta, NOW).record["id"] == "device-aaaa"
```

- [ ] **Step 2: Run to verify they fail**

Run: `python3 -m pytest -q -p no:cacheprovider -x`
Expected: FAIL: `AttributeError: module 'src.mobile_pairing' has no attribute 'new_token'` (und die übrigen neuen Namen).

- [ ] **Step 3: Implement**

In `src/mobile_pairing.py` ersetze

```python
from __future__ import annotations

import enum
import hmac
import secrets
import threading
import time
from collections.abc import Callable
```

durch

```python
from __future__ import annotations

import datetime
import enum
import hashlib
import hmac
import re
import secrets
import threading
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any
```

Hänge ans Ende von `src/mobile_pairing.py` an:

```python
# --- Gerätetoken und -datensätze ---------------------------------------------------------------------

TOKEN_LIFETIME = datetime.timedelta(days=30)
PREVIOUS_TOKEN_GRACE = datetime.timedelta(minutes=10)
_TIME_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
_MAX_TOKEN_LENGTH = 512
MAX_NAME_LENGTH = 60
DEFAULT_DEVICE_NAME = "Handy"
_DEVICE_ID_RE = re.compile(r"[A-Za-z0-9-]{8,64}")


Record = dict[str, Any]


def new_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    """SHA-256 (hex) des Tokens. Das Token hat 256 Bit Zufall, ein schneller Hash
    genügt: ein Wörterbuchangriff auf den Hash ist aussichtslos. `surrogatepass`,
    damit auch ein kaputtes Zeichen im Header zu einem (nie passenden) Hash wird."""
    return hashlib.sha256(token.encode("utf-8", errors="surrogatepass")).hexdigest()


def normalize_device_id(raw: object) -> str | None:
    """Die Geräte-ID des Handys (eine UUID, 8–64 Zeichen aus `A-Za-z0-9-`), sonst `None`."""
    if isinstance(raw, str) and _DEVICE_ID_RE.fullmatch(raw):
        return raw
    return None


def clean_device_name(raw: object) -> str:
    """Ein anzeigbarer Gerätename: ohne Steuerzeichen, getrimmt, höchstens
    `MAX_NAME_LENGTH` Zeichen; leer oder kein Text wird `Handy`."""
    if not isinstance(raw, str):
        return DEFAULT_DEVICE_NAME
    name = "".join(ch for ch in raw if ch.isprintable()).strip()[:MAX_NAME_LENGTH].strip()
    return name or DEFAULT_DEVICE_NAME


def shift(now: str, delta: datetime.timedelta) -> str:
    """`now` (UTC-Text) plus `delta`, im selben Format. Das feste Format macht den
    String-Vergleich der Zeitstempel korrekt."""
    moment = datetime.datetime.strptime(now, _TIME_FORMAT)
    return (moment + delta).strftime(_TIME_FORMAT)


def issue_device(device_id: str, name: str, now: str,
                 existing: Mapping[str, Any] | None = None) -> tuple[Record, str]:
    """Ein neues Gerät (oder ein erneutes Koppeln desselben): liefert den Datensatz
    **ohne Klartext-Token** und das Token zur einmaligen Übergabe an das Handy. Beim
    erneuten Koppeln bleiben `created_at` und `last_pull_at` erhalten (die Identität
    im Sync ändert sich nicht), ein Widerruf wird aufgehoben."""
    token = new_token()
    record: Record = {
        "id": device_id,
        "name": name,
        "token_hash": hash_token(token),
        "previous_token_hash": "",
        "previous_valid_until": "",
        "created_at": str(existing["created_at"]) if existing else now,
        "expires_at": shift(now, TOKEN_LIFETIME),
        "last_seen": now,
        "last_pull_at": str(existing["last_pull_at"]) if existing else "",
        "revoked": False,
    }
    return record, token


def renew(record: Mapping[str, Any], now: str, *,
          keep_previous: bool = False) -> tuple[Record, str]:
    """Erneuert das Token (Sliding Expiration): neues Token, Ablauf 30 Tage ab `now`.
    Das bisherige gilt noch 10 Minuten. Kam die Anfrage selbst mit dem **alten**
    Token (`keep_previous`: die Antwort mit dem neuen ging verloren), bleibt dieses
    alte als „vorheriges" erhalten, statt vom noch nie übergebenen aktuellen
    verdrängt zu werden — sonst sperrte ein zweiter Verlust das Handy aus."""
    token = new_token()
    updated: Record = dict(record)
    if not keep_previous:
        updated["previous_token_hash"] = str(record["token_hash"])
    updated["previous_valid_until"] = shift(now, PREVIOUS_TOKEN_GRACE)
    updated["token_hash"] = hash_token(token)
    updated["expires_at"] = shift(now, TOKEN_LIFETIME)
    updated["last_seen"] = now
    return updated, token


def revoke(record: Mapping[str, Any]) -> Record:
    """Der Datensatz bleibt (damit die Antwort `token_revoked` lauten kann), das Token
    ist nicht mehr brauchbar."""
    updated: Record = dict(record)
    updated["revoked"] = True
    updated["previous_token_hash"] = ""
    updated["previous_valid_until"] = ""
    return updated


@dataclass(frozen=True)
class AuthOutcome:
    status: str                      # "ok" | "unauthorized" | "expired" | "revoked"
    record: Record | None = None
    via_previous: bool = False       # das Token war das vorherige (Karenzfenster)

    @property
    def ok(self) -> bool:
        return self.status == "ok"


def authenticate(records: Iterable[Mapping[str, Any]], token: object, now: str) -> AuthOutcome:
    """Ordnet ein Token einem Gerät zu. Verglichen wird gegen alle Datensätze (kein
    früher Abbruch), konstantzeitig je Hash."""
    unknown = AuthOutcome("unauthorized")
    if not isinstance(token, str) or not token or len(token) > _MAX_TOKEN_LENGTH:
        return unknown
    candidate = hash_token(token).encode("ascii")
    current: Mapping[str, Any] | None = None
    previous: Mapping[str, Any] | None = None
    for record in records:
        if hmac.compare_digest(candidate, str(record.get("token_hash", "")).encode("ascii", "replace")):
            current = record
        prev_hash = str(record.get("previous_token_hash", ""))
        if prev_hash and hmac.compare_digest(candidate, prev_hash.encode("ascii", "replace")):
            previous = record
    if current is not None:
        return _state_of(current, now, via_previous=False)
    if previous is not None and str(previous.get("previous_valid_until", "")) >= now:
        return _state_of(previous, now, via_previous=True)
    return unknown


def _state_of(record: Mapping[str, Any], now: str, *, via_previous: bool) -> AuthOutcome:
    if record.get("revoked"):
        return AuthOutcome("revoked", dict(record), via_previous)
    if str(record.get("expires_at", "")) <= now:
        return AuthOutcome("expired", dict(record), via_previous)
    return AuthOutcome("ok", dict(record), via_previous)
```

- [ ] **Step 4: Run to verify they pass**

Run: `python3 -m pytest tests/test_mobile_pairing.py -q -p no:cacheprovider` und danach `python3 -m pytest -q -p no:cacheprovider && ruff check . && npx --yes pyright@1.1.411 src/mobile_pairing.py src/mobile_store.py`
Expected: PASS, `All checks passed!`, `0 errors`.

- [ ] **Step 5: Commit**

~~~bash
git add src/mobile_pairing.py tests/test_mobile_pairing.py
git commit -m "feat(mobile): Gerätetoken, Erneuerung, Widerruf und Zuordnung (#221)

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
~~~

### Task 3: `MobileStore`

**Interfaces:** Consumes: `mobile_pairing.Record`, `mobile_pairing.shift`; `json_store.atomic_write_json`, `load_json_or_quarantine`, `quarantine_corrupt(path, reason)`. Produces: `MobileStore(filepath='mobile_devices.json', lock=None)` mit `get_all()`, `get(device_id)`, `save(record)`, `replace_all(records)`, `prune(now) -> int`; `MobileStoreReadOnly`; `SCHEMA_VERSION = 1`, `FORGET_AFTER` (30 Tage).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_mobile_store.py`:

```python
# tests/test_mobile_store.py
import json
import logging
import os
import stat
import sys
import threading

import pytest

from src import mobile_pairing as mp
from src import mobile_store
from src.mobile_store import MobileStore, MobileStoreReadOnly

NOW = "2026-10-08T12:00:00Z"


def make_record(device_id="device-0001", name="Pixel", now=NOW):
    record, token = mp.issue_device(device_id, name, now)
    return record, token


@pytest.fixture
def path(tmp_path):
    return str(tmp_path / "mobile_devices.json")


def backups(path):
    directory = os.path.dirname(path)
    return sorted(n for n in os.listdir(directory) if ".corrupt-" in n)


# --- Grundfunktionen --------------------------------------------------------------------------

def test_a_missing_file_gives_an_empty_store(path):
    store = MobileStore(path)
    assert store.get_all() == [] and store.get("device-0001") is None
    assert not os.path.exists(path)                      # Lesen legt nichts an


def test_save_and_get_round_trip_through_the_file(path):
    record, token = make_record()
    MobileStore(path).save(record)

    again = MobileStore(path)

    assert again.get("device-0001") == record
    assert mp.authenticate(again.get_all(), token, NOW).ok


def test_saving_the_same_id_replaces_instead_of_duplicating(path):
    store = MobileStore(path)
    first, _ = make_record()
    store.save(first)
    second = dict(first, name="Pixel 2")

    store.save(second)

    assert [r["name"] for r in store.get_all()] == ["Pixel 2"]


def test_two_devices_are_kept_apart(path):
    store = MobileStore(path)
    a, _ = make_record("device-aaaa", "A")
    b, _ = make_record("device-bbbb", "B")
    store.save(a)
    store.save(b)
    assert [r["id"] for r in MobileStore(path).get_all()] == ["device-aaaa", "device-bbbb"]


def test_results_are_copies(path):
    store = MobileStore(path)
    record, _ = make_record()
    store.save(record)

    store.get("device-0001")["name"] = "geändert"
    store.get_all()[0]["revoked"] = True
    record["name"] = "auch geändert"

    assert store.get("device-0001")["name"] == "Pixel" and not store.get("device-0001")["revoked"]


def test_the_file_never_contains_a_plaintext_token(path):
    record, token = make_record()
    renewed, new_token = mp.renew(record, NOW)
    MobileStore(path).save(renewed)

    text = open(path, encoding="utf-8").read()

    assert token not in text and new_token not in text
    assert renewed["token_hash"] in text


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX-Rechte")
def test_the_file_is_private_on_posix(path):
    record, _ = make_record()
    MobileStore(path).save(record)
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600


def test_replace_all_writes_once_and_replaces_everything(path):
    store = MobileStore(path)
    a, _ = make_record("device-aaaa")
    b, _ = make_record("device-bbbb")
    store.save(a)
    store.save(b)

    store.replace_all([mp.revoke(a), mp.revoke(b)])

    assert all(r["revoked"] for r in MobileStore(path).get_all())


# --- prune ------------------------------------------------------------------------------------------

def test_prune_forgets_only_devices_expired_for_more_than_thirty_days(path):
    store = MobileStore(path)
    old, _ = make_record("device-old1", now="2026-07-01T00:00:00Z")      # läuft 2026-07-31 ab
    recent, _ = make_record("device-new1", now="2026-09-20T00:00:00Z")   # läuft 2026-10-20 ab
    fresh, _ = make_record("device-live", now=NOW)
    for record in (old, recent, fresh):
        store.save(record)

    removed = store.prune(NOW)                                            # Grenze: 2026-09-08

    assert removed == 1
    assert [r["id"] for r in MobileStore(path).get_all()] == ["device-new1", "device-live"]


def test_prune_without_a_hit_does_not_write(path, monkeypatch):
    store = MobileStore(path)
    record, _ = make_record()
    store.save(record)
    calls = []
    monkeypatch.setattr(mobile_store, "atomic_write_json", lambda *a, **k: calls.append(a))

    assert store.prune(NOW) == 0 and calls == []


# --- kaputte oder fremde Dateien ---------------------------------------------------------------------

def test_unparsable_json_is_quarantined(path):
    open(path, "w", encoding="utf-8").write("{ kaputt")
    store = MobileStore(path)
    assert store.get_all() == [] and not os.path.exists(path) and len(backups(path)) == 1
    record, _ = make_record()
    store.save(record)                                                    # und benutzbar
    assert MobileStore(path).get("device-0001") == record


@pytest.mark.parametrize("content", ["[]", '"text"', "42", "true"])
def test_a_non_object_top_level_is_quarantined(path, content, caplog):
    open(path, "w", encoding="utf-8").write(content)
    with caplog.at_level(logging.WARNING):
        store = MobileStore(path)
    assert store.get_all() == [] and len(backups(path)) == 1
    assert "Top-Level" in caplog.text


def test_malformed_records_are_skipped_and_never_logged_in_full(path, caplog):
    good, _ = make_record("device-good")
    bad_hash = dict(good, id="device-bad1", token_hash="xyz")
    secret_marker = "GEHEIMER-HASH-INHALT"
    junk = [None, "x", 5, {"id": "device-nope"}, bad_hash, dict(good, id="", ),
            dict(good, id="device-bad2", revoked="ja"), dict(good, id="device-bad3", name=5),
            dict(good, id="device-bad4", previous_token_hash=secret_marker)]
    open(path, "w", encoding="utf-8").write(
        json.dumps({"schema_version": 1, "devices": [*junk, good]}))

    with caplog.at_level(logging.WARNING):
        store = MobileStore(path)

    assert [r["id"] for r in store.get_all()] == ["device-good"]
    assert secret_marker not in caplog.text and good["token_hash"] not in caplog.text
    assert "übersprungen" in caplog.text


@pytest.mark.parametrize("devices", [None, "x", 5, {"a": 1}])
def test_a_devices_field_of_the_wrong_type_gives_an_empty_store(path, devices):
    open(path, "w", encoding="utf-8").write(json.dumps({"schema_version": 1, "devices": devices}))
    assert MobileStore(path).get_all() == []


def test_a_newer_schema_is_read_only_and_never_overwritten(path):
    original = json.dumps({"schema_version": 99, "devices": [], "neu": True})
    open(path, "w", encoding="utf-8").write(original)
    store = MobileStore(path)
    record, _ = make_record()

    with pytest.raises(MobileStoreReadOnly):
        store.save(record)

    assert open(path, encoding="utf-8").read() == original and store.get_all() == []


def test_an_unreadable_file_is_read_only_and_not_quarantined(path, monkeypatch):
    open(path, "w", encoding="utf-8").write(json.dumps({"schema_version": 1, "devices": []}))

    def boom(_path):
        raise PermissionError("gesperrt")
    monkeypatch.setattr(mobile_store, "load_json_or_quarantine", boom)

    store = MobileStore(path)
    record, _ = make_record()

    with pytest.raises(MobileStoreReadOnly):
        store.save(record)
    assert os.path.exists(path) and backups(path) == []


# --- Schreibfehler und Nebenläufigkeit -------------------------------------------------------------------

def test_a_failed_write_rolls_the_memory_back(path, monkeypatch):
    store = MobileStore(path)
    first, _ = make_record("device-0001")
    store.save(first)

    def boom(*_args, **_kwargs):
        raise OSError(28, "Platte voll")
    monkeypatch.setattr(mobile_store, "atomic_write_json", boom)
    second, _ = make_record("device-0002")

    with pytest.raises(OSError):
        store.save(second)
    with pytest.raises(OSError):
        store.replace_all([])

    assert [r["id"] for r in store.get_all()] == ["device-0001"]
    assert [r["id"] for r in MobileStore(path).get_all()] == ["device-0001"]


def test_concurrent_saves_lose_nothing(path):
    store = MobileStore(path)
    records = [make_record(f"device-{i:04d}")[0] for i in range(20)]
    threads = [threading.Thread(target=store.save, args=(r,)) for r in records]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sorted(r["id"] for r in MobileStore(path).get_all()) == sorted(r["id"] for r in records)


@pytest.mark.parametrize("field,value", [
    ("expires_at", "zzzz"), ("expires_at", ""), ("expires_at", "2026-11-07 12:00:00"),
    ("expires_at", "2026-11-07T12:00:00+00:00"), ("expires_at", "٢026-11-07T12:00:00Z"),
    ("created_at", "gestern"), ("last_seen", "9999"), ("last_pull_at", "irgendwann"),
    ("previous_valid_until", "bald"),
])
def test_a_record_with_a_malformed_timestamp_is_skipped(path, field, value):
    # Zeitstempel werden als Text verglichen; "zzzz" liefe sonst nie ab.
    good, _ = make_record("device-good")
    bad = dict(good, id="device-bad1", **{field: value})
    open(path, "w", encoding="utf-8").write(json.dumps({"schema_version": 1, "devices": [bad, good]}))

    assert [r["id"] for r in MobileStore(path).get_all()] == ["device-good"]


def test_empty_optional_timestamps_are_fine(path):
    record, _ = make_record()
    assert record["last_pull_at"] == "" and record["previous_valid_until"] == ""
    MobileStore(path).save(record)
    assert MobileStore(path).get("device-0001") == record
```

- [ ] **Step 2: Run to verify they fail**

Run: `python3 -m pytest -q -p no:cacheprovider -x`
Expected: ERROR beim Sammeln: `ModuleNotFoundError: No module named 'src.mobile_store'`.

- [ ] **Step 3: Implement**

Create `src/mobile_store.py`:

```python
# src/mobile_store.py
"""Gerätelokale Persistenz der gekoppelten Handys (#221), Tk-frei und stdlib-only.

`mobile_devices.json` liegt neben `smtp.json` im Datenverzeichnis, reist aber weder
per Drive-Sync noch im Share-Doc: eine Kopplung gilt für genau diesen Desktop.

Die Datei enthält **kein Geheimnis im Klartext**: von jedem Gerätetoken steht nur
der SHA-256-Hash darin (das Token hat 256 Bit Zufall, aus dem Hash lässt es sich
nicht herleiten). Deshalb schreibt der Store über `json_store.atomic_write_json`
und nicht über den gehärteten Schreibpfad der Secret-Dateien (`secure_file`, ein
`icacls`-Aufruf je Schreibvorgang wäre bei jedem Abgleich unnötige Last). Die
Datei bekommt über `mkstemp` unter POSIX trotzdem 0600.

Der Store hat wie `smtp_store` einen **eigenen** Lock: er nimmt an keinem
Sync-Flow der Einträge teil. Die Datensätze und ihre Regeln (Ablauf, Karenz,
Widerruf) stehen in `mobile_pairing`; hier liegt nur die Dateimechanik.
"""
from __future__ import annotations

import copy
import datetime
import logging
import re
import threading
from typing import Any

from src.json_store import atomic_write_json, load_json_or_quarantine, quarantine_corrupt
from src.mobile_pairing import Record, shift

log = logging.getLogger(__name__)

SCHEMA_VERSION = 1
# Abgelaufene Datensätze bleiben so lange sichtbar (für `token_expired` und die Liste
# im Tab), danach räumt `prune` sie weg.
FORGET_AFTER = datetime.timedelta(days=30)

_HASH_RE = re.compile(r"[0-9a-f]{64}")
# Zeitstempel stehen als Text im festen Format `utc_now_iso` (nur dann ist der String-
# Vergleich korrekt). Eine Datei mit `"zzzz"` als Ablauf liefe sonst nie ab.
_TIME_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z")
_REQUIRED_TIMES = ("created_at", "expires_at", "last_seen")
_OPTIONAL_TIMES = ("last_pull_at", "previous_valid_until")      # leer = nie gesetzt
_TEXT_KEYS = ("id", "name")


class MobileStoreReadOnly(Exception):
    """Die Datei darf nicht überschrieben werden (neuere `schema_version` oder beim
    Start nicht lesbar). Der Aufrufer zeigt das an — ein still verworfener
    Speichervorgang wäre schlimmer als ein Fehler."""


def _is_wellformed(record: Any) -> bool:
    """Strukturprüfung fürs Laden. Fremde oder handbearbeitete Datensätze, die
    `authenticate` oder den Tab zum Absturz brächten, werden übersprungen."""
    if not isinstance(record, dict):
        return False
    if not all(isinstance(record.get(key), str) for key in _TEXT_KEYS):
        return False
    if not record["id"]:
        return False
    for key in _REQUIRED_TIMES:
        if not isinstance(record.get(key), str) or not _TIME_RE.fullmatch(record[key]):
            return False
    for key in _OPTIONAL_TIMES:
        value = record.get(key)
        if not isinstance(value, str) or (value and not _TIME_RE.fullmatch(value)):
            return False
    if not _HASH_RE.fullmatch(str(record.get("token_hash", ""))):
        return False
    previous = record.get("previous_token_hash")
    if not isinstance(previous, str) or (previous and not _HASH_RE.fullmatch(previous)):
        return False
    return isinstance(record.get("revoked"), bool)


class MobileStore:
    def __init__(self, filepath: str = "mobile_devices.json",
                 lock: threading.RLock | None = None) -> None:
        self.filepath = filepath
        self._lock = lock if lock is not None else threading.RLock()
        self._devices: list[Record] = []
        self._readonly = False
        self._load()

    def _load(self) -> None:
        try:
            data = load_json_or_quarantine(self.filepath)
        except OSError:
            # KEINE Quarantäne: ein kurzzeitig gesperrtes File (Virenscanner, Backup)
            # ist kein defektes File. Lieber ohne Geräte laufen, ohne die Datei zu
            # überschreiben (wie smtp_store).
            self._readonly = True
            log.warning("mobile_devices.json nicht lesbar — starte ohne gekoppelte "
                        "Geräte, die Datei wird nicht überschrieben", exc_info=True)
            return
        if data is None:
            return
        if not isinstance(data, dict):
            quarantine_corrupt(self.filepath,
                               f"Top-Level ist {type(data).__name__}, erwartet ein Objekt")
            return
        version = data.get("schema_version")
        if isinstance(version, int) and not isinstance(version, bool) and version > SCHEMA_VERSION:
            self._readonly = True
            log.warning("mobile_devices.json hat schema_version %s (bekannt: %s) — die "
                        "Datei wird nicht gelesen und nicht überschrieben",
                        version, SCHEMA_VERSION)
            return
        raw = data.get("devices")
        if not isinstance(raw, list):
            return
        for record in raw:
            if _is_wellformed(record):
                self._devices.append(record)
            else:
                # Nie den Datensatz loggen (er trägt Token-Hashes), nur id und Name.
                log.warning("mobile_devices.json: Datensatz übersprungen (id=%r, name=%r)",
                            record.get("id") if isinstance(record, dict) else None,
                            record.get("name") if isinstance(record, dict) else None)

    def _save_to_disk(self) -> None:
        if self._readonly:
            raise MobileStoreReadOnly(self.filepath)
        atomic_write_json(self.filepath, {"schema_version": SCHEMA_VERSION,
                                          "devices": self._devices})

    def get_all(self) -> list[Record]:
        with self._lock:
            return copy.deepcopy(self._devices)

    def get(self, device_id: str) -> Record | None:
        with self._lock:
            for record in self._devices:
                if record["id"] == device_id:
                    return copy.deepcopy(record)
            return None

    def save(self, record: Record) -> None:
        """Legt an oder ersetzt nach `id`. Wirft `MobileStoreReadOnly` oder `OSError`;
        dann bleibt der Speicherstand unverändert (Rollback)."""
        with self._lock:
            previous = copy.deepcopy(self._devices)
            for i, existing in enumerate(self._devices):
                if existing["id"] == record["id"]:
                    self._devices[i] = copy.deepcopy(record)
                    break
            else:
                self._devices.append(copy.deepcopy(record))
            try:
                self._save_to_disk()
            except BaseException:
                self._devices = previous
                raise

    def replace_all(self, records: list[Record]) -> None:
        """Ersetzt den ganzen Bestand in einem Schreibvorgang (Widerruf aller,
        Aufräumen). Rollback wie bei `save`."""
        with self._lock:
            previous = self._devices
            self._devices = copy.deepcopy(records)
            try:
                self._save_to_disk()
            except BaseException:
                self._devices = previous
                raise

    def prune(self, now: str) -> int:
        """Entfernt Geräte, die seit mehr als `FORGET_AFTER` abgelaufen sind. Liefert
        die Zahl der entfernten Datensätze; ohne Treffer wird nicht geschrieben."""
        limit = shift(now, -FORGET_AFTER)
        with self._lock:
            kept = [r for r in self._devices if r["expires_at"] >= limit]
            removed = len(self._devices) - len(kept)
            if removed:
                self.replace_all(kept)
            return removed
```

In `tests/test_type_annotations.py` ersetze

```python
    "src/mobile_pairing.py",
```

durch

```python
    "src/mobile_pairing.py",
    "src/mobile_store.py",
```

- [ ] **Step 4: Run to verify they pass**

Run: `python3 -m pytest tests/test_mobile_store.py tests/test_type_annotations.py -q -p no:cacheprovider` und danach `python3 -m pytest -q -p no:cacheprovider && ruff check . && npx --yes pyright@1.1.411 src/mobile_pairing.py src/mobile_store.py`
Expected: PASS, `All checks passed!`, `0 errors`.

- [ ] **Step 5: Commit**

~~~bash
git add src/mobile_store.py tests/test_mobile_store.py tests/test_type_annotations.py
git commit -m "feat(mobile): gerätelokaler Store der gekoppelten Handys (#221)

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
~~~

### Task 4: Aufräumen, Ignorieren, Doku

**Interfaces:** Produces: `mobile_devices.json` in `removal.CREDENTIAL_FILES`, `installer.iss` (`[UninstallDelete]`) und `.gitignore`; Doku in `src/CLAUDE.md` und `CLAUDE.md`.

- [ ] **Step 1: Write the failing tests**

Hänge ans Ende von `tests/test_removal.py` an:

```python
def test_the_mobile_devices_file_is_removed_and_ignored():
    import pathlib
    assert "mobile_devices.json" in removal.CREDENTIAL_FILES
    ignore = (pathlib.Path(__file__).resolve().parent.parent / ".gitignore")
    lines = ignore.read_text(encoding="utf-8").splitlines()
    assert "mobile_devices.json" in lines and "mobile_devices.json.corrupt-*" in lines
```

- [ ] **Step 2: Run to verify they fail**

Run: `python3 -m pytest -q -p no:cacheprovider -x`
Expected: FAIL: `test_the_mobile_devices_file_is_removed_and_ignored` (und der Installer-Spiegeltest bleibt grün, solange `removal` und `installer.iss` gemeinsam geändert werden).

- [ ] **Step 3: Implement**

In `src/removal.py` ersetze

```python
    "credentials.json", "api-token",
)
```

durch

```python
    "credentials.json", "api-token", "mobile_devices.json",
)
```

In `installer.iss` ersetze

```ini
Type: files; Name: "{app}\api-token"
```

durch

```ini
Type: files; Name: "{app}\api-token"
Type: files; Name: "{app}\mobile_devices.json"
```

In `.gitignore` ersetze

```text
smtp.json.corrupt-*
```

durch

```text
smtp.json.corrupt-*
mobile_devices.json
mobile_devices.json.corrupt-*
```

In `src/CLAUDE.md` ersetze

```markdown
  selbst; auch dann wird die Datei gehärtet geschrieben.
```

durch

```markdown
  selbst; auch dann wird die Datei gehärtet geschrieben.

  `mobile_store.py` — gerätelokaler Store der gekoppelten Handys (`mobile_devices.json`,
  #221), Mechanik und eigener Lock wie `smtp_store`; nichts davon im Sync-Doc oder Share-Doc.
  Die Datei trägt von jedem Gerätetoken nur den **SHA-256-Hash** (256 Bit Zufall, nicht
  umkehrbar), deshalb schreibt der Store über `json_store.atomic_write_json` und nicht über den
  gehärteten Pfad der Secret-Dateien (kein `icacls`-Aufruf bei jedem Abgleich); sie steht trotzdem
  in `removal.CREDENTIAL_FILES`, `installer.iss` und `.gitignore`. Defekte Datensätze werden
  übersprungen (im Log nur `id` und Name, nie Hashes), eine kaputte Datei wird quarantäniert,
  eine neuere `schema_version` oder ein Lesefehler macht den Store read-only
  (`MobileStoreReadOnly`, die Datei bleibt unberührt), ein Schreibfehler rollt den Speicher
  zurück. `mobile_pairing.py` hält die Regeln dazu, rein und ohne I/O: der Einmalcode
  (`PairingSession`: 8 Zeichen aus 31, 5 Minuten, einmal einlösbar, nach 5 Fehlversuchen
  gesperrt, nur im Hauptspeicher) und das Gerätetoken (`issue_device`/`renew`/`revoke`/
  `authenticate`: 30 Tage ab der letzten Nutzung, ein erneuertes Token lässt das alte 10 Minuten
  gelten; ein widerrufener Datensatz bleibt erhalten, damit die Antwort `token_revoked` lauten
  kann). Geräte-ID, Name und Token kommen vom Handy — Fremddaten (`normalize_device_id`,
  `clean_device_name`). Design: `docs/superpowers/specs/2026-10-08-mobile-pwa-design.md`.
```

In `CLAUDE.md` ersetze

```markdown
- `src/keyring_store.py` — Passwörter im OS-Schlüsselbund
```

durch

```markdown
- `src/mobile_pairing.py` — Einmalcode und Gerätetoken der Handy-Erfassung per PWA (#221): rein, ohne I/O, Uhr als Parameter; Fremddaten vom Handy werden normalisiert (s. `src/CLAUDE.md`)
- `src/mobile_store.py` — gerätelokale Datei `mobile_devices.json` der gekoppelten Handys (nur Token-**Hashes**; reist nicht per Drive-Sync); Mechanik wie `smtp_store.py`
- `src/keyring_store.py` — Passwörter im OS-Schlüsselbund
```

- [ ] **Step 4: Run to verify they pass**

Run: `python3 -m pytest tests/test_removal.py tests/test_claude_md_claims.py -q -p no:cacheprovider` und danach `python3 -m pytest -q -p no:cacheprovider && ruff check . && npx --yes pyright@1.1.411 src/mobile_pairing.py src/mobile_store.py`
Expected: PASS, `All checks passed!`, `0 errors`.

- [ ] **Step 5: Commit**

~~~bash
git add src/removal.py installer.iss .gitignore src/CLAUDE.md CLAUDE.md tests/test_removal.py
git commit -m "chore(mobile): mobile_devices.json beim Entfernen, in .gitignore und in der Doku (#221)

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
~~~

---

## Mutationsprüfung (nach Task 4, vor dem Review)

Jeden Mutanten einzeln anwenden (Datei kopieren, genau eine Ersetzung, Tests laufen lassen, zurückkopieren). Jeder muss mindestens einen Test rot färben:

| Datei | Mutation | Erwartet rot |
|---|---|---|
| `mobile_pairing.py` | `CODE_ALPHABET` um `O` erweitern | `test_the_alphabet_has_31_unambiguous_characters` |
| `mobile_pairing.py` | `normalize_code` ohne Alphabetprüfung | `test_normalize_rejects_anything_that_cannot_be_a_code` |
| `mobile_pairing.py` | Code nach erfolgreichem Einlösen nicht verbrauchen | `test_open_returns_a_formatted_code_that_redeems_once` |
| `mobile_pairing.py` | `self._failures >= self._max_failures` → `>` | `test_five_wrong_attempts_lock_the_session_until_the_next_open` |
| `mobile_pairing.py` | Ablauf `>=` → `>` | `test_the_code_expires_after_five_minutes_exactly` |
| `mobile_pairing.py` | `open()` setzt `_locked` nicht zurück | `test_five_wrong_attempts_lock_the_session_until_the_next_open` |
| `mobile_pairing.py` | `close()` setzt `_locked` nicht zurück | `test_close_invalidates_the_code_and_clears_a_lock` |
| `mobile_pairing.py` | Karenzfenster nicht prüfen (`>= now` → `True`) | `test_the_previous_token_works_for_ten_minutes_after_a_renewal` |
| `mobile_pairing.py` | Ablauf `<=` → `<` | `test_the_token_expires_exactly_at_expires_at` |
| `mobile_pairing.py` | `keep_previous` ignorieren | `test_a_lost_answer_twice_does_not_lock_the_phone_out` |
| `mobile_pairing.py` | `revoke` lässt das vorherige Token gültig | `test_revoke_also_cuts_the_grace_of_the_previous_token` |
| `mobile_pairing.py` | erneutes Koppeln verliert `last_pull_at` | `test_pairing_again_keeps_the_sync_identity_and_lifts_a_revocation` |
| `mobile_pairing.py` | Gerätename nicht bereinigen | `test_a_device_name_is_cleaned` |
| `mobile_store.py` | kein Rollback bei `save` | `test_a_failed_write_rolls_the_memory_back` |
| `mobile_store.py` | Hash-Format beim Laden nicht prüfen | `test_malformed_records_are_skipped_and_never_logged_in_full` |
| `mobile_store.py` | Zeitformat beim Laden nicht prüfen | `test_a_record_with_a_malformed_timestamp_is_skipped` |
| `mobile_store.py` | Read-only beim Schreiben ignorieren | `test_a_newer_schema_is_read_only_and_never_overwritten` |
| `mobile_store.py` | `prune` schreibt immer | `test_prune_without_a_hit_does_not_write` |
| `mobile_store.py` | `get` ohne Kopie | `test_results_are_copies` |

## Finale

Nach Task 4: Review über den ganzen Branch mit einem frischen Reviewer auf dem leistungsfähigsten Modell (Review Focus und Rulings mitgeben; aktiver Angriff mit hostilen Tokens, Dateien und Zeitabläufen), Critical/Important in **einem** Fix-Durchlauf (je Fix ein Test, der zuerst rot war), Minors ins Ledger und in ein Issue. Danach `finishing-a-development-branch`: PR gegen `master` (`Refs #221`).
