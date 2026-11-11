# pyright: reportOptionalMemberAccess=true
"""Bereich „hauptfenster“: Kalender, Kopf- und Fußzeile, Tooltips und Tray-Menü."""

TEXTS: dict[str, str] = {
    # Tray-Menü (Basis-Einträge; die Quick-Actions liefert `App._tray_actions`).
    "tray.anzeigen": "Anzeigen",
    "tray.beenden": "Beenden",
    # Tray-Startfehler: erscheinen im Dialog „Infobereich-Icon“ (`App._apply_tray_setting`).
    "tray.nicht_unterstuetzt": "Tray auf dieser Plattform nicht unterstützt",
    "tray.kein_watcher": "Kein StatusNotifierWatcher hat innerhalb von {sekunden}s geantwortet — läuft ein SNI-fähiger Desktop (KDE Plasma)?",
    "tray.busname_belegt": "Busname {name} ist bereits belegt (Antwort: {antwort}) — läuft die Zeiterfassung doppelt?",
    "tray.keine_antwort": "keine Antwort",
    "tray.registrierung_abgelehnt": "StatusNotifierWatcher lehnte die Registrierung ab: {detail}",
}
