# pyright: reportOptionalMemberAccess=true
"""Bereich „meldungen“: Meldungsdialoge, Toasts, Banner und Tray."""

TEXTS: dict[str, str] = {
    # Fehlende OAuth-Client-Datei; der Text reist über `str(e)` in Dialog und Statuszeile.
    "meldungen.credentials_fehlen": "credentials.json nicht gefunden unter:\n{pfad}",
}
