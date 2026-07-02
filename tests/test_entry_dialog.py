import datetime

from src.dialogs.entry_dialog import (
    NO_CATEGORY_LABEL, category_choices, category_from_display,
    category_to_display, reservation_block_visible,
)


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


def test_category_empty_maps_to_no_category_label_and_back():
    # "" (keine Kategorie) ↔ Anzeige-Label, damit der Platzhalter nie als echte
    # Kategorie gespeichert wird.
    assert category_to_display("") == NO_CATEGORY_LABEL
    assert category_from_display(NO_CATEGORY_LABEL) == ""


def test_category_real_value_round_trips_unchanged():
    assert category_to_display("Office") == "Office"
    assert category_from_display("Office") == "Office"


def test_category_choices_puts_no_category_first():
    assert category_choices(["Office", "Homeoffice"]) == [
        NO_CATEGORY_LABEL, "Office", "Homeoffice"]
    # Keine Kategorien in den Einstellungen → nur der Platzhalter.
    assert category_choices([]) == [NO_CATEGORY_LABEL]
