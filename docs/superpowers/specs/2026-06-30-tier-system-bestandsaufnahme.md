# Tier-System — Bestandsaufnahme im Repo

> Abgleich des Konzepts „Tier-System" (Tier 0 = überall garantierter Kern,
> Tier 1 = strukturell nicht überall gleich gut machbarer Komfort, zentrale
> Capability-Prüfung, lautloses Fehlen) gegen den aktuellen Stand des Codes.
> Noch nicht committet — reine Findings, keine Entscheidung.

## Kurzfazit

`src/tray.py` + `src/tray_mac.py` sind bereits eine fast 1:1-Implementierung
des Tier-Modells — nur ohne den Begriff zu verwenden. Das ist die einzige
Stelle im Code, die strukturell wirklich „Tier 0 überall / Tier 1 wo möglich"
ist. Die referenzierte `notifications-plattform-modell.md` **existiert noch
nicht im Repo** — vermutlich der nächste Schritt, dieses Konzept für die
Toast-Notifications konkret auszuformulieren.

Daneben gibt es im Code mehrere **Drei-Wege-Plattform-Dispatches**
(`autostart.py`, `platform_open.py`, `paths.py`, `build.py::main`), die auf
den ersten Blick ähnlich aussehen, aber **keine Tiers** sind: Jede Plattform
hat dort eine gleichwertige, nicht-optionale eigene Umsetzung — fällt eine
weg, ist die Funktion auf dieser Plattform schlicht kaputt, nicht „nur ohne
Komfort". Das Konzept-Dokument sollte diese Abgrenzung (Tiering vs. reines
Plattform-Routing) explizit machen, sonst verwässert der Begriff.

## 1. `src/tray.py` / `src/tray_mac.py` — sauberster bestehender Fit

- **Zentrale Capability-Prüfung existiert bereits**, exakt wie in Regel 3
  gefordert: `is_supported()` (`tray.py:25-37`):
  Windows → `True`, macOS → nur mit Opt-in (`_macos_tray_opt_in()`,
  `ZEIT_MACOS_TRAY=1`), Linux → `False`. Aufrufer fragen das einmal ab,
  statt Plattform-Checks zu verteilen.
- **Tier 0 / Tier 1 lassen sich sauber zuordnen**, wenn man „Tier 0" nicht
  als „Tray-Icon" liest, sondern als „normales Fensterverhalten ohne
  Tray-Komfort" (funktioniert überall trivial, da reines Tk-Standardverhalten)
  und „Tier 1" als „Minimize-to-Tray + Toast-Notification" (Windows: voll;
  macOS: hinter Opt-in/Gate; Linux: nie). Damit erfüllt das Feature genau das
  Eignungskriterium aus dem Konzept-Dokument: Kernnutzen (normal nutzbares
  Fenster) überall ohne Sonderaufwand, Komfort-Zugewinn (Tray) strukturell
  teurer/unmöglich auf mind. einer Plattform, Komfort optional.
- **Rule 1 (Tier 0 hängt nie von Tier 1 ab)** ist erfüllt: `TrayIcon.start()`
  wirft bei fehlendem Backend `RuntimeError("Tray auf dieser Plattform nicht
  unterstützt")`, was vom Aufrufer abgefangen wird — die App läuft ohne Tray
  unverändert weiter.
- **Rule 3 (fehlendes Tier 1 ist kein Fehler)** ist für `notify()` wörtlich
  umgesetzt, nur eigenständig formuliert statt mit „Tier" benannt:
  `tray_mac.py` Kommentar zu `notify()` (Z. 120-137): „best-effort … ALLE
  Fehler geschluckt — Toast ist kosmetisch, Sync bleibt unberührt." Genau die
  im Konzept beschriebene Semantik.
- **Notifications sind strukturell an Tray gekoppelt**, nicht eigenständig:
  Jeglicher Toast läuft ausschließlich über `TrayIcon.notify()` /
  `MacTrayBackend.notify()` (`sync_orchestrator.py:95-96,195-196`,
  `ui.py:69-71,351`). Es gibt **kein** eigenständiges Notification-Modul. Für
  die geplante `notifications-plattform-modell.md` heißt das: Notifications
  selbst haben kein eigenes Tier-0-Äquivalent — ihr „Tier 0" ist schlicht
  „nichts passiert, kein Fehler" (Rule 3 trivial erfüllt), ihr ganzes
  Bestehen ist Tier-1-Komfort obendrauf auf dem Tray-Tier-1.
- **Wichtiger Punkt für die Doku**: Die drei Plattformen liegen nicht auf
  einer binären Tier-0/Tier-1-Linie, sondern dreistufig — Windows (voll),
  macOS (gated, vor Default-Aktivierung), Linux (nie). Das Modell beschreibt
  offiziell nur zwei Stufen; der macOS-Zwischenzustand „gated bis Gate
  besteht" ist ein **Rollout-Mechanismus für die Einführung von Tier 1**, kein
  dauerhafter dritter Tier — siehe Abschnitt 3.

## 2. Drei-Wege-Dispatches ohne Tiering (zur Abgrenzung relevant)

Diese Stellen sehen wie Plattform-Splits aus, sind aber laut den drei Regeln
**keine** Tier-System-Fälle — jede Plattform-Variante ist für sich
nicht-optionaler Kern, nicht „Komfort obendrauf":

