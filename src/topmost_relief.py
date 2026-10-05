"""„Immer im Vordergrund" kurz aufheben, solange der Schlüsselbund fragt
(Xveyn#186).

Der Passwort-Dialog des Systems (KWallet/GNOME Keyring unter Linux) ist ein
normales Fenster und liegt unter einem `-topmost`-Hauptfenster: man sieht ihn
nicht und kann das Passwort nicht eingeben; nach 30 s greift der Watchdog in
`keyring_store`, und das Secret gilt als nicht lesbar.

Deshalb hebt die App das Topmost auf, solange ein Zugriff **länger als eine
kurze Schwelle** läuft, und setzt es danach auf den Wert der Einstellung
zurück. Die Schwelle verhindert das Blinken: ein schneller Treffer ohne
Nachfrage lässt das Fenster unangetastet.

Tk-frei: Setzen des Attributs und Zeitplanung kommen als Callables herein
(in der App `root.after`/`root.after_cancel`), die Entscheidungslogik ist so
ohne Tk testbar. Alle Methoden laufen im UI-Thread — der Hook von
`keyring_store` meldet aus dem Worker und wird von der App übergeben.
"""

from typing import Any, Callable

# Wie lange ein Zugriff dauern muss, bevor das Topmost fällt. Ein Zugriff
# ohne Nachfrage ist in Millisekunden durch; ein Passwort-Prompt dauert, bis
# jemand tippt.
RELIEF_DELAY_MS = 300


class TopmostRelief:
    def __init__(self, set_topmost: Callable[[bool], None],
                 wanted: Callable[[], bool],
                 schedule: Callable[[int, Callable[[], None]], Any],
                 cancel: Callable[[Any], None],
                 delay_ms: int = RELIEF_DELAY_MS) -> None:
        self._set_topmost = set_topmost
        # Der Wert der Einstellung — bei jedem Zugriff frisch gelesen, denn
        # der Nutzer kann ihn ändern, während das Topmost gerade aufgehoben ist.
        self._wanted = wanted
        self._schedule = schedule
        self._cancel = cancel
        self._delay_ms = delay_ms
        self._active = False
        self._pending: Any = None
        self._lifted = False

    @property
    def lifted(self) -> bool:
        """Ist das Topmost gerade wegen eines Schlüsselbund-Zugriffs weg?"""
        return self._lifted

    def effective(self) -> bool:
        """Was am Fenster stehen soll: der Wunsch, außer es ist aufgehoben.
        Für `App._apply_always_on_top`, damit ein Speichern der Einstellungen
        mitten im Prompt das Topmost nicht wieder zurückholt."""
        return self._wanted() and not self._lifted

    def activity(self, active: bool) -> None:
        """Ein Schlüsselbund-Zugriff beginnt (`True`) bzw. alle sind fertig."""
        self._active = active
        if active:
            if self._lifted or self._pending is not None:
                return
            self._pending = self._schedule(self._delay_ms, self._after_delay)
            return
        if self._pending is not None:
            self._cancel(self._pending)
            self._pending = None
        if self._lifted:
            self._lifted = False
            self._set_topmost(self._wanted())

    def _after_delay(self) -> None:
        self._pending = None
        if self._active and self._wanted():
            self._lifted = True
            self._set_topmost(False)


def activity_hook(marshal: Callable[..., None],
                  relief: TopmostRelief) -> Callable[[bool], None]:
    """Der Hook für `keyring_store.set_activity_hook`: reicht den Übergang
    auf den UI-Thread und an `relief.activity`.

    Marshallt mit `force=True`: während „Zeiterfassung entfernen“ (#211)
    verwirft `App._marshal_to_ui` sonst jeden fremden Callback — und genau
    dann fragt der Schlüsselbund nach dem Passwort. Der Callback schreibt
    keine Daten, er stellt nur das Fensterattribut um; die Sperre soll
    Update-Check & Co. aufhalten, nicht diesen."""
    def hook(active: bool) -> None:
        marshal(lambda: relief.activity(active), force=True)
    return hook
