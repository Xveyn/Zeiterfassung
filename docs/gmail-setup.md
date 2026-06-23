# Gmail API einrichten — Anleitung

## 1. Google Cloud Projekt erstellen

1. Öffne die [Google Cloud Console](https://console.cloud.google.com/)
2. Klicke oben auf das Projekt-Dropdown → **Neues Projekt**
3. Name: z.B. "Zeiterfassung" → **Erstellen**
4. Warte bis das Projekt erstellt ist und wähle es aus

## 2. Gmail API aktivieren

1. Gehe zu **APIs & Dienste** → **Bibliothek**
2. Suche nach "Gmail API"
3. Klicke auf **Gmail API** → **Aktivieren**

## 3. OAuth-Zustimmungsbildschirm konfigurieren

1. Gehe zu **APIs & Dienste** → **OAuth-Zustimmungsbildschirm**
2. Wähle **Extern** → **Erstellen**
3. Fülle aus:
   - App-Name: "Zeiterfassung"
   - Support-E-Mail: deine Gmail-Adresse
   - E-Mail-Adressen des Entwicklers: deine Gmail-Adresse
4. Klicke **Speichern und fortfahren**
5. Bei **Bereiche**: Klicke **Bereiche hinzufügen oder entfernen**
   - Suche nach `gmail.send` und aktiviere es
   - Suche nach `userinfo.email` und aktiviere es (damit die App die Absender-Adresse automatisch aus dem Google-Konto übernimmt — non-sensitive, keine Verifizierung nötig)
   - **Aktualisieren** → **Speichern und fortfahren**
6. Bei **Testnutzer**: Klicke **Nutzer hinzufügen**
   - Trage deine Gmail-Adresse ein
   - **Speichern und fortfahren**

## 4. OAuth2 Client-ID erstellen

1. Gehe zu **APIs & Dienste** → **Anmeldedaten**
2. Klicke **Anmeldedaten erstellen** → **OAuth-Client-ID**
3. Anwendungstyp: **Desktopanwendung**
4. Name: "Zeiterfassung" → **Erstellen**
5. Klicke auf **JSON herunterladen**
6. Speichere die Datei als `credentials.json` im Zeiterfassung-Projektordner

## 5. Erster Versand

1. Starte die App: `python -m src.main`
2. Trage unter **Einstellungen** (Zahnrad-Symbol) einen Empfänger ein
3. Klicke auf **Arbeitszeiten senden**
4. Ein Browser-Fenster öffnet sich zur Google-Anmeldung
5. Melde dich mit deinem Google-Konto an und erlaube den Zugriff
6. Der Bericht wird gesendet — ab jetzt funktioniert es ohne erneute Anmeldung

## Hinweise

- Die App befindet sich im "Test"-Modus — nur die eingetragenen Testnutzer können sich anmelden
- Das Token (`token.json`) wird automatisch erneuert
- Falls das Token abläuft oder ungültig wird, öffnet sich der Browser erneut
- `credentials.json` und `token.json` sind in `.gitignore` eingetragen und werden nicht committed
