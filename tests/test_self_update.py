"""Reine Logik des In-App-Updates (Tk-frei, ohne Netzwerk)."""

import hashlib

from src.self_update import parse_sha256sums, verify_file

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
