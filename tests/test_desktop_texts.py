"""Ratsche gegen Oberflächentexte im Quelltext des Desktops.

Texte, die der Nutzer in einem Fenster, Dialog, Toast, Tooltip, Tray-Menü, Banner oder
Systemmenü liest, gehören über `t("…")` in den Katalog (`src/i18n/de/`). Maßgeblich ist
der Verbraucher, nicht der Dateiname: ein Fehlertext in `share.py`, den der Import-Dialog
zeigt, ist Oberfläche.

Was als Text gilt und welche Kontexte ausgenommen sind (Log, Docstrings, Dict-Schlüssel,
technische Aufrufe …), steht in `scripts/desktop_text_check.py`; der Test lädt das Skript
über seinen Pfad, damit Inventur, Äquivalenzprüfung und Ratsche dieselbe Regel lesen.
`raise`-Argumente sind bewusst **keine** Ausnahme: ein Text in einer Exception steht im
Katalog oder in `ALLOWED` mit dem Nachweis, dass er den Nutzer nie erreicht.

Drei Listen, je mit Grund:
- `FILE_EXEMPT` — ganze Dateien, deren Texte Ausgabe oder Protokoll sind (Teil 3).
- `ALLOWED` — einzelne technische oder nie angezeigte Literale einer sonst geprüften Datei.
- `PENDING` — noch nicht umgestellte Dateien; jede Umstellung nimmt ihre Dateien heraus.

Inventur: `python scripts/desktop_text_check.py --list`.
"""

import importlib.util
import pathlib
import subprocess

import pytest

from src.i18n import TEXTS

REPO = pathlib.Path(__file__).resolve().parent.parent
_SCRIPT = REPO / "scripts" / "desktop_text_check.py"
_spec = importlib.util.spec_from_file_location("_desktop_text_check", _SCRIPT)
assert _spec is not None and _spec.loader is not None
check = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check)

# Ganze Dateien, deren Texte nicht Oberfläche sind. Volle relative Pfade: ein Muster wie
# `mobile_*.py` träfe auch `dialogs/mobile_pair_dialog.py`. Nur Dateien mit Fundstellen;
# eine Datei des Bereichs ohne Text bleibt geprüft, damit ein neuer Oberflächentext auffällt.
_OUTPUT = "Ausgabe (PDF, Mail, Teilen, Kalender), Sprache folgt in Teil 3"
_API = "Antworttexte der lokalen API, erscheinen nie in der Oberfläche (Teil 3)"
_PROTOCOL = "Protokoll- und Fehlertexte von Handy-Abgleich und Relay, nie angezeigt"
FILE_EXEMPT: dict[str, str] = {
    "src/report.py": _OUTPUT,
    "src/share_message.py": _OUTPUT,
    "src/settings.py": f"{_OUTPUT}: Mail-Vorlagen als Default-Werte",
    "src/gcal.py": f"{_OUTPUT}: Titel und Beschreibung der Kalendertermine",
    "src/api_auth.py": _API,
    "src/api_entry_write.py": _API,
    "src/api_reservation_write.py": _API,
    "src/api_routes.py": _API,
    "src/api_server.py": _API,
    "src/api_vacation_write.py": _API,
    "src/mobile_box_cursor.py": _PROTOCOL,
    "src/mobile_box_store.py": _PROTOCOL,
    "src/mobile_crypto.py": _PROTOCOL,
    "src/mobile_keys.py": _PROTOCOL,
    "src/mobile_pairing.py": _PROTOCOL,
    "src/mobile_relay_codec.py": _PROTOCOL,
    "src/mobile_relay_store.py": _PROTOCOL,
    "src/mobile_reservations.py": _PROTOCOL,
    "src/mobile_routes.py": _PROTOCOL,
    "src/mobile_settings.py": _PROTOCOL,
    "src/mobile_store.py": _PROTOCOL,
    "src/mobile_sync.py": _PROTOCOL,
    "src/relay_adapter.py": _PROTOCOL,
    "src/relay_link.py": _PROTOCOL,
    "src/ws_client.py": _PROTOCOL,
    "src/box_relay.py": f"{_PROTOCOL} (User-Agent des Relay-Aufrufs)",
    "src/push_relay.py": f"{_PROTOCOL} (User-Agent, Weiterleitungs-Fehler)",
}

# Einzelne Literale in sonst geprüften Dateien: Datei → Texte (Template-Form, f-Strings mit
# `{}`), je mit Grund bzw. Verbraucher im Kommentar. Wächst mit den Umstellungen.
ALLOWED: dict[str, list[str]] = {}

