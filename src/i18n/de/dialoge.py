# pyright: reportOptionalMemberAccess=true
"""Bereich „dialoge“: die übrigen Dialoge (Tag, Versand, Teilen, Urlaub, Kopplung …)."""

TEXTS: dict[str, str] = {
    # Kategorie-Dropdown der Slot-Zeilen (`slot_rows`); das Glyph gehört zum Text.
    "kategorie.ohne": "(ohne Kategorie)",
    "kategorie.neu": "＋ Neue Kategorie",
    "datenschutz.ersatztext": "Die Datenschutzhinweise konnten nicht geladen werden. Sie stehen im Projekt unter ",
    # Konfliktdialog (`conflict_view`): Kartentitel, Platzhalter und die Klartext-Namen der Einstellungen.
    "konflikt.dieses_geraet": "Dieses Gerät",
    "konflikt.anderes_geraet": "Anderes Gerät",
    "konflikt.ohne_kategorie": "ohne Kategorie",
    "konflikt.geloescht": "Gelöscht",
    "konflikt.leer": "(leer)",
    "konflikt.an": "an",
    "konflikt.aus": "aus",
    "konflikt.stunden": "{wert} h",
    "konflikt.pause": "Pause {minuten} min",
    "konflikt.keine_pause": "keine Pause",
    "konflikt.geaendert": "geändert {zeit}",
    "konflikt.einstellung_empfaenger": "Empfänger",
    "konflikt.einstellung_name": "Name",
    "konflikt.einstellung_stundenlohn": "Stundenlohn",
    "konflikt.einstellung_mail_betreff": "Mail-Betreff",
    "konflikt.einstellung_mail_anrede": "Mail-Anrede",
    "konflikt.einstellung_mail_text": "Mail-Text",
    "konflikt.einstellung_mail_gruss": "Mail-Grußformel",
    "konflikt.einstellung_kalender": "Google Kalender",
    "konflikt.einstellung_kategorien": "Kategorien",
    "konflikt.einstellung_kategorie_zeiten": "Standardzeiten der Kategorien",
    "konflikt.einstellung_limit_aktiv": "Werkstudenten-Limit aktiv",
    "konflikt.einstellung_limit_beginn": "Werkstudenten-Limit Beginn",
    "konflikt.einstellung_limit_ende": "Werkstudenten-Limit Ende",
    "konflikt.einstellung_limit_stunden": "Werkstudenten-Limit Stunden/Woche",
    "konflikt.einstellung_pausenwarnung": "Pausenwarnung",
    "konflikt.einstellung_nur_werktage": "Nur Werktage",
}
