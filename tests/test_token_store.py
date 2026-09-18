"""token_store (#101): Refresh-Token im Schlüsselbund, Rest in token.json —
und Speichern behält den Ort bei. Kompatibilität mit ECHTEN
google-auth-Credentials."""

import datetime
import json

import pytest
from google.oauth2.credentials import Credentials

from src import keyring_store, oauth_utils
from src.token_store import load_credentials, save_credentials

SCOPES = ["https://www.googleapis.com/auth/gmail.send"]
# Festes expiry: google-auth setzt ein fehlendes expiry beim Laden auf
# utcnow() - REFRESH_THRESHOLD — zwei Ladevorgänge unterschieden sich sonst
# in den Mikrosekunden.
EXPIRY = datetime.datetime(2030, 1, 1, 12, 0, 0)


def _real_creds(refresh="1//refresh-token"):
    return Credentials(
        token="ya29.access", refresh_token=refresh,
        token_uri="https://oauth2.googleapis.com/token",
        client_id="cid.apps.googleusercontent.com", client_secret="csecret",
        scopes=SCOPES, expiry=EXPIRY)


def _read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _keyring_token(tmp_path, fake_keyring, refresh="1//refresh-token"):
    """token.json im Schlüsselbund-Modus, wie nach dem Umzug bzw. einer
    frischen Anmeldung (vorher gab es keine Datei)."""
    fake_keyring()
    path = tmp_path / "token.json"
    save_credentials(_real_creds(refresh), str(path))
    return path


def test_legacy_file_loads_exactly_as_before(tmp_path):
    """Kompatibilität: token.json, wie write_token sie heute schreibt."""
    path = tmp_path / "token.json"
    oauth_utils.write_token(_real_creds(), str(path))

    loaded = load_credentials(str(path), SCOPES, Credentials)
    reference = Credentials.from_authorized_user_file(str(path), SCOPES)

    assert loaded.to_json() == reference.to_json()


def test_legacy_file_stays_a_file_even_with_a_keyring(tmp_path, fake_keyring):
    """B1: Speichern behält den Ort bei. Umziehen darf nur secret_migration —
    sonst zöge der Start-Refresh still und ohne Zurücklesen um, und der
    Hinweis bliebe aus."""
    fake = fake_keyring()
    a, b = tmp_path / "a" / "token.json", tmp_path / "b" / "token.json"
    a.parent.mkdir()
    b.parent.mkdir()
    oauth_utils.write_token(_real_creds(), str(a))
    oauth_utils.write_token(_real_creds(), str(b))

    save_credentials(_real_creds("1//rotiert"), str(a))
    oauth_utils.write_token(_real_creds("1//rotiert"), str(b))

    assert a.read_text(encoding="utf-8") == b.read_text(encoding="utf-8")
    assert fake.store == {}


def test_without_keyring_save_writes_the_full_file_as_before(tmp_path):
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    save_credentials(_real_creds(), str(a))          # keine Datei, kein Schlüsselbund
    oauth_utils.write_token(_real_creds(), str(b))
    assert a.read_text(encoding="utf-8") == b.read_text(encoding="utf-8")


def test_fresh_login_goes_straight_to_the_keyring(tmp_path, fake_keyring):
    path = _keyring_token(tmp_path, fake_keyring)
    data = _read(path)
    assert "refresh_token" not in data
    assert data["token"] == "ya29.access"                  # Access-Token bleibt
    assert data[oauth_utils.REFRESH_TOKEN_LOCATION] == "keyring"
    assert keyring_store.fetch(data[oauth_utils.REFRESH_TOKEN_KEY]) == "1//refresh-token"


def test_keyring_roundtrip_loads_the_same_credentials(tmp_path, fake_keyring):
    path = _keyring_token(tmp_path, fake_keyring)
    loaded = load_credentials(str(path), SCOPES, Credentials)
    assert loaded.refresh_token == "1//refresh-token"
    assert loaded.token == "ya29.access"
    assert loaded.client_id == "cid.apps.googleusercontent.com"


def test_keyring_token_keeps_its_key_across_saves(tmp_path, fake_keyring):
    path = _keyring_token(tmp_path, fake_keyring)
    key = _read(path)[oauth_utils.REFRESH_TOKEN_KEY]
    save_credentials(_real_creds("1//rotiert"), str(path))
    assert _read(path)[oauth_utils.REFRESH_TOKEN_KEY] == key
    assert keyring_store.fetch(key) == "1//rotiert"


