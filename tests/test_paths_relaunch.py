from src.paths import relaunch_command


def test_relaunch_command_frozen_uses_executable_directly():
    cmd = relaunch_command(["app.exe", "--foo"], "app.exe", True)
    assert cmd == ["app.exe", "--foo"]


def test_relaunch_command_repo_uses_module_invocation():
    cmd = relaunch_command(["src/main.py", "--foo"], "python", False)
    assert cmd == ["python", "-m", "src.main", "--foo"]


def test_relaunch_command_strips_minimized_frozen():
    cmd = relaunch_command(["app.exe", "--minimized", "--bar"], "app.exe", True)
    assert cmd == ["app.exe", "--bar"]


def test_relaunch_command_strips_minimized_repo():
    cmd = relaunch_command(["main.py", "--minimized"], "python", False)
    assert cmd == ["python", "-m", "src.main"]
