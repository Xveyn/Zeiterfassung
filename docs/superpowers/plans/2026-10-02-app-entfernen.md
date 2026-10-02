# „Zeiterfassung entfernen" Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Unter macOS und Linux räumt ein Button im App-Tab Schlüsselbund, Zugangsdaten, Autostart, Menüeintrag und auf Wunsch die Nutzerdaten ab und beendet die App.

**Architecture:** Neues Tk-freies Modul `src/removal.py` plant und führt die Schritte aus (jeder Schritt einzeln abgesichert, nie wirft etwas nach außen). Ein dünner Bestätigungsdialog (`src/dialogs/removal_dialog.py`) fragt, `App.remove_application` stellt die App ruhig, lässt `removal.execute_removal` über den `BackgroundTaskRunner` laufen, zeigt das Ergebnis und beendet per `root.destroy()` — ohne Sync-Push und ohne Anwenden eines vorbereiteten Updates.

**Tech Stack:** Python 3.12, Tkinter, pytest. Keine neue Abhängigkeit.

**Spec:** `docs/superpowers/specs/2026-10-02-app-entfernen-design.md`

## Global Constraints

- Nur macOS und Linux, nur im installierten Build (`sys.frozen`); Windows bekommt den Button nicht.
- Die App löscht ihre eigene Programmdatei **nicht**; sie nennt sie (Linux `$APPIMAGE`, macOS die `.app`).
- Nutzerdaten nur mit ausdrücklichem Häkchen, Standard **aus**. Zugangsdaten immer.
- `--forget-secrets`-Logik (`secret_migration.forget_all`) läuft **vor** dem Löschen der Dateien, aus denen die Schlüssel stammen.
- Datenordner nur entfernen, wenn er leer ist; fremde Dateien bleiben.
- Jeder Catch-all loggt oder trägt eine Begründung im Handler (`tests/test_catch_all_handlers.py`, Xveyn#73).
- Neue Dialoge: `theme.create_dialog` + `center_dialog_on_parent` (Paarungs-Regel, `tests/test_dialog_reveal.py`); Pixelangaben über `px()` (`tests/test_pixel_scaling.py`).
- Tk-freie Module vollständig annotiert und in `tests/test_type_annotations.py` eingetragen.
- Windows-Shell des Entwicklers: PowerShell 5.1, kein `&&`; `;` bzw. `if ($?) { }`. Commits: Message per `git commit -F <Datei>` (Heredoc/Here-String-Probleme), Attribution-Zeile `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.
- Push nur mit `git -c credential.helper= -c credential.helper='!gh auth git-credential' push …`.
- **Kein Release, kein Versionsbump, kein CHANGELOG-Eintrag** in diesem PR; README-Zeile für Unveröffentlichtes trägt `*(ab --VERSION--)*`.

## Review Focus

1. **Ergebnis „✓ Schlüsselbund" trotz Timeout:** `secret_migration.forget_all` schluckt Fehler einzelner Einträge (wirft nie). Der Schritt meldet daher ✓, auch wenn ein Eintrag stehen blieb. Erwartet: die Zusammenfassung sagt es ehrlich („Fehler stehen im Protokoll"), und der Hinweis auf die Handarbeit (README) steht immer darin. → Task 1, `test_summary_always_points_to_readme`.
2. **Fremde Datei im Datenordner:** Liegt dort etwas, das die App nicht kennt, bleibt es und der Ordner bleibt. → Task 1, `test_data_dir_kept_with_foreign_file`.
3. **Teilweise gelöschte Umgebung:** Datei fehlt bereits (z. B. kein `smtp.json`, kein Menüeintrag, `logs/` fehlt). Erwartet: kein Fehler. → Task 1, `test_missing_files_are_not_errors`.
4. **Quarantäne-Dateien mit Secrets:** `webhooks.json.corrupt-<stamp>` kann Secrets enthalten und gehört zu den Zugangsdaten, nicht zu den Nutzerdaten (also auch **ohne** Häkchen weg). → Task 1, `test_credential_quarantine_removed_without_data`.
5. **Sync läuft gerade:** Lässt sich der `sync_guard` nicht nehmen, darf **nichts** gestoppt oder gelöscht werden; die App meldet es und bleibt benutzbar. → Task 2, Step 6 (manuelle Prüfung, UI nicht automatisiert testbar) plus Kommentar im Code.

---

## File Structure

| Datei | Verantwortung |
|---|---|
| `src/removal.py` (neu) | Dateilisten, `plan_removal`, `run_removal`, `execute_removal`, `app_file_hint`, `format_summary`, `is_available`. Tk-frei. |
| `tests/test_removal.py` (neu) | Alle Tk-freien Tests des Moduls. |
| `src/dialogs/removal_dialog.py` (neu) | `ask_removal(parent) -> bool \| None` — Bestätigung mit Häkchen. |
| `src/theme/messagebox.py`, `src/theme/__init__.py` | `_run_modal` wird öffentlich als `run_modal` (der neue Dialog braucht ihn). |
| `src/dialogs/settings_dialog/tab_app.py` | Button „Zeiterfassung entfernen…" im Bereich „Daten". |
| `src/dialogs/settings_dialog/dialog.py` | Parameter `on_request_removal`, Schließen ohne Speichern. |
| `src/ui.py` | `App.remove_application(with_data)`. |
| `tests/test_type_annotations.py` | `src/removal.py` in die Whitelist. |
| `README.md`, `docs/known-limitations.md`, `CLAUDE.md`, `src/CLAUDE.md` | Dokumentation. |

---

### Task 1: `src/removal.py` (Tk-freier Kern)

**Files:**
- Create: `src/removal.py`
- Create: `tests/test_removal.py`
- Modify: `tests/test_type_annotations.py` (Whitelist, Zeile ~59)

**Interfaces:**
- Produces:
  - `CREDENTIAL_FILES: tuple[str, ...]`, `USER_DATA_FILES: tuple[str, ...]`, `SETTINGS_FILE: str`, `LOGS_DIR: str`
  - `Step = tuple[str, Callable[[], None]]`
  - `@dataclass(frozen=True) class StepResult: name: str; ok: bool; error: str = ""`
  - `is_available(system: str, frozen: bool) -> bool`
  - `plan_removal(base_path: str, with_data: bool, system: str, pending_update_path: str = "") -> list[Step]`
  - `run_removal(steps: list[Step]) -> list[StepResult]`
  - `execute_removal(base_path: str, with_data: bool, system: str, pending_update_path: str = "") -> list[StepResult]` (wirft nie)
  - `app_file_hint(system: str, environ: Mapping[str, str], executable: str) -> str | None`
  - `format_summary(results: list[StepResult], app_file: str | None, had_token: bool) -> str`

- [ ] **Step 1: Failing tests schreiben**

`tests/test_removal.py`:

```python
"""„Zeiterfassung entfernen" (#50): Plan, Ausführung, Hinweise — Tk-frei."""

import os
import re

import pytest

from src import removal
from src.removal import StepResult


def _touch(path, text="x"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _populate(base, *, credentials=True, data=True):
    if credentials:
        for name in removal.CREDENTIAL_FILES:
            _touch(base / name)
    if data:
        for name in (*removal.USER_DATA_FILES, removal.SETTINGS_FILE):
            _touch(base / name)
        _touch(base / removal.LOGS_DIR / "zeiterfassung.log")


@pytest.fixture
def quiet(monkeypatch):
    """Schlüsselbund und Autostart sind hier nicht das Thema."""
    monkeypatch.setattr(removal.secret_migration, "forget_all", lambda base: None)
    monkeypatch.setattr(removal, "disable_autostart", lambda: None)


def _names(steps):
    return [name for name, _fn in steps]


# --- Verfügbarkeit ----------------------------------------------------------

@pytest.mark.parametrize("system, frozen, expected", [
    ("Linux", True, True), ("Darwin", True, True),
    ("Windows", True, False), ("Linux", False, False), ("Darwin", False, False),
])
def test_is_available(system, frozen, expected):
    assert removal.is_available(system, frozen) is expected


# --- Plan -------------------------------------------------------------------

def test_plan_is_empty_on_windows(tmp_path):
    assert removal.plan_removal(str(tmp_path), True, "Windows") == []


def test_plan_linux_with_data_in_order(tmp_path):
    steps = removal.plan_removal(str(tmp_path), True, "Linux",
                                 pending_update_path="/x/.u")
    assert _names(steps) == [
        "Schlüsselbund-Einträge", "Autostart", "Menüeintrag",
        "Vorbereitetes Update", "Zugangsdaten",
        "Zeiten, Einstellungen und Protokoll", "Datenordner",
    ]


def test_plan_macos_has_no_menu_entry_step(tmp_path):
    steps = removal.plan_removal(str(tmp_path), False, "Darwin")
    assert _names(steps) == ["Schlüsselbund-Einträge", "Autostart", "Zugangsdaten"]


def test_plan_without_data_skips_data_and_folder(tmp_path):
    names = _names(removal.plan_removal(str(tmp_path), False, "Linux"))
    assert "Zeiten, Einstellungen und Protokoll" not in names
    assert "Datenordner" not in names


def test_keyring_runs_before_any_file_is_deleted(tmp_path, monkeypatch):
    """Die Schlüssel stehen in token.json/webhooks.json/smtp.json — erst
    abräumen, dann löschen."""
    _populate(tmp_path)
    seen = {}
    monkeypatch.setattr(removal.secret_migration, "forget_all",
                        lambda base: seen.update(token=(tmp_path / "token.json").exists()))
    monkeypatch.setattr(removal, "disable_autostart", lambda: None)

    removal.execute_removal(str(tmp_path), True, "Linux")

    assert seen == {"token": True}


# --- Ausführung -------------------------------------------------------------

def test_run_removal_isolates_failures():
    calls = []

    def boom():
        raise OSError("gesperrt")

    steps = [("a", lambda: calls.append("a")), ("b", boom),
             ("c", lambda: calls.append("c"))]

    results = removal.run_removal(steps)

    assert calls == ["a", "c"]
    assert [(r.name, r.ok) for r in results] == [("a", True), ("b", False), ("c", True)]
    assert "gesperrt" in results[1].error


def test_execute_removal_never_raises(tmp_path, monkeypatch):
    def broken(*_a, **_k):
        raise RuntimeError("Plan kaputt")

    monkeypatch.setattr(removal, "plan_removal", broken)

    results = removal.execute_removal(str(tmp_path), True, "Linux")

    assert len(results) == 1 and results[0].ok is False
    assert "Plan kaputt" in results[0].error


# --- Dateischritte ----------------------------------------------------------

def test_credentials_removed_user_data_kept_without_data(tmp_path, quiet):
    _populate(tmp_path)

    results = removal.execute_removal(str(tmp_path), False, "Linux")

    assert all(r.ok for r in results)
    for name in removal.CREDENTIAL_FILES:
        assert not (tmp_path / name).exists()
    for name in (*removal.USER_DATA_FILES, removal.SETTINGS_FILE):
        assert (tmp_path / name).exists()
    assert (tmp_path / removal.LOGS_DIR).is_dir()


def test_credential_quarantine_removed_without_data(tmp_path, quiet):
    """Eine Quarantäne-Kopie von webhooks.json trägt dieselben Secrets."""
    _touch(tmp_path / "webhooks.json.corrupt-20260101")
    _touch(tmp_path / ".token-abc.tmp")
    _touch(tmp_path / "zeiterfassung.json.corrupt-20260101")

    removal.execute_removal(str(tmp_path), False, "Linux")

    assert not (tmp_path / "webhooks.json.corrupt-20260101").exists()
    assert not (tmp_path / ".token-abc.tmp").exists()
    # Nutzerdaten-Quarantäne gehört zum Häkchen, nicht zu den Zugangsdaten.
    assert (tmp_path / "zeiterfassung.json.corrupt-20260101").exists()


def test_user_data_removed_with_data_and_empty_dir_goes(tmp_path, quiet):
    base = tmp_path / "Zeiterfassung"
    _populate(base)
    _touch(base / "zeiterfassung.json.corrupt-20260101")

    results = removal.execute_removal(str(base), True, "Linux")

    assert all(r.ok for r in results), results
    assert not base.exists()


def test_data_dir_kept_with_foreign_file(tmp_path, quiet):
    _populate(tmp_path)
    _touch(tmp_path / "meine-notizen.txt")

    results = removal.execute_removal(str(tmp_path), True, "Linux")

    assert all(r.ok for r in results), results
    assert (tmp_path / "meine-notizen.txt").exists()
    assert not (tmp_path / "settings.json").exists()


def test_missing_files_are_not_errors(tmp_path, quiet):
    results = removal.execute_removal(str(tmp_path), True, "Linux")

    assert all(r.ok for r in results), results


def test_linux_menu_entry_and_icon_removed(tmp_path, monkeypatch, quiet):
    xdg = tmp_path / "xdg"
    monkeypatch.setenv("XDG_DATA_HOME", str(xdg))
    entry = xdg / "applications" / "Zeiterfassung.desktop"
    base = xdg / "Zeiterfassung"
    _touch(entry)
    _touch(base / "icon.png")

    results = removal.execute_removal(str(base), False, "Linux")

    assert all(r.ok for r in results), results
    assert not entry.exists()
    assert not (base / "icon.png").exists()


def test_pending_update_file_discarded(tmp_path, quiet):
    pending = tmp_path / ".Zeiterfassung.update-1-ab"
    _touch(pending)

    removal.execute_removal(str(tmp_path), False, "Linux",
                            pending_update_path=str(pending))

    assert not pending.exists()


# --- Hinweise ---------------------------------------------------------------

def test_app_file_hint_linux():
    env = {"APPIMAGE": "/home/u/Apps/Zeiterfassung-1.0-x86_64.AppImage"}
    assert (removal.app_file_hint("Linux", env, "/tmp/.mount_x/Zeiterfassung")
            == "/home/u/Apps/Zeiterfassung-1.0-x86_64.AppImage")


def test_app_file_hint_linux_without_appimage():
    assert removal.app_file_hint("Linux", {}, "/opt/z/Zeiterfassung") is None


def test_app_file_hint_macos_walks_up_to_bundle():
    exe = "/Applications/Zeiterfassung.app/Contents/MacOS/Zeiterfassung"
    assert removal.app_file_hint("Darwin", {}, exe) == "/Applications/Zeiterfassung.app"


def test_app_file_hint_macos_without_bundle():
    assert removal.app_file_hint("Darwin", {}, "/usr/local/bin/zeit") is None


def test_summary_lists_steps_and_app_file():
    text = removal.format_summary(
        [StepResult("Autostart", True), StepResult("Zugangsdaten", False, "OSError: x")],
        "/home/u/Z.AppImage", had_token=False)
    assert "✓ Autostart" in text
    assert "✗ Zugangsdaten — OSError: x" in text
    assert "/home/u/Z.AppImage" in text
    assert "myaccount.google.com" not in text


def test_summary_mentions_google_only_with_token():
    text = removal.format_summary([], None, had_token=True)
    assert "https://myaccount.google.com/permissions" in text


def test_summary_always_points_to_readme():
    """Review Focus 1: der Schlüsselbund-Schritt meldet ✓ auch bei einem
    geschluckten Fehler — der Hinweis auf die Handarbeit muss immer da sein."""
    text = removal.format_summary([StepResult("Schlüsselbund-Einträge", True)],
                                  None, had_token=False)
    assert "Vollständig entfernen" in text


# --- Listen gegen den Windows-Uninstaller ----------------------------------

def _installer():
    path = os.path.join(os.path.dirname(__file__), "..", "installer.iss")
    with open(path, encoding="utf-8") as f:
        return f.read()


def test_credential_files_match_installer():
    names = set(re.findall(r'Type: files; Name: "\{app\}\\([^"]+)"', _installer()))
    assert names == set(removal.CREDENTIAL_FILES)


def test_user_data_files_match_installer():
    names = set(re.findall(r"DeleteFile\(ExpandConstant\('\{app\}\\([^']+)'\)\)",
                           _installer()))
    assert names == {*removal.USER_DATA_FILES, removal.SETTINGS_FILE}
```

- [ ] **Step 2: Test laufen lassen, Fehlschlag prüfen**

Run: `python -m pytest tests/test_removal.py -q`
Expected: FAIL/ERROR — `ImportError: cannot import name 'removal' from 'src'`.

- [ ] **Step 3: `src/removal.py` schreiben**

```python
# src/removal.py
"""„Zeiterfassung entfernen" (macOS/Linux, #50): Plan und Ausführung.

Tk-frei. Der Windows-Uninstaller (`installer.iss`) ist die Vorlage:
Zugangsdaten gehen immer, Nutzerdaten nur auf ausdrückliche Nachfrage. Die
Dateilisten hier spiegeln seine — `tests/test_removal.py` hält beide
zusammen.

**Reihenfolge ist der Punkt:** der Schlüsselbund zuerst, denn die Schlüssel
stehen in `token.json`/`webhooks.json`/`smtp.json` (`secret_migration.
forget_all` liest sie von dort). Danach Autostart/Menüeintrag, dann die
Dateien; `settings.json` als letzte Datei.

Jeder Schritt läuft für sich: ein Fehler (gesperrte Datei, hängender
Schlüsselbund) hält die übrigen nicht auf und steht im Ergebnis. Nach außen
wirft nichts — der Aufrufer wartet auf `on_done`, und ein Worker, der
stirbt, ließe die App ruhiggestellt und unsichtbar zurück.

Die App löscht ihre eigene Programmdatei **nicht**; `app_file_hint` nennt
sie nur.
"""
from __future__ import annotations

import glob
import logging
import os
import shutil
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass

from src import desktop_entry, oauth_utils, secret_migration, self_update
from src.autostart import disable_autostart

log = logging.getLogger(__name__)

# Spiegel von `installer.iss` ([UninstallDelete] bzw. DeleteUserData).
CREDENTIAL_FILES: tuple[str, ...] = (
    "token.json", "instance-secret", "webhooks.json", "smtp.json",
    "credentials.json",
)
USER_DATA_FILES: tuple[str, ...] = (
    "zeiterfassung.json", "reservations.json", "vacations.json",
    "conflicts.json", "sync_history.json", "sync-apply.journal",
)
SETTINGS_FILE = "settings.json"
LOGS_DIR = "logs"

README_HINT = (
    "Bleibt etwas stehen, steht in der README unter „Vollständig entfernen“, "
    "wie du es von Hand abräumst.")
GOOGLE_PERMISSIONS_URL = "https://myaccount.google.com/permissions"

Step = tuple[str, Callable[[], None]]


@dataclass(frozen=True)
class StepResult:
    name: str
    ok: bool
    error: str = ""


def is_available(system: str, frozen: bool) -> bool:
    """Nur macOS/Linux und nur im installierten Build — aus dem Repo heraus
    würde der Button Dev-Daten löschen, unter Windows ist der Uninstaller
    zuständig."""
    return frozen and system in ("Darwin", "Linux")


def _remove_all(paths: Iterable[str]) -> None:
    """Löscht jede Datei einzeln; ein Fehler stoppt die übrigen nicht und
    wird am Ende gesammelt geworfen. Fehlende Dateien sind kein Fehler."""
    failures: list[str] = []
    for path in paths:
        try:
            os.remove(path)
        except FileNotFoundError:
            pass
        except OSError as e:
            failures.append(f"{os.path.basename(path)}: {e}")
    if failures:
        raise OSError("; ".join(failures))


def _glob(base_path: str, pattern: str) -> list[str]:
    return glob.glob(os.path.join(glob.escape(base_path), pattern))


def _credential_paths(base_path: str) -> list[str]:
    paths = [os.path.join(base_path, name) for name in CREDENTIAL_FILES]
    # Quarantäne-Kopie (`json_store`, N4) und liegengebliebene Temp-Datei
    # (`oauth_utils.write_token_json`) tragen dieselben Secrets.
    for name in CREDENTIAL_FILES:
        paths.extend(_glob(base_path, f"{glob.escape(name)}.corrupt-*"))
    paths.extend(_glob(base_path, ".token-*.tmp"))
    return paths


def _delete_credentials(base_path: str) -> None:
    # Unter TOKEN_LOCK: ein gleichzeitiger Token-Refresh darf die Datei nicht
    # zwischen Löschen und Beenden neu schreiben.
    with oauth_utils.TOKEN_LOCK:
        _remove_all(_credential_paths(base_path))


def _delete_user_data(base_path: str) -> None:
    failures: list[str] = []
    try:
        _remove_all(os.path.join(base_path, name) for name in USER_DATA_FILES)
        _remove_all(_glob(base_path, "*.corrupt-*"))
    except OSError as e:
        failures.append(str(e))
    logs = os.path.join(base_path, LOGS_DIR)
    if os.path.isdir(logs):
        try:
            shutil.rmtree(logs)
        except OSError as e:
            failures.append(f"{LOGS_DIR}: {e}")
    try:
        # Als letzte Datei: andere Schritte lesen sie nicht mehr.
        _remove_all([os.path.join(base_path, SETTINGS_FILE)])
    except OSError as e:
        failures.append(str(e))
    if failures:
        raise OSError("; ".join(failures))


def _remove_dir_if_empty(base_path: str) -> None:
    try:
        os.rmdir(base_path)
    except FileNotFoundError:
        pass
    except OSError:
        # Nicht leer: fremde Dateien bleiben, und mit ihnen der Ordner. Das
        # ist gewollt, kein Fehler. Jeder andere Grund (Rechte) wird gemeldet.
        if os.path.isdir(base_path) and os.listdir(base_path):
            return
        raise


def _remove_menu_entry(base_path: str) -> None:
    _remove_all([desktop_entry.menu_entry_path(),
                 os.path.join(base_path, desktop_entry.ICON_FILENAME)])


def plan_removal(base_path: str, with_data: bool, system: str,
                 pending_update_path: str = "") -> list[Step]:
    """Die Schritte in der Reihenfolge, in der sie laufen müssen. Leer, wo
    es nichts zu tun gibt (Windows)."""
    if system not in ("Darwin", "Linux"):
        return []
    steps: list[Step] = [
        ("Schlüsselbund-Einträge",
         lambda: secret_migration.forget_all(base_path)),
        ("Autostart", disable_autostart),
    ]
    if system == "Linux":
        steps.append(("Menüeintrag", lambda: _remove_menu_entry(base_path)))
    if pending_update_path:
        steps.append(("Vorbereitetes Update",
                      lambda: self_update.discard_download(pending_update_path)))
    steps.append(("Zugangsdaten", lambda: _delete_credentials(base_path)))
    if with_data:
        steps.append(("Zeiten, Einstellungen und Protokoll",
                      lambda: _delete_user_data(base_path)))
        steps.append(("Datenordner", lambda: _remove_dir_if_empty(base_path)))
    return steps


def run_removal(steps: list[Step]) -> list[StepResult]:
    results: list[StepResult] = []
    for name, fn in steps:
        try:
            fn()
        except Exception as e:
            # Bewusst alles: ein Schritt darf scheitern, die übrigen laufen
            # weiter (Modul-Docstring). Der Fehler steht im Ergebnis und im Log.
            log.warning("Entfernen: Schritt %r fehlgeschlagen", name, exc_info=True)
            results.append(StepResult(name, False, f"{type(e).__name__}: {e}"))
        else:
            results.append(StepResult(name, True))
    return results


def execute_removal(base_path: str, with_data: bool, system: str,
                    pending_update_path: str = "") -> list[StepResult]:
    """Plan + Ausführung in einem Aufruf — **wirft nie**, auch nicht beim
    Planen (Einstieg für `BackgroundTaskRunner.run`, dessen `on_done` bei
    einer Exception nie feuert)."""
    try:
        steps = plan_removal(base_path, with_data, system, pending_update_path)
    except Exception as e:
        log.exception("Entfernen: Planung fehlgeschlagen")
        return [StepResult("Planung", False, f"{type(e).__name__}: {e}")]
    return run_removal(steps)


def app_file_hint(system: str, environ: Mapping[str, str],
                  executable: str) -> str | None:
    """Die Programmdatei, die der Nutzer selbst löschen muss — oder `None`,
    wenn sie sich nicht bestimmen lässt."""
    if system == "Linux":
        return environ.get("APPIMAGE") or None
    if system == "Darwin":
        parts = executable.split("/")
        for i, part in enumerate(parts):
            if part.endswith(".app"):
                return "/".join(parts[:i + 1])
    return None


def format_summary(results: list[StepResult], app_file: str | None,
                   had_token: bool) -> str:
    lines = [f"✓ {r.name}" if r.ok else f"✗ {r.name} — {r.error}" for r in results]
    lines.append("")
    if app_file:
        lines.append("Die Programmdatei bleibt liegen. Lösche sie jetzt selbst:")
        lines.append(app_file)
    else:
        lines.append("Die Programmdatei bleibt liegen — lösche sie selbst.")
    if had_token:
        lines.append("")
        lines.append("Die Freigabe im Google-Konto bleibt bestehen. Zurückziehen "
                     f"lässt sie sich unter:\n{GOOGLE_PERMISSIONS_URL}")
    lines.append("")
    lines.append(README_HINT)
    return "\n".join(lines)
```

- [ ] **Step 4: Tests laufen lassen**

Run: `python -m pytest tests/test_removal.py -q`
Expected: alle PASS. Schlägt `test_user_data_files_match_installer` fehl, weil die Regex nicht greift, die Regex an die echten Zeilen in `installer.iss` (Z. 108–115) anpassen — nicht die Dateiliste.

- [ ] **Step 5: In die Annotations-Whitelist eintragen**

`tests/test_type_annotations.py`, in `ANNOTATED_MODULES` hinter `"src/single_instance.py",`:

```python
    "src/removal.py",
```

Run: `python -m pytest tests/test_type_annotations.py tests/test_catch_all_handlers.py tests/test_removal.py -q`
Expected: PASS.

- [ ] **Step 6: Lint und Typen**

Run: `ruff check src/removal.py tests/test_removal.py` und `npx pyright src/removal.py`
Expected: keine Befunde. Ein Befund → beheben, nicht unterdrücken.

- [ ] **Step 7: Commit**

```powershell
git add src/removal.py tests/test_removal.py tests/test_type_annotations.py
git commit -F <msg-datei>
```
Message: `feat(entfernen): Tk-freier Kern für "Zeiterfassung entfernen" (#50)`

---

### Task 2: Dialog, Button, `App.remove_application`

**Files:**
- Modify: `src/theme/messagebox.py` (`_run_modal` → `run_modal`, 4 Aufrufstellen)
- Modify: `src/theme/__init__.py` (Export)
- Create: `src/dialogs/removal_dialog.py`
- Modify: `src/dialogs/settings_dialog/tab_app.py`
- Modify: `src/dialogs/settings_dialog/dialog.py`
- Modify: `src/ui.py`

**Interfaces:**
- Consumes: `removal.is_available`, `removal.execute_removal`, `removal.app_file_hint`, `removal.format_summary` (Task 1).
- Produces: `ask_removal(parent) -> bool | None` (True = auch Nutzerdaten, False = nur Zugangsdaten usw., None = abgebrochen); `App.remove_application(with_data: bool) -> None`; `open_settings_dialog(..., on_request_removal=None)`; `AppTab(..., on_request_removal=None)`.

- [ ] **Step 1: `_run_modal` öffentlich machen**

In `src/theme/messagebox.py` die Funktion `_run_modal` in `run_modal` umbenennen (Definition Z. 25 und die vier Aufrufe Z. 98, 181, 224, 250). In `src/theme/__init__.py` im Import-Block aus `messagebox` `run_modal` ergänzen und in `__all__` aufnehmen (alphabetisch bei den übrigen eintragen).

Run: `python -m pytest tests -q -x -k "theme or messagebox or dialog"` — Expected: PASS.

- [ ] **Step 2: `src/dialogs/removal_dialog.py`**

```python
"""Rückfrage vor „Zeiterfassung entfernen" (#50).

Reiner Aufbau; was entfernt wird und in welcher Reihenfolge, steht in
`src/removal.py`.
"""
import tkinter as tk

from src.theme import (
    BG, CELL_BG, FONT, TEXT, center_dialog_on_parent, create_dialog, primary_button,
    px, run_modal, secondary_button,
)

MESSAGE = (
    "Entfernt werden:\n"
    "• Zugangsdaten und Schlüsselbund-Einträge\n"
    "• Autostart und Menüeintrag\n\n"
    "Die Programmdatei löschst du danach selbst — die App sagt dir, welche.\n"
    "Zeiten und Einstellungen bleiben erhalten, solange du nichts anderes "
    "ankreuzt."
)
DATA_LABEL = "Auch Zeiten, Einstellungen und Protokoll löschen"


def ask_removal(parent) -> bool | None:
    """Modal. `True`: auch die Nutzerdaten, `False`: nur Zugangsdaten und
    Integration, `None`: abgebrochen."""
    dialog = create_dialog(parent, "Zeiterfassung entfernen", modal=False,
                           escape_closes=False)
    result: dict[str, bool | None] = {"value": None}

    tk.Label(dialog, text=MESSAGE, font=FONT, bg=BG, fg=TEXT,
             wraplength=px(420), justify="left").pack(padx=24, pady=(20, 10))

    data_var = tk.BooleanVar(value=False)
    tk.Checkbutton(
        dialog, text=DATA_LABEL, variable=data_var, font=FONT, bg=BG, fg=TEXT,
        selectcolor=CELL_BG, activebackground=BG, activeforeground=TEXT,
        cursor="hand2",
    ).pack(padx=28, anchor="w")

    def confirm():
        result["value"] = bool(data_var.get())
        dialog.destroy()

    def cancel():
        dialog.destroy()

    btn_frame = tk.Frame(dialog, bg=BG)
    btn_frame.pack(pady=(14, 18))
    primary_button(btn_frame, "Entfernen", confirm).pack(side=tk.LEFT, padx=6)
    secondary_button(btn_frame, "Abbrechen", cancel).pack(side=tk.LEFT, padx=6)

    dialog.bind("<Escape>", lambda _e: cancel())
    dialog.protocol("WM_DELETE_WINDOW", cancel)

    center_dialog_on_parent(dialog, parent)
    run_modal(dialog)
    return result["value"]
```

Run: `python -m pytest tests/test_dialog_reveal.py tests/test_pixel_scaling.py -q`
Expected: PASS (Paarung `create_dialog`/`center_dialog_on_parent` vorhanden, `wraplength=px(...)`).
Falls ein Name aus `src.theme` nicht exportiert ist: Fehlermeldung zeigt es; den Namen im Theme-`__init__` ergänzen, nicht aus Teilmodulen importieren.

- [ ] **Step 3: `tab_app.py` — Button**

Import ergänzen: `import platform`, `import sys` und `from src import dpi, removal` (statt `from src import dpi`).

Konstruktor-Signatur: `on_change=None, on_request_removal=None)`; im Rumpf vor `form = Form(...)`: `self._on_request_removal = on_request_removal`.

Im Abschnitt „Daten" ersetzen:

```python
        specs = [("Datenordner öffnen", self._open_data_folder)]
        if storage is not None:
            specs.append(("Daten importieren", self._open_import_dialog))
        form.buttons(*specs)
        form.hint("Im Datenordner liegen Einträge, Einstellungen und "
                  "credentials.json. Importiert werden geteilte Arbeitszeiten "
                  "(JSON-Datei aus „Teilen“).")
```
durch:

```python
        specs = [("Datenordner öffnen", self._open_data_folder)]
        if storage is not None:
            specs.append(("Daten importieren", self._open_import_dialog))
        form.buttons(*specs)
        form.hint("Im Datenordner liegen Einträge, Einstellungen und "
                  "credentials.json. Importiert werden geteilte Arbeitszeiten "
                  "(JSON-Datei aus „Teilen“).")
        if on_request_removal is not None and removal.is_available(
                platform.system(), getattr(sys, "frozen", False)):
            form.buttons(("Zeiterfassung entfernen…", self._request_removal))
            form.hint("Räumt Schlüsselbund, Zugangsdaten, Autostart und "
                      "Menüeintrag ab und beendet die App. Die Programmdatei "
                      "löschst du danach selbst.")
```

Methode ergänzen (neben `_open_import_dialog`):

```python
    def _request_removal(self):
        from src.dialogs.removal_dialog import ask_removal

        with_data = ask_removal(self._dialog)
        if with_data is None:
            return
        # Schließt den Einstellungen-Dialog ohne Rückfrage nach ungespeicherten
        # Änderungen (dialog.py::_remove) — ein Speichern danach legte
        # settings.json neu an.
        self._on_request_removal(with_data)
```

- [ ] **Step 4: `dialog.py` — Durchreichen und Schließen**

Signatur von `open_settings_dialog`: `initial_tab=None)` → `initial_tab=None, on_request_removal=None)`; im Docstring eine Zeile: `on_request_removal: Rückruf(with_data) für „Zeiterfassung entfernen" (#50); schließt den Dialog ohne Speichern.`

Vor der `AppTab(...)`-Zeile einfügen:

```python
    def _remove(with_data):
        # Ohne Rückfrage nach ungespeicherten Änderungen schließen: ein Speichern
        # nach dem Aufräumen legte settings.json neu an (#50). Wie `_restart`
        # unten: der Dialog geht, dann übernimmt die App.
        dialog.destroy()
        if on_request_removal is not None:
            on_request_removal(with_data)
```

`AppTab(...)`-Aufruf erweitern um `on_request_removal=_remove`.

- [ ] **Step 5: `ui.py` — `remove_application`**

Import oben ergänzen: `from src import removal` (neben `from src import keyring_store, secret_migration`, Z. 23 → `from src import keyring_store, removal, secret_migration`).

In `_open_settings` dem `open_settings_dialog(...)`-Aufruf `on_request_removal=self.remove_application,` hinzufügen.

Methode nach `restart_for_scaling` einfügen:

```python
    def remove_application(self, with_data):
        """„Zeiterfassung entfernen" (#50): ruhigstellen, aufräumen, beenden.

        Kein `_quit_with_sync_push`: der Push bräuchte genau die Zugangsdaten,
        die hier gelöscht werden, und ein vorbereitetes Update soll nicht noch
        installiert werden. Ruhiggestellt wird, was Dateien neu schreiben
        könnte: Sync (über den `sync_guard`, der **nie** zurückgegeben wird),
        Tray, Erinnerungen, Tages-Tick, Single-Instance-Port.

        Lässt sich der Guard nicht nehmen, läuft gerade ein Sync: dann bleibt
        alles unangetastet und der Nutzer versucht es gleich noch einmal.
        """
        guard = self._sync_guard
        if guard is not None and not guard.acquire(blocking=False):
            themed_showinfo(
                self.root, "Sync läuft",
                "Gerade läuft ein Sync. Bitte in einem Moment erneut versuchen.")
            return
        if self._tray is not None:
            self._tray.stop()
        self._reminders.stop()
        self._send_reminders.stop()
        self._sync.stop_day_watch()
        if self._single_instance is not None:
            self._single_instance.release()

        base = self.base_path
        system = platform.system()
        pending = self.settings.get("pending_update_path") or ""
        had_token = os.path.exists(os.path.join(base, "token.json"))
        app_file = removal.app_file_hint(system, os.environ, sys.executable)

        def _done(results):
            themed_showinfo(self.root, "Zeiterfassung entfernt",
                            removal.format_summary(results, app_file, had_token))
            self.root.destroy()

        # Der Schlüsselbund-Schritt kann pro Eintrag bis zum 30-s-Watchdog
        # dauern; ohne Rückmeldung wirkte die App eingefroren.
        self.root.config(cursor="watch")
        self._bg.run(
            lambda: removal.execute_removal(base, with_data, system, pending),
            _done)
```

- [ ] **Step 6: Gesamtlauf und manuelle Prüfung**

Run: `python -m pytest -q` — Expected: alles PASS. `ruff check .` und `npx pyright` — keine neuen Befunde.

Manuell unter Windows (nur Wiring, der Button ist dort bewusst unsichtbar): `python -m src.main` mit `ZEITERFASSUNG_DATA_DIR` auf ein Scratch-Verzeichnis (siehe Memory „UI-Repro ohne Nutzerdaten") — App-Tab zeigt **keinen** Entfernen-Button. Für die UI-Strecke selbst ist ein Linux-Pre-Release nötig (Task 4). **Nicht** mit echten Nutzerdaten ausprobieren.

- [ ] **Step 7: Commit**

Message: `feat(entfernen): Button im App-Tab und App.remove_application (#50)`

---

### Task 3: Dokumentation

**Files:**
- Modify: `README.md`
- Modify: `docs/known-limitations.md`
- Modify: `CLAUDE.md` (Struktur-Abschnitt)
- Modify: `src/CLAUDE.md` (Abschnitt „Wo gehört neuer Code hin?" bzw. Plattform/Infra)

- [ ] **Step 1: README**

Im Abschnitt „App & Umgebung" nach der Zeile „Autostart & Einzelinstanz" einfügen:

```markdown
- **Entfernen aus der App** *(ab --VERSION--)* — Unter macOS und Linux räumt „Zeiterfassung entfernen…" (Einstellungen → App) Schlüsselbund, Zugangsdaten, Autostart und Menüeintrag ab, auf Wunsch auch Zeiten und Einstellungen; die Programmdatei löschst du danach selbst
```

Im Abschnitt „Vollständig entfernen" nach der Überschrift für macOS/Linux einen Satz ergänzen und die Schritte 1–5 als „Von Hand" einleiten:

```markdown
**Ab --VERSION--** erledigt das der Button „Zeiterfassung entfernen…" (Einstellungen → App → Daten) in einem Schritt, bis auf die Programmdatei selbst. Von Hand, in dieser Reihenfolge (…)
```
(den bestehenden Satz „Von Hand, in dieser Reihenfolge (…)" entsprechend anpassen, Rest unverändert).

In `docs/known-limitations.md` steht **kein** `--VERSION--`-Platzhalter: `resolve_readme_version.py` ersetzt nur README-Marker.

Run: `python -m pytest tests/test_readme_version.py -q` — Expected: PASS (Platzhalter erlaubt, nur im Release-PR aufgelöst).

- [ ] **Step 2: `docs/known-limitations.md`**

Im Abschnitt „macOS/Linux haben keinen Uninstaller" anfügen:

```markdown
Seit der Version, die diesen Eintrag einführt (siehe CHANGELOG), gibt es „Zeiterfassung entfernen…" (Einstellungen → App). Zwei Grenzen:

- Der Schritt „Schlüsselbund-Einträge" meldet ✓, sobald `--forget-secrets` durchlief — der läuft Eintrag für Eintrag durch und schluckt Einzelfehler (Timeout, gesperrter Schlüsselbund). Ein ✓ heißt „ausgeführt", nicht „nachgeprüft"; Fehler stehen nur im Protokoll, und mit dem Häkchen „Nutzerdaten" löscht die App auch dieses.
- Die Programmdatei löscht die App nicht (Linux: `$APPIMAGE`, macOS: `.app`). Unter macOS ist der Ablauf nicht auf einem Mac geprüft worden.
```
(`--VERSION--` hier durch die Platzhalter-Regel der README **nicht** abgedeckt: das Skript ersetzt nur README-Marker. In `known-limitations.md` stattdessen „Seit der Version, die diesen Eintrag einführt (siehe CHANGELOG)" schreiben — **kein** Platzhalter in dieser Datei.)

- [ ] **Step 3: `CLAUDE.md` und `src/CLAUDE.md`**

`CLAUDE.md`, Struktur-Liste nach dem Eintrag `src/secret_migration.py`:

```markdown
- `src/removal.py` — „Zeiterfassung entfernen" (macOS/Linux, #50): Dateilisten
  (Spiegel von `installer.iss`, `tests/test_removal.py` hält sie zusammen),
  `plan_removal`/`run_removal`/`execute_removal` (**wirft nie** — `on_done` des
  Runners feuert bei einer Exception nie) und die Hinweise für den Abschluss.
  Reihenfolge: Schlüsselbund → Autostart/Menüeintrag → Zugangsdaten →
  (nur mit Häkchen) Nutzerdaten, `settings.json` zuletzt → Datenordner nur
  wenn leer. Die App löscht ihre Programmdatei nicht, sie nennt sie.
  Eintrittspunkt `ui.App.remove_application`: nimmt den `sync_guard` und gibt
  ihn nie zurück, beendet ohne Sync-Push und ohne Update-Anwendung.
```

`src/CLAUDE.md`, unter „Wo gehört neuer Code hin?" einen Punkt anfügen:

```markdown
- **Etwas, das beim „Entfernen" aufgeräumt werden muss** (neue Datei im
  Datenordner, neuer Schlüsselbund-Eintrag, neue Autostart-Spur) → in
  `removal.py` ergänzen **und** in `installer.iss` (Windows). Zwei Test-
  Assertions halten beide Listen zusammen; ein neues Secret braucht außerdem
  den Eintrag in `secret_migration.forget_all` (s. oben).
```

Run: `python -m pytest tests/test_claude_md_claims.py -q` — Expected: PASS. Schlägt der Handler-Zähler an („rund 105"), die Zahl im Text mit dem Testbefund abgleichen und nachziehen.

- [ ] **Step 4: Commit**

Message: `docs(entfernen): README, Grenzen, CLAUDE.md (#50)`

---

### Task 4: Abschluss

- [ ] **Step 1: Gesamtlauf** — `python -m pytest -q`, `ruff check .`, `npx pyright` — alles grün.
- [ ] **Step 2: Push und PR** — Branch `feat/app-entfernen` pushen (Credential-Helper-Kette, s. Global Constraints), PR gegen `master` **ohne** `release:*`-Label. Im PR-Text: Linux-Pre-Release vor dem nächsten Release auslösen (CLAUDE.md „Plattformspezifische PRs"), macOS bleibt ungeprüft, wie in der Spec festgehalten.
- [ ] **Step 3: Pre-Release anstoßen (nach Merge, mit Zustimmung des Maintainers)** — Actions → Release → „Run workflow", Häkchen `prerelease`. Auf Linux mit **Scratch-Daten** testen (`ZEITERFASSUNG_DATA_DIR` ist im gefrorenen Build wirkungslos; stattdessen einen frischen Benutzer bzw. eine VM nehmen): Button sichtbar, Abbrechen ändert nichts, „Entfernen" ohne Häkchen lässt `zeiterfassung.json`/`settings.json` stehen, mit Häkchen ist der Ordner weg, Autostart-/Menüdatei sind weg, `--forget-secrets`-Wirkung im Schlüsselbund prüfen.
