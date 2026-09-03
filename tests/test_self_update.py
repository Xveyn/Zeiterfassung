"""Reine Logik des In-App-Updates (Tk-frei, ohne Netzwerk)."""

import hashlib
import os
import sys
import tempfile
from unittest.mock import patch

import pytest

from src.self_update import (
    UpdateBlocked, UpdatePlan, apply_windows, parse_sha256sums, plan_update,
    supports_self_update, verify_file,
)
from src.updater import Asset, Release

# So sieht die Datei im Release wirklich aus (coreutils `sha256sum`,
# zwei Leerzeichen zwischen Digest und Name).
SUMS_FIXTURE = (
    "3f786850e387550fdab836ed7e6dc881de23001b3f786850e387550fdab836ed  "
    "Zeiterfassung_Setup.exe\n"
    "89e6c98d92887913cadf06b2adb97f26cde4849b0a3b1a4b1a4b1a4b1a4b1a4b  "
    "Zeiterfassung-1.22.0-x86_64.AppImage\n"
)


def test_parse_sha256sums_reads_name_and_digest():
    sums = parse_sha256sums(SUMS_FIXTURE)
    assert sums["Zeiterfassung_Setup.exe"] == (
        "3f786850e387550fdab836ed7e6dc881de23001b3f786850e387550fdab836ed")
    assert len(sums) == 2


def test_parse_sha256sums_ignores_blank_and_broken_lines():
    text = SUMS_FIXTURE + "\n" + "nurwas\n" + "zzz  Datei.txt\n"
    sums = parse_sha256sums(text)
    assert len(sums) == 2          # die beiden kaputten Zeilen fallen raus


def test_parse_sha256sums_handles_crlf():
    sums = parse_sha256sums(SUMS_FIXTURE.replace("\n", "\r\n"))
    assert "Zeiterfassung_Setup.exe" in sums


def test_parse_sha256sums_handles_binary_marker():
    # `sha256sum -b` schreibt " *name" statt "  name".
    text = ("3f786850e387550fdab836ed7e6dc881de23001b3f786850e387550fdab836ed"
            " *Zeiterfassung_Setup.exe\n")
    assert "Zeiterfassung_Setup.exe" in parse_sha256sums(text)


def test_parse_sha256sums_on_empty_text():
    assert parse_sha256sums("") == {}


def test_verify_file_accepts_the_matching_digest(tmp_path):
    f = tmp_path / "a.bin"
    f.write_bytes(b"hallo welt")
    assert verify_file(str(f), hashlib.sha256(b"hallo welt").hexdigest())


def test_verify_file_rejects_a_different_digest(tmp_path):
    f = tmp_path / "a.bin"
    f.write_bytes(b"hallo welt")
    assert not verify_file(str(f), hashlib.sha256(b"etwas anderes").hexdigest())


def test_verify_file_is_case_insensitive_about_the_digest(tmp_path):
    f = tmp_path / "a.bin"
    f.write_bytes(b"hallo welt")
    assert verify_file(str(f), hashlib.sha256(b"hallo welt").hexdigest().upper())


def test_verify_file_on_missing_file_is_false(tmp_path):
    assert not verify_file(str(tmp_path / "gibtsnicht.bin"), "00" * 32)


def _release(version="1.23.0", with_sums=True):
    assets = [
        Asset(name="Zeiterfassung_Setup.exe", url="https://x/exe"),
        Asset(name=f"Zeiterfassung-{version}-x86_64.AppImage", url="https://x/img"),
        Asset(name=f"Zeiterfassung-{version}-arm64.dmg", url="https://x/dmg"),
    ]
    if with_sums:
        assets.append(Asset(name="SHA256SUMS", url="https://x/sums"))
    return Release(version=version, html_url="https://x/rel", assets=tuple(assets))


@pytest.mark.parametrize("system,frozen,expected", [
    ("Windows", True, True),
    ("Linux", True, True),
    ("Darwin", True, False),     # bewusst nicht unterstuetzt
    ("Windows", False, False),   # Repo-Modus: nichts zu ersetzen
    ("Linux", False, False),
    ("FreeBSD", True, False),
])
def test_supports_self_update(system, frozen, expected):
    assert supports_self_update(system, frozen) is expected


