# Google-Tab: gewährte OAuth-Scopes sichtbar machen

**Datum:** 2026-07-27
**Issue:** [#120](https://github.com/margenheld/Zeiterfassung/issues/120)
**Status:** entworfen, freigegeben

## Problem

Die App fordert je nach aktiven Features unterschiedliche OAuth-Scopes an
(`mail.get_scopes`): Kern immer, Drive und Kalender nur bei eingeschaltetem
Toggle. Was das Google-Konto der App **tatsächlich gewährt hat**, steht nur im
lokalen `token.json` oder in der Google Cloud Console — in der App selbst ist es
nirgends sichtbar.

Die Information liegt im Code bereits vor: `oauth_utils.discard_token_for_scope_upgrade`
liest die gewährten Scopes aus, um bei Lücken einen Re-Consent zu erzwingen. Sie
wird nur nie angezeigt.

## Entscheidungen

| Frage | Entscheidung | Grund |
|---|---|---|
| Anzeige oder auch Widerruf? | **Nur Anzeige** (read-only) | Widerruf hieße: Token verwerfen und mit reduziertem Set neu anfordern — eigener Feature-Brocken mit Bestätigung, OAuth-Worker und Fehlerpfaden, der sich zudem mit den vorhandenen Feature-Toggles überschneidet. |
| Klartext oder technische Scope-URLs? | **Beides** — Klartext-Label, darunter der technische Scope | Die Labels sind für Nicht-Techniker verständlich, die URL braucht, wer in der Cloud Console abgleicht. |
| Ungenutzte, aber gewährte Scopes? | **Eigener Zustand** | Wer den Sync abschaltet, behält die Drive-Berechtigung im Token. Genau diese Diskrepanz sichtbar zu machen ist der Zweck des Features. |
| Inline im Tab oder eigenes Modal? | **Modal hinter einem Button** | Gemessen (echte Tk-Widgets): Google-Tab heute **480 px**, die Liste inline **+156 px** (+32 %). Der Notebook zwingt alle Tabs auf die Höhe des größten — und der Google-Tab ist bereits der größte. Ein Button kostet ~30 px. |

## UI

### Google-Tab

Eine Zeile unter „Absender", noch unter dem Subheader „Google-Konto":
`Berechtigungen: [Anzeigen]`. Sonst ändert sich am Tab nichts; die nachfolgenden
Zeilen laufen ohnehin über die fortlaufende `next_google_row`.

**Nachtrag (nach der ersten Sichtung ergänzt):** Neben dem Button steht ein
Statustext in derselben Sprache wie die `credentials.json`-Zeile darüber —
„n von m Berechtigungen" mit ✓ / ○ / ✗ aus `mail.scope_summary`:

| Zeichen | Zustand | Bedeutung |
|---|---|---|
| ✓ grün | `ok` | alles Gebrauchte gewährt |
| ○ gedämpft | `partial` | Kern da, eine zuschaltbare Funktion wartet auf ihren Scope |
| ✗ rot | `core_missing` | ein Kern-Scope fehlt — auch der reine Mail-Versand geht nicht |

Ohne verwertbares Token: „✗ nicht angemeldet" bzw. „✗ Berechtigungen nicht lesbar".

Der Nenner zählt nur die **gebrauchten** Scopes: gewährte, aber ungenutzte
(Funktion abgeschaltet) und unbekannte Extras gehören nicht hinein — sie fehlen
ja nicht, und ein Nenner, der mit jeder Altlast wächst, wäre keine Aussage über
die Funktionsfähigkeit. Aktuell gehalten wird die Zeile vom **vorhandenen**
500-ms-Poll der `credentials.json`-Zeile, mit mtime/size-Cache auf `token.json`:
kein zweiter Timer, und sie zieht sowohl nach einem Re-Consent als auch nach dem
Umlegen der Sync-/Kalender-Schalter nach.

### Modal (`src/dialogs/scopes_dialog.py`)

Aufgebaut über `theme.create_dialog(parent, "Berechtigungen", …)` plus
`center_dialog_on_parent` nach dem Widget-Aufbau — Projektkonvention, keine
handgebaute `Toplevel`-Boilerplate, keine dialogspezifischen Stil-Extras.

```
Berechtigungen des Google-Kontos

  ✓ E-Mail senden
      https://www.googleapis.com/auth/gmail.send
  ✓ Eigene E-Mail-Adresse lesen
      https://www.googleapis.com/auth/userinfo.email
  ✓ Google Drive: App-Datenordner
      https://www.googleapis.com/auth/drive.appdata
  ○ Google Kalender: Termine lesen und schreiben
      https://www.googleapis.com/auth/calendar.events
  ○ Google Kalender: Kalenderliste lesen
      https://www.googleapis.com/auth/calendar.calendarlist.readonly

  ✓ gewährt und genutzt   ○ gewährt, zurzeit ungenutzt   ✗ fehlt, wird neu angefragt
                                                              [ Schließen ]
```

Das Modal liest `token.json` **beim Öffnen**. Damit ist es per Konstruktion immer
frisch, egal welcher Pfad vorher einen Re-Consent ausgelöst hat — kein Poll, kein
Timer, keine Invalidierung.

## Zustandslogik

Zwei Quellen: die im Token gewährten Scopes und das, was `mail.get_scopes(sync_enabled,
gcal_enabled)` für die **aktuellen** Einstellungen braucht.

| Zeichen | Bedingung | Bedeutung |
|---|---|---|
| ✓ | gewährt ∧ gebraucht | aktiv genutzt |
| ○ | gewährt ∧ ¬gebraucht | Berechtigung liegt weiter im Token, Funktion ist aus |
| ✗ | ¬gewährt ∧ gebraucht | Lücke; der nächste Zugriff erzwingt über `discard_token_for_scope_upgrade` einen frischen Consent |

Ein Scope, der weder gewährt noch gebraucht ist, wird **nicht** gezeigt — sonst
stünde die Liste voll mit Zeug, das den Nutzer nichts angeht (z.B. Kalender-Scopes
bei jemandem, der die Funktion nie einschaltet).

### Sonderfälle

- **Kein `token.json`** → statt der Liste eine Zeile „Noch nicht angemeldet — es sind
  keine Berechtigungen gewährt."
- **`token.json` unlesbar/kaputt** → „Berechtigungen nicht lesbar." Konservativ wie
  `discard_token_for_scope_upgrade`, das bei Lesefehlern ebenfalls nichts unterstellt
  (und den Token unangetastet lässt).
- **Unbekannte Scopes im Token** (Altlast einer früheren Version, manuell erteilt) →
  eigener Abschnitt „Weitere Berechtigungen" mit roher URL, ohne Zustandszeichen.
  Verschweigen wäre das Gegenteil dessen, was das Feature will.

## Code-Aufteilung

- **`src/mail.py`** — bei den vorhandenen Scope-Konstanten:
  - `SCOPE_LABELS: dict[str, str]` — Scope-URL → Klartext.
  - `ScopeStatus = namedtuple("ScopeStatus", ["scope", "label", "status"])` mit
    `status ∈ {"active", "unused", "missing"}` — namedtuple wie `tray.MenuEntry`, das
    dort dieselbe Rolle als backend-agnostisches Modell spielt.
  - `scope_overview(granted, sync_enabled, gcal_enabled) -> tuple[list[ScopeStatus], list[str]]`
    — die bewerteten Scopes in fester Reihenfolge und die unbekannten Extras als rohe
    URLs. `granted` ist eine Sequenz; `None` (Token unlesbar) fängt der Aufrufer ab,
    nicht diese Funktion.

  Muss nach `mail.py`, weil `oauth_utils` von `mail` importiert wird — ein Rückimport
  wäre ein Zyklus.
- **`src/oauth_utils.py`** — `read_granted_scopes(token_path) -> list[str] | None`.
  `None` = Datei fehlt **oder** ist unlesbar; die Unterscheidung der zwei Sonderfälle
  macht der Aufrufer über `os.path.exists`. `discard_token_for_scope_upgrade` zieht
  künftig auf diesen Helfer, damit es genau eine Leselogik gibt.
- **`src/dialogs/scopes_dialog.py`** — reines Rendering, keine Entscheidungslogik.

Beide Logik-Teile sind Tk-frei und ohne Netz testbar.

## Bewusst nicht enthalten

- **Kein Widerruf** einzelner Scopes (s. Entscheidungen).
- **Kein Live-Refresh** — entfällt durch das Modal.
- **Kein Tooltip** — die technische URL steht im Modal direkt in der Zeile.
- **Keine neue Einstellung**, kein persistierter Zustand.

## Tests

**`tests/test_mail.py`** — `scope_overview`:
- alles gewährt, Sync und Kalender an → fünfmal `active`
- Sync aus, Drive-Scope noch im Token → `unused`
- Sync an, Drive-Scope fehlt → `missing`
- nie eingeschalteter Kalender ohne Scopes → taucht gar nicht auf
- unbekannter Scope im Token → landet in den Extras, nicht in der Hauptliste
- Reihenfolge ist stabil (Kern, Drive, Kalender)

**`tests/test_oauth_utils.py`** — `read_granted_scopes`:
- gültiges Token → Liste
- fehlende Datei → `None`
- kaputtes JSON → `None`
- Token ohne `scopes`-Key → leere Liste (≠ `None`: die Datei war lesbar)
- `discard_token_for_scope_upgrade` verhält sich nach der Umstellung unverändert
  (bestehende Tests bleiben grün)

Das Rendering selbst bleibt ungetestet — konsistent mit der übrigen Tk-Schicht
(Audit M16, offen).

## Plattform

Kein plattformspezifischer Code; das Modal nutzt dieselben Theme-Helfer wie alle
anderen Dialoge. Keine Pre-Release-Verifikation nötig.
