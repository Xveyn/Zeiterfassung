# pyright: reportOptionalMemberAccess=true
"""Bereich „meldungen“: Meldungsdialoge, Toasts, Banner und Tray."""

TEXTS: dict[str, str] = {
    # Fehlende OAuth-Client-Datei; der Text reist über `str(e)` in Dialog und Statuszeile.
    "meldungen.credentials_fehlen": "credentials.json nicht gefunden unter:\n{pfad}",
    # Zusatz der Gmail-Fehlermeldung (Basis ist `meldungen.credentials_fehlen`).
    "meldungen.credentials_gmail_anleitung": "\n\nBitte erstelle ein Google Cloud Projekt mit Gmail API und lade die OAuth2 Client-ID dort ab.",
    "meldungen.schluesselbund_titel": "Schlüsselbund nicht erreichbar",
    "meldungen.schluesselbund_detail": "Der Schlüsselbund des Betriebssystems ist nicht erreichbar — dort liegt die Google-Anmeldung.",
    "meldungen.schluesselbund_hinweis": "Die Google-Anmeldung liegt im Schlüsselbund des Betriebssystems, und der antwortet gerade nicht (gesperrt oder nicht gestartet).\n\nBitte entsperre ihn und versuche es erneut.",
    # `TokenAuthError`-Texte (Start-Dialog über `friendly_token_message`).
    "meldungen.refresh_token_fehlt": "Der Refresh-Token fehlt im Schlüsselbund des Betriebssystems.",
    "meldungen.token_ungueltig": "Token ist ungültig und enthält kein Refresh-Token.",
    "meldungen.gmail_abgelaufen_titel": "Gmail-Anmeldung abgelaufen",
    "meldungen.gmail_abgelaufen_text": "Die Anmeldung bei Gmail ist abgelaufen oder wurde widerrufen. Das passiert nach längerer Zeit ohne Nutzung von selbst.\n\nEs geht nichts verloren: Beim nächsten Senden fragt die App automatisch nach einer neuen Freigabe.",
    "meldungen.gmail_erneuern_titel": "Gmail-Anmeldung erneuern",
    "meldungen.gmail_erneuern_text": "Die Gmail-Anmeldung konnte nicht automatisch erneuert werden:\n\n{text}\n\nBeim nächsten Senden fragt die App nach einer neuen Freigabe.",
    # Validierung (`time_utils`): Dialoge zeigen sie, die lokale API gibt sie unverändert zurück.
    "zeit.startzeit_ungueltig": "Startzeit ungültig (Format: HH:MM)",
    "zeit.endzeit_ungueltig": "Endzeit ungültig (Format: HH:MM)",
    "zeit.ende_nach_start": "Endzeit muss nach Startzeit liegen",
    "zeit.pause_negativ": "Pause darf nicht negativ sein",
    "zeit.pause_zu_lang": "Pause ({pause} Min) muss kleiner als die Arbeitszeit ({arbeit} Min) sein",
    "zeit.von_nach_bis": "Das Von-Datum muss vor dem Bis-Datum liegen.",
    "zeit.pause_keine_zahl": "Pause muss eine ganze Zahl (Minuten) sein.",
    "zeit.slots_ueberlappen": "Zeitslots dürfen sich zeitlich nicht überlappen.",
    # Urlaub: Kappungs-Hinweis (Zeitraum-Picker **und** Berichts-Fußnote, wortgleich) und
    # Fehler des Stores, die der Urlaubs-Dialog zeigt.
    "urlaub.kappung_wo_eins": "An 1 Tag ({datum})",
    "urlaub.kappung_satz_eins": "Der Urlaub ist dort um {stunden}h gekürzt, damit der Tag nicht doppelt zählt.",
    "urlaub.kappung_wo_viele": "An {anzahl} Tagen{liste}",
    "urlaub.kappung_satz_viele": "Der Urlaub ist dort um insgesamt {stunden}h gekürzt, damit die Tage nicht doppelt zählen.",
    "urlaub.kappung_gesamt": "{wo} liegt Urlaub auf erfasster Arbeitszeit. {satz}",
    "urlaub.bis_vor_von": "Das Bis-Datum liegt vor dem Von-Datum.",
    "urlaub.ueberschneidung": "Der Zeitraum überschneidet sich mit dem Urlaub „{name}“. Bearbeite stattdessen diesen Urlaub, wenn du ihn verlängern willst.",
    "version.dev_ohne_updates": "Dev-Builds (Test-Builds aus der CI und Start aus dem Quellcode) erhalten keine Updates.",
    "changelog.keine_aenderungen": "Keine Änderungen seit dem letzten Release.",
    # Themed Meldungsdialoge (`theme/messagebox.py`).
    "messagebox.ungespeichert_titel": "Ungespeicherte Änderungen",
    "messagebox.ungespeichert_text": "Im Tab „{tab}“ gibt es ungespeicherte Änderungen.\nSollen sie gespeichert werden?",
    "messagebox.kopiert": "In die Zwischenablage kopiert",
    "messagebox.befehl_kopieren": "Befehl kopieren",
    # Banner über dem Kalender (Update, Skalierung).
    "update_banner.installieren": "Update installieren",
    "update_banner.download": "Download",
    "update_banner.bereit": "Update bereit — wird beim Beenden installiert",
    "update_banner.vorabversion": "Vorabversion",
    "update_banner.version": "Version",
    "update_banner.verfuegbar": "{art} {version} verfügbar",
    "update_banner.ausblenden": "Diese Version ausblenden",
    "skalierung.banner": "Skalierung passt nicht zum Monitor",
    "skalierung.neu_starten": "Neu starten",
    # Hinweis, wenn sich ein Handy selbst getrennt hat (`unpair_notice`).
    "handy_getrennt.fallback_name": "Ein Handy",
    "handy_getrennt.titel": "Handy getrennt",
    "handy_getrennt.text": "{name} hat sich vom Desktop getrennt. Das Gerät wurde widerrufen; zum erneuten Verbinden muss es neu gekoppelt werden.",
    "handy_getrennt.toast": "{name} hat sich vom Desktop getrennt.",
    # Nativer Fehlerdialog bei einer unbehandelten Tk-Ausnahme (`logging_setup`).
    "logging.fehler_titel": "Unerwarteter Fehler",
    "logging.fehler_text": "{art}: {fehler}\n\nDetails im Logfile.",
    # Start ohne Tk (`main._create_root`): stderr ist der einzige Kanal.
    "main.kein_display": "Kein Display gefunden — Zeiterfassung braucht eine grafische Sitzung. Bitte aus einem Terminal im Desktop starten (per SSH fehlt das Display; `ssh -X` zeigt das Fenster, das Tray-Icon aber nicht).",
    "main.tk_start_fehler": "Tk konnte nicht gestartet werden: {fehler}",
    # Plattform-Fehler, die ein Dialog über `str(e)` zeigen kann (Autostart, Ordner öffnen).
    "autostart.nicht_unterstuetzt": "Autostart not supported on {system}",
    "platform_open.nicht_unterstuetzt": "Unsupported platform: {system}",
    # Hinweis nach einer Reparatur der Zeiterfassungsdaten beim Laden (`storage`, #242).
    "speicher.reparatur_titel": "Zeiterfassungsdaten repariert",
    "speicher.reparatur_probleme": "{verworfen} Eintrag/Einträge ohne Objektform, {slots} Eintrag/Einträge mit kaputter Slot-Liste, {werte} Eintrag/Einträge mit unbrauchbaren Metadaten/Zeichen",
    "speicher.reparatur_text_mit_sicherung": "Beim Start waren Teile der Zeiterfassungsdaten unbrauchbar und wurden verworfen bzw. repariert:\n{probleme}\n\nDie ursprüngliche Datei wurde gesichert:\n{pfad}\n\nFehlen Stunden, stehen sie dort noch drin.",
    "speicher.reparatur_text_ohne_sicherung": "Beim Start waren Teile der Zeiterfassungsdaten unbrauchbar und wurden verworfen bzw. repariert:\n{probleme}\n\nEine Sicherung war nicht möglich. Die Datei auf der Platte bleibt unverändert, bis die nächste Speicherung sie überschreibt.",
    "speicher.reparatur_toast_mit_sicherung": "Zeiterfassungsdaten repariert, Sicherung: {datei}",
    "speicher.reparatur_toast_ohne_sicherung": "Zeiterfassungsdaten repariert, aber ohne Sicherung (siehe Log).",
}
