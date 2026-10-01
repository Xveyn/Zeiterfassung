"""TopmostRelief (Xveyn#186): „Immer im Vordergrund" fällt, solange ein
Schlüsselbund-Zugriff länger als die Schwelle läuft, und kommt danach zurück.

Kein Tk: Zeitplanung und Setzen des Attributs sind Fakes, `tick()` lässt die
Schwelle verstreichen.
"""

from src.topmost_relief import RELIEF_DELAY_MS, TopmostRelief


class _Harness:
    def __init__(self, wanted=True):
        self.wanted = wanted
        self.calls = []            # jeder set_topmost-Aufruf
        self.scheduled = []        # (id, delay, fn)
        self.cancelled = []
        self.relief = TopmostRelief(
            self.calls.append, lambda: self.wanted, self._schedule, self.cancelled.append)

    def _schedule(self, delay, fn):
        entry = (len(self.scheduled), delay, fn)
        self.scheduled.append(entry)
        return entry[0]

    def tick(self):
        """Die Schwelle verstreicht: alles Geplante, das nicht abgebrochen
        wurde, feuert."""
        for ident, _, fn in list(self.scheduled):
            if ident not in self.cancelled:
                fn()
        self.scheduled.clear()


def test_a_quick_access_never_touches_the_window():
    """Ohne Nachfrage ist der Zugriff in Millisekunden durch — das Fenster darf
    dabei nicht blinken."""
    h = _Harness()

    h.relief.activity(True)
    h.relief.activity(False)
    h.tick()

    assert h.calls == []
    assert h.relief.lifted is False


def test_the_threshold_is_the_documented_one():
    h = _Harness()
    h.relief.activity(True)
    assert h.scheduled[0][1] == RELIEF_DELAY_MS == 300


def test_a_slow_access_lifts_topmost_and_restores_it_afterwards():
    h = _Harness()

    h.relief.activity(True)
    h.tick()
    assert h.calls == [False]
    assert h.relief.lifted is True

    h.relief.activity(False)
    assert h.calls == [False, True]
    assert h.relief.lifted is False


def test_restoring_follows_the_setting_at_that_moment():
    """Schaltet der Nutzer die Einstellung aus, während der Prompt offen ist,
    darf das Ende des Zugriffs das Topmost nicht wieder setzen."""
    h = _Harness()
    h.relief.activity(True)
    h.tick()

    h.wanted = False
    h.relief.activity(False)

    assert h.calls == [False, False]


def test_nothing_is_lifted_when_the_setting_is_off():
    h = _Harness(wanted=False)

    h.relief.activity(True)
    h.tick()
    h.relief.activity(False)

    assert h.calls == []


def test_ending_before_the_threshold_cancels_the_pending_check():
    h = _Harness()
    h.relief.activity(True)

    h.relief.activity(False)

    assert h.cancelled == [0]
    h.tick()
    assert h.calls == []


def test_a_second_start_does_not_schedule_twice_or_lift_twice():
    h = _Harness()
    h.relief.activity(True)
    h.relief.activity(True)
    assert len(h.scheduled) == 1

    h.tick()
    h.relief.activity(True)

    assert h.calls == [False]
    assert len(h.scheduled) == 0


def test_effective_is_false_while_lifted_even_if_the_setting_is_on():
    """`App._apply_always_on_top` fragt das: ein Speichern der Einstellungen
    mitten im Prompt darf das Topmost nicht zurückholen."""
    h = _Harness()
    assert h.relief.effective() is True

    h.relief.activity(True)
    h.tick()
    assert h.relief.effective() is False

    h.relief.activity(False)
    assert h.relief.effective() is True


def test_effective_follows_the_setting_when_not_lifted():
    h = _Harness(wanted=False)
    assert h.relief.effective() is False


def test_a_new_access_after_a_restore_lifts_again():
    h = _Harness()
    h.relief.activity(True)
    h.tick()
    h.relief.activity(False)

    h.relief.activity(True)
    h.tick()

    assert h.calls == [False, True, False]