def test_unreachable_keyring_raises_and_leaves_the_file(tmp_path, fake_keyring):
    path = _keyring_token(tmp_path, fake_keyring)
    before = path.read_bytes()
    fake_keyring(working=False)
    with pytest.raises(oauth_utils.TokenKeyringUnavailable):
        load_credentials(str(path), SCOPES, Credentials)
    assert path.read_bytes() == before


def test_missing_keyring_entry_means_no_credentials(tmp_path, fake_keyring):
    path = _keyring_token(tmp_path, fake_keyring)
    fake_keyring()                                 # frischer, leerer Schlüsselbund
    assert load_credentials(str(path), SCOPES, Credentials) is None


def test_save_falls_back_to_the_file_when_the_keyring_fails(tmp_path, fake_keyring):
    path = _keyring_token(tmp_path, fake_keyring)
    fake_keyring(working=False)
    save_credentials(_real_creds("1//rotiert"), str(path))
    data = _read(path)
    assert data["refresh_token"] == "1//rotiert"   # der neue Token geht nie verloren
    assert oauth_utils.REFRESH_TOKEN_LOCATION not in data


def test_unreadable_file_takes_the_legacy_path(tmp_path):
    path = tmp_path / "token.json"
    path.write_text("kaputt", encoding="utf-8")
    calls = []

    class _Cls:
        @staticmethod
        def from_authorized_user_file(p, scopes):
            calls.append(p)
            return "LEGACY"

    assert load_credentials(str(path), SCOPES, _Cls) == "LEGACY"
    assert calls == [str(path)]


def test_keyring_token_saved_without_refresh_token_keeps_its_location(tmp_path, fake_keyring):
    """Credentials ohne Refresh-Token (Google liefert beim Refresh keinen
    neuen) dürfen die Markierung nicht verlieren — sonst fehlte der Datei
    danach `refresh_token`, und das nächste Laden bräche mit ValueError ab."""
    path = _keyring_token(tmp_path, fake_keyring)
    key = _read(path)[oauth_utils.REFRESH_TOKEN_KEY]

    save_credentials(_real_creds(refresh=None), str(path))

    data = _read(path)
    assert "refresh_token" not in data
    assert data[oauth_utils.REFRESH_TOKEN_LOCATION] == "keyring"
    assert data[oauth_utils.REFRESH_TOKEN_KEY] == key
    assert load_credentials(str(path), SCOPES, Credentials).refresh_token == "1//refresh-token"


# --- Verdrahtung: nicht-interaktive Pfade starten keinen Flow (#129) -------


def _unreachable(tmp_path, fake_keyring):
    path = _keyring_token(tmp_path, fake_keyring)
    fake_keyring(working=False)
    return path


def test_drive_without_click_raises_unavailable_not_flow(tmp_path, fake_keyring, monkeypatch):
    from src import drive
    from tests.conftest import forbid_consent_flow
    path = _unreachable(tmp_path, fake_keyring)
    forbid_consent_flow(monkeypatch)
    with pytest.raises(oauth_utils.TokenKeyringUnavailable):
        drive.get_drive_service("credentials.json", str(path))


def test_calendar_without_click_raises_unavailable_not_flow(tmp_path, fake_keyring, monkeypatch):
    from src import gcal
    from tests.conftest import forbid_consent_flow
    path = _unreachable(tmp_path, fake_keyring)
    forbid_consent_flow(monkeypatch)
    with pytest.raises(oauth_utils.TokenKeyringUnavailable):
        gcal.get_calendar_service("credentials.json", str(path))


def test_start_refresh_raises_unavailable_for_the_runner(tmp_path, fake_keyring):
    from src.mail import refresh_token_if_needed
    path = _unreachable(tmp_path, fake_keyring)
    with pytest.raises(oauth_utils.TokenKeyringUnavailable):
        refresh_token_if_needed(str(path))


def test_missing_keyring_entry_is_an_auth_error_at_start(tmp_path, fake_keyring):
    from src.mail import TokenAuthError, refresh_token_if_needed
    path = _keyring_token(tmp_path, fake_keyring)
    fake_keyring()                                 # Eintrag weg
    with pytest.raises(TokenAuthError):
        refresh_token_if_needed(str(path))


def test_sender_lookup_is_empty_when_the_keyring_is_unreachable(tmp_path, fake_keyring):
    from src.mail import fetch_user_email
    path = _unreachable(tmp_path, fake_keyring)
    assert fetch_user_email(str(path)) == ""
