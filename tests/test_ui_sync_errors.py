"""Tests für die Klassifizierung von Drive-Sync-Fehlern im UI.

Hintergrund: Im manuellen Sync-/Push-/Reconcile-Pfad kommt der Fehler als
String (str(e)) bei classify_sync_error an — die Exception-Typinfo ist dann
weg. Ein 403 'insufficient authentication scopes' muss trotzdem als 'auth'
(Re-Consent nötig) erkannt werden, nicht als 'unknown' (roher Traceback) oder
'network' ('Keine Internetverbindung').
"""
from src.sync_orchestrator import classify_sync_error, _friendly_sync_message
from src.drive import DriveAuthError, DriveNetworkError
from src.sync import NEWER_REMOTE_VERSION_MSG


def test_classify_403_scope_string_is_auth():
    text = (
        "<HttpError 403 ... returned \"Request had insufficient authentication "
        "scopes.\". Details: 'reason': 'insufficientPermissions'>"
    )
    assert classify_sync_error(text) == "auth"


def test_classify_invalid_grant_string_is_auth():
    assert classify_sync_error("... invalid_grant: Token has been expired ...") == "auth"


def test_classify_drive_auth_error_instance_is_auth():
    assert classify_sync_error(DriveAuthError("insufficientPermissions")) == "auth"


def test_classify_network_error_instance_is_network():
    assert classify_sync_error(DriveNetworkError("connection reset")) == "network"


def test_push_timeout_is_known_and_themed():
    """Der Join-Timeout des Push-Workers ist ein erwarteter Fall: kein
    nativer Dialog mit 'unerwartetem Fehler', sondern bekannter themed Text."""
    from src.sync_runtime import SYNC_TIMEOUT_MSG
    assert classify_sync_error(SYNC_TIMEOUT_MSG) == "timeout"
    title, message, known = _friendly_sync_message(SYNC_TIMEOUT_MSG)
    assert known is True
    assert "unerwartet" not in message
    assert title == "Synchronisation dauert zu lange"


def test_classify_plain_error_is_unknown():
    assert classify_sync_error("ValueError: kaputt") == "unknown"


def test_newer_remote_version_is_friendly_known():
    """Der Forward-Compat-Hinweis muss als bekannter Fall (ohne Traceback,
    themed Info) gezeigt werden, nicht als roher 'unerwarteter Fehler'."""
    title, message, known = _friendly_sync_message(NEWER_REMOTE_VERSION_MSG)
    assert known is True
    assert message == NEWER_REMOTE_VERSION_MSG
    assert "Update" in title
