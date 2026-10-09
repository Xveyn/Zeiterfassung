# Mobile Erfassung, PR 5 von 9: Tab „Mobil", QR und Verdrahtung — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Die Handy-Instanz (#221) wird bedienbar: ein Reiter „Mobil" im Einstellungsdialog (Einschalten, Port, Adresse, Status, Geräteliste, Widerrufen), ein Koppel-Dialog mit QR-Code, und die Verdrahtung des `MobileService` in `main.py`/`ui.py` (Start, Beenden-Pfade, Skalierungs-Neustart, Entfernen). Danach lässt sich das Handy-Netz vom Nutzer einschalten und ein Gerät koppeln; die PWA selbst folgt in PR 6 und 7.

**Architecture:** Alles Entscheidbare liegt Tk-frei und getestet: `qr.py` (Matrix und Rechtecke aus `segno`), neue Regeln in `tab_rules.py` (Prüfung, Umrechnung, Statustexte, Adressauswahl, Geräte-Zeilen, Countdown). Der Reiter (`tab_mobile.py`) und der Koppel-Dialog (`mobile_pair_dialog.py`) sind dünne Tk-Schichten darüber und werden wie das übrige UI **nicht** automatisiert getestet (entschiedene Scope-Grenze); ihre Verdrahtung hält ein Quelltext-Test fest (Muster `test_api_wiring.py`). `App` baut den `MobileService` neben dem `ApiService` und ruft ihn an denselben Stellen.

**Tech Stack:** Python 3.12, Tkinter, neu `segno==1.6.6` (reines Python, `py3-none-any`, `Requires-Python >=3.5`, keine Abhängigkeiten auf 3.12).

**Spec:** `docs/superpowers/specs/2026-10-08-mobile-pwa-design.md` (Abschnitte „Bausteine" → Tab „Mobil", „Pairing und Token" 1 und 5, „Einschalten und Binden").

