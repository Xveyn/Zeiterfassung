# pyright: reportOptionalMemberAccess=true
"""Bereich „meldungen“: Meldungsdialoge, Toasts, Banner und Tray."""

TEXTS: dict[str, str] = {
    # Fehlende OAuth-Client-Datei; der Text reist über `str(e)` in Dialog und Statuszeile.
    "meldungen.credentials_fehlen": "credentials.json nicht gefunden unter:\n{pfad}",
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
}
