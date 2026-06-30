import datetime

from src.dialogs.entry_dialog import reservation_block_visible


TODAY = datetime.date(2026, 6, 26)


def test_reservation_block_hidden_for_past_day():
    """Vergangene Tage: kein Reservierungs-Block — auch nicht, wenn dort bereits
    eine Reservierung liegt. Linksklick darf keine neue Reservierung anlegen."""
    assert reservation_block_visible(datetime.date(2026, 6, 25), TODAY) is False
    assert reservation_block_visible(datetime.date(2026, 6, 25), TODAY,
                                     has_reservation=True) is False


def test_reservation_block_visible_today():
    assert reservation_block_visible(TODAY, TODAY) is True


def test_reservation_block_visible_future():
    assert reservation_block_visible(datetime.date(2026, 6, 27), TODAY) is True