**Voraussetzung:** PR 2 bis 4b (#252, #255, #257, #259) sind gemergt.

**Branching:** `feat/mobile-tab` vom aktuellen `master`; der PR zielt auf `master`, trägt `Refs #221`, kein `Closes`. Kein Versionsbump. **Plattform:** der Reiter, der Koppel-Dialog und die Firewall-Frage hängen an Windows, macOS und Linux; vor dem Merge einen Pre-Release über alle drei Plattformen vorschlagen (Dependency-Auflösung ändert sich: neue Abhängigkeit).

## Rulings aus der Planung

- **`segno` wird lazy importiert** (in `qr_matrix`, nicht auf Modulebene), wie die Google-Wrapper: Module bleiben ohne die Bibliothek importierbar. CI installiert sie über `requirements-test.txt`, weil `tests/test_qr.py` sie braucht. PyInstaller findet den Import statisch; ein `--collect-all` ist nicht nötig (reines Python, nur `.matrix` wird gelesen, kein Schreiber, keine Datendateien). Das bestätigt der Pre-Release.
- **QR-Fehlerkorrektur `M`, kein Micro-QR.** Der Link ist rund 70 Zeichen (`https://xveyn.github.io/Zeiterfassung/#pair=192.168.178.20:17654:K7M29QXA`), das ergibt Version 4 bis 5 (33 bis 37 Module). Eine zu lange Eingabe würde `segno.DataOverflowError` werfen; der Dialog zeigt dann nur Text.
- **Weiße Fläche mit 4 Modulen Ruhezone unabhängig vom Dark-Theme** (Spec); Modulgröße über `theme.px()` am Ort des Widget-Baus (nicht zur Import-Zeit).
- **Adresse und Code stehen immer zusätzlich als Text da** (Spec), auch wenn der QR-Code erscheint.
- **Der Koppel-Dialog erkennt das Koppeln** (Gerätestand vor und nach dem Öffnen eines Codes) und meldet es. Wurde dabei ein **vorhandenes, nicht widerrufenes** Gerät ersetzt (dieselbe `device_id`, neues Token), steht eine ausdrückliche Warnung im Dialog. Das beantwortet die Designfrage aus #258 ohne Protokolländerung: die Spec erlaubt das erneute Koppeln derselben ID bewusst, der Besitzer soll es aber sehen. Kein Sperren, kein Nachfragen.
- **Das erste Einschalten verlangt eine Bestätigung** (Spec: Hinweis zur unverschlüsselten Verbindung, zum vertrauenswürdigen Netz und dass die App laufen muss). Gemerkt in einem **vierten** gerätelokalen Key `mobile_notice_accepted` (Standard `False`; die Spec nennt nur drei). Antwortet der Nutzer mit „Abbrechen", springt das Häkchen zurück.
- **Der Reiter schreibt wie `ApiTab` nur die Formularfelder** (`mobile_enabled`, `mobile_port`, `mobile_address`); Koppeln und Widerrufen sind Aktionen, die sofort wirken. Der Status kommt per `after`-Poll aus `MobileService.status`.
- **Die Adressliste wird im Worker geladen** (`netinfo.lan_candidates` kann auf `getaddrinfo` warten). Das Feld hält die Adresse selbst (oder „Automatisch"); eine später eintreffende Kandidatenliste ändert nur die Auswahl, nie den Wert, und macht den Reiter nicht „geändert".
- **Geräteliste:** lesen ist günstig (der Store hält sie im Speicher, `get_all` kopiert), also direkt im UI-Thread per Poll; **Schreiben** (`revoke`, `revoke_all`) läuft über den `BackgroundTaskRunner`.
- **Ohne `MobileStore` (Tests, Alt-Aufrufer) gibt es keinen Dienst und keinen Reiter:** `App(mobile_store=None)` setzt `self._mobile = None`, alle Aufrufstellen prüfen darauf.
- **`desktop_name`** (in der Pair-Antwort) ist `settings.device_name`, sonst `devices.default_device_name()`.
- **`on_change` der Handy-Instanz teilt sich den `RefreshCoalescer` der lokalen API** (`self._api_refresh`): beide lösen dasselbe Neuzeichnen aus, und ein Schwung Abgleiche soll nur einen Refresh queuen.
- **Beenden-Reihenfolge:** `self._mobile.shutdown()` steht neben `self._api.shutdown()` in `_quit_with_sync_push` (vor dem finalen Push), `remove_application` (vor jedem Worker) und `restart_for_scaling` (vor dem Spawn; bei Fehlschlag `reopen()` und `apply()`).
- **README, `known-limitations` und die Prüfliste #248** folgen in PR 9 (Doku); hier nur `CLAUDE.md`, `src/CLAUDE.md`, `CONTRIBUTING.md` und die Spec.

## Global Constraints

- Tk-freie Module (`qr.py`, `tab_rules.py`) vollständig annotiert; `qr.py` kommt in `ANNOTATED_MODULES`. `ruff check .` und `pyright 1.1.411` sauber.
- Pixelangaben im Layout durch `theme.px()` (`tests/test_pixel_scaling.py`: `wraplength=`/`length=` nie als Zahl-Literal), nie zur Import-Zeit ausgewertet.
- Wer `create_dialog` ruft, ruft `center_dialog_on_parent` (`tests/test_dialog_reveal.py`). Neue Dialoge nutzen die themed Helfer und `theme.Form`, keine eigenen Farben.
- Jeder Catch-all loggt, meldet oder begründet im Handler (`tests/test_catch_all_handlers.py`); `except tk.TclError` mit Kommentar, wie in `tab_api.py`.
- Fehlerdialoge: bekannte Fehler themed, Tracebacks nativ (Konvention aus der `CLAUDE.md`).
- Weder Code noch Token noch Hash in einem Log oder Dialogtext; der Pair-Code steht nur im Koppel-Dialog.
- Datumsanzeige deutsch über `time_utils.format_iso_date`/`format_iso_datetime`.

## Review Focus

1. **Nichts bleibt offen:** jeder Weg aus der App (Beenden, Entfernen, Neustart) stoppt den Handy-Server und schließt die Kopplungssitzung; schließt der Nutzer den Koppel-Dialog (X, Escape, Schließen, Absturz des Reiters), ist der Code ungültig. Tasks 4 und 5.
2. **Ehrliche Anzeige:** ein Server, der nicht läuft, zeigt nie einen QR-Code; `address_gone` nennt die fehlende Adresse und bietet die Auswahl an; ein ersetztes Gerät wird beim Koppeln gewarnt. Tasks 2 bis 4.
3. **Eingaben des Reiters:** ungültiger Port, Adresse mit Müll (Leerraum, Port, IPv6, Unicode-Ziffern, Nicht-LAN) → Fehlermeldung beim Speichern, nichts wird geschrieben. Task 2.
4. **Das erste Einschalten:** ohne Bestätigung wird nichts eingeschaltet, `mobile_notice_accepted` wird erst nach Zustimmung gesetzt, nicht beim Anzeigen. Task 4.
5. **Poll und Lebensdauer:** keine `after`-Callbacks nach dem Schließen (`TclError`), kein Worker-Callback auf ein zerstörtes Widget, die Listbox verliert ihre Auswahl nicht bei jedem Poll. Tasks 4 und 5.
6. **QR-Code:** die Matrix ist quadratisch, hat die Finder-Muster, ist deterministisch; Rechtecke decken exakt die dunklen Module; Ruhezone 4 Module; die Größe skaliert mit `px()`. Task 1.

---

### Task 1: `segno` und `qr.py`

**Files:**
- Modify: `requirements.txt`, `requirements-test.txt`, `CONTRIBUTING.md`
- Create: `src/qr.py`
- Create: `tests/test_qr.py`
- Modify: `tests/test_type_annotations.py`

**Interfaces:** Produces: `QUIET_MODULES = 4`; `qr_matrix(text: str) -> list[list[bool]]` (`True` = dunkles Modul, ohne Ruhezone; wirft `QrTooLong`); `class QrTooLong(ValueError)`; `canvas_size(modules: int, module_px: int) -> int` (inkl. Ruhezone); `dark_rects(matrix, module_px) -> list[tuple[int, int, int, int]]` (zusammengefasste horizontale Läufe als `(x0, y0, x1, y1)` in Pixeln, Ruhezone eingerechnet).

- [ ] **Step 1: Install and verify the dependency**

Run: `pip install segno==1.6.6` und `python3 -c "import segno; print(segno.__version__)"`
Expected: `1.6.6`. Prüfe außerdem `pip show segno | grep -i requires` — keine Abhängigkeiten auf Python 3.12 (`importlib-metadata` nur für < 3.10).

- [ ] **Step 2: Write the failing tests**

Create `tests/test_qr.py`:

```python
# tests/test_qr.py
import pytest

from src import qr

LINK = "https://xveyn.github.io/Zeiterfassung/#pair=192.168.178.20:17654:K7M29QXA"


def test_the_matrix_is_square_and_boolean():
    matrix = qr.qr_matrix(LINK)

    size = len(matrix)
    assert size >= 21 and all(len(row) == size for row in matrix)
    assert all(isinstance(cell, bool) for row in matrix for cell in row)
    assert (size - 17) % 4 == 0                         # Version n hat 4n + 17 Module


def test_the_link_fits_into_a_small_version():
    # Version 4 bis 6 (33 bis 41 Module): größer wäre mit dem Handy schwer zu scannen.
    assert 33 <= len(qr.qr_matrix(LINK)) <= 41


def test_the_three_finder_patterns_are_there():
    matrix = qr.qr_matrix(LINK)
    size = len(matrix)

    def finder(top, left):
        return [row[left:left + 7] for row in matrix[top:top + 7]]

    expected = [
        [True] * 7,
        [True] + [False] * 5 + [True],
        [True, False, True, True, True, False, True],
        [True, False, True, True, True, False, True],
        [True, False, True, True, True, False, True],
        [True] + [False] * 5 + [True],
        [True] * 7,
    ]
    assert finder(0, 0) == expected
    assert finder(0, size - 7) == expected
    assert finder(size - 7, 0) == expected


def test_the_matrix_is_deterministic_and_depends_on_the_text():
    assert qr.qr_matrix(LINK) == qr.qr_matrix(LINK)
    assert qr.qr_matrix(LINK) != qr.qr_matrix(LINK.replace("K7M29QXA", "K7M29QXB"))


def test_too_long_a_text_raises_qr_too_long():
    with pytest.raises(qr.QrTooLong):
        qr.qr_matrix("x" * 5000)


def test_the_canvas_size_includes_the_quiet_zone():
    assert qr.canvas_size(33, 6) == (33 + 2 * qr.QUIET_MODULES) * 6
    assert qr.canvas_size(33, 1) == 41 and qr.QUIET_MODULES == 4


def test_dark_rects_cover_exactly_the_dark_modules():
    matrix = qr.qr_matrix(LINK)
    scale = 3

    painted = set()
    for x0, y0, x1, y1 in qr.dark_rects(matrix, scale):
        assert (y1 - y0) == scale and (x1 - x0) % scale == 0
        for x in range(x0, x1, scale):
            assert (x, y0) not in painted                 # kein Modul doppelt
            painted.add((x, y0))

    offset = qr.QUIET_MODULES * scale
    expected = {(offset + col * scale, offset + row * scale)
                for row, cells in enumerate(matrix) for col, dark in enumerate(cells) if dark}
    assert painted == expected


def test_dark_rects_merge_horizontal_runs():
    matrix = [[True, True, False, True], [False, False, False, False],
              [True, False, True, True], [False, True, True, False]]

    rects = qr.dark_rects(matrix, 2)

    offset = qr.QUIET_MODULES * 2
    assert rects[0] == (offset, offset, offset + 4, offset + 2)         # zwei Module in einem Lauf
    assert (offset + 6, offset, offset + 8, offset + 2) in rects           # das einzelne letzte
    assert len(rects) == 5


def test_an_empty_matrix_has_no_rects():
    assert qr.dark_rects([], 4) == []
    assert qr.dark_rects([[False, False]], 4) == []
```

- [ ] **Step 3: Run to verify they fail**

Run: `python3 -m pytest tests/test_qr.py -q -p no:cacheprovider -x`
Expected: ERROR beim Sammeln: `ImportError: cannot import name 'qr' from 'src'`.

- [ ] **Step 4: Implement**

Create `src/qr.py`:

```python
# src/qr.py
"""QR-Code für den Koppel-Dialog (#221), Tk-frei.

`segno` (reines Python, BSD) liefert die Matrix; gezeichnet wird sie vom Dialog auf
einem Tk-`Canvas`. Hier liegt alles, was sich ohne Fenster prüfen lässt: die Matrix
selbst, die Maße samt Ruhezone und die Rechtecke, aus denen der Dialog sie malt.

`segno` wird **lazy** importiert (wie die Google-Wrapper): das Modul bleibt ohne die
Bibliothek importierbar, und die CI installiert sie nur dort, wo ein Test sie braucht.
"""
from __future__ import annotations

# Die Ruhezone des QR-Standards: vier Module weiße Fläche rundherum, unabhängig vom
# Dark-Theme des Dialogs — ohne sie scannt kein Handy.
QUIET_MODULES = 4


class QrTooLong(ValueError):
    """Der Text passt nicht in einen QR-Code (der Dialog zeigt dann nur Text)."""


def qr_matrix(text: str) -> list[list[bool]]:
    """Die Module des QR-Codes (`True` = dunkel), ohne Ruhezone. Fehlerkorrektur `M`,
    kein Micro-QR (Handy-Kameras lesen ihn schlecht)."""
    import segno
    try:
        code = segno.make(text, error="m", micro=False, boost_error=False)
    except segno.DataOverflowError as exc:
        raise QrTooLong(str(exc)) from None
    return [[bool(cell) for cell in row] for row in code.matrix]


def canvas_size(modules: int, module_px: int) -> int:
    """Kantenlänge der quadratischen Zeichenfläche in Pixeln, mit Ruhezone."""
    return (modules + 2 * QUIET_MODULES) * module_px


def dark_rects(matrix: list[list[bool]], module_px: int) -> list[tuple[int, int, int, int]]:
    """Die dunklen Module als Rechtecke `(x0, y0, x1, y1)` in Pixeln, Ruhezone
    eingerechnet. Benachbarte dunkle Module einer Zeile sind **ein** Rechteck: das hält
    die Zahl der Canvas-Items klein (eine Version-5-Matrix hat über 600 dunkle Module)."""
    offset = QUIET_MODULES * module_px
    rects: list[tuple[int, int, int, int]] = []
    for row_index, row in enumerate(matrix):
        y0 = offset + row_index * module_px
        col = 0
        while col < len(row):
            if not row[col]:
                col += 1
                continue
            start = col
            while col < len(row) and row[col]:
                col += 1
            rects.append((offset + start * module_px, y0,
                          offset + col * module_px, y0 + module_px))
    return rects
```

Ergänze `segno==1.6.6` in `requirements.txt` (Kommentar: `# QR-Code im Koppel-Dialog der Handy-Erfassung; reines Python, py3-none-any, Requires-Python >=3.5` — Python-3.12-Gegencheck bestanden), in `requirements-test.txt` (Kommentar: `# tests/test_qr.py`) und in der Tabelle in `CONTRIBUTING.md`:

```markdown
| `segno` | QR-Code im Koppel-Dialog der Handy-Erfassung (reines Python) |
```

(vor der Zeile `| \`pystray\` |` einfügen). In `tests/test_type_annotations.py` ersetze

```python
    "src/api_summary.py",
```

durch

```python
    "src/api_summary.py",
    "src/qr.py",
```

- [ ] **Step 5: Run to verify they pass**

Run: `python3 -m pytest tests/test_qr.py tests/test_type_annotations.py tests/test_claude_md_claims.py -q -p no:cacheprovider` und danach `python3 -m pytest -q -p no:cacheprovider && ruff check . && npx --yes pyright@1.1.411 src/qr.py`
Expected: PASS, `All checks passed!`, `0 errors`. Ist `test_the_link_fits_into_a_small_version` zu eng (andere Version als 33 bis 41 Module), prüfe die tatsächliche Größe und passe die Grenzen mit einem Ruling an — die Aussage ist „kleiner QR-Code".

- [ ] **Step 6: Commit**

~~~bash
git add requirements.txt requirements-test.txt CONTRIBUTING.md src/qr.py tests/test_qr.py tests/test_type_annotations.py
git commit -m "feat(mobile): QR-Code-Modul mit segno (#221)

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
~~~

---

### Task 2: Regeln des Reiters in `tab_rules.py` und der Settings-Key

**Files:**
- Modify: `src/settings.py` (`mobile_notice_accepted`)
- Modify: `src/dialogs/settings_dialog/tab_rules.py`
- Modify: `tests/test_tab_rules.py`, `tests/test_settings.py`

**Interfaces:** Consumes: `mobile_service.MobileStatus/STATE_*/REASON_*/DEFAULT_PORT`, `api_service.parse_port`, `netinfo.is_lan_address`, `time_utils.format_iso_date/format_iso_datetime`. Produces in `tab_rules`: `AUTO_ADDRESS`; `address_options(candidates: list[str]) -> list[str]`; `address_from_choice(choice: str) -> str`; `address_to_choice(address: str) -> str`; `validate_mobile(raw) -> tuple[str, str] | None`; `mobile_updates(raw) -> dict`; `mobile_status_view(status) -> tuple[str, str]`; `device_row_text(record, now) -> str`; `format_countdown(seconds: int) -> str`; `FIRST_ENABLE_NOTICE`; `pair_changes(before, after) -> PairChanges`. Settings: `DEFAULTS["mobile_notice_accepted"] = False`.

- [ ] **Step 1: Write the failing tests**

Hänge an `tests/test_settings.py` an:

```python
def test_the_first_enable_notice_is_remembered_device_locally():
    from src.settings import DEFAULTS, SYNCED_SETTING_KEYS
    assert DEFAULTS["mobile_notice_accepted"] is False
    assert "mobile_notice_accepted" not in SYNCED_SETTING_KEYS
```

Hänge an `tests/test_tab_rules.py` an:

```python
# --- Mobil-Tab (#221, PR 5) -----------------------------------------------------------------

from src.mobile_service import (  # noqa: E402
    REASON_ADDRESS_GONE, REASON_INVALID_PORT, REASON_NO_ADDRESS, REASON_PORT_IN_USE,
    REASON_START_FAILED, MobileStatus,
)
from src.mobile_service import STATE_ERROR as M_ERROR  # noqa: E402
from src.mobile_service import STATE_OFF as M_OFF  # noqa: E402
from src.mobile_service import STATE_RUNNING as M_RUNNING  # noqa: E402
from src.mobile_service import STATE_STARTING as M_STARTING  # noqa: E402


def mobile_raw(**overrides):
    raw = {"mobile_enabled": True, "mobile_port": "17654", "mobile_address": tr.AUTO_ADDRESS}
    raw.update(overrides)
    return raw


def test_address_options_start_with_automatic_and_keep_the_order():
    assert tr.address_options(["192.168.1.20", "10.0.0.5"]) == [
        tr.AUTO_ADDRESS, "192.168.1.20", "10.0.0.5"]
    assert tr.address_options([]) == [tr.AUTO_ADDRESS]


def test_address_choice_round_trips():
    assert tr.address_from_choice(tr.AUTO_ADDRESS) == ""
    assert tr.address_from_choice("192.168.1.20") == "192.168.1.20"
    assert tr.address_to_choice("") == tr.AUTO_ADDRESS
    assert tr.address_to_choice("192.168.1.20") == "192.168.1.20"


def test_valid_mobile_input_passes_and_converts():
    assert tr.validate_mobile(mobile_raw()) is None
    assert tr.mobile_updates(mobile_raw()) == {
        "mobile_enabled": True, "mobile_port": 17654, "mobile_address": ""}
    assert tr.mobile_updates(mobile_raw(mobile_address="10.0.0.5", mobile_enabled=False,
                                        mobile_port=" 8080 ")) == {
        "mobile_enabled": False, "mobile_port": 8080, "mobile_address": "10.0.0.5"}


@pytest.mark.parametrize("port", ["", "abc", "80", "70000", "17654.5", "٨٠٨٠", "9" * 5000])
def test_an_invalid_port_is_refused_even_when_off(port):
    result = tr.validate_mobile(mobile_raw(mobile_port=port, mobile_enabled=False))
    assert result is not None and "Port" in result[0]


@pytest.mark.parametrize("address", [
    " 192.168.1.20", "192.168.1.20:17654", "8.8.8.8", "127.0.0.1", "0.0.0.0", "::1", "fe80::1",
    "192.168.001.001", "１９２.１６８.１.２０", "localhost", "192.168.1.256",
])
def test_an_address_that_is_not_a_lan_address_is_refused(address):
    result = tr.validate_mobile(mobile_raw(mobile_address=address))
    assert result is not None and "Adresse" in result[0]


def test_mobile_updates_write_exactly_the_three_form_keys():
    assert set(tr.mobile_updates(mobile_raw())) == {
        "mobile_enabled", "mobile_port", "mobile_address"}


@pytest.mark.parametrize("status,kind,fragment", [
    (MobileStatus(M_OFF), "muted", "Aus"),
    (MobileStatus(M_STARTING, None, 17654), "muted", "Startet"),
    (MobileStatus(M_RUNNING, "192.168.1.20", 17654), "ok", "192.168.1.20:17654"),
    (MobileStatus(M_ERROR, None, None, REASON_INVALID_PORT), "error", "Port"),
    (MobileStatus(M_ERROR, None, 17654, REASON_NO_ADDRESS), "error", "Netzwerk"),
    (MobileStatus(M_ERROR, "10.9.9.9", 17654, REASON_ADDRESS_GONE), "error", "10.9.9.9"),
    (MobileStatus(M_ERROR, "192.168.1.20", 17654, REASON_PORT_IN_USE), "error", "17654"),
    (MobileStatus(M_ERROR, "192.168.1.20", 17654, REASON_START_FAILED), "error", "Protokoll"),
])
def test_the_status_view(status, kind, fragment):
    text, got_kind = tr.mobile_status_view(status)
    assert got_kind == kind and fragment in text


def test_an_unknown_error_reason_still_gets_a_sentence():
    text, kind = tr.mobile_status_view(MobileStatus(M_ERROR, None, None, "ganz neu"))
    assert kind == "error" and "Protokoll" in text


def test_the_vanished_address_status_offers_the_choice():
    text, _kind = tr.mobile_status_view(
        MobileStatus(M_ERROR, "10.9.9.9", 17654, REASON_ADDRESS_GONE))
    assert "wählen" in text.lower()


NOW_ISO = "2026-10-08T12:00:00Z"


def device(**overrides):
    record = {"id": "phone-0001", "name": "Pixel von Sven", "revoked": False,
              "last_seen": "2026-10-07T09:15:00Z", "expires_at": "2026-11-06T09:15:00Z"}
    record.update(overrides)
    return record


def test_a_device_row_shows_name_last_seen_and_expiry_in_german_format():
    text = tr.device_row_text(device(), NOW_ISO)
    assert "Pixel von Sven" in text and "07.10.2026 09:15" in text and "06.11.2026" in text
    assert "widerrufen" not in text and "abgelaufen" not in text


def test_a_revoked_device_is_marked():
    assert "widerrufen" in tr.device_row_text(device(revoked=True), NOW_ISO)


def test_an_expired_device_is_marked_from_the_second_it_expires():
    assert "abgelaufen" not in tr.device_row_text(device(expires_at="2026-10-08T12:00:01Z"), NOW_ISO)
    assert "abgelaufen" in tr.device_row_text(device(expires_at="2026-10-08T12:00:00Z"), NOW_ISO)


def test_a_device_row_survives_missing_fields():
    text = tr.device_row_text({"id": "x", "name": ""}, NOW_ISO)
    assert isinstance(text, str) and text


@pytest.mark.parametrize("seconds,expected", [
    (300, "5:00"), (299, "4:59"), (61, "1:01"), (60, "1:00"), (9, "0:09"), (0, "0:00"),
    (-5, "0:00"),
])
def test_the_countdown(seconds, expected):
    assert tr.format_countdown(seconds) == expected


def test_the_first_enable_notice_names_the_three_things_the_spec_demands():
    notice = tr.FIRST_ENABLE_NOTICE
    assert "unverschlüsselt" in notice
    assert "vertrauenswürdig" in notice
    assert "Autostart" in notice


def dev(device_id, token_hash, name="P", revoked=False):
    return {"id": device_id, "token_hash": token_hash, "name": name, "revoked": revoked}


def test_pair_changes_finds_a_new_device():
    changes = tr.pair_changes([dev("a", "h1")], [dev("a", "h1"), dev("b", "h2", "Neu")])
    assert [d["name"] for d in changes.added] == ["Neu"] and changes.replaced == []


def test_pair_changes_flags_a_replaced_live_device():
    changes = tr.pair_changes([dev("a", "h1", "Alt")], [dev("a", "h2", "Alt")])
    assert changes.added == [] and [d["name"] for d in changes.replaced] == ["Alt"]


def test_pair_changes_does_not_warn_when_the_replaced_device_was_revoked():
    changes = tr.pair_changes([dev("a", "h1", "Alt", revoked=True)], [dev("a", "h2", "Alt")])
    assert changes.replaced == [] and [d["name"] for d in changes.added] == ["Alt"]


def test_pair_changes_ignores_renewals_that_keep_the_token_state():
    assert tr.pair_changes([dev("a", "h1")], [dev("a", "h1")]).empty


def test_pair_changes_reports_nothing_for_an_unchanged_or_shrunk_list():
    assert tr.pair_changes([dev("a", "h1")], []).empty
```

- [ ] **Step 2: Run to verify they fail**

Run: `python3 -m pytest tests/test_tab_rules.py tests/test_settings.py -q -p no:cacheprovider -x`
Expected: FAIL: `AttributeError: module 'src.dialogs.settings_dialog.tab_rules' has no attribute 'AUTO_ADDRESS'` bzw. `KeyError: 'mobile_notice_accepted'`.

- [ ] **Step 3: Implement**

In `src/settings.py` ersetze

```python
    "mobile_address": "",
```

durch

```python
    "mobile_address": "",
    # Der Hinweis beim ersten Einschalten (unverschlüsselte Verbindung, vertrauenswürdiges
    # Netz, App muss laufen) wurde bestätigt. Gerätelokal wie die übrigen mobile_*.
    "mobile_notice_accepted": False,
```

In `src/dialogs/settings_dialog/tab_rules.py` ergänze die Importe (zu den vorhandenen von `api_service`/`time_utils` einsortieren; prüfe mit `grep -n "^from\|^import" src/dialogs/settings_dialog/tab_rules.py`):

```python
from dataclasses import dataclass

from src.mobile_service import (
    DEFAULT_PORT as MOBILE_DEFAULT_PORT, REASON_ADDRESS_GONE, REASON_INVALID_PORT,
    REASON_NO_ADDRESS, REASON_PORT_IN_USE, STATE_ERROR as MOBILE_ERROR,
    STATE_RUNNING as MOBILE_RUNNING, STATE_STARTING as MOBILE_STARTING, MobileStatus,
)
from src.netinfo import is_lan_address
from src.time_utils import format_iso_date, format_iso_datetime
```

(`parse_port`/`MIN_PORT`/`MAX_PORT` kommen bereits aus `api_service`; `dataclass` ggf. schon vorhanden.) Hänge ans Ende an:

```python
# --- Mobil-Tab (#221) ---------------------------------------------------------------------------

AUTO_ADDRESS = "Automatisch"

FIRST_ENABLE_NOTICE = (
    "Die Handy-Erfassung öffnet einen Server in Ihrem WLAN/LAN. Die Verbindung zum Handy "
    "ist unverschlüsselt: wer im selben Netz mitlauscht, kann das Gerätetoken mitlesen "
    "und damit Arbeitszeiten lesen und eintragen. Nutzen Sie die Funktion nur in einem "
    "vertrauenswürdigen Netz.\\n\\n"
    "Die App muss laufen, damit sich das Handy abgleichen kann; ein Autostart "
    "(Tab „App“) wird empfohlen. Unter Windows fragt die Firewall beim ersten Mal, ob "
    "die App im privaten Netz Verbindungen annehmen darf.\\n\\n"
    "Jetzt einschalten?")

_MOBILE_ERRORS = {
    REASON_INVALID_PORT: "Der Port ist ungültig (1024 bis 65535).",
    REASON_NO_ADDRESS: ("Keine passende Netzwerkadresse gefunden. Mit einem WLAN oder "
                        "LAN verbinden und die Einstellungen erneut speichern."),
    REASON_ADDRESS_GONE: ("Die gewählte Adresse {address} gibt es nicht mehr (anderes "
                          "Netz?). Bitte eine Adresse wählen oder „Automatisch“ einstellen."),
    REASON_PORT_IN_USE: "Port {port} ist belegt. Einen anderen Port wählen.",
}


def address_options(candidates: list[str]) -> list[str]:
    """Die Auswahl der Adress-Combobox: „Automatisch“ (der Vorschlag der aktiven
    Verbindung) und die gefundenen LAN-Adressen."""
    return [AUTO_ADDRESS, *candidates]


def address_from_choice(choice: str) -> str:
    """Der Settings-Wert zu einer Auswahl: „Automatisch“ ist die leere Adresse."""
    return "" if choice == AUTO_ADDRESS else choice


def address_to_choice(address: str) -> str:
    return address or AUTO_ADDRESS


def validate_mobile(raw: Mapping[str, Any]) -> tuple[str, str] | None:
    """Port und Adresse müssen gültig sein — auch bei ausgeschaltetem Schalter, damit ein
    kaputter Wert nicht erst beim späteren Einschalten auffällt."""
    if parse_port(raw["mobile_port"]) is None:
        return ("Ungültiger Port",
                f"Der Port muss eine Zahl zwischen {MIN_PORT} und {MAX_PORT} sein.")
    address = address_from_choice(str(raw["mobile_address"]))
    if address and not is_lan_address(address):
        return ("Ungültige Adresse",
                "Die Adresse muss eine private IPv4-Adresse sein (10.x.x.x, 172.16–31.x.x "
                "oder 192.168.x.x) oder „Automatisch“.")
    return None


def mobile_updates(raw: Mapping[str, Any]) -> dict[str, Any]:
    """Settings-Werte des Mobil-Tabs. Tolerant wie die anderen Tabs: ein ungültiger Port
    fällt auf den Standard (`validate_mobile` fängt ihn vorher)."""
    return {
        "mobile_enabled": bool(raw["mobile_enabled"]),
        "mobile_port": parse_port(raw["mobile_port"]) or MOBILE_DEFAULT_PORT,
        "mobile_address": address_from_choice(str(raw["mobile_address"])),
    }


def mobile_status_view(status: MobileStatus) -> tuple[str, str]:
    """(Text, Art) für die Statuszeile; Art ist `ok`, `muted` oder `error`."""
    if status.state == MOBILE_RUNNING:
        return f"Läuft auf {status.address}:{status.port}", "ok"
    if status.state == MOBILE_STARTING:
        return "Startet …", "muted"
    if status.state == MOBILE_ERROR:
        text = _MOBILE_ERRORS.get(status.reason,
                                  "Start fehlgeschlagen. Details im Protokoll.")
        return text.format(address=status.address, port=status.port), "error"
    return "Aus.", "muted"


def device_row_text(record: Mapping[str, Any], now: str) -> str:
    """Eine Zeile der Geräteliste: Name, zuletzt gesehen, gültig bis; widerrufen und
    abgelaufen sind markiert."""
    name = str(record.get("name") or record.get("id") or "?")
    mark = ""
    if record.get("revoked"):
        mark = "  (widerrufen)"
    elif str(record.get("expires_at") or "9999") <= now:
        mark = "  (abgelaufen)"
    seen = format_iso_datetime(record.get("last_seen"))
    until = format_iso_date(record.get("expires_at"))
    return f"{name}{mark}  —  zuletzt {seen}, gültig bis {until}"


def format_countdown(seconds: int) -> str:
    """`299` → `4:59`. Negative Werte zeigen `0:00`."""
    seconds = max(0, int(seconds))
    return f"{seconds // 60}:{seconds % 60:02d}"


@dataclass(frozen=True)
class PairChanges:
    added: list[dict[str, Any]]
    replaced: list[dict[str, Any]]      # vorhandene, nicht widerrufene Geräte mit neuem Token

    @property
    def empty(self) -> bool:
        return not self.added and not self.replaced


def pair_changes(before: list[dict[str, Any]], after: list[dict[str, Any]]) -> PairChanges:
    """Was ein Koppeln am Gerätebestand geändert hat. Neu = unbekannte ID **oder** ein
    widerrufenes Gerät, das ein neues Token bekam. `replaced` = ein vorhandenes, nicht
    widerrufenes Gerät bekam ein neues Token (jemand hat sich mit seiner `device_id`
    gekoppelt): der Besitzer soll das sehen. Erneuerungen beim Abgleich fallen nicht
    darunter — der Koppel-Dialog schaut nur, solange sein Code offen ist."""
    known = {record["id"]: record for record in before}
    added: list[dict[str, Any]] = []
    replaced: list[dict[str, Any]] = []
    for record in after:
        old = known.get(record["id"])
        if old is None:
            added.append(record)
        elif old.get("token_hash") != record.get("token_hash"):
            (added if old.get("revoked") else replaced).append(record)
    return PairChanges(added, replaced)
```

Hinweis: `DEFAULT_PORT` des API-Tabs heißt in `tab_rules.py` schon `DEFAULT_PORT`, deshalb der Alias `MOBILE_DEFAULT_PORT`.

- [ ] **Step 4: Run to verify they pass**

Run: `python3 -m pytest tests/test_tab_rules.py tests/test_settings.py tests/test_type_annotations.py -q -p no:cacheprovider` und danach `python3 -m pytest -q -p no:cacheprovider && ruff check . && npx --yes pyright@1.1.411 src/dialogs/settings_dialog/tab_rules.py`
Expected: PASS, `All checks passed!`, `0 errors`. (`tab_rules.py` ist Tk-frei; ist es in der Whitelist, müssen die neuen Funktionen voll annotiert sein — sie sind es.)

- [ ] **Step 5: Commit**

~~~bash
git add src/settings.py src/dialogs/settings_dialog/tab_rules.py tests/test_tab_rules.py tests/test_settings.py
git commit -m "feat(mobile): Regeln des Reiters Mobil, Adressauswahl und Koppel-Änderungen (#221)

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
~~~

---

### Task 3: Koppel-Dialog

**Files:**
- Create: `src/dialogs/mobile_pair_dialog.py`

**Interfaces:** Consumes: `MobileService` (`status`, `pairing`, `pair_link`, `list_devices`), `qr` (Task 1), `tab_rules` (Task 2). Produces: `open_pair_dialog(parent, service)` — modal; schließt beim Verlassen die Kopplungssitzung.

Der Dialog ist Tk-Code und wird nicht automatisiert getestet (Scope-Grenze); seine Entscheidungen liegen in den getesteten Regeln aus Task 1 und 2. Geprüft wird er in Step 3 von Hand.

- [ ] **Step 1: Write the dialog**

Create `src/dialogs/mobile_pair_dialog.py`:

```python
"""Koppel-Dialog der Handy-Erfassung (#221): zeigt einen Einmalcode als QR-Code und als
Text, zählt seine Gültigkeit herunter und meldet das Koppeln.

Der Code lebt nur im Hauptspeicher (`PairingSession`). Verlässt der Nutzer den Dialog —
Schließen, X, Escape —, wird die Sitzung geschlossen: ein offener Code ohne Dialog wäre
ein Einmalpasswort, das niemand sieht. Der Dialog erkennt ein Koppeln am Gerätebestand
(vorher/nachher) und warnt, wenn dabei ein vorhandenes, nicht widerrufenes Gerät ersetzt
wurde (jemand hat sich mit dessen `device_id` gekoppelt).

Der Poll läuft per `after` am Dialog und stirbt mit ihm.
"""
import logging
import tkinter as tk

from src import qr
from src.dialogs.settings_dialog.tab_rules import format_countdown, pair_changes
from src.theme import (
    BG, FONT, FONT_BOLD, STATUS_OK, STATUS_WARN, TEXT, TEXT_MUTED, center_dialog_on_parent,
    create_dialog, primary_button, px, secondary_button,
)

log = logging.getLogger(__name__)

_POLL_MS = 1000
_WRAP_PX = 380
_MODULE_PX = 6           # Kantenlänge eines Moduls bei 100 %; skaliert über px()


class _PairDialog:
    def __init__(self, parent, service):
        self._service = service
        self._alive = True
        self._poll_id = None
        self._before = service.list_devices()
        self._dialog = dialog = create_dialog(parent, "Handy koppeln")

        tk.Label(
            dialog, text=("Kamera-App des Handys öffnen und den QR-Code scannen — oder "
                          "die Adresse im Browser öffnen und den Code eintippen."),
            font=FONT, bg=BG, fg=TEXT, justify="left", anchor="w",
            wraplength=px(_WRAP_PX)).pack(padx=16, pady=(14, 8), anchor="w")

        # Weiße Fläche samt Ruhezone, unabhängig vom Dark-Theme (sonst scannt es nicht).
        self._canvas = tk.Canvas(dialog, bg="#ffffff", highlightthickness=0)
        self._canvas.pack(pady=4)

        self._address = tk.Label(dialog, text="", font=FONT, bg=BG, fg=TEXT_MUTED)
        self._address.pack(pady=(6, 0))
        self._code = tk.Label(dialog, text="", font=FONT_BOLD, bg=BG, fg=TEXT)
        self._code.pack()
        self._countdown = tk.Label(dialog, text="", font=FONT, bg=BG, fg=TEXT_MUTED)
        self._countdown.pack()
        self._result = tk.Label(
            dialog, text="", font=FONT, bg=BG, fg=STATUS_OK, justify="left",
            wraplength=px(_WRAP_PX))
        self._result.pack(padx=16, pady=(6, 0), anchor="w")

        buttons = tk.Frame(dialog, bg=BG)
        buttons.pack(pady=12)
        primary_button(buttons, "Neuer Code", self._new_code).pack(side=tk.LEFT, padx=5)
        secondary_button(buttons, "Schließen", self._close).pack(side=tk.LEFT, padx=5)

        dialog.protocol("WM_DELETE_WINDOW", self._close)
        dialog.bind("<Escape>", lambda _e: self._close())
        dialog.bind("<Destroy>", self._on_destroy, add="+")
        self._new_code()
        center_dialog_on_parent(dialog, parent)

    # --- Code und Anzeige ---------------------------------------------------------

    def _new_code(self):
        status = self._service.status
        self._canvas.delete("all")
        self._result.config(text="")
        if status.state != "running":
            self._service.pairing.close()
            self._address.config(text="")
            self._code.config(text="")
            self._countdown.config(text="")
            self._result.config(
                text="Die Handy-Erfassung läuft gerade nicht. Im Reiter „Mobil“ "
                     "einschalten und speichern, dann hier erneut öffnen.",
                fg=STATUS_WARN)
            self._canvas.config(width=1, height=1)
            return
        self._before = self._service.list_devices()
        code = self._service.pairing.open()
        link = self._service.pair_link(code)
        self._address.config(text=f"Adresse: {status.address}:{status.port}")
        self._code.config(text=f"Code: {code}")
        self._draw(link)
        self._schedule_poll()

    def _draw(self, link):
        scale = px(_MODULE_PX)
        try:
            matrix = qr.qr_matrix(link) if link else None
        except qr.QrTooLong:
            log.warning("Koppel-Link zu lang für einen QR-Code", exc_info=True)
            matrix = None
        if matrix is None:
            self._canvas.config(width=1, height=1)
            self._result.config(text="Der QR-Code konnte nicht erzeugt werden — bitte "
                                     "Adresse und Code von Hand eintippen.", fg=STATUS_WARN)
            return
        size = qr.canvas_size(len(matrix), scale)
        self._canvas.config(width=size, height=size)
        for x0, y0, x1, y1 in qr.dark_rects(matrix, scale):
            self._canvas.create_rectangle(x0, y0, x1, y1, fill="#000000", outline="")

    def _schedule_poll(self):
        if self._poll_id is None:
            self._poll_id = self._dialog.after(_POLL_MS, self._poll)

    def _poll(self):
        self._poll_id = None
        if not self._alive:
            return
        try:
            left = self._service.pairing.seconds_left()
            changes = pair_changes(self._before, self._service.list_devices())
            if not changes.empty:
                self._show_paired(changes)
            elif left > 0:
                self._countdown.config(text=f"Gültig noch {format_countdown(left)}")
            elif not self._service.pairing.is_active():
                self._countdown.config(text="Der Code ist abgelaufen — „Neuer Code“.")
            if self._alive and (left > 0 or not changes.empty):
                self._schedule_poll()
        except tk.TclError:
            self._alive = False             # Fenster zwischenzeitlich zu

    def _show_paired(self, changes):
        names = ", ".join(d["name"] for d in changes.added + changes.replaced)
        text = f"Gekoppelt: {names}. Für ein weiteres Handy „Neuer Code“."
        color = STATUS_OK
        if changes.replaced:
            old = ", ".join(d["name"] for d in changes.replaced)
            text += (f"\nAchtung: dabei wurde das vorhandene Gerät „{old}“ ersetzt "
                     "(jemand hat sich mit dessen Kennung gekoppelt). Gehörte der Code "
                     "nicht zu Ihrem eigenen Handy, widerrufen Sie das Gerät im Reiter.")
            color = STATUS_WARN
        self._result.config(text=text, fg=color)
        self._canvas.delete("all")
        self._code.config(text="")
        self._countdown.config(text="")
        self._before = self._service.list_devices()

    # --- Schließen -------------------------------------------------------------------

    def _close(self):
        self._service.pairing.close()
        if self._dialog.winfo_exists():
            self._dialog.destroy()

    def _on_destroy(self, event):
        if event.widget is not self._dialog:
            return
        self._alive = False
        self._service.pairing.close()
        if self._poll_id is not None:
            try:
                self._dialog.after_cancel(self._poll_id)
            except tk.TclError:
                pass                        # Fenster schon weg: nichts mehr zu stornieren


def open_pair_dialog(parent, service):
    """Öffnet den Koppel-Dialog (modal). Schließt die Kopplungssitzung beim Verlassen."""
    _PairDialog(parent, service)
```

- [ ] **Step 2: Static checks**

Run: `python3 -c "import src.dialogs.mobile_pair_dialog" && python3 -m pytest tests/test_pixel_scaling.py tests/test_dialog_reveal.py tests/test_catch_all_handlers.py tests/test_claude_md_claims.py -q -p no:cacheprovider && ruff check .`
Expected: PASS, `All checks passed!`. Schlägt `test_dialog_reveal` fehl, fehlt `center_dialog_on_parent`; schlägt `test_pixel_scaling` fehl, steht ein Zahl-Literal in `wraplength=`; `test_catch_all_handlers` verlangt für das stumme `except tk.TclError` den Kommentar im Handler (steht).

- [ ] **Step 3: Manual check (DISPLAY vorhanden)**

Run (Beispielskript im Scratchpad, nicht ins Repo):

```bash
export SCRATCH=/tmp/claude-1000/-home-sven-projects-Zeiterfassung/4a6ac0e0-2b97-4606-aba1-33a39df36a81/scratchpad
cat > "$SCRATCH/pair_smoke.py" <<'E'
import tempfile, threading, tkinter as tk
from src import mobile_routes
from src.conflicts_store import ConflictsStore
from src.dialogs.mobile_pair_dialog import open_pair_dialog
from src.mobile_pairing import PairingSession
from src.mobile_service import MobileService
from src.mobile_store import MobileStore
from src.settings import Settings
from src.storage import Storage
from src.theme import init_fonts, apply_widget_defaults

root = tk.Tk(); init_fonts(root, 1.0); apply_widget_defaults(root)
d = tempfile.mkdtemp()
settings = Settings(d + "/s.json")
settings.set_many({"mobile_enabled": True, "mobile_port": 17654, "mobile_address": "127.0.0.1"})
ctx = mobile_routes.MobileContext(pairing=PairingSession(), devices=MobileStore(d + "/m.json"),
    devices_lock=threading.RLock(), storage=Storage(d + "/z.json", device_id="D"), settings=settings,
    conflicts_store=ConflictsStore(d + "/c.json"), base=d, desktop_name=lambda: "Desktop")
def run(fn, done=None):
    result = fn()
    if done is not None:
        done(result)


svc = MobileService(settings, ctx, run=run, lan_candidates=lambda: ["127.0.0.1"])
svc.apply()
root.after(300, lambda: open_pair_dialog(root, svc))
root.after(6000, root.destroy)
root.mainloop(); svc.shutdown()
E
PYTHONPATH=. python3 "$SCRATCH/pair_smoke.py"
```

Expected: ein Fenster mit weißem QR-Code, „Adresse: 127.0.0.1:17654", „Code: XXXX-XXXX" und Countdown erscheint, kein Traceback. (Der Aufruf von `init_fonts`/`apply_widget_defaults` folgt der Signatur aus `main.py`; weicht sie ab, übernimm die dortige.) Den QR-Code mit einem Handy scannen und prüfen, dass der Link `https://xveyn.github.io/Zeiterfassung/#pair=127.0.0.1:17654:<CODE>` zeigt.

- [ ] **Step 4: Commit**

~~~bash
git add src/dialogs/mobile_pair_dialog.py
git commit -m "feat(mobile): Koppel-Dialog mit QR-Code und Warnung bei ersetztem Gerät (#221)

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
~~~

---

### Task 4: Reiter „Mobil"

**Files:**
- Create: `src/dialogs/settings_dialog/tab_mobile.py`
- Modify: `src/dialogs/settings_dialog/dialog.py`
- Create: `tests/test_mobile_tab_wiring.py`

**Interfaces:** Consumes: `MobileService`, `tab_rules` (Task 2), `open_pair_dialog` (Task 3), `netinfo.lan_candidates`. Produces: `MobileTab(frame, dialog, settings, mobile_service, runner)` mit `title = "Mobil"`, `fields`, `values()`, `load()`, `validate()`, `save() -> SaveOutcome`; `open_settings_dialog(..., mobile_service=None)` — der Reiter erscheint nur mit Dienst, Schlüssel `mobile` (zwischen `api` und `app`).

- [ ] **Step 1: Write the failing wiring test**

Create `tests/test_mobile_tab_wiring.py`:

```python
# tests/test_mobile_tab_wiring.py
"""Der Reiter „Mobil" muss im Einstellungsdialog stehen, wenn der Dienst übergeben wird.
Tk-Code läuft hier nicht (entschiedene Scope-Grenze), deshalb prüft der Test die
Verdrahtung am Quelltext."""
import ast
import pathlib

SRC = pathlib.Path(__file__).resolve().parent.parent / "src"
DIALOG = SRC / "dialogs" / "settings_dialog" / "dialog.py"
TAB = SRC / "dialogs" / "settings_dialog" / "tab_mobile.py"
TREE = ast.parse(DIALOG.read_text(encoding="utf-8"))


def _open_settings_dialog():
    for node in ast.walk(TREE):
        if isinstance(node, ast.FunctionDef) and node.name == "open_settings_dialog":
            return node
    raise AssertionError("open_settings_dialog fehlt")


def test_the_dialog_takes_an_optional_mobile_service():
    args = _open_settings_dialog().args
    names = [a.arg for a in args.args + args.kwonlyargs]
    assert "mobile_service" in names


def test_the_mobile_tab_sits_between_api_and_app_and_only_exists_with_a_service():
    source = DIALOG.read_text(encoding="utf-8")
    assert "from src.dialogs.settings_dialog.tab_mobile import MobileTab" in source
    api, mobile, app = (source.index('tabs["api"] = api'),
                        source.index('tabs["mobile"] = mobile'),
                        source.index('tabs["app"] = app'))
    assert api < mobile < app
    assert "if mobile_service is not None" in source


def test_the_tab_title_and_interface():
    tab = ast.parse(TAB.read_text(encoding="utf-8"))
    cls = next(n for n in tab.body if isinstance(n, ast.ClassDef) and n.name == "MobileTab")
    methods = {n.name for n in cls.body if isinstance(n, ast.FunctionDef)}
    assert {"values", "load", "validate", "save"} <= methods
    assert 'self.title = "Mobil"' in TAB.read_text(encoding="utf-8")


def test_the_first_enable_asks_before_anything_is_switched_on():
    source = TAB.read_text(encoding="utf-8")
    assert "FIRST_ENABLE_NOTICE" in source and "mobile_notice_accepted" in source
    # Die Zustimmung wird erst nach der Antwort gespeichert, nicht beim Anzeigen.
    assert source.index("themed_askyesno") < source.index('"mobile_notice_accepted", True')


def test_the_tab_never_calls_the_service_writes_in_the_ui_thread():
    """`revoke`/`revoke_all` schreiben eine Datei: sie dürfen nur als Referenz oder in
    einem Lambda an `runner.run` hängen, nie direkt im UI-Thread gerufen werden."""
    tree = ast.parse(TAB.read_text(encoding="utf-8"))
    inside_lambda = {id(n) for lam in ast.walk(tree) if isinstance(lam, ast.Lambda)
                     for n in ast.walk(lam)}
    direct = [n for n in ast.walk(tree)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
              and n.func.attr in ("revoke", "revoke_all") and id(n) not in inside_lambda]
    assert direct == [], "revoke/revoke_all gehören in den Worker (runner.run)"
    assert "self._service.revoke" in TAB.read_text(encoding="utf-8")
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 -m pytest tests/test_mobile_tab_wiring.py -q -p no:cacheprovider -x`
Expected: FAIL: `assert 'mobile_service' in names`.

- [ ] **Step 3: Implement the tab**

Create `src/dialogs/settings_dialog/tab_mobile.py`:

```python
"""Tab „Mobil" (#221): Handy-Erfassung per PWA ein-/ausschalten, Port, Adresse, Status,
gekoppelte Geräte und Koppeln.

Schalter, Port und Adresse sind Formularfelder (Speichern je Tab, `SaveCoordinator`);
„Gerät koppeln …", „Widerrufen" und „Alle widerrufen …" sind Aktionen, die sofort wirken.
Schreiben (Widerruf) läuft über den `BackgroundTaskRunner`; die Geräteliste zu lesen ist
günstig (der Store hält sie im Speicher) und geschieht im Poll. Den Status liefert ein
`after`-Poll aus `MobileService.status` — wie im API-Tab ein Poll, der mit dem Tab
stirbt, statt eines Callbacks, der nach dem Schließen zurückkommen könnte.

Das erste Einschalten fragt nach (unverschlüsselte Verbindung, vertrauenswürdiges Netz,
App muss laufen); erst die Zustimmung wird gemerkt (`mobile_notice_accepted`).
"""

import tkinter as tk

from src import netinfo
from src.dialogs.mobile_pair_dialog import open_pair_dialog
from src.dialogs.settings_dialog.fields import FieldSet
from src.dialogs.settings_dialog.form_model import SaveOutcome
from src.dialogs.settings_dialog.tab_rules import (
    FIRST_ENABLE_NOTICE, address_options, address_to_choice, device_row_text,
    mobile_status_view, mobile_updates, validate_mobile,
)
from src.theme import (
    ACCENT, BG, ENTRY_BG, FONT, STATUS_OK, STATUS_WARN, TEXT, TEXT_MUTED, Form, dark_combo,
    dark_entry, empty_state, px, set_secondary_button_enabled, themed_askyesno,
)
from src.time_utils import utc_now_iso

_POLL_MS = 500
_WRAP_PX = 380       # wie im API-Tab: die Reiterbreite ist beim Öffnen festgenagelt
_STATUS_COLORS = {"ok": STATUS_OK, "muted": TEXT_MUTED, "error": STATUS_WARN}


class MobileTab:
    """Baut den Mobil-Tab; Tab-Schnittstelle für den `SaveCoordinator`."""

    def __init__(self, frame, dialog, settings, mobile_service, runner):
        self.frame = frame
        self.title = "Mobil"
        self._dialog = dialog
        self._settings = settings
        self._service = mobile_service
        self._runner = runner
        self._alive = True
        self._busy = False                  # Widerruf läuft
        self._poll_id = None
        self._rows = []                     # Datensätze, parallel zur Listbox
        self._row_texts = []

        form = Form(frame, scroll=True)
        form.frame.pack(fill="both", expand=True)
        body = form.body

        enabled_var = tk.BooleanVar(value=bool(settings.get("mobile_enabled")))
        port_var = tk.StringVar(value=str(settings.get("mobile_port")))
        address_var = tk.StringVar(
            value=address_to_choice(str(settings.get("mobile_address") or "")))
        self._enabled_var = enabled_var
        self._last_enabled = enabled_var.get()

        form.section("Handy-Erfassung")
        form.hint("Zeiten unterwegs auf dem Handy nachtragen — auch ohne Verbindung — und im "
                  "selben WLAN mit dieser App abgleichen. Die Verbindung ist unverschlüsselt "
                  "(nur in vertrauenswürdigen Netzen nutzen), die App muss laufen. Unter "
                  "Windows fragt die Firewall beim ersten Einschalten nach.")
        form.check("Handy-Erfassung aktivieren", enabled_var)
        with form.depends_on(enabled_var):
            form.row("Port:", dark_entry(body, port_var, width=7))
            self._combo = dark_combo(body, address_var, address_options([]), width=20)
            form.row("Adresse:", self._combo)
        self._status_label = tk.Label(
            body, text="", font=FONT, bg=BG, fg=TEXT_MUTED, anchor="w",
            justify="left", wraplength=px(_WRAP_PX))
        form.row("Status:", self._status_label)

        form.section("Gekoppelte Geräte")
        box = tk.Frame(body, bg=BG)
        box.columnconfigure(0, weight=1)
        self._listbox = tk.Listbox(
            box, height=4, width=30, font=FONT, bg=ENTRY_BG, fg=TEXT, selectbackground=ACCENT,
            selectforeground="#ffffff", relief="flat", highlightthickness=0,
            activestyle="none", exportselection=False)
        self._listbox.grid(row=0, column=0, sticky="nsew")
        self._empty = empty_state(box, "Noch kein Handy gekoppelt.", bg=ENTRY_BG)
        self._empty.grid(row=0, column=0, sticky="nsew")
        form.block(box)
        self._pair_btn, self._revoke_btn, self._revoke_all_btn = form.buttons(
            ("Gerät koppeln …", self._pair),
            ("Widerrufen", self._revoke),
            ("Alle widerrufen …", self._revoke_all))
        self._listbox.bind("<<ListboxSelect>>", lambda _e: self._sync_buttons())

        port_var.trace_add("write", lambda *_args: self._sync_buttons())
        enabled_var.trace_add("write", self._on_enabled_changed)

        fields = FieldSet()
        fields.add("mobile_enabled", enabled_var)
        fields.add("mobile_port", port_var)
        fields.add("mobile_address", address_var)
        self.fields = fields

        self._runner.run(netinfo.lan_candidates, self._candidates_loaded)
        self._sync_buttons()
        frame.bind("<Destroy>", self._on_destroy, add="+")
        self._poll()

    # --- Tab-Schnittstelle --------------------------------------------------

    def values(self):
        return self.fields.values()

    def load(self, values):
        self.fields.load(values)

    def validate(self):
        return validate_mobile(self.values())

    def save(self):
        self._settings.apply_updates(mobile_updates(self.values()))
        return SaveOutcome(saved=True)

    # --- Schalter und Adressen ------------------------------------------------------

    def _on_enabled_changed(self, *_args):
        enabled = bool(self._enabled_var.get())
        if enabled and not self._last_enabled and not self._settings.get("mobile_notice_accepted"):
            if not themed_askyesno(self._dialog, "Handy-Erfassung einschalten",
                                   FIRST_ENABLE_NOTICE, lock_ms=600):
                self._enabled_var.set(False)            # zurück, nichts eingeschaltet
                return
            self._settings.set("mobile_notice_accepted", True)
        self._last_enabled = bool(self._enabled_var.get())
        self._sync_buttons()

    def _candidates_loaded(self, candidates):
        if not self._alive:
            return
        try:
            # Nur die Auswahl, nie der Wert: eine später eintreffende Liste macht den
            # Reiter nicht „geändert".
            self._combo.configure(values=address_options(candidates or []))
        except tk.TclError:
            self._alive = False

    # --- Anzeige --------------------------------------------------------------------

    def _on_destroy(self, event):
        if event.widget is not self.frame:
            return
        self._alive = False
        if self._poll_id is not None:
            try:
                self.frame.after_cancel(self._poll_id)
            except tk.TclError:
                pass                    # Fenster schon weg: nichts mehr zu stornieren

    def _poll(self):
        if not self._alive:
            return
        try:
            text, kind = mobile_status_view(self._service.status)
            self._status_label.config(text=text, fg=_STATUS_COLORS[kind])
            self._refresh_devices()
            self._poll_id = self.frame.after(_POLL_MS, self._poll)
        except tk.TclError:
            self._alive = False             # Fenster zwischenzeitlich zu

    def _refresh_devices(self):
        records = self._service.list_devices()
        now = utc_now_iso()
        texts = [device_row_text(record, now) for record in records]
        if texts == self._row_texts:
            return                          # nichts geändert: die Auswahl bleibt
        selected = self._selected_id()
        self._rows, self._row_texts = records, texts
        self._listbox.delete(0, tk.END)
        for text in texts:
            self._listbox.insert(tk.END, text)
        for index, record in enumerate(records):
            if record["id"] == selected:
                self._listbox.selection_set(index)
        if texts:
            self._empty.grid_remove()
        else:
            self._empty.grid()
        self._sync_buttons()

    def _selected_id(self):
        selection = self._listbox.curselection()
        if not selection or selection[0] >= len(self._rows):
            return None
        return self._rows[selection[0]]["id"]

    def _sync_buttons(self):
        running = self._service.status.state == "running"
        has_devices = bool(self._rows)
        has_selection = self._selected_id() is not None
        set_secondary_button_enabled(self._pair_btn, running and not self._busy)
        set_secondary_button_enabled(self._revoke_btn, has_selection and not self._busy)
        set_secondary_button_enabled(self._revoke_all_btn, has_devices and not self._busy)

    # --- Aktionen ---------------------------------------------------------------------

    def _pair(self):
        if self._service.status.state != "running" or self._busy:
            return
        open_pair_dialog(self._dialog, self._service)
        if self._alive:
            self._refresh_devices()

    def _revoke(self):
        device_id = self._selected_id()
        if device_id is None or self._busy:
            return
        name = next((r["name"] for r in self._rows if r["id"] == device_id), device_id)
        if not themed_askyesno(
                self._dialog, "Gerät widerrufen",
                f"„{name}“ wird ausgesperrt und muss neu gekoppelt werden.\n\nFortfahren?",
                lock_ms=600):
            return
        self._busy = True
        self._sync_buttons()
        self._runner.run(lambda: self._service.revoke(device_id), self._revoked)

    def _revoke_all(self):
        if not self._rows or self._busy:
            return
        if not themed_askyesno(
                self._dialog, "Alle Geräte widerrufen",
                "Alle gekoppelten Handys werden ausgesperrt und müssen neu gekoppelt "
                "werden.\n\nFortfahren?", lock_ms=600):
            return
        self._busy = True
        self._sync_buttons()
        self._runner.run(self._service.revoke_all, self._revoked)

    def _revoked(self, _result):
        self._busy = False
        if not self._alive:
            return
        try:
            self._refresh_devices()
            self._sync_buttons()
        except tk.TclError:
            self._alive = False
```

(Scheitert `revoke` an der Platte, wirft es; der Runner loggt den Fehler und ruft `on_done` nicht. Ein Fehlerdialog dafür ist ein Folge-Issue und kein Teil dieses PR; `_busy` bliebe dann gesetzt, bis der Dialog neu geöffnet wird — bewusst akzeptiert, der Zustand heilt beim Schließen des Dialogs.)

In `src/dialogs/settings_dialog/dialog.py`:

1. Importe: nach `from src.dialogs.settings_dialog.tab_google import GoogleTab` einfügen `from src.dialogs.settings_dialog.tab_mobile import MobileTab`.
2. Signatur: `on_request_removal=None, api_service=None):` → `on_request_removal=None, api_service=None,\n                         mobile_service=None):`.
3. Docstring: in der Aufzählung „sieben Tabs (Arbeitszeit / Erinnerungen / Versand / Google / API / App / Updates)" `Mobil` ergänzen (`/ API / Mobil / App`), im Absatz zu `initial_tab` den Schlüssel `mobile`, und nach dem `api_service`-Absatz: `mobile_service: der mobile_service.MobileService der App (#221); ohne ihn gibt es keinen Tab „Mobil".`
4. Rahmen: nach

```python
    if api_service is not None:
        frame_keys.append("api")
```

einfügen

```python
    if mobile_service is not None:
        frame_keys.append("mobile")
```

5. Bau: nach dem `ApiTab`-Block

```python
    mobile = None
    if mobile_service is not None:
        mobile = MobileTab(frames["mobile"], dialog, settings, mobile_service, runner)
```

6. Reiterliste: nach

```python
    if api is not None:
        tabs["api"] = api
```

einfügen

```python
    if mobile is not None:
        tabs["mobile"] = mobile
```

- [ ] **Step 4: Run to verify**

Run: `python3 -m pytest tests/test_mobile_tab_wiring.py tests/test_pixel_scaling.py tests/test_catch_all_handlers.py tests/test_type_annotations.py -q -p no:cacheprovider` und danach `python3 -m pytest -q -p no:cacheprovider && ruff check .`
Expected: PASS, `All checks passed!`.

- [ ] **Step 5: Manual check**

Erweitere das Skript aus Task 3 Step 3 und öffne den Einstellungsdialog mit `mobile_service=svc` (Aufruf `open_settings_dialog(root, settings, d, lambda: None, runner=<Runner mit run(fn, done)>, auto_updater=None, mobile_service=svc, initial_tab="mobile")`; ein Runner-Stand-in mit `run(fn, done=None)` genügt). Prüfe: Reiter „Mobil" zwischen „API" und „App"; Häkchen aus → Port/Adresse grau; Einschalten fragt einmalig nach (Abbrechen setzt das Häkchen zurück); Statuszeile folgt dem Dienst; „Gerät koppeln …" ist grau, solange der Dienst nicht läuft; Geräteliste aktualisiert sich nach einem Koppeln (per `curl` gegen `/v1/pair` mit dem Code aus dem Dialog), „Widerrufen" markiert die Zeile als widerrufen.

- [ ] **Step 6: Commit**

~~~bash
git add src/dialogs/settings_dialog/tab_mobile.py src/dialogs/settings_dialog/dialog.py tests/test_mobile_tab_wiring.py
git commit -m "feat(mobile): Reiter Mobil im Einstellungsdialog (#221)

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
~~~

---

### Task 5: Verdrahtung in `main.py` und `ui.py`

**Files:**
- Modify: `src/main.py`, `src/ui.py`
- Create: `tests/test_mobile_wiring.py`

**Interfaces:** Consumes: `MobileStore`, `MobileContext`, `MobileService`, `PairingSession`, `devices.default_device_name`. Produces: `App(..., mobile_store=None)`; `self._mobile` (None ohne Store); `App._apply_mobile_setting()`; `shutdown()` in `_quit_with_sync_push`, `remove_application`, `restart_for_scaling` (+ `reopen`/`apply` bei Fehlschlag); `_apply_mobile_setting` nach dem Start und nach jedem Speichern der Einstellungen; `open_settings_dialog(..., mobile_service=self._mobile)`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_mobile_wiring.py` (Muster `tests/test_api_wiring.py`):

```python
# tests/test_mobile_wiring.py
"""Die Handy-Instanz muss an allen Stellen stehen, an denen die App Ressourcen freigibt
oder neu startet — sonst bleibt ein Port im LAN offen. Tk-Code läuft hier nicht
(entschiedene Scope-Grenze), deshalb prüft der Test die Verdrahtung am Quelltext."""
import ast
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent / "src"
UI = ROOT / "ui.py"
MAIN = ROOT / "main.py"
TREE = ast.parse(UI.read_text(encoding="utf-8"))


def _function(name):
    for node in ast.walk(TREE):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{name} fehlt in src/ui.py")


def _self_calls(func, owner, method):
    found = []
    for node in ast.walk(func):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        target = node.func
        if (target.attr == method and isinstance(target.value, ast.Attribute)
                and target.value.attr == owner
                and isinstance(target.value.value, ast.Name)
                and target.value.value.id == "self"):
            found.append(node)
    return found


def _self_method_calls(func, method):
    return [n for n in ast.walk(func)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
            and n.func.attr == method and isinstance(n.func.value, ast.Name)
            and n.func.value.id == "self"]


def test_the_app_takes_a_mobile_store_and_builds_the_service_in_init():
    init = _function("__init__")
    assert "mobile_store" in [a.arg for a in init.args.args + init.args.kwonlyargs]
    assigned = [t for node in ast.walk(init) if isinstance(node, ast.Assign)
                for t in node.targets if isinstance(t, ast.Attribute) and t.attr == "_mobile"]
    assert assigned, "App.__init__ muss self._mobile anlegen"


def test_the_setting_is_applied_at_start_and_after_every_settings_save():
    assert _self_method_calls(_function("__init__"), "_apply_mobile_setting")
    assert _self_method_calls(_function("_open_settings"), "_apply_mobile_setting")


def test_apply_mobile_setting_delegates_to_the_service():
    assert _self_calls(_function("_apply_mobile_setting"), "_mobile", "apply")


def test_every_exit_path_shuts_the_phone_server_down():
    for name in ("_quit_with_sync_push", "remove_application", "restart_for_scaling"):
        assert _self_calls(_function(name), "_mobile", "shutdown"), (
            f"{name} muss self._mobile.shutdown() rufen")


def test_the_quit_stops_the_phone_server_before_the_final_push():
    quit_ = _function("_quit_with_sync_push")
    shutdown = _self_calls(quit_, "_mobile", "shutdown")[0]
    push = _self_calls(quit_, "_sync", "push_on_quit")[0]
    assert shutdown.lineno < push.lineno


def test_the_restart_frees_the_port_before_spawning_and_recovers_on_failure():
    restart = _function("restart_for_scaling")
    shutdown = _self_calls(restart, "_mobile", "shutdown")[0]
    spawn = [n for n in ast.walk(restart)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
             and n.func.attr == "Popen"][0]
    assert shutdown.lineno < spawn.lineno
    assert _self_calls(restart, "_mobile", "reopen")
    assert _self_calls(restart, "_mobile", "apply")


def test_removal_stops_the_phone_server_before_any_background_job_is_queued():
    removal = _function("remove_application")
    shutdown = _self_calls(removal, "_mobile", "shutdown")[0]
    queued = _self_calls(removal, "_bg", "run")[0]
    assert shutdown.lineno < queued.lineno


def test_the_settings_dialog_gets_the_service():
    source = ast.get_source_segment(UI.read_text(encoding="utf-8"), _function("_open_settings"))
    assert "mobile_service=self._mobile" in source


def test_main_builds_the_store_in_the_data_folder_and_passes_it_on():
    source = MAIN.read_text(encoding="utf-8")
    assert 'MobileStore(os.path.join(base, "mobile_devices.json"))' in source
    assert "mobile_store=mobile_store" in source
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 -m pytest tests/test_mobile_wiring.py -q -p no:cacheprovider`
Expected: FAIL: `AssertionError` (`mobile_store` nicht in der Signatur).

- [ ] **Step 3: Implement**

In `src/main.py`:

1. Import (neben `from src.smtp_store import SmtpStore`): `from src.mobile_store import MobileStore`.
2. Nach dem `smtp_store`-Block:

```python
    # Gekoppelte Handys (#221): gerätelokal, eigener Lock, nur Token-Hashes. Nimmt an
    # keinem Sync-Flow teil; die Handy-Instanz selbst startet nur bei `mobile_enabled`.
    mobile_store = MobileStore(os.path.join(base, "mobile_devices.json"))
```

3. In den `App(...)`-Aufruf `smtp_store=smtp_store)` → `smtp_store=smtp_store, mobile_store=mobile_store)`.

In `src/ui.py`:

1. Importe: `import threading` (falls noch nicht da), `from src.devices import default_device_name` (falls nicht schon importiert; prüfe `grep -n "^from src.devices\|^import threading" src/ui.py`), `from src.mobile_pairing import PairingSession`, `from src.mobile_routes import MobileContext`, `from src.mobile_service import MobileService`.
2. Signatur: `vacation_store=None, smtp_store=None):` → `vacation_store=None, smtp_store=None, mobile_store=None):`.
3. Direkt nach dem `self._api = ApiService(...)`-Block einfügen:

```python
        # Handy-Instanz (#221): gleiche Bauart wie die lokale API, aber im LAN und mit
        # Gerätetoken. Ohne Store (Tests, Alt-Aufrufer) gibt es sie nicht. Teilt sich
        # den Coalescer: ein Schwung Abgleiche löst nur EINEN Refresh aus. Der Dienst
        # startet nur bei `mobile_enabled`.
        self._mobile = None
        if mobile_store is not None:
            self._mobile = MobileService(
                self.settings,
                MobileContext(
                    pairing=PairingSession(), devices=mobile_store,
                    devices_lock=threading.RLock(), storage=self.storage,
                    settings=self.settings, conflicts_store=self.conflicts_store,
                    base=self.base_path,
                    desktop_name=lambda: self.settings.get("device_name") or default_device_name(),
                    data_lock=self._data_lock, sync_guard=self._sync_guard,
                    on_change=self._api_refresh.request),
                run=self._bg.run)
```

4. Neue Methode nach `_apply_api_setting`:

```python
    def _apply_mobile_setting(self):
        """Bringt die Handy-Instanz in den Zustand der Settings (#221). Die Arbeit läuft
        im Worker (Adressauflösung kann blockieren); hier wird nur angestoßen."""
        if self._mobile is not None:
            self._mobile.apply()
```

5. Dort, wo `__init__` `self._apply_api_setting()` aufruft, direkt danach `self._apply_mobile_setting()`; in `_on_change` des `_open_settings` nach `self._apply_api_setting()` ebenso `self._apply_mobile_setting()`; im `open_settings_dialog(...)`-Aufruf nach `api_service=self._api,` die Zeile `mobile_service=self._mobile,`.
6. Beenden-Pfade (je direkt nach der `self._api.shutdown()`-Zeile, **vor** dem jeweils Folgenden):

```python
        if self._mobile is not None:
            self._mobile.shutdown()
```

in `_quit_with_sync_push` (vor `self._sync.push_on_quit()`), in `remove_application` (vor `self._tray.stop()`, also vor jedem Worker) und in `restart_for_scaling` (vor dem `single_instance.release()`/Spawn). Im `except`-Zweig von `restart_for_scaling`, nach `self._api.reopen()`/`self._api.apply()`:

```python
            if self._mobile is not None:
                self._mobile.reopen()
                self._mobile.apply()
```

- [ ] **Step 4: Run to verify they pass**

Run: `python3 -m pytest tests/test_mobile_wiring.py tests/test_api_wiring.py -q -p no:cacheprovider` und danach `python3 -m pytest -q -p no:cacheprovider && ruff check . && npx --yes pyright@1.1.411 src/main.py` (falls `main.py` geprüft wird; sonst nur ruff)
Expected: PASS, `All checks passed!`.

- [ ] **Step 5: Manual end-to-end check**

Starte die App aus dem Repo (`python -m src.main`, auf dieser Linux-Maschine sind Repo-Root-Daten unkritisch), öffne Einstellungen → Mobil, schalte ein (Bestätigung), speichere; Status zeigt „Läuft auf <ip>:17654". Mit dem Koppel-Dialog einen Code erzeugen und per `curl` koppeln und abgleichen:

```bash
CODE=<Code aus dem Dialog>
curl -s -X POST http://<ip>:17654/v1/pair -H "Origin: https://xveyn.github.io" -H "Content-Type: application/json" \
  -d "{\"code\":\"$CODE\",\"device_name\":\"curl\",\"device_id\":\"curl-test-0001\"}"
```

Expected: JSON mit `token`; das Gerät erscheint in der Liste. Danach App beenden und prüfen, dass der Port zu ist (`ss -ltn | grep 17654` leer). Skalierung ändern → Neustart → Server läuft danach wieder.

- [ ] **Step 6: Commit**

~~~bash
git add src/main.py src/ui.py tests/test_mobile_wiring.py
git commit -m "feat(mobile): Handy-Instanz in main.py und ui.py verdrahtet (#221)

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
~~~

---

### Task 6: Doku

**Files:**
- Modify: `CLAUDE.md`, `src/CLAUDE.md`
- Modify: `docs/superpowers/specs/2026-10-08-mobile-pwa-design.md`

- [ ] **Step 1: Edit the docs**

In `CLAUDE.md` ersetze

```markdown
- `src/mobile_service.py` — Lebenszyklus der Handy-Instanz (Muster `ApiService`): bindet nur die gewählte LAN-Adresse, Statusgründe (`address_gone`, `no_address`, `port_in_use` …), Geräteverwaltung und Koppel-Link. Noch nicht in `ui.py` verdrahtet (PR 5)
```

durch

```markdown
- `src/mobile_service.py` — Lebenszyklus der Handy-Instanz (Muster `ApiService`): bindet nur die gewählte LAN-Adresse, Statusgründe (`address_gone`, `no_address`, `port_in_use` …), Geräteverwaltung und Koppel-Link. Von `ui.App` gebaut (nur mit `mobile_store`), an denselben Stellen wie die lokale API gestartet und gestoppt
- `src/qr.py` — QR-Code für den Koppel-Dialog (`segno`, lazy importiert): Matrix, Maße samt Ruhezone, dunkle Module als zusammengefasste Rechtecke für den Canvas. Tk-frei
- `src/dialogs/mobile_pair_dialog.py` — Koppel-Dialog: QR-Code (weiße Fläche mit Ruhezone, unabhängig vom Dark-Theme), Adresse und Code immer auch als Text, Countdown; erkennt das Koppeln am Gerätebestand und warnt, wenn ein vorhandenes, nicht widerrufenes Gerät ersetzt wurde (#258). Schließt beim Verlassen die Kopplungssitzung
- `src/dialogs/settings_dialog/tab_mobile.py` — Reiter „Mobil": Schalter (erstes Einschalten fragt nach), Port, Adresse, Status, Geräteliste, Koppeln/Widerrufen; Regeln Tk-frei in `tab_rules.py`
```

In `src/CLAUDE.md` ersetze (Anker: der Satz am Ende des `mobile_routes`/`mobile_service`-Absatzes)

```markdown
Settings `mobile_enabled`/`mobile_port`/`mobile_address` sind gerätelokal.
```

durch

```markdown
Settings `mobile_enabled`/`mobile_port`/`mobile_address` und `mobile_notice_accepted` (der Hinweis beim ersten Einschalten wurde bestätigt) sind gerätelokal. **Verdrahtung (PR 5):** `main.py` baut den `MobileStore` (`mobile_devices.json`), `App(mobile_store=…)` den `MobileService` (ohne Store `self._mobile = None`, alle Aufrufstellen prüfen darauf); `_apply_mobile_setting` läuft beim Start und nach jedem Speichern der Einstellungen, `shutdown()` in `_quit_with_sync_push` (vor dem finalen Push), `remove_application` (vor jedem Worker) und `restart_for_scaling` (vor dem Spawn, bei Fehlschlag `reopen()` und `apply()`); `tests/test_mobile_wiring.py` hält das am Quelltext fest. Der Reiter „Mobil" (`tab_mobile.py`, nur mit Dienst) schreibt wie `ApiTab` nur die Formularfelder; Koppeln und Widerrufen wirken sofort, Widerruf über den Runner. Der Koppel-Dialog (`mobile_pair_dialog.py`) schließt beim Verlassen die Kopplungssitzung, jeder Statuswechsel des Dienstes tut es ebenso.
```

In `docs/superpowers/specs/2026-10-08-mobile-pwa-design.md` ergänze am Ende des Absatzes „**Umsetzung (PR 4b):**" einen Absatz:

```markdown

**Umsetzung (PR 5):** Der Koppel-Dialog erkennt das Koppeln am Gerätebestand (vorher/nachher) und warnt, wenn dabei ein vorhandenes, nicht widerrufenes Gerät ersetzt wurde (dieselbe `device_id`, neues Token): die Spec erlaubt das erneute Koppeln derselben ID bewusst, der Besitzer soll es aber sehen (#258). Das erste Einschalten fragt nach und merkt die Zustimmung im gerätelokalen Key `mobile_notice_accepted` (ein vierter Key neben den drei der Spec). `segno` wird lazy importiert; die QR-Matrix hat Fehlerkorrektur `M`, kein Micro-QR.
```

- [ ] **Step 2: Run to verify**

Run: `python3 -m pytest tests/test_claude_md_claims.py tests/test_type_annotations.py -q -p no:cacheprovider` und danach `python3 -m pytest -q -p no:cacheprovider && ruff check .`
Expected: PASS, `All checks passed!`.

- [ ] **Step 3: Commit**

~~~bash
git add CLAUDE.md src/CLAUDE.md docs/superpowers/specs/2026-10-08-mobile-pwa-design.md
git commit -m "docs(mobile): Reiter Mobil, Koppel-Dialog und Verdrahtung in CLAUDE.md und Spec (#221)

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
~~~

---

## Mutationsprüfung (nach Task 6, vor dem Review)

Für die Tk-freien Teile wie bisher (`PYTHONDONTWRITEBYTECODE=1`, Datei sichern, genau eine Ersetzung, Tests laufen lassen, zurückkopieren; **nicht parallel zu anderen Arbeiten am Arbeitsbaum**). Jeder muss mindestens einen Test rot färben:

| Datei | Mutation | Erwartet rot |
|---|---|---|
| `qr.py` | `QUIET_MODULES = 3` | `test_the_canvas_size_includes_the_quiet_zone`, `test_dark_rects_cover_exactly_the_dark_modules` |
| `qr.py` | `error="m"` → `error="l"` | `test_the_link_fits_into_a_small_version` (nur falls die Version kippt) — sonst Eintrag streichen |
| `qr.py` | Läufe nicht zusammenfassen (jedes Modul ein Rechteck) | `test_dark_rects_merge_horizontal_runs` |
| `qr.py` | `except segno.DataOverflowError` entfernen | `test_too_long_a_text_raises_qr_too_long` |
| `qr.py` | Zeilenoffset ohne Ruhezone | `test_dark_rects_cover_exactly_the_dark_modules` |
| `tab_rules.py` | `address_from_choice` ohne AUTO-Sonderfall | `test_address_choice_round_trips` |
| `tab_rules.py` | `is_lan_address`-Prüfung in `validate_mobile` entfernen | `test_an_address_that_is_not_a_lan_address_is_refused` |
| `tab_rules.py` | Portprüfung in `validate_mobile` entfernen | `test_an_invalid_port_is_refused_even_when_off` |
| `tab_rules.py` | `<=` → `<` in `device_row_text` (Ablauf) | `test_an_expired_device_is_marked_from_the_second_it_expires` |
| `tab_rules.py` | `revoked` und `abgelaufen` vertauschen | `test_a_revoked_device_is_marked` |
| `tab_rules.py` | `format_countdown` ohne `max(0, …)` | `test_the_countdown` |
| `tab_rules.py` | `pair_changes`: `replaced` auch bei widerrufenem Altgerät | `test_pair_changes_does_not_warn_when_the_replaced_device_was_revoked` |
| `tab_rules.py` | `pair_changes`: Token-Vergleich entfernen | `test_pair_changes_flags_a_replaced_live_device` |
| `tab_rules.py` | `ADDRESS_GONE`-Text ohne `{address}` | `test_the_status_view` |
| `ui.py` | `self._mobile.shutdown()` aus `restart_for_scaling` | `test_every_exit_path_shuts_the_phone_server_down` |
| `ui.py` | `shutdown` hinter `push_on_quit` | `test_the_quit_stops_the_phone_server_before_the_final_push` |
| `ui.py` | `reopen()` entfernen | `test_the_restart_frees_the_port_before_spawning_and_recovers_on_failure` |
| `ui.py` | `mobile_service=self._mobile` entfernen | `test_the_settings_dialog_gets_the_service` |
| `dialog.py` | Reiter `mobile` hinter `app` | `test_the_mobile_tab_sits_between_api_and_app_and_only_exists_with_a_service` |

Überlebt ein Mutant, ist das ein Testfehler: Test schärfen, gegen den Mutanten rot sehen, committen.

## Finale

Nach Task 6: Review über den ganzen Branch mit einem frischen Reviewer auf dem leistungsfähigsten Modell (Review Focus und Rulings mitgeben; der Reviewer prüft die Tk-Dateien **durch Lesen und, wo `DISPLAY` vorhanden ist, durch Ausführen der Skripte aus Task 3 und 4**). Critical/Important in **einem** Fix-Durchlauf (je Fix ein Test, der zuerst rot war, wo der Code Tk-frei ist), Minors ins Ledger und in ein Issue. Danach `finishing-a-development-branch`: PR gegen `master` (`Refs #221`, „PR 5 von 9" im Titel), **mit dem Vorschlag, vor dem Merge einen Pre-Release über alle drei Plattformen zu bauen** (neue Abhängigkeit `segno`, neuer Reiter, Firewall-Verhalten unter Windows; `platform:*`-Labels sind hier nicht passend, weil der Code plattformübergreifend wirkt).

**Danach PR 6:** PWA-Kern (`pwa/`: Module `db.js`, `sync.js`, `pairing.js`, `minutes.js`, Tests mit `node --test`, Vertragsbeispiele in `pwa/test/fixtures/`, CI-Job).
