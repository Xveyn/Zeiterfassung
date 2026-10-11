"""Vertrag aller Schreiber lokaler Secrets (#246).

Jede Datei mit einem Secret läuft über `secure_file.write_secret_bytes`. Dieser Test geht
durch den **öffentlichen** Einstieg jedes Schreibers und hält fest, was für alle gelten muss:

* gehärtet wird die Temp-Datei, solange sie noch **leer** ist (nie steht ein Secret in einer
  Datei mit geerbten Rechten), und bevor sie unter dem Zielnamen sichtbar wird;
* kein Temp bleibt liegen, auch nicht nach einem Fehler; die alte Datei bleibt unberührt;
* ein kurz blockierter Rename (Virenscanner) wird wiederholt.

Neue Secret-Dateien tragen sich hier ein. Ein Schreiber mit eigenem Ablauf fiele durch den
Quelltext-Test unten.
"""
import ast
import os
import pathlib
import stat

import pytest

from src import api_auth, oauth_utils, secure_file, single_instance
from src.smtp_store import SmtpStore
from src.webhook_store import WebhookStore
from tests.test_smtp_store import _record as smtp_record
from tests.test_webhook_store import _record as webhook_record

SRC = pathlib.Path(__file__).resolve().parent.parent / "src"


def _bytes(directory):
    path = directory / "s.bin"
    secure_file.write_secret_bytes(str(path), os.urandom(8), prefix=".sec-")
    return path


def _json(directory):
    path = directory / "s.json"
    secure_file.write_secret_json(str(path), {"n": os.urandom(4).hex()}, prefix=".sec-")
    return path


def _token_json(directory):
    path = directory / "token.json"
    oauth_utils.write_token_json('{"n": "%s"}' % os.urandom(4).hex(), str(path))
    return path


def _webhooks(directory):
    path = directory / "webhooks.json"
    WebhookStore(str(path)).save(webhook_record(name=os.urandom(4).hex()))
    return path


def _smtp(directory):
    path = directory / "smtp.json"
    SmtpStore(str(path)).save(smtp_record(name=os.urandom(4).hex()))
    return path


def _api_token(directory):
    api_auth.rotate_token(str(directory))
    return directory / api_auth.TOKEN_FILENAME


def _instance_secret(directory):
    path = directory / "instance-secret"
    single_instance._write_secret_atomic(str(path), os.urandom(32))
    return path


WRITERS = {"bytes": _bytes, "json": _json, "token.json": _token_json, "webhooks": _webhooks,
           "smtp": _smtp, "api-token": _api_token, "instance-secret": _instance_secret}
writers = pytest.mark.parametrize("write", WRITERS.values(), ids=WRITERS.keys())


@writers
def test_the_temp_file_is_hardened_while_it_is_still_empty_and_before_it_is_visible(
        write, tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(secure_file, "harden_windows_acl", lambda p: seen.append(
        (os.path.getsize(p), os.path.basename(p), list(os.listdir(tmp_path)))))

    target = write(tmp_path)

    assert len(seen) == 1
    size, name, listing = seen[0]
    assert size == 0                                      # noch kein Secret in der Datei
    assert name.startswith(".") and name.endswith(".tmp")
    assert target.name not in listing                     # und das Ziel noch nicht sichtbar
    assert target.stat().st_size > 0


@writers
def test_no_temp_file_is_left_behind_and_the_file_is_private(write, tmp_path):
    target = write(tmp_path)

    assert [p.name for p in tmp_path.iterdir()] == [target.name]
    if os.name != "nt":
        assert stat.S_IMODE(target.stat().st_mode) == 0o600


@writers
def test_a_failed_rename_cleans_up_and_keeps_the_old_file(write, tmp_path, monkeypatch):
    target = write(tmp_path)
    before = target.read_bytes()
    monkeypatch.setattr(os, "replace", lambda a, b: (_ for _ in ()).throw(OSError("voll")))

    try:
        write(tmp_path)
    except Exception:      # noqa: BLE001 — manche Einstiege melden den Fehler, andere geben ihn weiter
        pass

    assert target.read_bytes() == before
    assert [p.name for p in tmp_path.iterdir()] == [target.name]


@writers
def test_a_briefly_blocked_rename_is_retried(write, tmp_path, monkeypatch):
    real_replace, attempts = os.replace, []

    def flaky(a, b):
        attempts.append(1)
        if len(attempts) < 3:
            raise PermissionError("Virenscanner")
        return real_replace(a, b)

    monkeypatch.setattr(os, "replace", flaky)
    monkeypatch.setattr(secure_file.time, "sleep", lambda s: None)

    target = write(tmp_path)

    assert len(attempts) == 3 and target.exists()


def test_only_secure_file_and_the_token_reader_harden_files():
    """Kein Modul baut einen eigenen Schreibablauf mit `harden_windows_acl`: außer
    `secure_file` darf nur `api_auth` es rufen, und dort nur für eine **vorhandene** Datei
    (`_harden_existing`). Ein weiteres Vorkommen ist ein neuer Schreibpfad, der den Vertrag oben
    umgeht."""
    callers = {}
    for path in SRC.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
                if name == "harden_windows_acl":
                    callers.setdefault(path.relative_to(SRC).as_posix(), []).append(node.lineno)

    assert set(callers) == {"secure_file.py", "api_auth.py"}, callers
    assert len(callers["api_auth.py"]) == 1                      # `_harden_existing`