def test_plan_update_on_windows_yields_setup_and_sums():
    plan = plan_update(_release(), "Windows", "AMD64", True, "",
                       r"C:\Apps\Zeiterfassung\Zeiterfassung.exe")
    assert isinstance(plan, UpdatePlan)
    assert plan.asset_name == "Zeiterfassung_Setup.exe"
    assert plan.asset_url == "https://x/exe"
    assert plan.sums_url == "https://x/sums"
    assert plan.target == r"C:\Apps\Zeiterfassung\Zeiterfassung.exe"


def test_plan_update_on_linux_targets_the_appimage():
    plan = plan_update(_release(), "Linux", "x86_64", True,
                       "/home/u/Apps/Zeiterfassung.AppImage", "/tmp/whatever")
    assert isinstance(plan, UpdatePlan)
    assert plan.asset_name == "Zeiterfassung-1.23.0-x86_64.AppImage"
    assert plan.target == "/home/u/Apps/Zeiterfassung.AppImage"


def test_plan_update_blocks_on_macos():
    blocked = plan_update(_release(), "Darwin", "arm64", True, "", "/A/Z.app")
    assert isinstance(blocked, UpdateBlocked)
    assert "macOS" in blocked.reason


def test_plan_update_blocks_in_repo_mode():
    blocked = plan_update(_release(), "Windows", "AMD64", False, "", "python.exe")
    assert isinstance(blocked, UpdateBlocked)


def test_plan_update_blocks_when_architecture_does_not_match():
    blocked = plan_update(_release(), "Linux", "aarch64", True,
                          "/home/u/Z.AppImage", "/tmp/x")
    assert isinstance(blocked, UpdateBlocked)
    assert "Architektur" in blocked.reason


def test_plan_update_blocks_without_a_sums_asset():
    blocked = plan_update(_release(with_sums=False), "Windows", "AMD64", True,
                          "", r"C:\Apps\Z.exe")
    assert isinstance(blocked, UpdateBlocked)
    assert "Prüfsumme" in blocked.reason


def test_plan_update_blocks_on_linux_without_appimage_env():
    # Die nackte PyInstaller-Ausgabe hat $APPIMAGE nicht.
    blocked = plan_update(_release(), "Linux", "x86_64", True, "", "/tmp/x")
    assert isinstance(blocked, UpdateBlocked)
    assert "AppImage" in blocked.reason


# === Tests für download_to und fetch_text ===

class _FakeResponse:
    def __init__(self, payload, length=None):
        self._payload = payload
        self._pos = 0
        self.headers = {"Content-Length": str(length if length is not None
                                              else len(payload))}

    def read(self, size):
        chunk = self._payload[self._pos:self._pos + size]
        self._pos += len(chunk)
        return chunk

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_download_to_writes_the_payload(tmp_path):
    from src.self_update import download_to
    dest = tmp_path / "out.bin"
    with patch("src.self_update.urlopen", return_value=_FakeResponse(b"x" * 5000)):
        assert download_to("https://x/f", str(dest)) is True
    assert dest.read_bytes() == b"x" * 5000


def test_download_to_reports_progress(tmp_path):
    from src.self_update import download_to
    seen = []
    with patch("src.self_update.urlopen", return_value=_FakeResponse(b"y" * 3000)):
        download_to("https://x/f", str(tmp_path / "o.bin"),
                    on_progress=lambda done, total: seen.append((done, total)))
    assert seen, "es muss mindestens einmal gemeldet werden"
    assert seen[-1] == (3000, 3000)


def test_download_to_removes_the_partial_file_on_error(tmp_path):
    from src.self_update import download_to
    import urllib.error
    dest = tmp_path / "out.bin"
    with patch("src.self_update.urlopen",
               side_effect=urllib.error.URLError("weg")):
        assert download_to("https://x/f", str(dest)) is False
    assert not dest.exists(), "eine halbe Datei darf nicht liegenbleiben"


def test_fetch_text_returns_none_on_error():
    from src.self_update import fetch_text
    import urllib.error
    with patch("src.self_update.urlopen",
               side_effect=urllib.error.URLError("weg")):
        assert fetch_text("https://x/sums") is None


