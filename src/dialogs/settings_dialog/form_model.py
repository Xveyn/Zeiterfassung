"""Tk-freie Logik des Einstellungs-Dialogs (#132).

Hier entscheidet sich, ob ein Tab ungespeicherte Änderungen hat
(`is_dirty`), und was beim Speichern, Verlassen eines Tabs und Schließen
des Dialogs geschieht (`SaveCoordinator`). Der Dialog selbst (`dialog.py`)
setzt diese Entscheidungen nur in Tk um.
"""

import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Literal, Protocol

# Nur schlichte Dezimalzahlen gelten als Zahl — "08:00", "nan" oder "1e3"
# bleiben Text. So wird aus einer Uhrzeit nie versehentlich eine Zahl.
_NUMBER = re.compile(r"-?\d+(\.\d+)?")


def normalize(value: Any) -> Any:
    """Vergleichsform eines Formularwerts.

    Ein Tk-Entry liefert Text, `settings.json` hält Zahlen: `"20"`, `20` und
    `20.0` sind derselbe gespeicherte Wert und dürfen nicht als Änderung
    zählen. Bools bleiben eigen (`True` ist hier nicht `1`), Zeilenenden
    werden vereinheitlicht (Tk-Text liefert `\\n`, eine alte Datei evtl.
    `\\r\\n`). Leerzeichen in Text bleiben signifikant — wer sie tippt,
    ändert etwas."""
    if isinstance(value, bool):
        return ("bool", value)
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        text = value.replace("\r\n", "\n")
        stripped = text.strip()
        if _NUMBER.fullmatch(stripped):
            return float(stripped)
        return text
    if isinstance(value, Mapping):
        return {key: normalize(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [normalize(item) for item in value]
    return value


def is_dirty(baseline: Mapping[str, Any], current: Mapping[str, Any]) -> bool:
    """True, wenn sich der Formularstand `current` vom gespeicherten Stand
    `baseline` unterscheidet (Vergleich über `normalize`). Ein fehlender oder
    zusätzlicher Schlüssel zählt als Änderung."""
    return normalize(baseline) != normalize(current)


SaveChoice = Literal["save", "discard", "cancel"]


@dataclass(frozen=True)
class SaveOutcome:
    """Ausgang von `SettingsTab.save`.

    `saved=False`: der Tab hat selbst abgebrochen (Autostart ließ sich nicht
    umschalten, Skalierungs-Rückfrage verneint) und seine Meldung schon
    gezeigt — geschrieben ist nichts, der Tab bleibt geändert.
    `restart`: die gespeicherte Änderung braucht einen Neustart (Skalierung)."""

    saved: bool
    restart: bool = False


class SettingsTab(Protocol):
    """Was der Coordinator von einem Tab braucht.

    `values()` ist der **rohe** Formularstand (was in den Feldern steht),
    nicht die Settings-Form: es läuft bei jedem Tastendruck und darf auch
    bei „abc" im Stundenfeld nicht werfen. Umgerechnet wird erst in `save()`."""

    title: str

    def values(self) -> dict[str, Any]: ...

    def validate(self) -> tuple[str, str] | None: ...

    def save(self) -> SaveOutcome: ...

    def load(self, values: Mapping[str, Any]) -> None: ...


class SaveCoordinator:
    """Speichern je Tab (#132): hält je Tab den zuletzt gespeicherten Stand
    (Baseline) und entscheidet, ob ein Tab-Wechsel oder das Schließen
    erlaubt ist.

    Gefragt wird nur nach dem **aktiven** Tab — andere können keine
    Änderungen tragen, weil sie nur über dieses Tor verlassen werden.
    `ask`, `show_error`, `on_change` und `on_restart` sind injiziert; der
    Coordinator kennt kein Tk. `on_restart` beendet den Dialog: danach
    liefern `request_switch`/`request_close` `False`, damit der Aufrufer
    nichts mehr an einem zerstörten Fenster tut. `save_current` meldet den
    Neustart dagegen als Erfolg — der Speichern-Knopf fragt deshalb `closed`,
    bevor er den Dialog anfasst (nach dem Neustart ist der Tcl-Interpreter
    weg, schon `winfo_exists` wirft dann)."""

    def __init__(self, tabs: Mapping[str, SettingsTab], current: str, *,
                 ask: Callable[[str], SaveChoice],
                 show_error: Callable[[str, str], None],
                 on_change: Callable[[], None],
                 on_restart: Callable[[], None]) -> None:
        if current not in tabs:
            raise KeyError(current)
        self._tabs = dict(tabs)
        self._current = current
        self._ask = ask
        self._show_error = show_error
        self._on_change = on_change
        self._on_restart = on_restart
        self._closed = False
        self._baselines: dict[str, dict[str, Any]] = {
            key: dict(tab.values()) for key, tab in self._tabs.items()}

    @property
    def current(self) -> str:
        return self._current

    @property
    def closed(self) -> bool:
        """True, sobald `on_restart` den Dialog abgebaut hat."""
        return self._closed

    def dirty(self, key: str | None = None) -> bool:
        """Hat der Tab `key` (Default: der aktive) ungespeicherte Änderungen?"""
        key = self._current if key is None else key
        return is_dirty(self._baselines[key], self._tabs[key].values())

    def rebaseline(self, key: str, fields: Iterable[str] | None = None) -> None:
        """Übernimmt den aktuellen Stand als gespeichert — für Werte, die im
        Hintergrund nachgeladen werden (Kalenderliste). Mit `fields` nur diese
        Felder: eine Änderung, die der Nutzer in der Zwischenzeit an einem
        anderen Feld gemacht hat, bleibt eine Änderung."""
        current = self._tabs[key].values()
        if fields is None:
            self._baselines[key] = dict(current)
            return
        for field in fields:
            if field in current:
                self._baselines[key][field] = current[field]

    def save_current(self) -> bool:
        """Knopf „Speichern": ohne Rückfrage. True, wenn danach nichts
        Ungespeichertes mehr übrig ist (auch: es gab nichts zu speichern)."""
        if not self.dirty():
            return True
        return self._save(self._current) != "failed"

    def request_switch(self, target: str) -> bool:
        """Darf auf `target` gewechselt werden? Bei True ist `target` aktiv."""
        if target not in self._tabs:
            raise KeyError(target)
        if target == self._current:
            return True
        if not self._leave():
            return False
        self._current = target
        return True

    def request_close(self) -> bool:
        """Darf der Dialog geschlossen werden?"""
        return self._leave()

    def _leave(self) -> bool:
        key = self._current
        if not self.dirty(key):
            return True
        choice = self._ask(self._tabs[key].title)
        if choice == "discard":
            self._tabs[key].load(self._baselines[key])
            return True
        if choice == "save":
            return self._save(key) == "saved"
        return False

    def _save(self, key: str) -> Literal["saved", "failed", "restart"]:
        tab = self._tabs[key]
        error = tab.validate()
        if error is not None:
            self._show_error(*error)
            return "failed"
        outcome = tab.save()
        if not outcome.saved:
            return "failed"
        self._baselines[key] = dict(tab.values())
        self._on_change()
        if outcome.restart:
            self._closed = True
            self._on_restart()
            return "restart"
        return "saved"
