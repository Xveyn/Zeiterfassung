# Datenschutzhinweise in der App Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** In Einstellungen → App öffnet ein Button „Datenschutzhinweise“ einen Dialog, der den Inhalt von `docs/datenschutz.md` ansehnlich im Stil der App zeigt (Überschriften, Absätze, Listen, fett, Code, anklickbare Links) — kein roher Markdown.

**Architecture:** Ein Tk-freier Parser (`src/privacy_doc.py`) macht aus dem Markdown anzeigefertige Blöcke und lädt die gebündelte Datei; ein Dialog (`src/dialogs/privacy_dialog.py`) rendert sie in ein `dark_text`-Widget mit Tags, nach dem Muster des Changelog-Felds im Updates-Tab (`changelog.parse_changelog_markdown`). Die Datei `docs/datenschutz.md` bleibt die **einzige** Quelle und wird per `--add-data` in den Build gebündelt; ein Test hält den Parser gegen die echte Datei (kein Markdown-Rest im Text), damit Doku-Änderungen die Anzeige nicht still verderben.

**Tech Stack:** Python 3.12, Tkinter, pytest, PyInstaller (`scripts/build.py`).

**Spec:** keine eigene Spec; Anforderung des Nutzers vom 2026-11-04 (Memory `datenschutz-dialog-nach-pr5`): Button „Datenschutzhinweise“ in Einstellungen → App, Dialog mit den Informationen aus `docs/datenschutz.md`, ansehnlich formatiert und im Stil der App. Vorbild im Code: `src/changelog.py::parse_changelog_markdown` und `src/dialogs/settings_dialog/tab_updates.py` (Text-Widget mit Tags), Dialog-Regeln: Wurzel-`CLAUDE.md` „Dialog-Styling“.

## Global Constraints