class _FailingResponse:
    """Liefert erst `good_chunks` Bloecke, dann wirft `exc`."""

    def __init__(self, exc, good_chunks=2, block=b"z" * 4096):
        self.headers = {"Content-Length": "999999"}
        self._exc = exc
        self._left = good_chunks
        self._block = block

    def read(self, size):
        if self._left <= 0:
            raise self._exc
        self._left -= 1
        return self._block

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_download_to_removes_the_partial_file_when_writing_fails(tmp_path):
    """OSError während write() (z.B. Platte voll) — echte Datei wird angelegt,
    dann beim Schreiben Fehler, dann muss Datei weg sein."""
    import builtins
    from src.self_update import download_to
    dest = tmp_path / "halb.bin"
    real_open = builtins.open

    def open_failing_after_first_write(*args, **kwargs):
        handle = real_open(*args, **kwargs)
        original = handle.write
        seen = []

        def write(data):
            seen.append(1)
            if len(seen) > 1:
                raise OSError(28, "No space left on device")
            return original(data)

        handle.write = write
        return handle

    with patch("src.self_update.urlopen",
               return_value=_FailingResponse(None, good_chunks=5)), \
         patch("builtins.open", side_effect=open_failing_after_first_write):
        assert download_to("https://x/f", str(dest)) is False

    assert not dest.exists(), "die angefangene Datei muss weg sein"


def test_download_to_removes_file_on_http_exception_during_download(tmp_path):
    """http.client.HTTPException (z.B. IncompleteRead) mitten im Download —
    echte Datei wird angelegt, dann wirft Response, dann muss Datei weg sein."""
    from src.self_update import download_to
    import http.client
    dest = tmp_path / "out.bin"

    # Response liefert 2 Bloecke, dann wirft HTTPException
    with patch("src.self_update.urlopen",
               return_value=_FailingResponse(
                   http.client.IncompleteRead(b"partial", 999),
                   good_chunks=2)):
        assert download_to("https://x/f", str(dest)) is False

    assert not dest.exists(), "halbe Datei muss aufgeräumt sein"


# === Tests für Windows Update-Helfer (Task 5) ===


def test_windows_helper_script_quotes_every_path():
    from src.self_update import windows_helper_script
    script = windows_helper_script(
        4711,
        r"C:\Temp\Zeiterfassung_Setup.exe",
        r"D:\Programme (x86)\Zeiterfassung\Zeiterfassung.exe",
        r"C:\Temp\update.log")
    # Pfade mit Leerzeichen und Klammern sind hier der NORMALFALL.
    assert '"D:\\Programme (x86)\\Zeiterfassung\\Zeiterfassung.exe"' in script
    assert '"C:\\Temp\\Zeiterfassung_Setup.exe"' in script
    assert "4711" in script


def test_windows_helper_script_waits_then_installs_then_starts():
    from src.self_update import windows_helper_script
    script = windows_helper_script(1, "s.exe", "z.exe", "l.log")
    wait_at = script.index("tasklist")
    install_at = script.index("/SILENT")
    start_at = script.rindex("start ")
    assert wait_at < install_at < start_at, "Reihenfolge ist der ganze Punkt"


def test_windows_helper_script_uses_neither_verysilent_nor_suppressmsgboxes():
    from src.self_update import windows_helper_script
    script = windows_helper_script(1, "s.exe", "z.exe", "l.log")
    assert "/SILENT" in script
    assert "/VERYSILENT" not in script       # Fortschritt soll sichtbar sein
    assert "/SUPPRESSMSGBOXES" not in script  # echte Fehler sollen auffallen
    assert "/SMS" not in script               # nicht mehr dokumentiert


def test_windows_helper_script_has_a_wait_timeout():
    from src.self_update import windows_helper_script
    script = windows_helper_script(1, "s.exe", "z.exe", "l.log")
    # Ohne Obergrenze liefe der Helfer ewig, falls die PID nie verschwindet.
    assert "TRIES" in script


