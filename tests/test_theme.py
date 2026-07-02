from src.theme import _click_keeps_focus, scaled_size


class _FakeWidget:
    def __init__(self, cls):
        self._cls = cls

    def winfo_class(self):
        return self._cls


def test_click_keeps_focus_for_input_widget():
    assert _click_keeps_focus(_FakeWidget("Entry")) is True
    assert _click_keeps_focus(_FakeWidget("TCombobox")) is True


def test_click_releases_focus_for_non_input_widget():
    assert _click_keeps_focus(_FakeWidget("Label")) is False
    assert _click_keeps_focus(_FakeWidget("Frame")) is False


def test_click_keeps_focus_handles_destroyed_widget_path_string():
    # Regression: ein während seines Klick-Events zerstörtes Widget (z.B. die
    # "×"-Schaltfläche einer Slot-Zeile) liefert event.widget als Pfad-String.
    # Darf NICHT crashen (AttributeError: 'str' has no 'winfo_class').
    assert _click_keeps_focus(".!toplevel.!frame.!label") is False


def test_scaled_size_scales_and_rounds():
    assert scaled_size(10, 1.5) == 15
    assert scaled_size(8, 1.5) == 12
    assert scaled_size(10, 1.0) == 10


def test_scaled_size_never_zero():
    # Sehr kleiner Faktor darf einen Font nicht auf 0 (unsichtbar) kollabieren.
    assert scaled_size(1, 0.1) == 1


def test_scaled_size_keeps_negative_sign():
    # Standard-Tk-Fonts können negative (Pixel-)Größen tragen — Vorzeichen bleibt.
    assert scaled_size(-10, 1.5) == -15
    assert scaled_size(-2, 0.1) == -1
