# Sicherheitsrichtlinie

## Unterstützte Versionen

Zeiterfassung ist ein kleines Desktop-Tool ohne Server-Komponente. Sicherheits-Fixes
fließen ausschließlich in die **jeweils aktuelle Release-Version** ein. Ältere Versionen
werden nicht rückwirkend gepatcht — bitte vor einer Meldung auf das
[neueste Release](https://github.com/Xveyn/Zeiterfassung/releases/latest)
aktualisieren.

| Version            | Unterstützt |
|--------------------|:-----------:|
| Neuestes Release   | ✅          |
| Ältere Versionen   | ❌          |

## Schwachstelle melden

Bitte melde Sicherheitslücken **nicht** über öffentliche GitHub-Issues.

Meldungen laufen über die privaten
[**Security Advisories**](https://github.com/Xveyn/Zeiterfassung/security/advisories/new)
dieses Repositorys („Report a vulnerability").

Hilfreich für eine schnelle Einschätzung:

- Betroffene Version und Plattform (Windows / macOS / Linux)
- Beschreibung der Schwachstelle und der möglichen Auswirkung
- Schritte zur Reproduktion oder ein Proof of Concept
- Falls vorhanden: ein Vorschlag zur Behebung

Zeiterfassung ist nebenbei als maßgeschneiderte Lösung für die eigene
Arbeitszeiterfassung entstanden — garantierte Reaktionszeiten gibt es daher
nicht. Eine erste Rückmeldung erfolgt in der Regel innerhalb weniger Tage. Bitte gib uns Gelegenheit,
ein Problem zu beheben, bevor du Details öffentlich machst (Coordinated Disclosure).

## Sicherheitsrelevante Hinweise zur Nutzung

Die App speichert sensible Daten **lokal im Klartext**. Wer das damit verbundene
Risiko kennt, kann es vermeiden:

- **`token.json`** enthält einen langlebigen OAuth-Refresh-Token mit laufendem Zugriff
  auf das verbundene Google-Konto (Gmail-Versand, Drive-Sync, ggf. Kalender). Unter
  macOS/Linux wird die Datei per `chmod 0600` nur für den eigenen Benutzer lesbar
  gemacht; unter Windows setzt die App per `icacls` eine explizite ACL (geerbte
  Rechte entfernt, nur das eigene Benutzerkonto bleibt berechtigt). Beides ist
  Zugriffsschutz auf Dateiebene, **keine** Verschlüsselung. **Wer den Daten- bzw.
  Installationsordner kopiert, sichert oder in die Cloud synchronisiert, nimmt diesen
  Token mit** — den Ordner entsprechend vertraulich behandeln.
- **`credentials.json`** (OAuth-Client-Secret des eigenen Google-Cloud-Projekts) und
  **`token.json`** gehören **nicht** ins Repository und werden über `.gitignore`
  ausgeschlossen.
- Bei Verdacht auf Kompromittierung den App-Zugriff in den
  [Google-Kontoeinstellungen](https://myaccount.google.com/permissions) entziehen und
  `token.json` löschen — die App startet beim nächsten Versand einen neuen
  Anmelde-Flow.

Weitere Details zur Datenspeicherung stehen im
[README](README.md#datenspeicherung).
