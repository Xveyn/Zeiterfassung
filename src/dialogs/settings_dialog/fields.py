"""Die Formularfelder eines Einstellungs-Tabs als ein Dict (#132).

Ein Tab registriert seine Tk-Variablen und Textfelder unter einem Schlüssel;
daraus entstehen `values()` (der rohe Formularstand, den der
`SaveCoordinator` mit der Baseline vergleicht) und `load()` (Verwerfen).
Jede Änderung meldet `on_edit` — daran hängt der Speichern-Knopf.

Bewusst ohne `import tkinter`: gebraucht wird nur die Schnittstelle von
`tk.Variable` (`get`/`set`/`trace_add`) und `tk.Text`. So lässt sich das
Modul mit Attrappen testen, obwohl es Tk-Objekte verwaltet.
"""

from collections.abc import Callable, Mapping
from typing import Any


class FieldSet:
    """Schlüssel → Tk-Variable bzw. Textfeld, in Registrierungsreihenfolge."""

    def __init__(self) -> None:
        # Ein Dict statt zweier: die Reihenfolge über beide Arten hinweg ist
        # die von `load` (s. dort).
        self._fields: dict[str, tuple[str, Any, Callable[[Any], Any] | None]] = {}
        self._listeners: list[Callable[[], None]] = []

    def add(self, key: str, var: Any, *,
            read: Callable[[Any], Any] | None = None) -> Any:
        """Registriert eine Tk-Variable. `read` bildet den gelesenen Wert auf
        seine Vergleichsform ab (Schieberegler: auf 5er-Schritte gerastert,
        sonst wäre ein hin- und zurückgezogener Regler „geändert")."""
        self._check_new(key)
        self._fields[key] = ("var", var, read)
        var.trace_add("write", self._on_var_write)
        return var

    def add_text(self, key: str, widget: Any) -> Any:
        """Registriert ein `tk.Text`. Aufrufen, NACHDEM der Anfangstext
        eingefügt ist — das Einfügen setzt das Modified-Flag, das hier
        zurückgesetzt wird."""
        self._check_new(key)
        self._fields[key] = ("text", widget, None)
        widget.edit_modified(False)
        widget.bind("<<Modified>>", self._on_text_modified, add="+")
        return widget

    def on_edit(self, callback: Callable[[], None]) -> None:
        self._listeners.append(callback)

    def keys(self) -> list[str]:
        return list(self._fields)

    def values(self) -> dict[str, Any]:
        """Roher Formularstand — ohne Parsen, darf nicht werfen."""
        out: dict[str, Any] = {}
        for key, (kind, obj, read) in self._fields.items():
            if kind == "text":
                out[key] = obj.get("1.0", "end-1c")
                continue
            value = obj.get()
            out[key] = read(value) if read is not None else value
        return out

    def load(self, values: Mapping[str, Any]) -> None:
        """Setzt die Felder auf `values` — in **Registrierungsreihenfolge**,
        nicht in der des Dicts: die Datumszeile klemmt den Tag bei jedem
        Schreibzugriff auf die Monatslänge, ein Tag vor seinem Monat würde
        also verfälscht. Unbekannte Schlüssel werden übergangen."""
        for key, (kind, obj, _read) in self._fields.items():
            if key not in values:
                continue
            if kind == "text":
                obj.delete("1.0", "end")
                obj.insert("1.0", values[key])
            else:
                obj.set(values[key])

    def _check_new(self, key: str) -> None:
        if key in self._fields:
            raise ValueError(f"Feld {key!r} ist schon registriert")

    def _on_var_write(self, *_args: Any) -> None:
        self._notify()

    def _on_text_modified(self, event: Any) -> None:
        # tk.Text meldet <<Modified>> nur, wenn das Flag WECHSELT. Ohne
        # Zurücksetzen käme also nur der erste Tastendruck an. Das
        # Zurücksetzen löst selbst wieder <<Modified>> aus — das fängt die
        # Abfrage des Flags ab.
        widget = event.widget
        if not widget.edit_modified():
            return
        widget.edit_modified(False)
        self._notify()

    def _notify(self) -> None:
        for callback in list(self._listeners):
            callback()
