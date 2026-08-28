"""Guards für die Deinstallations-Bereinigung in `installer.iss` (#50).

Kein echter Setup-Lauf — Inno Setup fehlt auf den Test-Runnern (und lokal
meistens auch), gebaut wird der Installer nur in `release.yml` bzw. im
Build-Workflow mit gesetztem `installer`-Häkchen. Was sich hier prüfen lässt,
ist die statische Zusicherung: dass die Zugangsdaten überhaupt in der
Löschliste stehen und die Autostart-Bereinigung nicht wieder an den Setup-Task
gekoppelt wird.

Genau das war der Fehler aus #50 — `token.json` überlebte die Deinstallation,
und der Registry-Wert blieb stehen, wenn der Autostart erst in der App
eingeschaltet wurde. Beides ist unsichtbar, bis jemand deinstalliert, und
deshalb hier festgenagelt.

Der Test kann NICHT prüfen, ob der Uninstaller tatsächlich sauber räumt —
dafür braucht es einen gebauten Setup und einen echten Durchlauf.
"""

import pathlib
import re

_ISS = pathlib.Path(__file__).resolve().parent.parent / "installer.iss"


def _text():
    return _ISS.read_text(encoding="utf-8")


def _section(name):
    """Inhalt eines .iss-Abschnitts ohne dessen Kopfzeile."""
    body = _text()
    start = body.index(f"[{name}]") + len(name) + 2
    rest = body[start:]
    nxt = re.search(r"^\[[A-Za-z]+\]", rest, re.MULTILINE)
    return rest[: nxt.start()] if nxt else rest


# Zugangsdaten: kein Nutzerinhalt, sondern laufender Zugriff bzw. Secrets.
# Die müssen IMMER weg — ohne Rückfrage, sonst überlebt ein OAuth-Refresh-Token
# die Deinstallation.
CREDENTIAL_FILES = ["token.json", "instance-secret", "webhooks.json", "credentials.json"]

# Nutzerdaten: nur nach Rückfrage, dafür vollständig.
USER_DATA_FILES = [
    "zeiterfassung.json", "reservations.json", "settings.json",
    "conflicts.json", "sync_history.json", "sync-apply.journal",
]


class TestUninstallDelete:
    def test_section_exists(self):
        assert "[UninstallDelete]" in _text()

    def test_every_credential_file_is_deleted_unconditionally(self):
        section = _section("UninstallDelete")
        for name in CREDENTIAL_FILES:
            assert f'Name: "{{app}}\\{name}"' in section, name

    def test_no_wildcard_over_the_app_folder(self):
        """Die Inno-Doku warnt ausdrücklich davor: der Nutzer könnte eigene
        Dateien dort abgelegt haben, und bei einer versehentlichen Installation
        in ein Systemverzeichnis wäre ein Wildcard fatal."""
        section = _section("UninstallDelete")
        assert "*" not in section


class TestUninstallCode:
    def test_autostart_registry_value_is_removed(self):
        code = _section("Code")
        assert "RegDeleteValue(HKEY_CURRENT_USER" in code
        assert "CurrentVersion\\Run" in code

    def test_registry_cleanup_is_not_tied_to_the_setup_task(self):
        """Der Kern von #50: der [Registry]-Eintrag trägt `uninsdeletevalue`,
        hängt aber an `Tasks: autostart`. Wer den Task nicht wählt und den
        Autostart später in der App einschaltet, hinterlässt einen Wert, von
        dem der Uninstaller nichts weiß. Die Bereinigung im Code darf deshalb
        nicht ihrerseits an einer Task-Bedingung hängen."""
        code = _section("Code")
        registry_line = next(
            line for line in code.splitlines() if "RegDeleteValue" in line)
        assert "Tasks" not in registry_line
        assert "WizardIsTaskSelected" not in code

    def test_user_data_is_deleted_only_after_asking(self):
        code = _section("Code")
        assert "MsgBox" in code and "MB_YESNO" in code
        for name in USER_DATA_FILES:
            assert name in code, name

    def test_silent_uninstall_does_not_prompt(self):
        """Ohne die Abfrage bliebe ein /SILENT-Uninstall an einer Dialogbox
        hängen. Nicht fragen heißt hier zugleich: nichts löschen."""
        assert "UninstallSilent" in _section("Code")

    def test_app_folder_is_removed_only_when_empty(self):
        """RemoveDir statt DelTree auf {app}: wer seine Daten behält, behält
        auch den Ordner."""
        code = _section("Code")
        assert "RemoveDir(ExpandConstant('{app}'))" in code
        assert "DelTree(ExpandConstant('{app}')" not in code


class TestPascalSyntax:
    def test_code_section_uses_pascal_comments(self):
        """Innerhalb von [Code] ist die Sprache Pascal — dort leitet `;` keinen
        Kommentar ein, sondern wäre ein Syntaxfehler. Nur die übrigen
        .iss-Abschnitte kommentieren mit `;`."""
        for line in _section("Code").splitlines():
            assert not line.strip().startswith(";"), line