# Noch nicht umgestellte Dateien, nach dem Task des Plans gruppiert
# (docs/superpowers/plans/2026-11-11-desktop-textschicht.md). Jede Umstellung nimmt ihre
# Dateien heraus; eine Datei hier ohne verbleibende Fundstelle macht den Test rot.
PENDING: list[str] = [
    # Task 2: geteilte Tk-freie Bausteine
    "src/time_utils.py",
    "src/vacations.py",
    "src/default_times.py",
    "src/send_reminder.py",
    "src/dpi.py",
    "src/version.py",
    "src/changelog.py",
    "src/privacy_doc.py",
    "src/oauth_utils.py",
    "src/mail.py",
    "src/locale_format.py",
    "src/dialogs/slot_rows.py",
    # Task 3: Meldungsbausteine und Tray
    "src/theme/messagebox.py",
    "src/update_banner.py",
    "src/scale_banner.py",
    "src/unpair_notice.py",
    "src/tray/model.py",
    "src/tray/windows.py",
    "src/logging_setup.py",
    "src/main.py",
    "src/desktop_entry.py",
    # Task 4: Zustands- und Meldungsmodule
    "src/conflict_view.py",
    "src/storage.py",
    "src/removal.py",
    "src/updater.py",
    "src/self_update.py",
    "src/secret_migration.py",
    "src/weekly_limit.py",
    "src/reminder_scheduler.py",
    "src/send_reminder_scheduler.py",
    "src/sync_orchestrator.py",
    "src/sync.py",
    "src/dialogs/settings_dialog/oauth_task.py",
    # Task 5: Stores, Validierung, Versandmeldungen
    "src/smtp_store.py",
    "src/webhook_store.py",
    "src/webhook_secrets.py",
    "src/vacation_plan.py",
    "src/webhook.py",
    "src/smtp.py",
    "src/mime_message.py",
    "src/share.py",
    # Task 6: Einstellungen, Teil 1
    "src/dialogs/settings_dialog/tab_rules.py",
    "src/dialogs/settings_dialog/tab_work.py",
    "src/dialogs/settings_dialog/tab_reminders.py",
    "src/dialogs/settings_dialog/tab_app.py",
    "src/dialogs/settings_dialog/tab_sending.py",
    "src/dialogs/settings_dialog/dialog.py",
    # Task 7: Einstellungen, Teil 2
    "src/dialogs/settings_dialog/tab_google.py",
    "src/dialogs/settings_dialog/tab_updates.py",
    "src/dialogs/settings_dialog/tab_api.py",
    "src/dialogs/settings_dialog/tab_mobile.py",
    "src/dialogs/settings_dialog/tab_smtp.py",
    "src/dialogs/settings_dialog/tab_webhooks.py",
    "src/dialogs/settings_dialog/_record_list_tab.py",
    "src/dialogs/scopes_dialog.py",
    # Task 8: Dialoge A
    "src/dialogs/period_picker.py",
    "src/dialogs/category_dialog.py",
    "src/dialogs/conflicts_dialog.py",
    "src/dialogs/entry_dialog.py",
    # Task 9: Dialoge B
    "src/dialogs/send_task.py",
    "src/dialogs/send_dialog.py",
    "src/dialogs/export_dialog.py",
    "src/dialogs/share_task.py",
    "src/dialogs/share_dialog.py",
    "src/dialogs/import_dialog.py",
    # Task 10: Dialoge C
    "src/dialogs/smtp_dialog.py",
    "src/dialogs/webhook_dialog.py",
    "src/dialogs/vacation_dialog.py",
    "src/dialogs/mobile_pair_dialog.py",
    "src/dialogs/removal_dialog.py",
    "src/dialogs/privacy_dialog.py",
    # Task 11: Hauptfenster
    "src/ui.py",
    "src/grid_renderer.py",
    # Ohne Task im Plan: überwiegend technische Literale (→ ALLOWED), dazu die
    # Bundesland-Namen der Auswahl in `holidays_region.py` (Oberfläche).
    "src/autostart.py",
    "src/drive.py",
    "src/holidays_region.py",
    "src/json_store.py",
    "src/platform_open.py",
    "src/reservations.py",
    "src/startup_info.py",
    "src/sync_runtime.py",
    "src/theme/fonts.py",
    "src/theme/form.py",
    "src/theme/form_logic.py",
    "src/theme/widgets.py",
    "src/tray/__init__.py",
    "src/tray/linux.py",
    "src/dialogs/settings_dialog/fields.py",
]