- Neue Dialoge entstehen über `theme.create_dialog(...)`; **wer `create_dialog` ruft, ruft `center_dialog_on_parent`** (`tests/test_dialog_reveal.py`). Keine dialogspezifischen Stil-Extras: nur vorhandene Fonts (`FONT`, `FONT_BOLD`, `FONT_HEADER_SMALL`), Farben (`TEXT`, `TEXT_MUTED`, `ACCENT`, `ENTRY_BG`, `CELL_BG`) und Fabriken (`dark_text`, `secondary_button`, `Form`).
- Pixelangaben nur über `theme.px()` (nie `wraplength=`/`length=` mit Zahl-Literal; `tests/test_pixel_scaling.py`); Breite des Text-Widgets in **Zeichen**.
- Tk-gebundener Code wird nicht automatisiert getestet: Verhalten gehört in den Tk-freien Parser und dort in Tests. Der Dialog bekommt Quelltext-Zusicherungen und einen manuellen Rauchtest mit Screenshot.
- Anzeige deutsch; Datum/Zahlen unverändert aus dem Dokument. Texte nie mit `innerHTML`-Äquivalent: das Text-Widget bekommt nur Klartext-Segmente.
- Links: nur `https://` (und `http://`) werden anklickbar und per `webbrowser.open` geöffnet (wie `tab_updates`); relative Verweise oder fremde Schemata erscheinen als normaler Text.
- Fehlerpfade nach der Konvention: erwartete Fehler (Datei fehlt) → kuratierter Ersatztext im selben Dialog, kein Traceback; Catch-all nur mit Begründung im Handler (`tests/test_catch_all_handlers.py`).
- Docstrings: das Warum und der Vertrag, keine Historie, höchstens acht Zeilen (Wurzel-`CLAUDE.md`).
- Commits enden mit `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`; Shell: kein `&&` in Befehlen an den Nutzer (PowerShell 5.1).
- Branch `feat/datenschutz-dialog` (von `master`, #429 gemerged). Push und PR als `Xveyn` (aktiver `gh`-Account kann Sven-MH sein: `GH_TOKEN="$(gh auth token --user Xveyn)"` nur für den Push- und den PR-Befehl).

## Entscheidungen, die der Plan trifft

- **Die Datei wird gebündelt, nicht kopiert.** `docs/datenschutz.md` geht per `--add-data docs/datenschutz.md<sep>docs` in den Build (eine Stelle: `_pyinstaller_common`, gilt für alle drei Plattformen); gelesen wird `Path(get_resource_path()) / "docs" / "datenschutz.md"`. Im Repo-Modus ist das Repo-Root. Ein zweiter Text im Code würde auseinanderlaufen.
- **Inhalt unverändert.** Das Dokument nennt auch Dateinamen und Bezeichner (`mobile_box.json`, `DELETE /v1/box`, `RELAY_PAIR_HINT`); sie erscheinen als Code-Auszeichnung (gedämpfte Farbe, hinterlegt), nicht entfernt. Wer das Dokument nutzerfreundlicher will, ändert die Quelle, nicht den Dialog.
- **Doku-Pfad, der die App verändert, ist keine Doku mehr.** Der `changes`-Job in `.github/workflows/test.yml` und der Absatz „Doku-only-PRs überspringen die Tests“ in der Wurzel-`CLAUDE.md` zählen `docs/**` als Doku. `docs/datenschutz.md` wird jetzt gebündelt **und** vom Parser-Test geprüft: ein PR, der nur diese Datei ändert, darf die Tests nicht überspringen. Der Job nimmt sie deshalb aus dem Doku-Muster aus.
- **Kein Neuladen zur Laufzeit, keine Übersetzung.** Der Dialog liest die Datei einmal beim Öffnen.
- **Platz im Tab:** neuer Abschnitt „Datenschutz“ nach „Daten“ (nicht in „Daten“ selbst: das Wort ist dort schon durch Dateien belegt).

## Review Focus

Eingaben und Zustände, die die Aufgabe nur andeutet; jede Zeile hat ihren Test im besitzenden Task.

1. **Datei fehlt oder ist unlesbar** (Build ohne `--add-data`, Datei gelöscht, Rechte): der Dialog öffnet trotzdem und zeigt einen kuratierten Hinweis mit dem Link auf das Dokument im Repository, nie einen Traceback und nie ein leeres Fenster (Task 1, 2).
2. **Markdown-Reste im Text:** `**`, Backticks, `](`, führende `## `/`- `/`> ` erscheinen in keinem angezeigten Text des echten Dokuments (Task 1).
3. **Unbekannte Konstruktion** (Tabelle, nummerierte Liste, Codeblock, HTML, verschachtelte Auszeichnung): wird als lesbarer Text gezeigt, nicht verschluckt und nicht als Fehler (Task 1).
4. **Links:** `https://…` klickbar; relativer Link, `javascript:`, `file:` und ein Link ohne Text bleiben normaler Text (Task 1, 2).
5. **Harte Zeilenumbrüche des Dokuments** (Fortsetzungszeilen, 120 Spalten) erscheinen als ein Absatz, den das Widget selbst umbricht (Task 1).
6. **Skalierung 150/200 %:** Breite in Zeichen, Dialog passt auf den Bildschirm (Task 2, manuell).
7. **Doku-only-PR auf `docs/datenschutz.md`** läuft die Tests (Task 3).

---

### Task 1: Parser und Loader `src/privacy_doc.py`

**Files:**
- Create: `src/privacy_doc.py`
- Test: `tests/test_privacy_doc.py`

**Interfaces:**
- Produces:
  - `parse_privacy_markdown(text: str) -> list[Block]` mit `Block = {"kind": str, "segments": list[Segment], "level": int}`; `Segment = {"text": str, "style": "plain" | "bold" | "code" | "link", "url": str | None}`. `kind` ist `title` (`# `), `heading` (`## `), `quote` (`> `), `paragraph`, `bullet`; `level` ist die Einrückungstiefe eines Bullets (0 = oberste Ebene, 1 = eingerückt), sonst 0. Leerzeilen trennen Blöcke; Fortsetzungszeilen eines Absatzes, Zitats oder Bullets werden mit einem Leerzeichen zu **einem** Block zusammengeführt. Die Reihenfolge der Blöcke ist die des Dokuments.
  - `parse_inline(text: str) -> list[Segment]`: `**fett**`, `` `code` ``, `[Text](url)`; ein Link ist nur dann `style: "link"` mit `url`, wenn die URL mit `https://` oder `http://` beginnt und der Text nicht leer ist, sonst erscheint er als `plain` mit dem Linktext (ohne die URL). Nicht geschlossene Auszeichnung bleibt als `plain` stehen (kein Wegwerfen von Text).
  - `is_web_url(url: object) -> bool`: wahr nur für Text, der mit `https://` oder `http://` beginnt (Schema ohne Rücksicht auf Groß-/Kleinschreibung); `parse_inline` und der Dialog entscheiden Links ausschließlich darüber.
  - `plain_text(blocks: list[Block]) -> str`: alle Segmente je Block verkettet, Blöcke mit `\n` getrennt (für Tests und Fallback).
  - `PRIVACY_DOC_RELATIVE = ("docs", "datenschutz.md")`, `PRIVACY_DOC_URL: str` (die Datei auf GitHub, `https://github.com/Xveyn/Zeiterfassung/blob/master/docs/datenschutz.md`), `load_privacy_doc(resource_dir: str) -> str | None`: liest die Datei UTF-8 und liefert den Text, bei `FileNotFoundError`/`OSError`/`UnicodeDecodeError` `None` und loggt einen Hinweis (`log.warning`, nur Typ der Ausnahme, kein Pfad aus Nutzereingaben nötig).
  - `FALLBACK_TEXT: str`: kuratierter Ersatztext („Die Datenschutzhinweise konnten nicht geladen werden. Sie stehen im Projekt unter …“) und `fallback_blocks() -> list[Block]` mit genau einem Absatz (Text) und einem Link-Segment auf `PRIVACY_DOC_URL`.

- [ ] **Step 1: Failing tests** in `tests/test_privacy_doc.py` (Namen, Kernzusicherungen):
  - `test_headings_and_title_are_recognised`: `# T`, `## 1. A` → Blöcke `title`, `heading` mit Text ohne Markierung.
  - `test_wrapped_lines_become_one_paragraph`: zwei Zeilen → ein `paragraph` mit einem Leerzeichen dazwischen; Leerzeile trennt zwei Absätze.
  - `test_bullets_and_nested_bullets_keep_their_level_and_join_continuations`: `- a`, Fortsetzung, `  - b` → `bullet` Ebene 0 mit zusammengeführtem Text, `bullet` Ebene 1.
  - `test_blockquote_is_a_quote_block`.
  - `test_inline_bold_code_and_link_become_styled_segments`: `**a** und `b` und [c](https://x.example/y)` → `bold`, `code`, `link` mit `url`.
  - `test_links_without_http_scheme_or_text_stay_plain`: `[x](docs/a.md)`, `[x](javascript:alert(1))`, `[x](file:///c:/a)`, `[](https://x.example)` → kein `link`-Segment, Text bleibt (ohne URL).
  - `test_unclosed_markup_is_kept_as_text`: `**offen`, `` `offen ``, `[offen](` → alles bleibt sichtbarer `plain`-Text.
  - `test_unknown_constructs_are_shown_as_plain_text`: Tabellenzeile `| a | b |`, `1. eins`, ```` ``` ````-Zeile, `<b>x</b>` → je ein `paragraph` mit dem Zeilentext, kein Fehler.
  - `test_the_real_document_has_no_markdown_left_over`: lade `docs/datenschutz.md` aus dem Repo, parse; in **keinem** Segmenttext `**`, `` ` ``, `](`, und kein Block-Text beginnt mit `## `, `# `, `- `, `> `; es gibt genau einen `title` und mindestens zehn `heading`; `plain_text` enthält „keine Rechtsberatung“ und „Aufbewahrung im Leerlauf: 90 Tage“ (die Zahl prüft `test_datenschutz_claims` bereits gegen den Relay).
  - `test_every_link_of_the_real_document_is_https`: alle `link`-Segmente haben `https://`-URLs; kein `plain`-Segment enthält `](`.
  - `test_is_web_url_truth_table`: `https://x.example`, `http://x.example`, `HTTPS://x.example` wahr; `javascript:alert(1)`, `file:///c:/a`, `docs/a.md`, `ftp://x`, `` (leer), `None`, `5` falsch.
  - `test_load_returns_the_text_and_none_when_missing`: `load_privacy_doc(<Repo-Root>)` liefert Text mit `# Datenschutz`; `load_privacy_doc(<leeres tmp>)` liefert `None`, wirft nie; ein Verzeichnis statt Datei und eine nicht UTF-8-lesbare Datei (`b"\xff\xfe"`) liefern `None`.
  - `test_the_fallback_names_the_document_and_links_to_it`: `fallback_blocks()` enthält einen `link` mit `PRIVACY_DOC_URL`.
- [ ] **Step 2:** `python -m pytest tests/test_privacy_doc.py -q` → FAIL (Modul fehlt).
- [ ] **Step 3: Implementieren** gemäß Signaturen: zeilenweise Zustandsmaschine (wie `parse_changelog_markdown`), Inline-Auszeichnung per einem kleinen Scanner (kein verschachteltes Markdown; `**` und Backtick-Code zuerst, Links über `[text](url)`), HTML-Kommentare entfernen. Eigenes `log = logging.getLogger(__name__)`.
- [ ] **Step 4:** `python -m pytest tests/test_privacy_doc.py -q` → grün; `python -m ruff check src tests`, `npx pyright src/privacy_doc.py`.
- [ ] **Step 5: Commit** — `feat(privacy): Parser und Loader fuer die Datenschutzhinweise (Refs #358)`.

---

### Task 2: Dialog und Button

**Files:**
- Create: `src/dialogs/privacy_dialog.py`
- Modify: `src/dialogs/settings_dialog/tab_app.py` (neuer Abschnitt nach „Daten“)
- Test: `tests/test_privacy_dialog_wiring.py`

**Interfaces:**
- Consumes: `privacy_doc.parse_privacy_markdown`, `load_privacy_doc`, `fallback_blocks`, `paths.get_resource_path`, `theme.create_dialog`, `center_dialog_on_parent`, `dark_text`, `apply_combobox_style` (stylt `Vertical.TScrollbar`), `secondary_button`, `px`, Fonts/Farben (s. Global Constraints), `webbrowser.open`.
- Produces: `open_privacy_dialog(parent) -> None` (modal). Aufbau: Text-Widget (Breite 78 Zeichen, Höhe 26 Zeilen) mit `ttk.Scrollbar` (`style="Vertical.TScrollbar"`), „Schließen“ unten. Tags: `title` (`FONT_HEADER_SMALL`), `heading` (`FONT_BOLD`, Abstand davor), `bold` (`FONT_BOLD`), `code` (Vordergrund `TEXT_MUTED`, Hintergrund `ENTRY_BG`), `link` (`ACCENT`, unterstrichen, Cursor `hand2`), `quote` (`TEXT_MUTED`, eingerückt), `bullet0`/`bullet1` (hängender Einzug, `•`/`–` voran). Das Widget ist schreibgeschützt (`state=disabled`), Auswahl und Kopieren bleiben möglich. Jeder Link bekommt ein eigenes Tag mit `<Button-1>`-Bindung → `webbrowser.open(url)` in `try/except` mit Begründung (Browser-Start darf nie den Dialog beenden; Fehler per `log.warning`).
- `tab_app.AppTab.__init__`: nach dem Abschnitt „Daten“ `form.section("Datenschutz")`, `form.buttons(("Datenschutzhinweise", self._open_privacy))`, `form.hint("Was die Handy-Erfassung über den Relay weitergibt und wo es liegt.")`; `_open_privacy` importiert `open_privacy_dialog` **lazy** (wie `_open_import_dialog`) und ruft ihn mit `self._parent`.
- Ladefehler: fehlt die Datei, zeigt derselbe Dialog `fallback_blocks()` (Review Focus 1).

- [ ] **Step 1: Failing tests** `tests/test_privacy_dialog_wiring.py` (Quelltext/AST, kein Tk):
  - `test_tab_app_has_the_privacy_button_in_its_own_section`: `tab_app.py` enthält `form.section("Datenschutz")`, den Button-Text „Datenschutzhinweise“ und ruft `open_privacy_dialog` nur über einen lazy Import innerhalb einer Methode (kein Import auf Modulebene).
  - `test_the_privacy_dialog_pairs_create_dialog_with_center_dialog_on_parent` — deckt bereits `tests/test_dialog_reveal.py` ab; hier zusätzlich: `privacy_dialog.py` importiert `webbrowser` und öffnet nur über eine Funktion, die URLs mit `https://`/`http://` prüft (AST: jeder `webbrowser.open`-Aufruf steht in einer Funktion, die `startswith(("https://", "http://"))` oder `privacy_doc.is_web_url` verwendet).
  - `test_the_privacy_dialog_loads_through_the_resource_path_and_falls_back`: `privacy_dialog.py` ruft `get_resource_path`, `load_privacy_doc` und `fallback_blocks`.
- [ ] **Step 2:** `python -m pytest tests/test_privacy_dialog_wiring.py tests/test_privacy_doc.py -q` → FAIL.
- [ ] **Step 3: Implementieren** `privacy_dialog.py` und die Änderung in `tab_app.py` gemäß Interfaces; Link-Klicks gehen nur durch `privacy_doc.is_web_url`. Der Dialog rendert die Blöcke einmal; `apply_combobox_style(dialog)` vor dem Scrollbalken (Muster `import_dialog`).
- [ ] **Step 4:** `python -m pytest -q -k "privacy or dialog_reveal or pixel_scaling or catch_all or type_annotations"`, `python -m ruff check src tests`, `npx pyright src/dialogs src/privacy_doc.py` → grün.
- [ ] **Step 5: Manueller Rauchtest** (Tk ist nicht automatisiert getestet): Scratchpad-Skript wie in PR 3c/5: `Tk()`, `init_fonts(root, 1.0)` (dann 1.5 und 2.0), `open_privacy_dialog(root)` mit `root.after`-Hook, der den Text des Widgets liest, die Tags zählt (Überschriften, Links), einen Link-Klick mit ersetztem `webbrowser.open` auslöst und das Fenster per `ImageGrab` fotografiert; zusätzlich ein Lauf mit `get_resource_path` auf ein leeres Verzeichnis (Fallback). Screenshot dem Nutzer zeigen.
- [ ] **Step 6: Commit** — `feat(privacy): Dialog Datenschutzhinweise unter Einstellungen - App (Refs #358)`.

---

### Task 3: Build, CI-Muster, Doku

**Files:**
- Modify: `scripts/build.py` (`_pyinstaller_common`: zweites `--add-data`)
- Modify: `.github/workflows/test.yml` (`changes`-Job: `docs/datenschutz.md` ist Code)
- Modify: `CLAUDE.md` (Abschnitt „Doku-only-PRs“; Struktur: `src/privacy_doc.py`, `src/dialogs/privacy_dialog.py`), `src/CLAUDE.md` (Abschnitt „Dialoge“ ein Satz), `docs/datenschutz.md` (Kopf: „… ist die Quelle für den Dialog Einstellungen → App → Datenschutzhinweise“)
- Test: `tests/test_build.py`, `tests/test_claude_md_claims.py` (läuft mit), ein neuer Test für das CI-Muster

**Interfaces:** keine neuen.

- [ ] **Step 1: Failing tests:**
  - `tests/test_build.py::test_all_platforms_bundle_the_privacy_document`: für Windows, macOS und Linux enthält der Befehl (`_pyinstaller_common`-Ergebnis, nach dem Muster der anderen Tests dort) ein `--add-data` mit `docs/datenschutz.md` und Ziel `docs`; Trenner `os.pathsep`.
  - `tests/test_ci_doc_patterns.py` (neu): liest `.github/workflows/test.yml`, extrahiert das `grep -qvE '…'`-Muster des `changes`-Jobs und prüft mit `re`: reine Doku wie `README.md`, `docs/known-limitations.md`, `docs/superpowers/plans/x.md`, `.superpowers/x`, `LICENSE` ⇒ **Doku** (Muster passt); `docs/datenschutz.md` ⇒ **Code** (Muster passt nicht); `src/privacy_doc.py` ⇒ Code. Schlägt der Parser des Tests fehl (Muster nicht gefunden), ist der Test **rot**, nicht grün (Muster wie `test_claude_md_claims`).
- [ ] **Step 2:** `python -m pytest tests/test_build.py tests/test_ci_doc_patterns.py -q -k "privacy or doc_patterns"` → FAIL.
- [ ] **Step 3: Implementieren.** `_pyinstaller_common`: `"--add-data", f"docs{os.sep}datenschutz.md{os.pathsep}docs"` (neben `assets`); Workflow-Muster: `grep -qvE '(^|/)[^/]+\.md$|^docs/|…'` so ändern, dass `docs/datenschutz.md` nicht als Doku zählt (z. B. Vorfilter `grep -vx 'docs/datenschutz.md'` auf die Dateiliste, mit Kommentar im Job, **warum**: die Datei wird gebündelt und vom Parser-Test geprüft); die Wurzel-`CLAUDE.md`-Regel „Als Dokumentation gilt …“ um die Ausnahme ergänzen.
- [ ] **Step 4: Gesamtlauf** — `python -m pytest -q` (lokal bekannt rot: `test_report_pdf_layout`), `python -m ruff check .`, `python -m pytest tests/test_claude_md_claims.py tests/test_datenschutz_claims.py -q`. **Gebauter Test:** `python scripts/build.py` lokal (Windows, ohne Inno ok) und prüfen, dass `dist\Zeiterfassung\_internal\docs\datenschutz.md` existiert; die gebaute Exe starten (Datenordner per `ZEITERFASSUNG_DATA_DIR` auf ein leeres Verzeichnis), Einstellungen → App → „Datenschutzhinweise“ öffnen, Screenshot. (Die Frozen-Prüfung ist der eigentliche Beleg für `--add-data`.)
- [ ] **Step 5: Commit, Push, PR** — `feat(privacy): Datenschutzhinweise als Dialog in den Einstellungen (Refs #358)`; PR-Text: was der Nutzer sieht (Screenshot beschreiben), dass die Datei gebündelt wird, die CI-Muster-Änderung samt Begründung, nicht geprüft: Linux/macOS (gebündelte Datei im AppImage/DMG; ein Pre-Release zeigt es), Skalierung 175 %.

---

## Self-Review

- **Anforderung → Task:** Button in Einstellungen → App (Task 2), Dialog mit Inhalt aus `datenschutz.md` (Task 1 Parser, Task 2 Anzeige, Task 3 Bündelung), „ansehnlich formatiert und im App-Stil“ (Task 2: vorhandene Fonts/Farben, Tags, klickbare Links), Absicherung mit Tests (Task 1 und 3: Parser, Echt-Dokument-Wächter, Build, CI-Muster; Task 2: Quelltext-Zusicherungen, `test_dialog_reveal`; Tk selbst manuell wie im Projekt üblich).
- **Typkonsistenz:** `Block`/`Segment` und `is_web_url` entstehen in Task 1 (`privacy_doc.py`) und werden in Task 2 vom Dialog gerendert bzw. für Link-Klicks benutzt.
- **Proportion:** Der Plan beschreibt Signaturen, Tag-Namen, Testfälle und Muster, keine Rümpfe.
- **Offen für den Implementierer:** (1) ob das `grep`-Muster im `changes`-Job mit einem Vorfilter oder einem Negativ-Lookahead sauber auszudrücken ist (`grep -E` kennt kein Lookahead: Vorfilter); (2) die genaue Form des `--add-data`-Pfads unter Windows (`docs\datenschutz.md;docs`) — der gebaute Test in Task 3 Step 4 entscheidet; (3) ob 78 Zeichen Breite bei 100 % in den Dialog der Einstellungen passen, ohne zu verbreitern (Dialog ist ein eigenes Toplevel, nicht der Tab).
