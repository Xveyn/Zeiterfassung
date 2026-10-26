# Sicherheitsrichtlinie

## Geltungsbereich

Zeiterfassung ist ein Desktop-Tool für Windows, macOS und Linux. Diese Richtlinie
gilt für

- die **Desktop-App** samt den beiden optionalen HTTP-Schnittstellen, die sie
  öffnen kann: der lokalen API (nur Loopback) und der Handy-Instanz (nur die
  gewählte LAN-Adresse). Beide sind standardmäßig **aus**,
- die **Handy-PWA** der Handy-Erfassung (Verzeichnis `pwa/`), die im Browser des
  Handys läuft und mit der Handy-Instanz des Desktops spricht,
- den **Push-Relay** (Verzeichnis `relay/`), einen Cloudflare Worker im Internet, der
  Erinnerungen als Push an die PWA weiterleitet. Er ist optional und der einzige Teil,
  der nicht im eigenen Netz läuft.

## Unterstützte Versionen

Sicherheits-Fixes fließen ausschließlich in den **jeweils aktuellen Stand** ein.
Ältere Versionen werden nicht rückwirkend gepatcht. Was „aktuell“ heißt,
unterscheidet sich zwischen Desktop und PWA:

| Teil | Aktueller Stand | Unterstützt |
|------|-----------------|:-----------:|
| Desktop-App | [neuestes Release](https://github.com/Xveyn/Zeiterfassung/releases/latest) | ✅ |
| Desktop-App | ältere Releases | ❌ |
| Handy-PWA | die ausgelieferte Version unter `https://xveyn.github.io/Zeiterfassung/` | ✅ |
| Handy-PWA | ältere, noch gecachte Stände | ❌ |
| Push-Relay | der ausgerollte Stand des Workers | ✅ |

**Desktop:** Updates kommen als Release. Windows und Linux können sich selbst
aktualisieren, unter macOS ist der Download manuell. Bitte vor einer Meldung auf
das neueste Release aktualisieren.

**Relay:** Er hat kein Release. Jeder Merge auf `master` mit Änderungen unter `relay/**`
rollt ihn nach grünen Tests automatisch aus (`.github/workflows/relay-deploy.yml`);
ein Fix erreicht ihn damit sofort.

**PWA:** Sie hat kein Release. Jeder Push auf `master` mit Änderungen unter
`pwa/**` wird über GitHub Pages veröffentlicht, und die PWA zieht sich die neue
Fassung selbst nach (Service Worker). Das Einspielen geschieht erst nach einer
Rückfrage („Neue Version verfügbar“); wer „Automatisch einspielen“ einschaltet,
bekommt es an einem sicheren Zeitpunkt ohne Rückfrage. Ein Fix erreicht die PWA
damit sofort, den Desktop erst mit dem nächsten Release. Beide Seiten können also
unterschiedlich alt sein; die Verträge zwischen ihnen sind darauf ausgelegt
(`pwa/CLAUDE.md`, Abschnitt „Kompatibilität“). Die Build-Kennung der PWA
(`N/X.Y.Z (sha)`: Änderungen seit dem Desktop-Release, dessen Version, Commit) steht im Verbindungsdialog der PWA.

## Schwachstelle melden

Bitte melde Sicherheitslücken **nicht** über öffentliche GitHub-Issues.

Meldungen laufen über die privaten
[**Security Advisories**](https://github.com/Xveyn/Zeiterfassung/security/advisories/new)
dieses Repositorys („Report a vulnerability").

Hilfreich für eine schnelle Einschätzung:

- Betroffener Teil: Desktop-App, lokale API, Handy-Instanz, PWA oder Push-Relay
- Version und Plattform (Windows / macOS / Linux); bei der PWA zusätzlich die
  Build-Kennung und der Browser auf dem Handy
- Beschreibung der Schwachstelle und der möglichen Auswirkung
- Schritte zur Reproduktion oder ein Proof of Concept
- Falls vorhanden: ein Vorschlag zur Behebung

Zeiterfassung ist nebenbei als maßgeschneiderte Lösung für die eigene
Arbeitszeiterfassung entstanden — garantierte Reaktionszeiten gibt es daher
nicht. Eine erste Rückmeldung erfolgt in der Regel innerhalb weniger Tage. Bitte gib uns Gelegenheit,
ein Problem zu beheben, bevor du Details öffentlich machst (Coordinated Disclosure).

## Sicherheitsrelevante Hinweise zur Nutzung

Die App speichert sensible Daten **lokal**. Wer das damit verbundene Risiko kennt,
kann es vermeiden:

- **Schlüsselbund.** Mit verfügbarem Schlüsselbund des Betriebssystems (Windows
  Anmeldeinformationsverwaltung, macOS-Schlüsselbund, Linux Secret Service) liegen
  OAuth-Refresh-Token, Webhook-Secrets, SMTP-Passwörter und die Geräteschlüssel
  der Handy-Erfassung dort und **nicht** im Klartext im Datenordner. Ohne
  Schlüsselbund fällt die App auf Dateien zurück, und das jeweilige Secret steht
  dann im Klartext darin.
- **`token.json`** enthält im Datei-Fallback einen langlebigen OAuth-Refresh-Token
  mit laufendem Zugriff auf das verbundene Google-Konto (Gmail-Versand, Drive-Sync,
  ggf. Kalender). Auch mit Schlüsselbund liegt die Datei im Datenordner und
  trägt dann den Verweis darauf. Unter macOS/Linux wird sie per `chmod 0600` nur
  für den eigenen Benutzer lesbar gemacht; unter Windows setzt die App per
  `icacls` eine explizite ACL (geerbte Rechte entfernt, nur das eigene
  Benutzerkonto bleibt berechtigt). Dasselbe gilt für `webhooks.json`,
  `smtp.json`, `api-token`, `mobile_keys.json` und `mobile_relay.json`. Das ist Zugriffsschutz auf
  Dateiebene, **keine** Verschlüsselung. **Wer den Daten- bzw. Installationsordner
  kopiert, sichert oder in die Cloud synchronisiert, nimmt die dort verbliebenen
  Klartext-Secrets mit** — den Ordner entsprechend vertraulich behandeln.
- **`credentials.json`** (OAuth-Client-Secret des eigenen Google-Cloud-Projekts) und
  **`token.json`** gehören **nicht** ins Repository und werden über `.gitignore`
  ausgeschlossen.
- Bei Verdacht auf Kompromittierung den App-Zugriff in den
  [Google-Kontoeinstellungen](https://myaccount.google.com/permissions) entziehen und
  `token.json` löschen — die App startet beim nächsten Versand einen neuen
  Anmelde-Flow.

### Handy-Erfassung und PWA

Die Handy-Erfassung ist standardmäßig **aus** und lässt sich jederzeit
ausschalten. Im Einzelnen:

- **Verbindung.** Handy und Desktop sprechen im WLAN `http://`, nicht HTTPS. Die
  Nutzdaten sind aber **Ende-zu-Ende verschlüsselt** (AES-256-GCM, getrennte
  Schlüssel je Richtung, Schutz gegen Fälschen und Wiedereinspielen). Wer im
  selben WLAN mitliest, sieht weder Einträge noch Kategorien noch das
  Gerätetoken im Klartext; sichtbar bleibt, *dass* ein Handy mit dem Rechner
  spricht, wann und wie viel. Es gibt keine Forward Secrecy: wer später den
  Geräteschlüssel erbeutet, kann Mitschnitte von vorher lesen. Nur in
  vertrauenswürdigen Netzen nutzen.
- **Kopplung.** Der Kopplungscode (28 Zeichen) ist zugleich Schlüsselmaterial,
  gilt kurz und nur einmal und steht nie im Netz. Er steckt im QR-Code des
  Koppel-Dialogs — den QR-Code nicht weitergeben oder abfotografieren lassen, solange
  der Dialog offen ist.
- **Am Desktop** liegt von jedem gekoppelten Handy nur ein **Hash** des
  Gerätetokens in `mobile_devices.json`. Das Token ist pro Gerät widerrufbar und
  läuft 30 Tage nach dem letzten Abgleich ab. Der Geräteschlüssel liegt im
  Schlüsselbund, ohne Schlüsselbund in `mobile_keys.json` (nur für das eigene
  Benutzerkonto lesbar). Der Server lauscht nur auf der gewählten Adresse, nie auf
  allen Schnittstellen.
- **Am Handy** liegen die erfassten Tage in der IndexedDB des Browsers, dazu das
  Gerätetoken und der Geräteschlüssel. Das ist der Speicher der Web-App und
  hängt an der Browser-Sicherheit des Handys (Bildschirmsperre, Geräteverschlüsselung).
  Wer das Handy verliert, widerruft das Gerät im Tab „Mobil“ der Desktop-App (das löscht auch dessen Relay-Objekt).
- **Push-Erinnerungen und Relay** (optional, nur wenn am Desktop „Auch aufs Handy
  senden“ und am Handy Benachrichtigungen eingeschaltet sind). Der Relay sieht den
  Endpoint des Push-Dienstes des Browsers, die Abo-Schlüssel, das Zufallsgeheimnis des
  Handys (nur als Hash gespeichert, der Worker sieht es aber bei jeder Anfrage im
  Klartext), die Zeitpunkte der Erinnerungen und einen Text, den nur das Handy
  entschlüsseln kann. Er sieht keine Arbeitszeiten, Kategorien oder Namen. Die
  Push-Dienste (Google, Mozilla, Apple, Microsoft) sehen Metadaten, nicht den Inhalt.
  Das Geheimnis liegt am Desktop in `mobile_relay.json`. Beim Widerruf eines Handys
  löscht der Desktop dessen Relay-Objekt (best effort), sonst verfällt es nach 90 Tagen.
  Fällt der Relay aus oder wird er missbraucht, entfallen nur die Push-Erinnerungen
  (Rate-Limit je Absender-Adresse, kein Konto). Details: `relay/CLAUDE.md` und
  [`docs/known-limitations.md`](docs/known-limitations.md#push-relay-331-ein-neuer-vertrauens-ort).
- **Updates der PWA** laufen über GitHub Pages. Vertrauensanker ist TLS zu
  `xveyn.github.io`; der ausgelieferte Code ist nicht signiert.

### Updates der Desktop-App

Das Selbst-Update (Windows, Linux) lädt das Release-Asset von GitHub und prüft es
gegen die `SHA256SUMS` desselben Releases. Das erkennt abgebrochene und
beschädigte Übertragungen, schützt aber **nicht** gegen ein kompromittiertes
Release: die Summen-Datei liegt neben den Assets und ist selbst nicht signiert.
Vertrauensanker ist TLS zu GitHub, derselbe wie beim Browser-Download. Die
Updates der App sind **nicht signiert**.

Weitere Details zur Datenspeicherung stehen im
[README](README.md#datenspeicherung), die bekannten Grenzen der Handy-Erfassung in
[`docs/known-limitations.md`](docs/known-limitations.md#handy-erfassung-221-bekannte-grenzen).