def test_apply_windows_preserves_umlauts_on_disk(tmp_path):
    """`apply_windows` selbst muss einen Umlaut im Pfad unbeschadet auf die
    Platte bringen — nicht nur eine Kopie seiner Encoding-Logik.

    Ruft die echte Produktionsfunktion auf; nur das tatsächliche Starten des
    Helfer-Prozesses wird unterbunden (`subprocess.Popen` gepatcht), damit der
    Test nicht wirklich `cmd.exe` lostreten muss. Die geschriebene Datei wird
    danach genau so zurückgelesen, wie `cmd.exe` sie lesen würde: über die
    OEM-Codepage.

    Rot-Nachweis (Task-Vorgabe, manuell durchgeführt — s. Report): mit dem
    alten `encoding="ascii", errors="replace"` wird "Müller" beim Schreiben
    lautlos zu "M?ller", und die zweite Assertion unten schlägt fehl.
    """
    if sys.platform != "win32":
        pytest.skip("cmd.exe/OEM-Codec nur unter Windows verfügbar")

    exe_path = str(tmp_path / "Müller" / "Zeiterfassung.exe")
    setup_path = str(tmp_path / "Zeiterfassung_Setup.exe")

    with patch("subprocess.Popen") as mock_popen:
        result = apply_windows(exe_path, setup_path, 4711)

    assert result is True
    script_path = mock_popen.call_args[0][0][2]
    try:
        with open(script_path, "r", encoding="oem") as handle:
            written = handle.read()
        assert "Müller" in written, f"Umlaut verloren! Inhalt: {written!r}"
        assert "M?ller" not in written, (
            f"Umlaut zu ? ersetzt (passiert mit ascii+replace)! Inhalt: {written!r}")
    finally:
        os.remove(script_path)


def test_apply_windows_deletes_leftover_script_on_popen_failure(tmp_path, monkeypatch):
    """Scheitert das Starten des Helfers, darf keine halbe `.cmd`-Datei in
    %TEMP% liegen bleiben (dieselbe Aufräum-Regel wie bei `download_to`).

    `tempfile.gettempdir` wird auf `tmp_path` umgelenkt, damit der Test die
    tatsächlich angelegte Datei wiederfindet, ohne im echten %TEMP% zu
    wühlen.
    """
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path))
    exe_path = str(tmp_path / "Zeiterfassung.exe")
    setup_path = str(tmp_path / "Zeiterfassung_Setup.exe")

    with patch("subprocess.Popen", side_effect=OSError("kein cmd.exe gefunden")):
        result = apply_windows(exe_path, setup_path, 4711)

    assert result is False
    leftover = list(tmp_path.glob("*.cmd"))
    assert leftover == [], f"Halbe .cmd-Datei bleibt liegen: {leftover}"


def test_apply_windows_deletes_leftover_script_on_encoding_error(tmp_path, monkeypatch):
    """Dieselbe Aufräum-Regel gilt für den `UnicodeEncodeError`-Zweig: ein
    Zeichen, das die OEM-Codepage nicht kennt, darf keine halbe `.cmd`-Datei
    zurücklassen.
    """
    if sys.platform != "win32":
        pytest.skip("OEM-Codec nur unter Windows verfügbar")

    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path))
    exe_path = str(tmp_path / "中文_Zeiterfassung.exe")
    setup_path = str(tmp_path / "Zeiterfassung_Setup.exe")

    result = apply_windows(exe_path, setup_path, 4711)

    assert result is False
    leftover = list(tmp_path.glob("*.cmd"))
    assert leftover == [], f"Halbe .cmd-Datei bleibt liegen: {leftover}"


def test_apply_windows_encoding_error_returns_false(tmp_path):
    """Zeichen außerhalb der Codepage führen zu Fehler-Logging, nicht zu crash.

    Mit errors="strict" (nicht "replace") wirft UnicodeEncodeError bei
    un-kodierbaren Zeichen. apply_windows fängt das, loggt und gibt False zurück,
    damit der Aufrufer eine Meldung zeigen kann.
    """
    # Windows: OEM-Codec testen. Linux: skipzen.
    if sys.platform != "win32":
        pytest.skip("OEM-Codec nur auf Windows verfügbar")

    # Ein Zeichen, das OEM-850 nicht kodieren kann (z.B. chinesisches Zeichen)
    exe_with_impossible_char = str(tmp_path / "中文_Zeiterfassung.exe")
    setup = str(tmp_path / "setup.exe")

    # apply_windows sollte False liefern, weil der Umlaut nicht kodierbar ist
    result = apply_windows(exe_with_impossible_char, setup, 1234)

    # Falsch würde sein: Exception, crash, True (silent fail), oder Datei mit Datenverlust
    # Richtig: False, weil UnicodeEncodeError gefangen und geloggt
    assert result is False, "apply_windows sollte False liefern bei Kodierfehler"


