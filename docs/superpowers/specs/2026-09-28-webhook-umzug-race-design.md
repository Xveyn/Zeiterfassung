# Webhook-Secrets: Umzug in den Schlüsselbund race-frei — Design

**Datum:** 2026-09-28
**Status:** Entwurf, zur Prüfung
**Branch:** `fix/webhook-umzug-race`
**Issue:** Xveyn/Zeiterfassung#173
**Bezug:** `docs/superpowers/specs/2026-09-18-secrets-keyring-design.md` (#101)

## Problem

Beim Start zieht `secret_migration.migrate` Klartext-Secrets aus
`webhooks.json` in den Schlüsselbund (#101). Das läuft im
`BackgroundTaskRunner`, und dasselbe tun zwei andere Wege, jeder in seinem
eigenen Worker-Thread:

| Weg | Wo | Was er tut |
|---|---|---|
| Umzug | `secret_migration._move_webhook` | `put`, Zurücklesen, Datensatz neu lesen, `store.save(stored_in_keyring(...))` |
| Speichern | `webhook_dialog.do_save` → `fn` | `webhook_secrets.persist` (ggf. `put`), `store.save`, danach `remove(stale)` |
| Löschen | `_record_list_tab.remove_record` | `store.delete`, danach `webhook_secrets.forget_by_id` |

Beim OAuth-Token koordiniert `TOKEN_LOCK` die Schreiber. Für Webhooks gibt es
kein Gegenstück: die drei Wege laufen unkoordiniert. Das Issue beschreibt
einen Fall davon. Die Prüfung vor diesem Spec ergab vier:

1. **Verwaister Eintrag (das Issue).** Wird der Webhook zwischen dem
   Start-Snapshot und `_move_webhook` gelöscht, schreibt der Umzug das Secret
   trotzdem nach `webhook:<id>`, erkennt die Löschung erst danach und räumt
   nicht ab. Kein Codepfad erreicht den Eintrag mehr: `forget_by_id` lief
   schon, und `forget_all` kennt nur die aktuellen Datensätze.
2. **Überschriebenes neues Secret.** Speichert der Dialog ein neu
   eingegebenes Secret (`put(webhook:<id>, neu)`), kurz bevor der Umzug sein
   `put(webhook:<id>, alt)` macht, liegt danach das **alte** Secret im
   Schlüsselbund. Der Datensatz zeigt auf den Schlüsselbund, der Webhook
   sendet still mit dem veralteten Token.
3. **Wiederbelebter Webhook.** Wird gelöscht, nachdem `_move_webhook` den
   Datensatz geprüft, aber bevor es gespeichert hat, legt `store.save` den
   Webhook wieder an: `save` legt an oder ersetzt nach `id`.
4. **Die Fix-Richtung des Issues verschlimmert Fall 2.** Ein pauschales
   `keyring_store.remove(webhook:<id>)` im Zweig „Datensatz hat sich
   geändert" löscht auch das Secret, das der Dialog gerade frisch abgelegt
   hat. Der Datensatz zeigt dann auf einen leeren Eintrag, und Senden
   scheitert mit „Zugangsdaten neu eingeben".

Das Zeitfenster ist schmal: der Nutzer muss in den ersten Sekunden nach dem
Start einen Webhook bearbeiten oder löschen, und es muss noch etwas
umzuziehen geben. Mit dem Schlüsselbund-Watchdog (bis 30 s je Aufruf) kann es
aber deutlich breiter werden, und wo es trifft, liegt ein Secret an der
falschen Stelle, ohne dass es jemand merkt.

## Randbedingungen

- **Die Store-Sperre darf nie über einen Schlüsselbund-Aufruf gehalten
  werden.** `webhook_dialog.py:188` ruft `store.get_all()` im UI-Thread (die
  Validierung vor dem Speichern). Ein `put` unter der Store-Sperre könnte die
  Oberfläche bis zum Watchdog (30 s) einfrieren.
- **`webhook_store` bleibt reine Dateipersistenz** und kennt den
  Schlüsselbund nicht (Trennung aus #101, wie `smtp_store`/`keyring_store`).
- **Der Schlüssel ist deterministisch** (`webhook:<id>`, `id` aus
  `webhook_store.new_id`, nie wiederverwendet). Ein Eintrag kann also nur
  verwaisen, wenn seine `id` aus `webhooks.json` verschwunden ist.
- **Alle drei Wege laufen bereits im Worker.** Eine Sperre, auf die sie
  warten, blockiert nie die Oberfläche.

## Ansätze

**A — Eine Secret-Sperre plus bedingtes Speichern (empfohlen).**
Eine eigene Sperre in `webhook_secrets` serialisiert *Umzug* und *Speichern
im Dialog*. Das Löschen bleibt ohne neue Sperre. Es wird über ein
atomares „Speichern nur, wenn unverändert" im Store abgefangen, das ohne
Schlüsselbund-Aufruf auskommt. Details s. „Design".

**B — Die Store-Sperre für alles.** Umzug, Speichern und Löschen halten
`WebhookStore._lock` über ihre ganze Sequenz, samt Schlüsselbund-Aufrufen.
Am wenigsten Code, verletzt aber die erste Randbedingung. Der UI-Thread
wartete an `get_all()` auf den Watchdog. Verworfen.

**C — Eine Secret-Sperre um alle drei Wege.** Wie A, aber auch das Löschen
nimmt die Secret-Sperre. Braucht dafür einen Sperr-Haken in der
gemeinsamen `RecordListKind`, die SMTP und Webhooks teilen. Das ist ein
Eingriff in eine geteilte Abstraktion für einen Fall, den das bedingte
Speichern aus A ohnehin abdeckt. Verworfen.

**D — Die Fix-Richtung des Issues** (`remove` in beiden Fehlerzweigen).
Behebt Fall 1, erzeugt Fall 4 und lässt Fall 2 und 3 offen. Verworfen.

## Design (Ansatz A)

### `webhook_secrets.SECRETS_LOCK`

Ein `threading.Lock` auf Modulebene. Kein `RLock`: keiner der Wege ruft sich
selbst geschachtelt auf. Er serialisiert alles, was ein Webhook-Secret im
Schlüsselbund **schreibt** und den Datensatz dazu speichert:

- `_move_webhook` hält ihn pro Webhook, vom erneuten Lesen des Datensatzes
  bis nach dem Speichern.
- `webhook_dialog.do_save.fn` hält ihn um `persist` und `store.save`.
  Das `remove(stale)` danach läuft **außerhalb**: es betrifft einen
  Schlüssel, den der gerade gespeicherte Datensatz nicht mehr referenziert.

Das Löschen nimmt ihn nicht (s. Ansatz C).

### `WebhookStore.save_if_unchanged(expected, record) -> bool`

Prüft und schreibt atomar unter der Store-Sperre: steht unter
`expected["id"]` genau `expected` (Vergleich per `==` auf den Datensätzen),
wird `record` gespeichert und `True` geliefert. Fehlt der Datensatz oder
weicht er ab, wird nichts geschrieben und `False` geliefert. Schreibfehler
werfen wie bei `save` (`WebhookStoreReadOnly`/`OSError`), mit demselben
Rollback. Kein Schlüsselbund-Aufruf, die Sperre ist also nur für die Dauer
eines Dateischreibens gehalten, wie heute bei `save`.

### Neuer Ablauf von `_move_webhook`

```
with SECRETS_LOCK:
    current = Datensatz mit record["id"] aus store.get_all()
    if current is None or plaintext_secret(current) != secret:
        return False              # geändert/gelöscht: Schlüsselbund unberührt
    if not _stored_and_verified(key, secret):
        return False              # räumt bei Fehlschlag selbst ab (wie heute)
    try:
        saved = store.save_if_unchanged(current, stored_in_keyring(current))
    except (WebhookStoreReadOnly, OSError):
        keyring_store.remove(key); return False
    if not saved:
        keyring_store.remove(key); return False
    return True
```

Warum das jeden der vier Fälle schließt:

1. **Gelöscht vor dem Umzug:** `current is None`, und der Schlüsselbund
   bleibt unberührt. **Gelöscht zwischen Prüfung und Speichern:**
   `save_if_unchanged` liefert `False`, und der Umzug räumt seinen eigenen
   Eintrag ab. Sicher, weil unter `webhook:<id>` einer gelöschten `id` nur
   der Umzug geschrieben haben kann: der Dialog-Weg ist durch
   `SECRETS_LOCK` ausgeschlossen, und `forget_by_id` löscht ohnehin.
2. **Dialog speichert vor dem Umzug:** unter der Sperre sieht der Umzug den
   neuen Datensatz (im Schlüsselbund oder mit anderem Secret) und fasst den
   Schlüsselbund nicht an. **Dialog speichert während des Umzugs:** wartet
   auf die Sperre und schreibt danach sein Secret über das des Umzugs. Das
   ist die gewollte Reihenfolge.
3. **Löschen zwischen Prüfung und Speichern:** `save_if_unchanged` findet
   den Datensatz nicht und legt ihn nicht wieder an.
4. **Abgeräumt wird nur, wo der Eintrag sicher dem Umzug gehört:**
   Schreibfehler (der Datensatz trägt weiter den Klartext, kein anderer Weg
   hat unter der Sperre geschrieben) und „vor dem Speichern
   verschwunden/geändert". Im zweiten Fall hat innerhalb der Sperre nur das
   Löschen den Datensatz ändern können, und das schreibt keinen
   Schlüsselbund-Eintrag.

Ein Punkt zu Fall 4, zweiter Zweig: Ändern kann den Datensatz zwischen
Prüfung und `save_if_unchanged` außer dem Löschen niemand, denn der
Dialog-Weg wartet auf `SECRETS_LOCK`. Weicht er trotzdem ab (etwa ein
künftiger dritter Schreiber ohne Sperre), ist Abräumen die sichere Seite:
der Datensatz zeigt dann nicht auf den Schlüsselbund, sonst hätte der Umzug
ihn nicht als Klartext vorgefunden.

### Bewusst unverändert

- **Dialog offen über den Umzug hinweg.** Öffnet der Nutzer den Dialog vor
  dem Umzug und speichert danach, ohne ein Secret einzugeben, schreibt er den
  alten Klartext-Datensatz zurück. Kein Datenverlust: das Secret steht dann
  wieder im Klartext, der Schlüsselbund-Eintrag unter demselben
  deterministischen Schlüssel wird beim nächsten Start wiederverwendet bzw.
  beim Löschen abgeräumt. Der nächste Start zieht erneut um. Das ist ein
  bekannter, selbstheilender Zustand und nicht Teil dieses Issues.
- **`forget_all`** (Uninstaller) bleibt, wie es ist.
- **Token-Weg** (`_move_token`, `TOKEN_LOCK`) bleibt unberührt.

## Tests

Tk-frei in `tests/test_secret_migration.py` und `tests/test_webhook_store.py`,
mit dem vorhandenen `fake_keyring`. Die Races werden deterministisch
nachgestellt, indem ein Fake-Aufruf (`fetch` beim Zurücklesen bzw.
`store.get_all`) die konkurrierende Aktion auslöst, nach dem Muster von
`test_changed_token_between_check_and_write_is_not_moved`.

- Gelöscht vor dem Umzug: kein Schlüsselbund-Eintrag, nicht umgezogen.
- Gelöscht zwischen Zurücklesen und Speichern: kein verwaister Eintrag, der
  Webhook bleibt gelöscht (Fall 1 + 3).
- Dialog hat vor dem Umzug ein neues Secret im Schlüsselbund abgelegt: der
  Eintrag enthält danach das **neue** Secret (Fall 2, 4).
- Speichern scheitert (`OSError`): Eintrag abgeräumt, Datei trägt weiter den
  Klartext.
- `save_if_unchanged`: speichert bei Gleichheit, verweigert bei fehlendem
  und bei abweichendem Datensatz, rollt bei Schreibfehler zurück.
- Die Sperre wird gehalten: eine zweite Sperranforderung während eines
  `put` blockiert (per `acquire(blocking=False)` im Fake geprüft).

Der Dialog-Weg (`do_save`) ist Tk-Code und nach Projektregel nicht
automatisiert getestet. Er ändert sich nur um das `with SECRETS_LOCK:`,
geprüft per Review.

## Doku

- `src/CLAUDE.md`, Abschnitt „Google-Integration"/Secrets bzw. der
  `webhook_secrets`-Eintrag: die Sperr-Regel (wer sie nimmt, dass die
  Store-Sperre nie über einen Schlüsselbund-Aufruf gehalten wird, dass das
  Löschen über `save_if_unchanged` abgefangen ist).
- Root-`CLAUDE.md`, Modulliste `webhook_secrets.py`: ein Satz zur Sperre.

## Nicht im Umfang

- Dieselbe Frage für SMTP-Konten: dort gibt es keinen automatischen Umzug,
  also keinen konkurrierenden Hintergrund-Schreiber.
- Eine allgemeine Sperr-Abstraktion für alle Secret-Stores.
