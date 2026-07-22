# Design: Pre-Releases im Updates-Tab (Opt-in)

> Stand 2026-07-22 · Branch `feat/prerelease-updates` · Ergebnis des
> Brainstormings zum Wunsch „Unter Updates auch Pre-Releases sehen und
> herunterladen können, Benachrichtigung nur nach expliziter Aktivierung".

## Problem

Pre-Releases (`vX.Y.Z-pre.N`, gebaut über `release.yml` mit gesetztem
`prerelease`-Input) sind für Nutzer der App heute unsichtbar:

- `updater.check_latest_release` fragt `/releases/latest` — GitHub liefert dort
  **nie** ein als Pre-Release markiertes Release. Das ist bewusst so gebaut
  (siehe `CLAUDE.md`, „Pre-Releases"), damit normale Nutzer keine Testbuilds
  angeboten bekommen.
- Wer plattformübergreifend testen soll (macOS/Linux, auf der Windows-Dev-
  Maschine nicht verifizierbar), muss den Build daher manuell auf GitHub
  suchen und herunterladen.

Zwei Eigenschaften des bestehenden Workflows prägen die Lösung:

1. **Pre-Releases bumpen die Version nicht.** Der Tag ist `v<VERSION>-pre.N`
   mit `VERSION` aus `src/version.py`; N zählt je Zielversion hoch. Real:
   `v1.18.2` wurde am 2026-07-16 getaggt, `v1.18.2-pre.1` am 2026-07-20 —
   der Pre-Release ist also **neuer** als das gleichnamige echte Release.
2. **Die App kennt ihre eigene Pre-Nummer nicht.** `build.py::generate_build_info`
   stempelt `CHANNEL`, `GIT_SHA`, `GIT_DIRTY`, `BUILD_TIME` — nicht den Tag.
   `version_label()` zeigt deshalb nur `1.18.2-pre` ohne N.

Dazu kommt ein Defekt, der beim Einschalten sofort zuschlägt: `is_newer`
rechnet `tuple(int(part) for part in version.split("."))` und wirft bei
`"1.18.2-pre.1"` ein `ValueError` (`int("2-pre")`).

## Ziele

- Optional (Default aus) auch Pre-Releases als Update anbieten: im
  Updates-Tab sichtbar, per Download-Button installierbar, und im
  Hintergrund-Check als Toast/Banner gemeldet.
- Ein Nutzer, der auf einem Pre-Build läuft, erkennt zuverlässig, ob es einen
  neueren Pre-Build gibt.
- Für Nutzer **ohne** Häkchen bleibt das Verhalten unverändert — gleiche
  Datenquelle, gleiche Texte, gleiche Netzlast.

## Nicht-Ziele

- Kein In-App-Update/Installer-Aufruf (Download öffnet weiterhin nur die URL).
- Kein Downgrade-Pfad („zurück auf das letzte echte Release").
- Der Kanal wird **nicht** über Drive synchronisiert.
- Keine Änderung an der Bump-Politik für Pre-Releases (weiterhin kein Bump).

## Getroffene Entscheidungen (aus dem Brainstorming)

1. **Ordnung statt Semver.** Ein Tag wird auf `(major, minor, patch, pre_rank)`
   abgebildet, wobei ein echtes Release `pre_rank = 0` bekommt und `-pre.N`
   den Rang `N`. Damit gilt `1.19.0 < 1.19.0-pre.1 < 1.19.0-pre.2 < 1.19.1`.
   Das ist die Umkehrung der Semver-Regel und entspricht der Praxis des Repos
   (Pre-Release entsteht **nach** dem gleichnamigen Release, aus neuerem Code).
2. **Die Annahme wird Prozess-Regel, nicht Code.** Würde ein Pre-Release
   künftig *vor* seinem echten Release gebaut (erst bumpen, dann Pre), böte die
   App nach dem echten Release weiter den älteren Pre an. Statt datumsbasierter
   Vergleichslogik wird die Reihenfolge in `CLAUDE.md` als Regel festgehalten.
3. **Zwei Fetch-Pfade.** Stable bleibt exakt bei `/releases/latest`. Nur mit
   Häkchen kommt ein Call auf `/releases?per_page=10` dazu. Begründung: für
   Nicht-Opt-in-Nutzer ändert sich weder Quelle noch Payload-Größe (bis zu 30
   volle Release-Objekte statt einem beim täglichen Hintergrund-Check).
4. **Build-Identität wird gestempelt.** `release.yml` reicht den in `pre-check`
   bereits berechneten Tag als `ZEIT_RELEASE_TAG` an die Build-Jobs,
   `build.py` schreibt ihn als `RELEASE_TAG` nach `build_info.py`. Fehlt er
   (Alt-Build, Dev-/Repo-Modus), gilt `VERSION` mit Rang 0 = heutiges Verhalten.
5. **Das Häkchen schaltet alles.** Ohne Häkchen verhält sich auch der
   Updates-Tab wie heute (nur echte Releases). Kein „sichtbar, aber stumm".
6. **Changelog eines Pre-Releases = GitHub-Release-Notes.** `CHANGELOG.md` am
   Pre-Tag enthält nur den Abschnitt der zuletzt veröffentlichten Version, also
   genau das, was der Nutzer schon hat. Stattdessen wird der `body` des
   Releases angezeigt (die von `--generate-notes` erzeugte PR-Liste seit dem
   letzten echten Release) — er kommt im Listen-Payload gratis mit, **kein**
   zusätzlicher Netzwerk-Call. Echte Releases bleiben bei `CHANGELOG.md`.
7. **Kanal ist gerätelokal.** `prerelease_updates_enabled` kommt nicht in
   `SYNCED_SETTING_KEYS` — wie alle Update-Keys. Der Rechner, auf dem getestet
   wird, soll die anderen Geräte nicht in den Pre-Kanal ziehen.

## Komponenten

### `src/settings.py`
Neuer Key in `DEFAULTS`, **nicht** in `SYNCED_SETTING_KEYS`:
- `prerelease_updates_enabled`: `bool`, Default `False`

### `src/updater.py` (Erweiterung)

`Release` bekommt zwei zusätzliche Felder; `version` behält seine Bedeutung
**Basisversion** (`1.19.0`), weil `pick_asset_url` daraus die Asset-Namen baut:

```python
@dataclass(frozen=True)
class Release:
    version: str            # Basisversion ohne v/-pre, z.B. "1.19.0"
    html_url: str
    assets: tuple[Asset, ...]
    release_id: str = ""    # volle Kennung ohne v: "1.19.0" | "1.19.0-pre.2"
    is_prerelease: bool = False
    notes: str = ""         # API-`body`; nur bei Pre-Releases angezeigt
```

Neue bzw. geänderte reine Funktionen (alle ohne Netzwerk testbar):

```python
def parse_release_id(release_id: str) -> tuple[int, int, int, int] | None
# "1.19.0" -> (1,19,0,0) | "1.19.0-pre.2" -> (1,19,0,2) | Müll -> None

def base_version(release_id: str) -> str
# "1.19.0-pre.2" -> "1.19.0"; ohne Suffix unverändert

def is_newer(current: str, latest: str) -> bool
# vergleicht über parse_release_id; nicht parsebar auf einer Seite -> False
# (heute: ValueError). Beide Argumente sind release_ids.

def release_from_payload(payload: dict) -> Release | None
# ein API-Release-Objekt -> Release; None bei fehlendem tag_name/html_url

def select_newest_payload(payloads: list[dict]) -> dict | None
# überspringt draft-Einträge und unparsebare Tags, wählt das Maximum nach
# parse_release_id
```

Netzwerk-Ebene:

```python
def check_latest_release(repo, timeout=5.0) -> Release | None
# unverändert: /releases/latest, jetzt über release_from_payload

def check_latest_release_any(repo, timeout=5.0) -> Release | None
# /releases?per_page=10 -> select_newest_payload -> release_from_payload

def check_for_update(repo, include_prereleases: bool, timeout=5.0) -> Release | None
# der eine Einstieg für beide Call-Sites (Tab + Hintergrund-Check)
```

Fehlerverhalten bleibt die bestehende Konvention: jeder Fehler (Netz, Timeout,
kaputtes JSON, unbekannte Struktur) → `None`, nie eine Exception nach außen.

`resolve_check_result(installed_id, release)` wird um den Pre-Fall erweitert:

| Fall | `status_text` | Download | Changelog |
|---|---|---|---|
| `release is None` | „Prüfung fehlgeschlagen — keine Verbindung?" | nein | — |
| nicht neuer | „Du hast die aktuelle Version (`installed_id`)." | nein | `changelog_version = base_version(installed_id)` |
| neuer, echtes Release | „Version X.Y.Z verfügbar" | ja | `changelog_version = release.version` |
| neuer, Pre-Release | „Vorabversion X.Y.Z-pre.N verfügbar" | ja | `changelog_notes = release.notes` |

`persist` schreibt `dismissed_version`/`update_toast_shown_version` künftig mit
`release.release_id` statt `release.version`, damit `pre.1 → pre.2` erneut
meldet. Altwerte (`"1.19.0"`) bleiben kompatibel — die Felder werden nur
verglichen, nie geparst.

`update_toast_text(release)` unterscheidet ebenfalls Release/Vorabversion.

### `src/version.py`

```python
RELEASE_TAG = getattr(_build_info, "RELEASE_TAG", "")  # z.B. "v1.19.0-pre.2"

def installed_release_id() -> str
# RELEASE_TAG ohne v-Prefix, wenn gesetzt und parsebar; sonst VERSION
```

`version_label()` zeigt im Pre-Kanal die volle Kennung (`1.19.0-pre.2`), fällt
ohne `RELEASE_TAG` auf das heutige `1.19.0-pre` zurück. Release-/Dev-/Source-
Kanal unverändert.

### `build.py` + `.github/workflows/release.yml`

- `generate_build_info()` liest `ZEIT_RELEASE_TAG` und schreibt
  `RELEASE_TAG = "..."` (leer, wenn nicht gesetzt). Docstring nachziehen: der
  Tag steht für Release-Läufe bereits vor dem Build fest (Job `pre-check`).
- Die drei Build-Jobs bekommen `ZEIT_RELEASE_TAG: ${{ needs.pre-check.outputs.tag }}`
  in ihren `env`-Block, neben den bestehenden `ZEIT_RELEASE`/`ZEIT_PRERELEASE`.

### `src/changelog.py` (Parser-Erweiterung)

`parse_changelog_markdown` versteht zusätzlich das Format der GitHub-Notes:
- `* `-Bullets werden wie `- `-Bullets behandelt,
- `## `-Überschriften (z.B. „What's Changed") werden wie `### ` zu `heading`
  gerendert. Die bestehende Sonderbehandlung „erste Zeile weglassen" trifft
  heute jedes `## `; sie wird auf Versions-Überschriften eingegrenzt (erste
  Zeile matcht `^##\s+\d+\.\d+\.\d+`), sonst verschluckt der Pre-Pfad die
  „What's Changed"-Zeile.
- Die abschließende Zeile `**Full Changelog**: <url>` bleibt normaler Text.

`fetch_changelog_entry` bleibt unverändert (nur für echte Releases benutzt).

### `src/dialogs/settings_dialog/tab_updates.py`

- Neue Checkbox unter der Frequenz-Zeile: „Auch Vorabversionen (Pre-Releases)
  anbieten", darunter gedämpft „Testbuilds vor dem echten Release — können
  Fehler enthalten." Variable `prerelease_var` wird für `save_settings`
  exponiert (wie `frequency_var`).
- `_check_now` liest **den aktuellen Checkbox-Zustand**, nicht den
  gespeicherten Wert — sonst wirkt das Häkchen erst nach Speichern und
  erneutem Öffnen des Dialogs.
- Statustext/Download/Changelog folgen `resolve_check_result`: Liefert das
  Ergebnis `changelog_notes`, wird der Text direkt gerendert; sonst wie bisher
  `_fetch_changelog(changelog_version)` im Worker.
- `_open_download` nutzt weiterhin `release.version` (Basisversion) für den
  Asset-Match — die Assets eines Pre-Releases heißen `Zeiterfassung-1.19.0-*`,
  `build.py` benennt sie unabhängig vom Kanal.

### `src/dialogs/settings_dialog/dialog.py`
`save_settings` schreibt zusätzlich
`"prerelease_updates_enabled": updates_tab.prerelease_var.get()`.

### `src/background_tasks.py`, `src/ui.py`, `src/update_banner.py`
- `check_update` ruft `check_for_update(REPO, settings.get("prerelease_updates_enabled"))`
  und vergleicht mit `installed_release_id()` statt `VERSION`.
- `_route_update_notification` und `UpdateBanner` vergleichen/persistieren
  `release.release_id` statt `release.version`; die angezeigten Texte
  unterscheiden Release und Vorabversion.

## Datenfluss

```
Hintergrund (BackgroundTaskRunner.run)          Updates-Tab („Jetzt prüfen")
  should_check(frequency)                         prerelease_var.get()
        │                                                │
        └────────► check_for_update(REPO, include) ◄─────┘
                          │
        include=False → /releases/latest
        include=True  → /releases?per_page=10 → select_newest_payload
                          │
                    release_from_payload → Release(release_id, is_prerelease, notes)
                          │
        is_newer(installed_release_id(), release.release_id)
                          │
        Hintergrund → Toast/Banner            Tab → resolve_check_result → Status,
        (release_id als „gesehen"-Merker)            Download-Button, Changelog
```

## Fehlerbehandlung

Unverändert die bestehende Linie: Update-Prüfung ist nice-to-have. Jeder Netz-
oder Parse-Fehler endet in `None` bzw. „Prüfung fehlgeschlagen"; ein Release mit
unparsebarem Tag wird still übersprungen statt die Auswahl zu sprengen. Kein
neuer Fehlerdialog.

## Tests (alle Tk-frei)

| Was | Wo |
|---|---|
| `parse_release_id`/`base_version`/`is_newer` inkl. Müll-Tags und der Ordnung `1.19.0 < 1.19.0-pre.1 < 1.19.1` | `tests/test_updater.py` |
| `select_newest_payload`: Mischung Pre/Real, Drafts, unparsebare Tags | `tests/test_updater.py` |
| `release_from_payload`: `release_id`, `version` (Basis), `is_prerelease`, `notes` | `tests/test_updater.py` |
| `resolve_check_result` für alle vier Fälle der Tabelle oben | `tests/test_updater.py` |
| `pick_asset_url` mit Pre-Release-Assets (Basisversion im Namen) | `tests/test_updater.py` |
| GitHub-Notes-Markdown (`* `-Bullets, `## `-Heading, Full-Changelog-Zeile) | `tests/test_changelog.py` |
| `installed_release_id`/`version_label` mit und ohne `RELEASE_TAG` | `tests/test_version_label.py` |
| Kanal-Auswahl im Hintergrund-Check (Flag steuert den Fetch-Pfad) | `tests/test_background_tasks.py` |
| Routing/Merker auf `release_id` (pre.1 → pre.2 meldet erneut) | `tests/test_ui_update_routing.py`, `tests/test_update_banner.py` |
| Neuer Settings-Key wird gespeichert | `tests/test_settings_dialog.py` |

Die `build.py`-Stempelung hat kein Test-Vorbild im Repo und wird über einen
echten Pre-Release-Lauf verifiziert (Titel zeigt `X.Y.Z-pre.N`).

## Doku im selben PR

- `CLAUDE.md`: Pre-Release-Abschnitt um die Ordnungs-Regel („ein Pre-Release
  wird immer nach dem gleichnamigen echten Release gebaut") und den
  `ZEIT_RELEASE_TAG`-Stempel ergänzen.
- `README.md`: Feature-Liste (Update-Check-Zeile) und Einstellungs-Tabelle.

## Akzeptierte Grenzen

- **Alt-Builds ohne `RELEASE_TAG`** (alles vor diesem Feature) melden sich als
  Basisversion. Ein bereits installierter `1.18.2-pre.1` bekäme deshalb einmalig
  jeden Pre dieser Basisversion angeboten — inklusive des eigenen. Betrifft nur
  bestehende Pre-Installationen und heilt mit dem nächsten Build.
- **Kanal abwählen bringt kein Downgrade.** Wer auf einem Pre läuft und das
  Häkchen entfernt, sieht erst beim nächsten höheren echten Release wieder ein
  Angebot.
- **Ein Pre-Nutzer bekommt das gleichnamige echte Release nicht angeboten** —
  nach der Ordnung ist sein Build neuer, und inhaltlich stimmt das.
- **`per_page=10`** deckt die neuesten zehn Releases ab; die Liste ist absteigend
  nach Erstellung sortiert, das Maximum liegt immer darin.