# Bereiche, die nur Oberfläche bauen: dort ist eine ganze Datei nie ausgenommen.
_UI_FOLDERS = ("src/dialogs/", "src/theme/", "src/tray/")

SOURCES = check.source_files(str(REPO))


def _read(rel: str) -> str:
    return check.read_source(rel, str(REPO))


def _open_findings(rel: str) -> list[str]:
    allowed = set(ALLOWED.get(rel, []))
    return [f"{rel}:{f.line} [{f.reason}] {f.text!r}"
            for f in check.findings(_read(rel)) if f.text not in allowed]


# --- Die Regel -------------------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "Speichern", "Abbrechen", "Bis:", "Kein Empfänger", "über", "Pause {} min",
    "{} Einträge", "Feiertag: {}", "Drive-Sync", "⚠ noch nie", "Gesamtstunden: —",
])
def test_rule_counts_texts(text):
    assert check.text_reason(text) is not None


@pytest.mark.parametrize("text", [
    "", "APPIMAGE", "RGBA", "OK", "GET /", "Windows", "Linux", "Darwin", "Zeiterfassung",
    "settings.json", "a.b", "%Y-%m-%d %H:%M", "<Button-3>", "TkDefaultFont", "macOS",
    "TCombobox", "URLError", "default_start", "-topmost", "{}:{}",
    "%(asctime)s [%(levelname)s] %(name)s: %(message)s", "werkstudent_limit_{}.year",
    "https://example.org/a", "✓", " · ",
])
def test_rule_ignores_technical_strings(text):
    assert check.text_reason(text) is None


def _texts(source: str) -> list[str]:
    return [f.text for f in check.findings(source)]


def test_scan_exempts_log_docstrings_keys_and_technical_contexts():
    source = '''
"""Modul-Docstring mit Text."""
import logging, os, platform, re
log = logging.getLogger(__name__)


def f(x: "Annotation Text") -> "Rückgabe Text":
    """Docstring der Funktion."""
    log.warning("Log bleibt deutsch: %s", "Auch im Log")
    _log_skipped("Hilfsfunktion fürs Log")
    os.environ.get("Kein Text hier")
    re.compile("Muster mit Leerzeichen")
    x.startswith("Ein Präfix")
    widget(style="Dark Style", font="Font Name", state="Kein Zustand")
    d = {"Schlüssel Text": "Wert Text"}
    d["Index Text"]
    if platform.system() == "Mac Os":
        pass
    t("hauptfenster.titel")
    N_("dialoge.knopf")
    raise ValueError("Fehler für den Nutzer")
    return f"Hallo {x}, Welt"

__all__ = ["Kein Text"]
'''
    assert _texts(source) == ["Wert Text", "Fehler für den Nutzer", "Hallo {}, Welt"]


def test_scan_reads_an_fstring_as_one_template_and_skips_format_specs():
    source = 'x = f"Noch {n:>5} Tage, {name!r} übrig"\n'
    assert _texts(source) == ["Noch {} Tage, {} übrig"]


def test_scan_finds_texts_nested_in_a_log_call_argument_only_inside_it():
    source = 'show(title="Titel Text", body=f"{log.info(\'Im Log\')} Rest Text")\n'
    assert _texts(source) == ["Titel Text", "{} Rest Text"]


def test_key_literals_and_dynamic_keys():
    source = (
        't("a.b")\n'
        'i18n.t("c.d", n=1)\n'
        'TABLE = {"x": N_("e.f")}\n'
        't(TABLE[code])\n'
        't(TABLE.get(code, N_("g.h")))\n'
        't(f"a.{x}")\n'
        't("a." + x)\n'
        't(name)\n'
        'N_(name)\n'
    )
    assert check.key_literals(source) == ["a.b", "c.d", "e.f", "g.h"]
    assert check.dynamic_keys(source) == [6, 7, 8, 9]


# --- Die Ratsche -----------------------------------------------------------------------

@pytest.mark.parametrize("rel", [s for s in SOURCES if s not in PENDING and s not in FILE_EXEMPT])
def test_converted_files_have_no_user_texts(rel):
    assert _open_findings(rel) == [], (
        "Text gehört in den Katalog (src/i18n/de/) und über t(\"…\") in den Code; "
        "ist er technisch oder nie angezeigt, nach ALLOWED mit Grund")


@pytest.mark.parametrize("rel", PENDING)
def test_pending_files_still_have_texts(rel):
    assert _open_findings(rel), f"{rel} hat keine Texte mehr: aus PENDING streichen"


