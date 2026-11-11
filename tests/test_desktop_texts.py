"""Ratsche gegen Oberflächentexte im Quelltext des Desktops.

Texte, die der Nutzer in einem Fenster, Dialog, Toast, Tooltip, Tray-Menü, Banner oder
Systemmenü liest, gehören über `t("…")` in den Katalog (`src/i18n/de/`). Maßgeblich ist
der Verbraucher, nicht der Dateiname: ein Fehlertext in `share.py`, den der Import-Dialog
zeigt, ist Oberfläche.

Was als Text gilt und welche Kontexte ausgenommen sind (Log, Docstrings, HTTP-Kopfzeilen,
technische Aufrufe …), steht in `scripts/desktop_text_check.py`; der Test lädt das Skript
über seinen Pfad, damit Inventur, Äquivalenzprüfung und Ratsche dieselbe Regel lesen.
`raise`-Argumente sind bewusst **keine** Ausnahme: ein Text in einer Exception steht im
Katalog oder in `ALLOWED` mit dem Nachweis, dass er den Nutzer nie erreicht.

Drei Listen, je mit Grund:
- `FILE_EXEMPT` — ganze Dateien, deren Texte Ausgabe oder Protokoll sind (Teil 3).
- `ALLOWED` — einzelne technische oder nie angezeigte Literale einer sonst geprüften Datei.
- `PENDING` — noch nicht umgestellte Dateien; jede Umstellung nimmt ihre Dateien heraus.
  Die Gruppen-Kommentare („Task 3“ …) sind Markierungen für die Dauer der Umstellung und
  fallen mit der leeren Liste weg.

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
# `mobile_*.py` träfe auch `dialogs/mobile_pair_dialog.py`. Nur Dateien mit Fundstellen
# (ein Test hält das fest); eine Datei des Bereichs ohne Text bleibt geprüft, damit ein
# neuer Oberflächentext auffällt. Dateien, in denen nur Teile Ausgabe sind, stehen nicht
# hier, sondern mit ihren Ausgabetexten in ALLOWED.
_OUTPUT = "Ausgabe (PDF, Mail, Teilen), Sprache folgt in Teil 3"
_API = "Antworttexte der lokalen API, erscheinen nie in der Oberfläche (Teil 3)"
_PROTOCOL = "Protokoll- und Fehlertexte von Handy-Abgleich und Relay, nie angezeigt"
FILE_EXEMPT: dict[str, str] = {
    "src/report.py": _OUTPUT,
    "src/share_message.py": _OUTPUT,
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

# Einzelne Literale in sonst geprüften Dateien: Datei → {Text: Grund}. Texte in
# Template-Form (f-String-Ausdrücke als `{}`); der Grund nennt den Verbraucher.
_CALENDAR = "Ausgabe/Teil 3: Text des Google-Kalendertermins"
_MAIL_TEMPLATE = "Ausgabe/Teil 3: Default der Mail-Vorlage, gespeichert als Einstellungswert"
_QUARANTINE = "Grund im Log der Quarantäne (`_quarantine_corrupt`), nie angezeigt"
_LOCALE_TABLE = "Locale-Tabelle: die eine Stelle für Namen und Muster je Locale, kein Katalogtext"
ALLOWED: dict[str, dict[str, str]] = {
    "src/locale_format.py": {
        "{weekday} - {date}": _LOCALE_TABLE,
        **{n: _LOCALE_TABLE for n in (
            "Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag",
            "Mo", "Di", "Mi", "Do", "Fr", "Sa", "So",
            "Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August",
            "September", "Oktober", "November", "Dezember")},
    },
    "src/time_utils.py": {
        **{n: "Ausgabe/Teil 3: Wochentage des Berichts (`DAYS_DE`, nur von report.py gelesen)"
           for n in ("Mo", "Di", "Mi", "Do", "Fr", "Sa", "So")},
    },
    "src/version.py": {
        "{}-dev ({})": "Build-Kennung im Fenstertitel und Installer (`build_label`), sprachneutral",
    },
    "src/vacations.py": {
        "apply_reconciled: entry {} missing keys {}": (
            "Invariante: die Eingabe stammt aus `store.get_all_raw()` (vacations_sync.py), "
            "ein Verstoß endet als Worker-Traceback im nativen Fehlerdialog, nie als Meldung"),
    },
    "src/gcal.py": {
        "Arbeitszeit (reserviert)": _CALENDAR,
        "Von der Zeiterfassung verwaltete Reservierung.": _CALENDAR,
        "Urlaub": _CALENDAR,
        "Von der Zeiterfassung verwalteter Urlaub.": _CALENDAR,
        "{}\nZeitspanne brutto, Pause {} min nicht abgezogen.": _CALENDAR,
    },
    "src/settings.py": {
        "Zeiterfassung — {zeitraum}": _MAIL_TEMPLATE,
        "Sehr geehrte Damen und Herren,": _MAIL_TEMPLATE,
        "anbei erhalten Sie meine Zeiterfassung für den Zeitraum {zeitraum}.": _MAIL_TEMPLATE,
        "Mit freundlichen Grüßen": _MAIL_TEMPLATE,
        "JSON nicht parsebar": _QUARANTINE,
        "unerwartetes Toplevel-Format ({})": _QUARANTINE,
    },
}

# Noch nicht umgestellte Dateien, nach dem Task der Umstellung gruppiert. Jede Umstellung
# nimmt ihre Dateien heraus; eine Datei hier ohne verbleibende Fundstelle macht den Test rot.
PENDING: list[str] = [
    # Task 2
    "src/oauth_utils.py",
    "src/mail.py",
    "src/dialogs/slot_rows.py",
    # Task 3
    "src/theme/messagebox.py",
    "src/update_banner.py",
    "src/scale_banner.py",
    "src/unpair_notice.py",
    "src/tray/model.py",
    "src/tray/windows.py",
    "src/logging_setup.py",
    "src/main.py",
    "src/desktop_entry.py",
    "src/theme/fonts.py",
    "src/theme/form.py",
    "src/theme/form_logic.py",
    "src/theme/widgets.py",
    "src/tray/__init__.py",
    "src/tray/linux.py",
    "src/autostart.py",
    "src/platform_open.py",
    # Task 4
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
    "src/drive.py",
    "src/sync_runtime.py",
    "src/reservations.py",
    "src/json_store.py",
    "src/startup_info.py",
    "src/dialogs/settings_dialog/fields.py",
    # Task 5
    "src/smtp_store.py",
    "src/webhook_store.py",
    "src/webhook_secrets.py",
    "src/vacation_plan.py",
    "src/webhook.py",
    "src/smtp.py",
    "src/mime_message.py",
    "src/share.py",
    # Task 6 (holidays_region: die Beschriftungen liest tab_work/tab_rules, beide hier)
    "src/dialogs/settings_dialog/tab_rules.py",
    "src/dialogs/settings_dialog/tab_work.py",
    "src/dialogs/settings_dialog/tab_reminders.py",
    "src/dialogs/settings_dialog/tab_app.py",
    "src/dialogs/settings_dialog/tab_sending.py",
    "src/dialogs/settings_dialog/dialog.py",
    "src/holidays_region.py",
    # Task 7
    "src/dialogs/settings_dialog/tab_google.py",
    "src/dialogs/settings_dialog/tab_updates.py",
    "src/dialogs/settings_dialog/tab_api.py",
    "src/dialogs/settings_dialog/tab_mobile.py",
    "src/dialogs/settings_dialog/tab_smtp.py",
    "src/dialogs/settings_dialog/tab_webhooks.py",
    "src/dialogs/settings_dialog/_record_list_tab.py",
    "src/dialogs/scopes_dialog.py",
    # Task 8 (category_dialog: auch „variabel“ (≈183 f.), ein einzelnes kleines Wort über
    # eine Variable — die Regel sieht es nicht, die Umstellung muss es von Hand mitnehmen)
    "src/dialogs/period_picker.py",
    "src/dialogs/category_dialog.py",
    "src/dialogs/conflicts_dialog.py",
    "src/dialogs/entry_dialog.py",
    # Task 9
    "src/dialogs/send_task.py",
    "src/dialogs/send_dialog.py",
    "src/dialogs/export_dialog.py",
    "src/dialogs/share_task.py",
    "src/dialogs/share_dialog.py",
    "src/dialogs/import_dialog.py",
    # Task 10
    "src/dialogs/smtp_dialog.py",
    "src/dialogs/webhook_dialog.py",
    "src/dialogs/vacation_dialog.py",
    "src/dialogs/mobile_pair_dialog.py",
    "src/dialogs/removal_dialog.py",
    "src/dialogs/privacy_dialog.py",
    # Task 11
    "src/ui.py",
    "src/grid_renderer.py",
]

# Bereiche, die nur Oberfläche bauen: dort ist eine ganze Datei nie ausgenommen.
_UI_FOLDERS = ("src/dialogs/", "src/theme/", "src/tray/")

SOURCES = check.source_files(str(REPO))


def _read(rel: str) -> str:
    return check.read_source(rel, str(REPO))


def _open_findings(rel: str) -> list[str]:
    allowed = ALLOWED.get(rel, {})
    return [f"{rel}:{f.line} [{f.reason}] {f.text!r}"
            for f in check.findings(_read(rel)) if f.text not in allowed]


# --- Die Regel -------------------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "Speichern", "Abbrechen", "Bis:", "Kein Empfänger", "über", "Pause {} min",
    "{} Einträge", "Feiertag: {}", "Drive-Sync", "⚠ noch nie", "Gesamtstunden: —",
    # Leerraum zählt mit dem Ausdruck: `{} h` ist eine Anzeige, kein Format
    "{} h", "{} min", "{} importieren", "{} {} gekoppelt. {}",
    # Satzzeichen am Ende und Abkürzungen sind Text, keine Punktnamen
    "Speichern...", "Aus.", "Synchronisiert.", "z.B.", "u.a.",
])
def test_rule_counts_texts(text):
    assert check.text_reason(text) is not None


@pytest.mark.parametrize("text", [
    "", "APPIMAGE", "RGBA", "OK", "GET /", "Windows", "Linux", "Darwin", "Zeiterfassung",
    "settings.json", "a.b", "%Y-%m-%d %H:%M", "<Button-3>", "TkDefaultFont", "macOS",
    "TCombobox", "URLError", "default_start", "-topmost", "{}:{}", "{} {}", "{} - {}",
    "%(asctime)s [%(levelname)s] %(name)s: %(message)s", "werkstudent_limit_{}.year",
    ".{}-*.tmp", "{}x{}", "entry:{}", "localhost:{}", "%d.%m.",
    "https://example.org/a", "✓", " · ", "lokal", "variabel",
])
def test_rule_ignores_technical_strings(text):
    assert check.text_reason(text) is None


@pytest.mark.parametrize("text", ["lokal", "import", "variabel", "v{}"])
def test_a_single_lowercase_word_counts_at_a_display_slot(text):
    assert check.text_reason(text, ui_slot=True) == "Anzeigeargument"


@pytest.mark.parametrize("text", ["settings.json", "default_start", "{}", "✕", "OK"])
def test_a_display_slot_does_not_make_technical_strings_text(text):
    assert check.text_reason(text, ui_slot=True) is None


def _texts(source: str) -> list[str]:
    return [f.text for f in check.findings(source)]


def test_scan_exempts_log_docstrings_headers_and_technical_contexts():
    source = '''
"""Modul-Docstring mit Text."""
import logging, os, platform, re, unicodedata
log = logging.getLogger(__name__)


def f(x: "Annotation Text") -> "Rückgabe Text":
    """Docstring der Funktion."""
    log.warning("Log bleibt deutsch: %s", "Auch im Log")
    logging.getLogger(__name__).info("Auch das ist Log")
    _log_skipped("Hilfsfunktion fürs Log")
    os.environ.get("Kein Text hier")
    re.compile("Muster mit Leerzeichen")
    x.startswith("Ein Präfix")
    service.files().list(fields="files(id, name)", q="name = 'x'")
    headers = {"Content-Type": "application/json", "Authorization": token}
    headers["Content-Length"]
    if platform.system() == "Mac Os" or unicodedata.category(c) in ("Cc", "Cs"):
        pass
    getattr(obj, "Attribut Name")
    t("hauptfenster.titel")
    N_("dialoge.knopf")
    return f"Hallo {x}, Welt"

__all__ = ["Kein Text"]
'''
    assert _texts(source) == ["Hallo {}, Welt"]


def test_scan_keeps_texts_that_only_look_technical_by_context():
    source = '''
banner.info("Banner Text")
self.status.error("Status Text")
raise ValueError("Fehler für den Nutzer")
LABELS = {"Allgemein": "general", "Tageweise": "per_day"}
CODES["Ein Label"]
getattr(obj, "attr", "Ersatz Text")
widget(name="Sichtbarer Name", state="Ein Zustand", style="Ein Stil", font="Font Text")
tk.Radiobutton(frame, text="lokal", value="L")
form.row(label="kurz")
themed_showinfo(parent, "titel", "meldung")
messagebox.showerror("fehler", detail)
primary_button(parent, "ok-knopf", command)
'''
    assert _texts(source) == [
        "Banner Text", "Status Text", "Fehler für den Nutzer", "Allgemein", "Tageweise",
        "Ein Label", "Ersatz Text", "Sichtbarer Name", "Ein Zustand", "Ein Stil", "Font Text",
        "lokal", "kurz", "titel", "meldung", "fehler", "ok-knopf"]


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
        't(var.get())\n'
        't(KEYS[f"a.{x}"])\n'
        't(KEYS["a." + x])\n'
        't(TABLE.get())\n'
        't(table[code])\n'
        't(_KIND_TEXTS[kind])\n'
        't(tab_rules.LABELS.get(code))\n'
    )
    assert check.key_literals(source) == ["a.b", "c.d", "e.f", "g.h"]
    assert check.dynamic_keys(source) == [6, 7, 8, 9, 10, 11, 12, 13, 14]


# --- Die Ratsche -----------------------------------------------------------------------

@pytest.mark.parametrize("rel", [s for s in SOURCES if s not in PENDING and s not in FILE_EXEMPT])
def test_converted_files_have_no_user_texts(rel):
    assert _open_findings(rel) == [], (
        "Text gehört in den Katalog (src/i18n/de/) und über t(\"…\") in den Code; "
        "ist er technisch oder nie angezeigt, nach ALLOWED mit Grund")


@pytest.mark.parametrize("rel", PENDING)
def test_pending_files_still_have_texts(rel):
    assert _open_findings(rel), f"{rel} hat keine Texte mehr: aus PENDING streichen"


@pytest.mark.parametrize("rel", sorted(FILE_EXEMPT))
def test_exempt_files_still_have_texts(rel):
    assert check.findings(_read(rel)), f"{rel} hat keine Texte mehr: aus FILE_EXEMPT streichen"


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


def test_every_allowed_text_has_a_reason():
    missing = [f"{rel}: {text!r}" for rel, texts in ALLOWED.items()
               for text, reason in texts.items() if not reason.strip()]
    assert missing == []


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


def test_missing_credentials_text_keeps_its_wording():
    # Gleicher Wortlaut wie vor der Umstellung; drive/mail/send_dialog übernehmen den Schlüssel.
    assert TEXTS["meldungen.credentials_fehlen"] == "credentials.json nicht gefunden unter:\n{pfad}"


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


def _has_git() -> bool:
    head = subprocess.run(["git", "rev-parse", "--verify", "-q", "HEAD"], cwd=REPO,
                          capture_output=True, text=True)
    return head.returncode == 0


def test_read_base_from_a_folder_and_from_git(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "x.py").write_text('a = "Alter Text"\n', encoding="utf-8")
    assert check.read_base(str(tmp_path), "src/x.py") == 'a = "Alter Text"\n'
    assert check.read_base(str(tmp_path), "src/fehlt.py") == ""
    if not _has_git():
        pytest.skip("kein git-Checkout")
    assert "def normalize_country" in check.read_base("HEAD", "src/region.py")
    assert check.read_base("HEAD", "src/gibt_es_nicht.py") == ""


def test_an_unknown_base_fails_instead_of_comparing_against_nothing(tmp_path, capsys):
    if not _has_git():
        pytest.skip("kein git-Checkout")
    check.resolve_base("HEAD")
    check.resolve_base(str(tmp_path))
    with pytest.raises(check.UnknownBase):
        check.resolve_base("gibt-es-nicht-als-ref")
    assert check.main(["--base", "gibt-es-nicht-als-ref", "--files", "src/region.py"]) == 2
    assert "weder Ordner noch git-Ref" in capsys.readouterr().err


def test_script_cli_runs(capsys):
    assert check.main(["--summary"]) == 0
    assert "insgesamt:" in capsys.readouterr().out
    if _has_git():
        assert check.main(["--base", "HEAD", "--files", "src/region.py"]) == 0
