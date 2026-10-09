# tests/test_mobile_pairing.py
import datetime
import threading

import pytest

from src import mobile_pairing as mp
from src.mobile_pairing import PairingSession, RedeemResult

NOW = "2026-10-08T12:00:00Z"


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
    session.open()
    for _ in range(5):
        session.redeem("AAAA-AAAA")
    assert session.redeem("AAAA-AAAA") is RedeemResult.LOCKED
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


# --- Token --------------------------------------------------------------------------------

def test_tokens_are_long_unique_and_urlsafe():
    tokens = {mp.new_token() for _ in range(100)}
    assert len(tokens) == 100 and all(len(t) == 43 for t in tokens)


def test_the_hash_is_stable_hex_and_differs_per_token():
    assert mp.hash_token("abc") == mp.hash_token("abc")
    assert mp.hash_token("abc") != mp.hash_token("abd")
    assert len(mp.hash_token("abc")) == 64 and int(mp.hash_token("abc"), 16) >= 0


def test_a_lone_surrogate_hashes_without_raising():
    assert len(mp.hash_token("\ud800")) == 64
    assert mp.hash_token("\ud800") != mp.hash_token("\udc00")


# --- Fremddaten vom Handy ---------------------------------------------------------------------

@pytest.mark.parametrize("raw", ["6f1c2b9e-3d4a-4b5c-8d7e-9f0a1b2c3d4e", "ABCDEFGH", "a" * 64])
def test_a_plausible_device_id_is_kept(raw):
    assert mp.normalize_device_id(raw) == raw


@pytest.mark.parametrize("raw", [None, 5, "", "kurz", "a" * 65, "mit leerzeichen!", "ä" * 10,
                                 "٢" * 10, "id\n12345678"])
def test_an_implausible_device_id_is_rejected(raw):
    assert mp.normalize_device_id(raw) is None


def test_a_device_name_is_cleaned():
    assert mp.clean_device_name("  Pixel von Sven ") == "Pixel von Sven"
    assert mp.clean_device_name("Pi\nxel\x00\x07") == "Pixel"
    assert mp.clean_device_name("x" * 500) == "x" * mp.MAX_NAME_LENGTH
    for junk in (None, 5, "", "   ", "\n\x00"):
        assert mp.clean_device_name(junk) == mp.DEFAULT_DEVICE_NAME


# --- Zeit ----------------------------------------------------------------------------------------

def test_shift_adds_and_subtracts_in_the_fixed_format():
    assert mp.shift(NOW, datetime.timedelta(days=30)) == "2026-11-07T12:00:00Z"
    assert mp.shift(NOW, -datetime.timedelta(minutes=1)) == "2026-10-08T11:59:00Z"
    assert mp.shift("2026-12-31T23:59:59Z", datetime.timedelta(seconds=1)) == "2027-01-01T00:00:00Z"


# --- Geräte, Erneuerung, Widerruf ----------------------------------------------------------------

def test_issue_device_returns_a_record_without_the_token():
    record, token = mp.issue_device("device-0001", "Pixel", NOW)

    assert token not in repr(record)
    assert record["token_hash"] == mp.hash_token(token)
    assert (record["id"], record["name"], record["revoked"]) == ("device-0001", "Pixel", False)
    assert (record["created_at"], record["last_seen"], record["last_pull_at"]) == (NOW, NOW, "")
    assert record["expires_at"] == "2026-11-07T12:00:00Z"
    assert (record["previous_token_hash"], record["previous_valid_until"]) == ("", "")


def test_pairing_again_keeps_the_sync_identity_and_lifts_a_revocation():
    old, _ = mp.issue_device("device-0001", "Pixel", NOW)
    old["last_pull_at"] = "2026-10-07T09:00:00Z"
    old = mp.revoke(old)

    record, token = mp.issue_device("device-0001", "Pixel neu", "2026-10-09T08:00:00Z", existing=old)

    assert record["created_at"] == NOW and record["last_pull_at"] == "2026-10-07T09:00:00Z"
    assert record["revoked"] is False and record["name"] == "Pixel neu"
    assert mp.authenticate([record], token, "2026-10-09T08:00:00Z").ok


def test_a_valid_token_authenticates_and_an_unknown_one_does_not():
    record, token = mp.issue_device("device-0001", "Pixel", NOW)

    outcome = mp.authenticate([record], token, NOW)
    assert outcome.ok and outcome.record["id"] == "device-0001" and not outcome.via_previous
    assert mp.authenticate([record], token + "x", NOW).status == "unauthorized"
    assert mp.authenticate([], token, NOW).status == "unauthorized"


@pytest.mark.parametrize("junk", [None, 5, "", b"abc", "x" * 5000, ["a"], "\ud800"])
def test_a_junk_token_is_unauthorized_and_never_raises(junk):
    record, _ = mp.issue_device("device-0001", "Pixel", NOW)
    assert mp.authenticate([record], junk, NOW).status == "unauthorized"