def test_lists_name_existing_disjoint_files():
    for rel in [*FILE_EXEMPT, *ALLOWED, *PENDING]:
        assert (REPO / rel).is_file(), rel
        assert rel in SOURCES, rel
    assert len(PENDING) == len(set(PENDING))
    assert not set(PENDING) & set(FILE_EXEMPT)
    assert not set(ALLOWED) & set(FILE_EXEMPT)
    assert all(reason.strip() for reason in FILE_EXEMPT.values())


def test_ui_folders_are_never_exempt_as_a_whole():
    assert [rel for rel in FILE_EXEMPT if rel.startswith(_UI_FOLDERS)] == []
    assert "src/dialogs/mobile_pair_dialog.py" not in FILE_EXEMPT


def test_every_allowed_text_still_occurs_in_its_file():
    stale = []
    for rel, texts in ALLOWED.items():
        found = {f.text for f in check.findings(_read(rel))}
        stale += [f"{rel}: {text!r}" for text in texts if text not in found]
    assert stale == [], "veraltete ALLOWED-Einträge entfernen"


# --- Schlüssel gegen Katalog -------------------------------------------------------------

def _all_keys() -> dict[str, list[str]]:
    used: dict[str, list[str]] = {}
    for rel in SOURCES:
        for key in check.key_literals(_read(rel)):
            used.setdefault(key, []).append(rel)
    return used


def test_every_key_exists_in_the_catalog():
    missing = sorted(f"{key} ({', '.join(files)})"
                     for key, files in _all_keys().items() if key not in TEXTS)
    assert missing == []


def test_every_catalog_key_is_used():
    used = _all_keys()
    unused = sorted(k for k in TEXTS if not k.startswith("i18n.") and k not in used)
    assert unused == []


def test_keys_are_literals_never_built():
    built = [f"{rel}:{line}" for rel in SOURCES for line in check.dynamic_keys(_read(rel))]
    assert built == []


# --- Äquivalenzprüfung ------------------------------------------------------------------

_CATALOG = {"dialoge.gruss": "Hallo {name}, willkommen", "dialoge.knopf": "Speichern",
            "dialoge.neu": "Ganz neuer Text"}


def test_equivalence_accepts_a_conversion_with_the_same_texts():
    old = 'a = f"Hallo {name}, willkommen"\nb = "Speichern"\n'
    new = 'a = t("dialoge.gruss", name=name)\nb = t("dialoge.knopf")\n'
    assert check.compare(old, new, _CATALOG).ok


def test_equivalence_reports_lost_texts_new_values_and_unknown_keys():
    old = 'a = "Hallo " + name + ", willkommen"\nb = "Speichern"\n'
    new = 'a = t("dialoge.gruss", name=name)\nb = t("dialoge.neu")\nc = t("fehlt.ganz")\n'
    result = check.compare(old, new, _CATALOG)
    assert not result.ok
    assert result.removed_without_key == [", willkommen", "Hallo ", "Speichern"]
    assert result.keys_without_text == ["dialoge.gruss = 'Hallo {}, willkommen'",
                                        "dialoge.neu = 'Ganz neuer Text'"]
    assert result.unknown_keys == ["fehlt.ganz"]


def test_equivalence_counts_texts_as_a_multiset():
    old = 'a = "Speichern"\nb = "Speichern"\n'
    new = 'a = t("dialoge.knopf")\nb = "Speichern"\n'
    assert check.compare(old, new, _CATALOG).ok
    assert not check.compare(old, 'a = t("dialoge.knopf")\nb = t("dialoge.knopf")\n'
                             'c = t("dialoge.knopf")\n', _CATALOG).ok


def test_read_base_from_a_folder_and_from_git(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "x.py").write_text('a = "Alter Text"\n', encoding="utf-8")
    assert check.read_base(str(tmp_path), "src/x.py") == 'a = "Alter Text"\n'
    assert check.read_base(str(tmp_path), "src/fehlt.py") == ""
    head = subprocess.run(["git", "rev-parse", "--verify", "-q", "HEAD"], cwd=REPO,
                          capture_output=True, text=True)
    if head.returncode != 0:
        pytest.skip("kein git-Checkout")
    assert "def normalize_country" in check.read_base("HEAD", "src/region.py")
    assert check.read_base("HEAD", "src/gibt_es_nicht.py") == ""


def test_script_cli_runs(capsys):
    assert check.main(["--summary"]) == 0
    assert "insgesamt:" in capsys.readouterr().out
    assert check.main(["--base", "HEAD", "--files", "src/region.py"]) == 0
