"""Die Startzeilen des Logs (Xveyn#401)."""
from src.startup_info import FEATURE_FLAGS, describe_environment, describe_features


def _env_line(**over):
    base = dict(label="1.25.2", channel="release", frozen=True,
                system="Windows", platform_text="Windows-11-10.0.26200-SP0",
                machine="AMD64", python="3.12.4", tk=8.6, env={})
    base.update(over)
    return describe_environment(**base)


def test_environment_line_has_build_platform_python_and_tk():
    assert _env_line() == (
        "Zeiterfassung 1.25.2 gestartet · Kanal release · gebaut · "
        "Windows-11-10.0.26200-SP0 (AMD64) · Python 3.12.4 · Tk 8.6")


def test_environment_line_marks_source_runs():
    line = _env_line(channel="source", frozen=False, label="1.25.2-dev (abc1234)")
    assert "Kanal source · Quellcode" in line


def test_linux_adds_session_and_desktop():
    line = _env_line(system="Linux", env={
        "XDG_SESSION_TYPE": "wayland", "XDG_CURRENT_DESKTOP": "KDE",
        "HOME": "/home/geheim", "USER": "geheim"})
    assert line.endswith("XDG_SESSION_TYPE=wayland, XDG_CURRENT_DESKTOP=KDE")
    assert "geheim" not in line


def test_non_linux_ignores_the_session_variables():
    line = _env_line(system="Windows", env={"XDG_SESSION_TYPE": "x11"})
    assert "XDG" not in line


def test_linux_without_session_variables_adds_nothing():
    assert _env_line(system="Linux", env={}).endswith("Tk 8.6")


def test_features_split_into_on_and_off():
    values = {"sync_enabled": True, "mobile_enabled": True, "ui_scale": 125}
    line = describe_features(values.get)
    assert line.startswith("Funktionen an: sync, mobil · aus: ")
    assert "kalender" in line.split(" · aus: ")[1]
    assert line.endswith("UI-Skalierung 125 %")


def test_features_with_nothing_on():
    line = describe_features(lambda key: None)
    assert line.startswith("Funktionen an: keine · aus: sync, ")
    assert "UI-Skalierung" not in line


def test_every_feature_flag_is_a_real_setting():
    from src.settings import DEFAULTS
    for key, _name in FEATURE_FLAGS:
        assert key in DEFAULTS, key
