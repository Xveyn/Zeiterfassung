import pytest

from src.unpair_notice import unpair_notice_channel, unpair_notice_text, unpair_toast_text


@pytest.mark.parametrize("visible,tray,expected", [
    (True, True, "dialog"), (True, False, "dialog"),
    (False, True, "toast"), (False, False, "log"),
])
def test_the_channel_follows_window_and_tray(visible, tray, expected):
    assert unpair_notice_channel(window_visible=visible, tray_available=tray) == expected


def test_the_dialog_text_names_the_device_and_says_what_happened():
    title, body = unpair_notice_text("Pixel von Sven")
    assert "Pixel von Sven" in body and title
    assert "getrennt" in (title + body)


def test_the_toast_text_names_the_device():
    assert "Pixel" in unpair_toast_text("Pixel")


@pytest.mark.parametrize("name", ["", "   ", None])
def test_a_missing_name_becomes_ein_handy(name):
    assert "Ein Handy" in unpair_toast_text(name)
    assert "Ein Handy" in unpair_notice_text(name)[1]


def test_a_long_name_is_shortened_in_the_toast_and_the_toast_stays_short():
    text = unpair_toast_text("x" * 500)
    assert len(text) <= 120 and "x" * 41 not in text


def test_line_breaks_in_a_name_do_not_reach_the_toast():
    assert "\n" not in unpair_toast_text("Pixel\nzweite Zeile")


@pytest.mark.parametrize("builder", [unpair_toast_text, lambda n: " ".join(unpair_notice_text(n))])
def test_no_text_mentions_secrets(builder):
    for name in ("Pixel", "", "x" * 500):
        lowered = builder(name).lower()
        assert not any(word in lowered for word in ("token", "secret", "geheimnis", "schlüssel"))
