"""_hover faerbt Frame, uebergebene Labels und vorhandene Eck-Overlays."""

from src.ui import App


class _FakeWidget:
    def __init__(self):
        self.bg = None

    def config(self, bg):
        self.bg = bg


def test_hover_colors_frame_and_labels():
    frame, day, time = _FakeWidget(), _FakeWidget(), _FakeWidget()
    App._hover(frame, "#123456", day, time)
    assert frame.bg == "#123456"
    assert day.bg == "#123456"
    assert time.bg == "#123456"


def test_hover_colors_overlay_widgets_when_present():
    frame = _FakeWidget()
    frame._reservation_marker = _FakeWidget()
    frame._delete_button = _FakeWidget()
    App._hover(frame, "#abcdef")
    assert frame._reservation_marker.bg == "#abcdef"
    assert frame._delete_button.bg == "#abcdef"


def test_hover_without_overlays_does_not_fail():
    frame, day = _FakeWidget(), _FakeWidget()
    App._hover(frame, "#000000", day)
    assert frame.bg == "#000000"
    assert day.bg == "#000000"
