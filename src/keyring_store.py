"""Passwörter im OS-Schlüsselbund, mit Datei-Fallback (Tk-frei).

Windows Credential Manager / macOS Keychain / Linux Secret Service. Ist kein
Backend verfügbar — Linux ohne laufenden Secret Service, `keyring` gar nicht
installiert, oder der Schlüsselbund antwortet nicht —, meldet `set_secret` das
ehrlich als `"file"` zurück; der Aufrufer legt das Passwort dann in seinen
eigenen, gehärtet geschriebenen Store und zeigt es dem Nutzer an.

`import keyring` steht bewusst INNERHALB der Funktionen: die Importkette
`src.ui → … → smtp_store → keyring_store` zöge die Lib sonst in die CI, die
bewusst nur `requirements-test.txt` installiert (gleiches Muster wie die
Google-Wrapper in drive.py/gcal.py).

**Warum jeder Zugriff hinter einem Watchdog läuft:** Auf Linux meldet sich das
SecretService-Backend schon dann als nutzbar, wenn der D-Bus-Name lediglich
*aktivierbar* ist — im AppImage-Fall also praktisch immer. `keyring` ruft dann
`collection.unlock()` OHNE Timeout, obwohl SecretStorage einen anbietet;
blockiert das (gesperrter Schlüsselbund, kein Prompt), kehrt der Aufruf nie
zurück. Da diese Funktionen aus `BackgroundTaskRunner`-Workern gerufen werden
und der Runner `on_done` erst nach der Rückkehr von `fn()` ruft, stünde der
Sende-Dialog dauerhaft auf „Sende…" — bis zum App-Neustart. Genau dieser
Ausfall ist in pip (#7883) und poetry (#8623) dokumentiert.
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Callable

log = logging.getLogger(__name__)

SERVICE = "Zeiterfassung"

# Der Watchdog schützt gegen ein BLOCKIERENDES `collection.unlock()` ohne
# Prompt (s. Docstring oben) — nicht gegen einen langsamen Menschen. Bei
# einem echten Keychain-Prompt wartet man auf jemanden, der einen Dialog
# liest und sein Anmeldepasswort tippt; 5s reichen dafür nicht annähernd
# (macOS nach einem App-Update: ad-hoc-Signatur, geänderter cdhash, der
# Prompt kommt erneut). Die Wartezeit sitzt ohnehin im Worker-Thread, nicht
# im UI — ein längerer Timeout kostet hier nichts außer Geduld.
WATCHDOG_TIMEOUT = 30.0


def _call_guarded(work: Callable[[], Any]) -> tuple[bool, Any]:
    """Ruft `work` in einem Sekundär-Thread und gibt nach `WATCHDOG_TIMEOUT`
    auf.

    Liefert `(True, ergebnis)` bei rechtzeitiger Rückkehr, sonst
    `(False, None)`. Eine Exception aus `work` wird im Aufrufer-Thread erneut
    geworfen. Der Thread ist ein Daemon: bleibt er hängen, blockiert er das
    Beenden der App nicht.
    """
    box: dict[str, Any] = {}

    def runner() -> None:
        try:
            box["value"] = work()
        except BaseException as exc:  # bewusst alles — wird unten weitergereicht
            # Asymmetrisch zu den drei öffentlichen Funktionen (die fangen nur
            # `Exception`): das ist Absicht, nicht ein übersehener Fall. Hier
            # muss JEDE Exception aus dem Sekundär-Thread eingefangen werden,
            # sonst entkäme sie unbehandelt aus einem Thread ohne eigenen
            # Excepthook. Der Aufrufer (set_secret/get_secret/delete_secret)
            # fängt dagegen bewusst nur `Exception` und lässt
            # KeyboardInterrupt/SystemExit durch — die sollen nicht als "kein
            # Schlüsselbund verfügbar" verschluckt werden, sondern die App wie
            # gewohnt beenden.
            box["error"] = exc

    thread = threading.Thread(target=runner, daemon=True,
                              name="keyring-watchdog")
    thread.start()
    thread.join(WATCHDOG_TIMEOUT)
    if thread.is_alive():
        return False, None
    if "error" in box:
        raise box["error"]
    return True, box.get("value")


def set_secret(record_id: str, password: str) -> str:
    """Legt `password` im Schlüsselbund ab.

    Liefert `"keyring"` bei Erfolg, sonst `"file"` — dieser Wert gehört als
    `password_location` in den Datensatz des Aufrufers.
    """
    def work() -> None:
        import keyring  # pyright: ignore[reportMissingImports]

        keyring.set_password(SERVICE, record_id, password)

    try:
        ok, _ = _call_guarded(work)
    except Exception:
        # Bewusst alles: NoKeyringError, ein fehlgeschlagener D-Bus-Aufruf,
        # eine gar nicht installierte Lib. Für den Aufrufer ist all das
        # dasselbe — es gibt keinen Schlüsselbund.
        log.warning("Schlüsselbund nicht verfügbar — Passwort wird lokal "
                    "in der Konfigurationsdatei abgelegt", exc_info=True)
        return "file"
    if not ok:
        log.warning("Schlüsselbund antwortet nicht (Timeout nach %.1fs) — "
                    "Passwort wird lokal abgelegt", WATCHDOG_TIMEOUT)
        return "file"
    return "keyring"


def get_secret(record: dict[str, Any]) -> str | None:
    """Liest das Passwort zu `record`.

    Steht `password_location` auf `"file"`, wird der Schlüsselbund gar nicht
    erst gefragt — das spart auf Linux einen D-Bus-Roundtrip, der ohnehin
    nichts liefern würde. Für diesen Fall ist eine leere Zurückgabe ein
    gültiger Zustand (Relay ohne Auth) und liefert immer `str`, nie `None`.

    Für den Schlüsselbund-Fall liefert die Funktion **`None`**, wenn sich
    NICHT ermitteln ließ, ob ein Passwort existiert (Timeout oder eine
    Exception aus `work`) UND `record` keine lokale Fallback-Kopie trägt.
    Das ist bewusst von einem tatsächlich leeren Passwort unterschieden
    (`""`, wenn der Schlüsselbund erfolgreich geantwortet und „nichts
    gespeichert" gesagt hat): ein Aufrufer, der `None` mit `""` verwechselt,
    meldet sich sonst mit einem leeren Passwort beim Server an — der Server
    antwortet 535, und der Nutzer sucht beim Passwort, obwohl der
    Schlüsselbund das Problem war (genau der Fehler, der `WATCHDOG_TIMEOUT`
    beim Hochsetzen abgefangen werden sollte, aber allein nicht abfängt).
    Jeder Aufrufer MUSS `None` prüfen und darf sich damit nicht anmelden.
    """
    if record.get("password_location") == "file":
        return record.get("password") or ""

    def work() -> Any:
        import keyring  # pyright: ignore[reportMissingImports]

        return keyring.get_password(SERVICE, record.get("id", ""))

    try:
        ok, stored = _call_guarded(work)
    except Exception:
        log.warning("Schlüsselbund nicht lesbar — greife auf die lokal "
                    "abgelegte Kopie zurück, falls vorhanden", exc_info=True)
        return record.get("password") or None
    if not ok:
        log.warning("Schlüsselbund antwortet nicht (Timeout nach %.1fs)",
                    WATCHDOG_TIMEOUT)
        return record.get("password") or None
    if stored:
        return str(stored)
    return record.get("password") or ""


def delete_secret(record_id: str) -> None:
    """Räumt das Secret ab. Fehlt es, ist das kein Fehler.

    Muss beim Löschen eines Kontos gerufen werden — sonst bliebe der Eintrag
    für immer im Schlüsselbund stehen, unter einer id, die in keiner Datei
    mehr steht.
    """
    def work() -> None:
        import keyring  # pyright: ignore[reportMissingImports]

        keyring.delete_password(SERVICE, record_id)

    try:
        ok, _ = _call_guarded(work)
    except Exception:
        # Bewusst OHNE die record_id: sie wird aus einem Datensatz gelesen,
        # der im Datei-Fallback das Klartext-Passwort trägt. Ein Feld aus
        # so einem Dict gehört nicht ins Log — logs/zeiterfassung.log ist
        # ungehärtet und genau die Datei, die Nutzer bei Problemen anhängen.
        # (CodeQL flaggt den Zugriff entsprechend, py/clear-text-logging.)
        log.debug("Ein Secret ließ sich nicht löschen (kein Schlüsselbund "
                  "oder kein Eintrag)", exc_info=True)
        return
    if not ok:
        # Ebenfalls ohne die record_id, s. o.
        log.warning("Schlüsselbund antwortet nicht — ein Secret blieb stehen")


def persist_password(candidate: dict[str, Any], typed: str,
                     stored: dict[str, Any] | None = None) -> dict[str, Any]:
    """Entscheidet, wo das Passwort landet, und legt es ab.

    Vier Fälle, und alle vier gehören hierher statt in eine Dialog-Closure —
    sonst lebte die Regel nur im Widget und wäre durch nichts gedeckt
    (CLAUDE.md, „Getestet wird Logik, nicht UI").

    - `typed` gefüllt → in den Schlüsselbund; klappt das nicht, in den
      Datensatz (`password_location="file"`).
    - `typed` leer → unverändert: `stored` bestimmt Ort und Wert. Bei einem
      bestehenden Datei-Fallback wird das dort abgelegte Passwort übernommen,
      sonst bliebe es beim nächsten Speichern weg.
    - Kein `stored` (neues Konto ohne Passwort) → `keyring`, kein `password`.

    Verändert `candidate` nicht.
    """
    result = dict(candidate)
    if typed:
        location = set_secret(result["id"], typed)
        result["password_location"] = location
        if location == "file":
            result["password"] = typed
        else:
            result.pop("password", None)
        return result

    location = (stored or {}).get("password_location", "keyring")
    result["password_location"] = location
    if location == "file":
        result["password"] = (stored or {}).get("password", "")
    else:
        result.pop("password", None)
    return result
