# tests/test_mobile_pairing.py
import threading

import pytest

from src import mobile_pairing as mp
from src.mobile_pairing import PairingSession, RedeemResult


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


# --- Code -------------------------------------------------------------------------------

def test_the_alphabet_has_31_unambiguous_characters():
    assert len(mp.CODE_ALPHABET) == 31 and len(set(mp.CODE_ALPHABET)) == 31
    assert not set("01ILO") & set(mp.CODE_ALPHABET)


def test_a_generated_code_has_eight_characters_from_the_alphabet():
    for _ in range(200):
        code = mp.generate_code()
        assert len(code) == 8 and set(code) <= set(mp.CODE_ALPHABET)


def test_generated_codes_differ():
    assert len({mp.generate_code() for _ in range(200)}) == 200


def test_format_code_puts_a_dash_in_the_middle():
    assert mp.format_code("K7M29QXA") == "K7M2-9QXA"


@pytest.mark.parametrize("raw", ["K7M2-9QXA", "k7m2-9qxa", " K7M29QXA ", "K7M2 9QXA", "K7-M2-9Q-XA"])
def test_normalize_accepts_case_dashes_and_spaces(raw):
    assert mp.normalize_code(raw) == "K7M29QXA"


@pytest.mark.parametrize("raw", [
    None, 5, b"K7M29QXA", "", "K7M2-9QX", "K7M2-9QXAA", "K7M2-9QX0", "K7M2-9QXO", "K7M2-9QX1",
    "K7M2-9QXI", "K7M2-9QXL", "K7M2-9QXÄ", "٢" * 8, "A" * 5000, "K7M2-9QX\n",
])
def test_normalize_rejects_anything_that_cannot_be_a_code(raw):
    assert mp.normalize_code(raw) is None


# --- PairingSession ---------------------------------------------------------------------

def test_no_code_is_active_before_open():
    session = PairingSession(FakeClock())
    assert not session.is_active() and session.seconds_left() == 0
    assert session.redeem("K7M2-9QXA") is RedeemResult.INVALID


def test_open_returns_a_formatted_code_that_redeems_once():
    session = PairingSession(FakeClock())
    shown = session.open()

    assert len(shown) == 9 and shown[4] == "-"
    assert session.is_active()
    assert session.redeem(shown) is RedeemResult.OK
    assert not session.is_active()
    assert session.redeem(shown) is RedeemResult.INVALID                # verbraucht


def test_the_code_is_accepted_in_any_spelling():
    session = PairingSession(FakeClock())
    shown = session.open()
    assert session.redeem(shown.lower().replace("-", " ")) is RedeemResult.OK


def test_the_code_expires_after_five_minutes_exactly():
    clock = FakeClock()
    session = PairingSession(clock)
    shown = session.open()
    clock.advance(299)
    assert session.is_active() and session.seconds_left() == 1
    clock.advance(1)                                                     # 300 s: abgelaufen
    assert not session.is_active() and session.seconds_left() == 0
    assert session.redeem(shown) is RedeemResult.INVALID


def test_five_wrong_attempts_lock_the_session_until_the_next_open():
    session = PairingSession(FakeClock())
    shown = session.open()

    results = [session.redeem("AAAA-AAAA") for _ in range(5)]
    assert results == [RedeemResult.INVALID] * 5                          # der fünfte ist noch INVALID
    assert session.redeem("AAAA-AAAA") is RedeemResult.LOCKED
    assert session.redeem(shown) is RedeemResult.LOCKED                   # auch der richtige Code
    assert not session.is_active()

    fresh = session.open()                                                # neuer Code hebt die Sperre auf
    assert session.redeem(fresh) is RedeemResult.OK


def test_four_wrong_attempts_do_not_lock():
    session = PairingSession(FakeClock())
    shown = session.open()
    for _ in range(4):
        session.redeem("AAAA-AAAA")
    assert session.redeem(shown) is RedeemResult.OK


def test_malformed_input_counts_as_a_failed_attempt():
    session = PairingSession(FakeClock())
    session.open()
    for raw in (None, 5, "", "zu kurz", "٢" * 8):
        session.redeem(raw)
    assert session.redeem("AAAA-AAAA") is RedeemResult.LOCKED


def test_close_invalidates_the_code_and_clears_a_lock():
    session = PairingSession(FakeClock())
    shown = session.open()
    session.close()
    assert session.redeem(shown) is RedeemResult.INVALID
    for _ in range(5):
        session.open()
        session.redeem("AAAA-AAAA")
    session.close()
    assert session.redeem("AAAA-AAAA") is RedeemResult.INVALID            # nicht LOCKED


def test_reopening_replaces_the_old_code():
    session = PairingSession(FakeClock())
    first = session.open()
    second = session.open()
    assert first != second
    assert session.redeem(first) is RedeemResult.INVALID
    assert session.redeem(second) is RedeemResult.OK


def test_exactly_one_of_many_concurrent_redeems_wins():
    session = PairingSession()
    shown = session.open()
    results = []

    def attempt():
        results.append(session.redeem(shown))

    threads = [threading.Thread(target=attempt) for _ in range(40)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert results.count(RedeemResult.OK) == 1
