import pytest

from src.drive import DriveAuthError, DriveConflictError, DriveNetworkError


def test_exceptions_are_distinct():
    assert not issubclass(DriveAuthError, DriveNetworkError)
    assert not issubclass(DriveNetworkError, DriveAuthError)
    assert not issubclass(DriveConflictError, DriveAuthError)