| Stelle | Was passiert | Warum kein Tiering |
|---|---|---|
| `src/autostart.py:62-82` | Windows-Shortcut / macOS-LaunchAgent / Linux `.desktop`, je `subprocess.run(check=True)` | Jede Variante ist gleichwertig erforderlich; Fehler wird **nicht** geschluckt (`CalledProcessError` propagiert), unbekannte Plattform → `RuntimeError`. Kein „Kern überall, Rest optional". |
| `src/platform_open.py:15-23` | `os.startfile` / `open` / `xdg-open` | Docstring sagt explizit: Fehler wird **propagiert**, nicht abgefangen. Reines Routing. |
| `src/paths.py:30-44` | Datenverzeichnis je OS | Alle drei Zweige sind zwingend (App braucht ein Datenverzeichnis), kein „ohne Tier 1 geht's auch". |
| `build.py:265-273` (`main()`) | PyInstaller-Aufruf je OS | Jede Plattform baut ihr eigenes natives Artefakt — kein Kern/Komfort-Verhältnis zwischen den dreien. |
| `src/theme.py:10-16` | Font-Familie je OS | Rein kosmetisches Routing, keine „fehlt lautlos"-Semantik nötig, da immer ein Wert zurückkommt. |

→ Vorschlag fürs Konzept-Dokument: einen Abgrenzungspunkt „Kein reines
Plattform-Routing" ergänzen (analog zu „Kein Feature-Flag" / „Kein Graceful
Degradation"), der genau diese Fälle ausschließt. Sonst wird jeder
`platform.system()`-Dispatch im Code fälschlich als „Tier-System" gelesen.

## 3. Bereits Tier-1-förmige Stellen, aber **ohne** zentrale Capability-Prüfung

Diese existieren im Code, verstoßen aber (nur) gegen Regel 3 zweiter Satz
(„Aufrufer fragen [die Prüfung] einmal ab, statt Plattform-Checks im Code zu
verteilen") — Kandidaten, falls das Tier-System auf weitere Bereiche
ausgerollt wird:

- `src/theme.py` Z. 374, 562, 596, 663 — vier Windows-only UI-Polish-Zweige
  (Multi-Monitor-Workarea via ctypes, App-Icon, dunkle Titelleiste,
  deaktivierte Min/Max-Buttons). Jeweils inline `platform.system() ==
  "Windows"` statt einer zentralen Prüfung; andere Plattformen `return`n
  früh, kein Fehler — Verhalten ist also bereits Tier-1-konform, nur nicht
  über eine gemeinsame Capability-Funktion gebündelt.
- `src/grid_renderer.py:400-402` — macOS-only Lösch-✕ auf der Tageszelle
  (Workaround für unzuverlässigen Rechtsklick auf macOS, siehe
  `CLAUDE.md`-Abschnitt „Plattform-Ausnahme macOS"). Gleiches Muster:
  inline-Check statt zentraler Prüfung.
- `build.py` — Pack-Tool-Verfügbarkeit (Inno Setup `_find_inno_compiler()`
  Z. 97-109, `create-dmg` Z. 156-158, `appimagetool` Z. 184-186): fehlt das
  Tool, wird der Pack-Schritt übersprungen, gewarnt, der PyInstaller-Build
  läuft trotzdem durch — **schon heute** ein „fehlendes Tier 1 ist kein
  Fehler"-Verhalten, aber dreimal separat dupliziert statt über eine
  gemeinsame Prüfung.

## 4. Bezug zum macOS-Tray-Rollout (`docs/superpowers/specs/2026-06-30-macos-native-tray-design.md`)

Das Spec-Dokument beschreibt unabhängig vom Tier-Konzept ein eigenes,
ähnliches, aber **zeitlich begrenztes** Vokabular: „dormant" / Opt-in via
`ZEIT_MACOS_TRAY=1` / manuelles „Mac-Gate" (siehe Issue #96) / anschließender
Flip-PR, der `is_supported()` auf macOS unconditional `True` setzt (Z. 34-43,
252-268 im Spec, identisch im Plan-Dokument).

Das ist **kein** Dauerzustand des Tier-Modells, sondern ein
Einführungs-/Risiko-Staging-Mechanismus für eine neue Tier-1-Fähigkeit, die
sich nicht in CI verifizieren lässt (AppKit-Exceptions, nur auf echtem Mac
feststellbar — der Auslöser für den separaten Pre-Release-Workflow-Issue
#99). Nach bestandenem Gate verschwindet der „dormant"-Zwischenzustand
wieder, und macOS steht gleichwertig neben Windows als Tier-1-Plattform da.

→ Für das Tier-System-Dokument relevant: Falls es einen Abschnitt zu
„Einführung neuer Tier-1-Fähigkeiten" bekommt, ist dieses Rollout-Muster
(Opt-in-Flag → manuelle Verifikation → Default-Flip) ein direkt
wiederverwendbares, bereits bewährtes Vorgehen — aber als eigener,
ergänzender Baustein, nicht Teil der Drei-Regeln selbst.

## Referenzen

- `src/tray.py` (`is_supported()` Z. 25-37, `_select_backend` Z. 64-72,
  `start()` Z. 268-274)
- `src/tray_mac.py` (`notify()` Z. 120-137, `_safe()` Z. 22-29)
- `src/autostart.py`, `src/platform_open.py`, `src/paths.py`, `build.py`,
  `src/theme.py`, `src/grid_renderer.py`
- `docs/superpowers/specs/2026-06-30-macos-native-tray-design.md`
- Issue #96 (manuelles macOS-Gate), Issue #99 (Pre-Release-Workflow als
  praktischer Enabler für genau dieses Gate)
