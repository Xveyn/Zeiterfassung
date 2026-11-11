"""Kein Leser liest `state` mehr direkt; Land und Region kommen aus `region.country_region`."""
import ast
import datetime
import pathlib

from src.api_summary import holidays_for
from src.send_reminder import free_dates_for_month, upcoming_send_times
from src.vacations import expand_days

SRC = pathlib.Path(__file__).resolve().parent.parent / "src"
ALLOWED = {"region.py", "dialogs/settings_dialog/tab_rules.py"}
RECEIVERS = {"settings", "_settings"}  # letztes Pfadsegment: auch self._settings, ctx.settings


def _receiver(node):
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return parts[0]
    return None


def _state_reads(tree):
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "get" and node.args
                and isinstance(node.args[0], ast.Constant) and node.args[0].value == "state"
                and _receiver(node.func.value) in RECEIVERS):
            yield node.lineno
        if (isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant)
                and node.slice.value == "state" and _receiver(node.value) in RECEIVERS):
            yield node.lineno


def test_guard_flags_attribute_receivers():
    for code in ('self._settings.get("state")', 'ctx.settings["state"]', 'settings.get("state")'):
        assert list(_state_reads(ast.parse(code)))
    assert not list(_state_reads(ast.parse('status.get("state")')))


def test_no_module_reads_state_key_directly():
    offenders = []
    for path in SRC.rglob("*.py"):
        rel = path.relative_to(SRC).as_posix()
        if rel in ALLOWED:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        offenders += [f"{rel}:{n}" for n in _state_reads(tree)]
    assert offenders == []


def test_holidays_for_reads_region_only():
    bayern = {h["date"] for h in holidays_for({"country": "DE", "region": "BY"}, 2026)["holidays"]}
    assert "2026-01-06" in bayern
    assert holidays_for({"state": "BY"}, 2026)["holidays"] == []


def test_expand_days_with_country_keyword_matches_default():
    assert expand_days("2026-01-01", "2026-01-07", 480, "BY") == \
        expand_days("2026-01-01", "2026-01-07", 480, "BY", country="DE")


def test_free_dates_use_region_and_country():
    free = free_dates_for_month(2026, 1, "BY", True, "DE")
    assert datetime.date(2026, 1, 6) in free


def test_upcoming_send_times_without_country_key_still_works():
    now = datetime.datetime(2026, 1, 1, 8, 0)
    monthly = {"day": 5, "time": "18:00", "shift": "forward", "state": "BY", "holidays": True}
    assert upcoming_send_times(now, monthly=monthly, daily_slots=[], tz=datetime.timezone.utc)
