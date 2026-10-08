"""Schutz vor Test-IDs, die unter Windows das Setup sprengen (siehe conftest.py)."""
import types

import pytest

from tests.conftest import MAX_NODE_ID_LENGTH, pytest_collection_modifyitems


def _items(*lengths):
    return [types.SimpleNamespace(nodeid="tests/test_x.py::test[" + "a" * n + "]") for n in lengths]


def test_short_ids_pass():
    pytest_collection_modifyitems(_items(10, 200, 1000))


def test_an_id_at_the_limit_passes():
    pytest_collection_modifyitems(_items(MAX_NODE_ID_LENGTH - len("tests/test_x.py::test[]")))


def test_a_100000_character_id_is_rejected_with_a_helpful_message():
    with pytest.raises(pytest.UsageError) as info:
        pytest_collection_modifyitems(_items(10, 100_000))
    message = str(info.value)
    assert "32 767" in message and "pytest.param" in message and "100" in message


def test_the_whole_suite_is_collected_without_long_ids():
    # Läuft die Sammlung bis hierher, hat der Hook keine zu lange ID gefunden.
    assert MAX_NODE_ID_LENGTH < 32_767
