import datetime

from src.dialogs.entry_dialog import (
    NO_CATEGORY_LABEL, category_choices, category_from_display,
    category_to_display, plan_entry_save, reservation_block_visible,
    slot_category_display, suggest_ist_category,
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


def test_category_from_display_strips_trailing_override_marker():
    assert category_from_display("Office*") == "Office"
    assert category_from_display("Office") == "Office"
    assert category_from_display(NO_CATEGORY_LABEL) == ""


class TestSuggestIstCategory:
    """Kategorie-Vorschlag für die neu vorbelegte Ist-Zeit-Zeile, wenn noch
    keine Ist-Zeit existiert, aber eine Reservierung — nur bei GENAU EINEM
    Reservierungs-Slot (bei mehreren wäre unklar, welcher Slot die Kategorie
    der einen vorgeschlagenen Zeile bestimmen sollte)."""

    def test_single_slot_with_category_is_suggested(self):
        slots = [{"start": "09:30", "end": "17:00", "kategorie": "Office"}]
        assert suggest_ist_category(slots) == "Office"

    def test_single_slot_without_category_suggests_empty(self):
        slots = [{"start": "09:30", "end": "17:00", "kategorie": ""}]
        assert suggest_ist_category(slots) == ""

    def test_single_slot_missing_kategorie_key_suggests_empty(self):
        slots = [{"start": "09:30", "end": "17:00"}]
        assert suggest_ist_category(slots) == ""

    def test_multiple_slots_suggest_nothing_even_with_category(self):
        slots = [
            {"start": "08:00", "end": "12:00", "kategorie": "Office"},
            {"start": "13:00", "end": "17:00", "kategorie": "Homeoffice"},
        ]
        assert suggest_ist_category(slots) == ""

    def test_empty_slot_list_suggests_nothing(self):
        assert suggest_ist_category([]) == ""


class TestSlotCategoryDisplay:
    """Kategorie-Dropdown zeigt ein '*' an, wenn die Slot-Zeiten manuell von
    den für diese Kategorie hinterlegten Standardzeiten abweichen — reine
    Anzeige, der persistierte Kategoriewert bleibt sauber (category_from_display
    strippt das Sternchen wieder ab)."""

    CATEGORY_TIMES = {"Office": {"start": "09:00", "end": "17:00", "pause": 30}}

    def test_no_category_shows_placeholder_without_marker(self):
        result = slot_category_display(
            "", "08:00", "16:00", 30, self.CATEGORY_TIMES, "mon",
            "08:00", "16:00", 30,
        )
        assert result == NO_CATEGORY_LABEL

    def test_matching_times_show_plain_category_name(self):
        result = slot_category_display(
            "Office", "09:00", "17:00", 30, self.CATEGORY_TIMES, "mon",
            "08:00", "16:00", 30,
        )
        assert result == "Office"

    def test_overridden_start_appends_marker(self):
        result = slot_category_display(
            "Office", "07:30", "17:00", 30, self.CATEGORY_TIMES, "mon",
            "08:00", "16:00", 30,
        )
        assert result == "Office*"

    def test_overridden_end_appends_marker(self):
        result = slot_category_display(
            "Office", "09:00", "18:00", 30, self.CATEGORY_TIMES, "mon",
            "08:00", "16:00", 30,
        )
        assert result == "Office*"

    def test_overridden_pause_appends_marker(self):
        result = slot_category_display(
            "Office", "09:00", "17:00", 45, self.CATEGORY_TIMES, "mon",
            "08:00", "16:00", 30,
        )
        assert result == "Office*"

    def test_reservation_slot_without_pause_ignores_pause_difference(self):
        # Reservierungen kennen keine Pause -> pause=None übergeben, dann
        # zählt nur Start/Ende für den Abgleich.
        result = slot_category_display(
            "Office", "09:00", "17:00", None, self.CATEGORY_TIMES, "mon",
            "08:00", "16:00", 30,
        )
        assert result == "Office"

    def test_unknown_category_falls_back_to_global_defaults_for_comparison(self):
        # Kategorie ohne eigenen category_times-Eintrag -> resolve_slot_defaults
        # fällt auf die globalen Standardzeiten zurück; stimmen die Slot-Zeiten
        # damit überein, kein Sternchen.
        result = slot_category_display(
            "Homeoffice", "08:00", "16:00", 30, self.CATEGORY_TIMES, "mon",
            "08:00", "16:00", 30,
        )
        assert result == "Homeoffice"


VALID_IST_SLOT = {"start": "08:00", "end": "16:00", "pause": 30, "kategorie": ""}
VALID_RES_SLOT = {"start": "09:00", "end": "17:00", "kategorie": ""}
INVALID_SLOT = {"start": "16:00", "end": "08:00", "pause": 0, "kategorie": ""}


class TestPlanEntrySave:
    """Entscheidungslogik für den einen kombinierten Speichern-Button: beide
    sichtbaren Blöcke werden komplett validiert, bevor irgendetwas persistiert
    wird (alles-oder-nichts) — kein stiller Teil-Save, wenn der andere Block
    einen Fehler hat."""

    def test_both_blocks_valid_saves_both(self):
        result = plan_entry_save([VALID_IST_SLOT], [VALID_RES_SLOT], show_reservation=True)
        assert result == {"error": None, "save_ist": True, "save_reservation": True}

    def test_empty_ist_with_valid_reservation_saves_only_reservation(self):
        result = plan_entry_save([], [VALID_RES_SLOT], show_reservation=True)
        assert result == {"error": None, "save_ist": False, "save_reservation": True}

    def test_valid_ist_with_empty_reservation_saves_only_ist(self):
        result = plan_entry_save([VALID_IST_SLOT], [], show_reservation=True)
        assert result == {"error": None, "save_ist": True, "save_reservation": False}

    def test_both_empty_saves_nothing_without_error(self):
        result = plan_entry_save([], [], show_reservation=True)
        assert result == {"error": None, "save_ist": False, "save_reservation": False}

    def test_invalid_ist_blocks_both_saves_even_if_reservation_valid(self):
        result = plan_entry_save([INVALID_SLOT], [VALID_RES_SLOT], show_reservation=True)
        assert result["save_ist"] is False
        assert result["save_reservation"] is False
        assert result["error"] == "Arbeitszeit: Endzeit muss nach Startzeit liegen"

    def test_invalid_reservation_blocks_both_saves_even_if_ist_valid(self):
        result = plan_entry_save([VALID_IST_SLOT], [INVALID_SLOT], show_reservation=True)
        assert result["save_ist"] is False
        assert result["save_reservation"] is False
        assert result["error"] == "Reservierung: Endzeit muss nach Startzeit liegen"

    def test_reservation_hidden_ignores_reservation_slots_entirely(self):
        # An vergangenen Tagen gibt es keinen Reservierungs-Block — auch
        # ungültige res_slots (kämen aus der UI ohnehin nie vor) dürfen den
        # Ist-Zeit-Save nicht blockieren.
        result = plan_entry_save([VALID_IST_SLOT], [INVALID_SLOT], show_reservation=False)
        assert result == {"error": None, "save_ist": True, "save_reservation": False}

    def test_error_message_unprefixed_when_no_reservation_block(self):
        result = plan_entry_save([INVALID_SLOT], [], show_reservation=False)
        assert result["error"] == "Endzeit muss nach Startzeit liegen"


def _rslot(start, end, minutes=None):
    return {"start": start, "end": end, "kategorie": "",
            "send_reminder_minutes": minutes}


def test_apply_reminder_marks_only_the_chosen_slot():
    from src.dialogs.entry_dialog import apply_reminder_to_slots

    slots = [_rslot("08:00", "12:00", 30), _rslot("13:00", "17:00")]
    apply_reminder_to_slots(slots, 1, 15, True)
    assert [s["send_reminder_minutes"] for s in slots] == [None, 15]


def test_apply_reminder_disabled_clears_all():
    from src.dialogs.entry_dialog import apply_reminder_to_slots

    slots = [_rslot("08:00", "12:00", 30), _rslot("13:00", "17:00")]
    apply_reminder_to_slots(slots, 0, 15, False)
    assert [s["send_reminder_minutes"] for s in slots] == [None, None]


def test_apply_reminder_invalid_index_clears_all():
    from src.dialogs.entry_dialog import apply_reminder_to_slots

    slots = [_rslot("08:00", "12:00", 30)]
    apply_reminder_to_slots(slots, 5, 15, True)
    assert slots[0]["send_reminder_minutes"] is None
    apply_reminder_to_slots(slots, None, 15, True)
    assert slots[0]["send_reminder_minutes"] is None


def test_apply_reminder_invalid_minutes_clears_all():
    from src.dialogs.entry_dialog import apply_reminder_to_slots

    slots = [_rslot("08:00", "12:00")]
    apply_reminder_to_slots(slots, 0, None, True)
    assert slots[0]["send_reminder_minutes"] is None


def test_reminder_block_visible_needs_both_settings_and_reservation_block():
    from src.dialogs.entry_dialog import reminder_block_visible

    class _S:
        def __init__(self, **kw):
            self._d = kw

        def get(self, key):
            return self._d.get(key)

    on = _S(send_reminder_enabled=True, send_reminder_reservations_enabled=True)
    assert reminder_block_visible(on, True) is True
    assert reminder_block_visible(on, False) is False
    assert reminder_block_visible(
        _S(send_reminder_enabled=False,
           send_reminder_reservations_enabled=True), True) is False
    assert reminder_block_visible(
        _S(send_reminder_enabled=True,
           send_reminder_reservations_enabled=False), True) is False


def test_reminder_slot_labels_are_unique_and_ordered():
    from src.dialogs.entry_dialog import reminder_slot_labels

    rows = [{"start": "08:00", "end": "12:00", "kategorie": "Office"},
            {"start": "08:00", "end": "12:00", "kategorie": "Office"},
            {"start": "13:00", "end": "17:00", "kategorie": ""}]
    labels = reminder_slot_labels(rows)
    assert labels == ["1. 08:00–12:00  Office", "2. 08:00–12:00  Office",
                      "3. 13:00–17:00"]
    assert len(set(labels)) == 3
