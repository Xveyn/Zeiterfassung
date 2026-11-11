# pyright: reportOptionalMemberAccess=true
"""Bereich „einstellungen“: der Einstellungen-Dialog und seine Reiter."""

TEXTS: dict[str, str] = {
    # Berechtigungen-Dialog (`mail.scope_overview`/`scope_summary`).
    "berechtigung.gmail_senden": "E-Mail senden",
    "berechtigung.adresse_lesen": "Eigene E-Mail-Adresse lesen",
    "berechtigung.drive_appdata": "Google Drive: App-Datenordner",
    "berechtigung.kalender_termine": "Google Kalender: Termine lesen und schreiben",
    "berechtigung.kalender_liste": "Google Kalender: Kalenderliste lesen",
    "berechtigung.zusammenfassung": "{n} von {m} Berechtigungen",
    "standardzeiten.modus_allgemein": "Allgemein",
    "standardzeiten.modus_tageweise": "Tageweise",
    "erinnerung.verschiebung_keine": "nicht verschieben",
    "erinnerung.verschiebung_davor": "vorziehen (davor)",
    "erinnerung.verschiebung_danach": "nachziehen (danach)",
    "erinnerung.tooltip_vor_ende": "Erinnerung ans Verschicken: {minuten} min vor Ende",
    "erinnerung.tooltip_zum_ende": "Erinnerung ans Verschicken: zum Ende",
    "erinnerung.tooltip_zum_ende_uhr": "Erinnerung ans Verschicken: zum Ende ({uhr} Uhr)",
    "erinnerung.tooltip_vor_ende_uhr": "Erinnerung ans Verschicken: {minuten} min vor Ende ({uhr} Uhr)",
    "skalierung.hinweis_system": "Die Anzeigeskalierung des Systems ({prozent} %) wird automatisch berücksichtigt; der Wert hier gilt zusätzlich.",
}