def test_the_token_expires_exactly_at_expires_at():
    record, token = mp.issue_device("device-0001", "Pixel", NOW)
    before = mp.shift(record["expires_at"], -datetime.timedelta(seconds=1))

    assert mp.authenticate([record], token, before).ok
    assert mp.authenticate([record], token, record["expires_at"]).status == "expired"
    assert mp.authenticate([record], token, record["expires_at"]).record["id"] == "device-0001"


def test_a_revoked_device_is_reported_as_revoked_not_as_unknown():
    record, token = mp.issue_device("device-0001", "Pixel", NOW)
    assert mp.authenticate([mp.revoke(record)], token, NOW).status == "revoked"


def test_revoke_also_cuts_the_grace_of_the_previous_token():
    record, token = mp.issue_device("device-0001", "Pixel", NOW)
    renewed, _ = mp.renew(record, NOW)
    revoked = mp.revoke(renewed)

    assert mp.authenticate([revoked], token, NOW).status == "unauthorized"


def test_renew_issues_a_new_token_and_extends_the_expiry():
    record, token = mp.issue_device("device-0001", "Pixel", NOW)
    later = "2026-10-20T08:00:00Z"

    renewed, new_token = mp.renew(record, later)

    assert new_token != token and renewed["token_hash"] == mp.hash_token(new_token)
    assert renewed["expires_at"] == "2026-11-19T08:00:00Z" and renewed["last_seen"] == later
    assert mp.authenticate([renewed], new_token, later).ok
    assert record["token_hash"] == mp.hash_token(token)                    # das Original bleibt unverändert


def test_the_previous_token_works_for_ten_minutes_after_a_renewal():
    record, token = mp.issue_device("device-0001", "Pixel", NOW)
    renewed, _ = mp.renew(record, NOW)

    inside = mp.authenticate([renewed], token, "2026-10-08T12:10:00Z")
    outside = mp.authenticate([renewed], token, "2026-10-08T12:10:01Z")

    assert inside.ok and inside.via_previous
    assert outside.status == "unauthorized"


def test_a_lost_answer_twice_does_not_lock_the_phone_out():
    # T1 -> Antwort mit T2 geht verloren -> Handy sendet weiter mit T1 -> Antwort mit T3 geht verloren
    record, t1 = mp.issue_device("device-0001", "Pixel", NOW)
    second, _t2 = mp.renew(record, NOW)
    outcome = mp.authenticate([second], t1, "2026-10-08T12:05:00Z")
    assert outcome.ok and outcome.via_previous

    third, t3 = mp.renew(outcome.record, "2026-10-08T12:05:00Z", keep_previous=outcome.via_previous)

    assert mp.authenticate([third], t1, "2026-10-08T12:06:00Z").ok         # T1 gilt noch
    assert mp.authenticate([third], t3, "2026-10-08T12:06:00Z").ok


def test_renewing_with_the_current_token_replaces_the_previous_one():
    record, t1 = mp.issue_device("device-0001", "Pixel", NOW)
    second, t2 = mp.renew(record, NOW)
    third, _t3 = mp.renew(second, "2026-10-08T12:01:00Z")                  # normal: keep_previous=False

    assert mp.authenticate([third], t2, "2026-10-08T12:02:00Z").via_previous
    assert mp.authenticate([third], t1, "2026-10-08T12:02:00Z").status == "unauthorized"


def test_the_right_device_is_found_among_several():
    a, ta = mp.issue_device("device-aaaa", "A", NOW)
    b, tb = mp.issue_device("device-bbbb", "B", NOW)

    assert mp.authenticate([a, b], tb, NOW).record["id"] == "device-bbbb"
    assert mp.authenticate([a, b], ta, NOW).record["id"] == "device-aaaa"


def test_every_pairing_counts_up_and_renewal_and_revocation_keep_the_count():
    first, _ = mp.issue_device("device-0001", "Pixel", NOW)
    assert first["pair_count"] == 1

    renewed, _ = mp.renew(first, NOW)
    assert renewed["pair_count"] == 1                          # ein Abgleich ist kein Koppeln
    assert mp.revoke(renewed)["pair_count"] == 1

    again, _ = mp.issue_device("device-0001", "Pixel", NOW, existing=mp.renew(renewed, NOW)[0])
    assert again["pair_count"] == 2                            # auch in derselben Sekunde
    assert mp.issue_device("device-0001", "Pixel", NOW, existing=again)[0]["pair_count"] == 3


def test_a_record_from_before_the_counter_counts_from_zero():
    legacy, _ = mp.issue_device("device-0001", "Pixel", NOW)
    del legacy["pair_count"]

    assert mp.issue_device("device-0001", "Pixel", NOW, existing=legacy)[0]["pair_count"] == 1
    assert mp.issue_device("device-0001", "Pixel", NOW, existing={**legacy, "pair_count": "x"}
                           )[0]["pair_count"] == 1