def test_linux_apply_paths_are_siblings_of_the_appimage():
    from src.self_update import linux_apply_paths
    tmp, backup = linux_apply_paths("/home/u/Apps/Zeiterfassung.AppImage")
    assert tmp.startswith("/home/u/Apps/")
    assert backup == "/home/u/Apps/Zeiterfassung.AppImage.old"
    assert tmp != backup


def test_apply_linux_replaces_the_file_and_keeps_a_backup(tmp_path):
    from src.self_update import apply_linux
    target = tmp_path / "Zeiterfassung.AppImage"
    target.write_bytes(b"alt")
    neu = tmp_path / "geladen.tmp"
    neu.write_bytes(b"neu")

    assert apply_linux(str(target), str(neu)) is None
    assert target.read_bytes() == b"neu"
    assert (tmp_path / "Zeiterfassung.AppImage.old").read_bytes() == b"alt"


def test_apply_linux_makes_the_new_file_executable(tmp_path):
    import os as _os
    import stat
    from src.self_update import apply_linux
    target = tmp_path / "Z.AppImage"
    target.write_bytes(b"alt")
    neu = tmp_path / "n.tmp"
    neu.write_bytes(b"neu")
    apply_linux(str(target), str(neu))
    if sys.platform == "win32":
        pytest.skip("Ausfuehrbarkeits-Bit (S_IXUSR) ist unter Windows kein aussagekraeftiges Konzept")
    assert _os.stat(str(target)).st_mode & stat.S_IXUSR


def test_apply_linux_restores_the_backup_when_replacing_fails(tmp_path):
    import os as _os
    from unittest.mock import patch
    from src.self_update import apply_linux
    target = tmp_path / "Z.AppImage"
    target.write_bytes(b"alt")
    neu = tmp_path / "n.tmp"
    neu.write_bytes(b"neu")

    # NUR der zweite os.replace scheitert. `os.replace` global zu werfen waere
    # zweierlei falsch: schon die Sicherung schluege fehl (die Funktion kaeme
    # nie zum Rollback), und weil die Dateien sich unter einem Mock gar nicht
    # bewegen, wuerde die Schluss-Assertion ohnehin nur die Ausgangslage
    # bestaetigen. Deshalb echte Aufrufe, mit einer gezielten Ausnahme.
    real_replace = _os.replace
    calls = []

    def flaky(src, dst):
        calls.append((src, dst))
        if len(calls) == 2:          # das Einsetzen der neuen Datei
            raise OSError("kein Platz")
        return real_replace(src, dst)

    with patch("src.self_update.os.replace", side_effect=flaky):
        error = apply_linux(str(target), str(neu))

    assert error is not None
    assert len(calls) == 3, "sichern, einsetzen (faellt), zurueckrollen"
    assert target.read_bytes() == b"alt", "die alte Datei muss zurueck sein"
    assert not (tmp_path / "Z.AppImage.old").exists()


def test_sweep_appimage_backup_removes_a_leftover(tmp_path):
    from src.self_update import sweep_appimage_backup
    target = tmp_path / "Z.AppImage"
    target.write_bytes(b"neu")
    (tmp_path / "Z.AppImage.old").write_bytes(b"alt")
    assert sweep_appimage_backup(str(target)) is True
    assert not (tmp_path / "Z.AppImage.old").exists()


def test_sweep_appimage_backup_without_a_leftover_is_false(tmp_path):
    from src.self_update import sweep_appimage_backup
    target = tmp_path / "Z.AppImage"
    target.write_bytes(b"neu")
    assert sweep_appimage_backup(str(target)) is False
