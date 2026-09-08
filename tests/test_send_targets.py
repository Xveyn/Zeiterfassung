"""Tk-freie Helfer der Ziel-/Empfängerwahl in Sende- und Teilen-Dialog."""

from src.dialogs.send_dialog import mail_target_label, smtp_target_label
from src.dialogs.share_dialog import default_share_recipient


def test_mail_label_names_recipient():
    assert mail_target_label("chef@example.com", True) == "An chef@example.com"


def test_mail_label_says_why_it_is_dead():
    # Ohne den Zusatz stünde dort nur die Adresse, und nichts erklärte, warum
    # die Zeile nicht anwählbar ist.
    assert mail_target_label("chef@example.com", False) == (
        "An chef@example.com (Zugangsdaten fehlen)")
    assert mail_target_label("", True) == "Kein Empfänger eingetragen"
    assert mail_target_label("", False) == "Kein Empfänger eingetragen"


def test_smtp_label_names_account_and_target():
    assert smtp_target_label({"name": "Büro", "recipient": "chef@example.com"}) == (
        "Büro → chef@example.com")


def test_smtp_label_survives_incomplete_record():
    assert smtp_target_label({}) == " → "


def test_share_recipient_prefers_account():
    assert default_share_recipient(
        {"recipient": "chef@example.com"}, "alt@example.com"
    ) == "chef@example.com"


def test_share_recipient_falls_back_to_saved_default():
    # Konto ohne Empfänger: lieber der gespeicherte Standard als ein leeres
    # Feld.
    assert default_share_recipient({"recipient": ""}, "alt@example.com") == (
        "alt@example.com")
    assert default_share_recipient({}, "alt@example.com") == "alt@example.com"


def test_share_recipient_gmail_uses_saved_default():
    assert default_share_recipient(None, "alt@example.com") == "alt@example.com"


def test_share_recipient_without_anything_is_empty():
    assert default_share_recipient(None, None) == ""
    assert default_share_recipient({"recipient": "  "}, "") == ""
