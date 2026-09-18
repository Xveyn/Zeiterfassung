"""`--forget-secrets` (Deinstallation): räumt ab und beendet sich, ohne Tk,
ohne Single-Instance-Guard und ohne Autostart-Migration."""

import sys


def test_forget_secrets_mode_returns_before_anything_else(tmp_path, monkeypatch):
    from src import main as main_mod, secret_migration
    calls = []
    monkeypatch.setattr(sys, "argv", ["Zeiterfassung.exe", "--forget-secrets"])
    monkeypatch.setattr(main_mod, "get_base_path", lambda: str(tmp_path))
    monkeypatch.setattr(main_mod, "setup_logging", lambda base: None)
    monkeypatch.setattr(secret_migration, "forget_all", lambda base: calls.append(base))

    def forbidden(*a, **k):
        raise AssertionError("darf im --forget-secrets-Modus nicht laufen")

    monkeypatch.setattr(main_mod, "migrate_legacy_autostart", forbidden)
    monkeypatch.setattr("src.single_instance.acquire", forbidden)
    monkeypatch.setattr(main_mod.tk, "Tk", forbidden)

    main_mod.main()

    assert calls == [str(tmp_path)]
