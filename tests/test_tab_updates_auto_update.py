"""Der Ein-Klick-Weg im Updates-Tab (`UpdatesTab._start_self_update`) und
sein Verhältnis zum stillen Hintergrund-Download.

Die Auto-Update-Policy selbst (Häkchen, vorbereitete Datei, Guard) liegt seit
R9 in `src/auto_update.py` und wird in `test_auto_update.py` geprüft. Hier
bleibt, was der Tab selbst entscheidet: dass er den gemeinsamen Guard
respektiert und freigibt, und was mit einer fertigen Datei geschieht, wenn
der Dialog inzwischen zu ist (L2).

Duck-Typed Stand-in wie in test_tab_updates_apply.py, aber mit ECHTEM
`AutoUpdater` — der Guard ist genau das, worum es geht.
"""

from types import MethodType
from unittest.mock import MagicMock

from src.auto_update import AutoUpdater
from src.dialogs.settings_dialog.tab_updates import UpdatesTab
from src.self_update import DownloadedUpdate, UpdatePlan


class _Rel:
    version = "1.9.0"
    release_id = "1.9.0"


class _FakeSettings:
    def __init__(self, data=None):
        self._data = data or {}
        self.set_many_calls = []

    def get(self, key):
        return self._data.get(key, "")

    def set_many(self, updates):
        self.set_many_calls.append(dict(updates))
        self._data.update(updates)


class _ImmediateRunner:
    """Fuehrt Worker und on_done sofort und synchron aus (wie der echte
    Runner, nur ohne Thread und ohne root.after)."""

    def run(self, fn, on_done):
        on_done(fn())


class _HeldRunner:
    """Haelt Jobs fest — der Download laeuft also noch."""

    def __init__(self):
        self.jobs = []

    def run(self, fn, on_done=None):
        self.jobs.append((fn, on_done))


_PLAN = UpdatePlan(asset_url="https://x/exe",
                   asset_name="Zeiterfassung_Setup.exe",
                   sums_url="https://x/sums", target=r"C:\Apps\Z.exe")


def _manual_tab(monkeypatch, tmp_path, *, runner, dialog_alive=True):
    """Bindet `_start_self_update` an ein Fake-Tab mit echtem AutoUpdater.
    Liefert (tab, geladene_datei, downloads)."""
    import platform

    import src.dialogs.settings_dialog.tab_updates as tab_updates_module

    monkeypatch.setattr(platform, "system", lambda: "Windows")
    monkeypatch.setattr(tab_updates_module, "set_primary_button_enabled",
                        lambda *a, **k: None)
    monkeypatch.setattr(tab_updates_module, "set_secondary_button_enabled",
                        lambda *a, **k: None)
    monkeypatch.setattr(tab_updates_module, "plan_update", lambda *a, **k: _PLAN)

    local = tmp_path / "Zeiterfassung_Setup-4711-ab12cd34.exe"
    monkeypatch.setattr(tab_updates_module, "download_dest",
                        lambda *a, **k: str(local))
    downloads = []

    def fake_download(plan_arg, dest, **kwargs):
        downloads.append(dest)
        local.write_bytes(b"geprueftes Update")   # der Download ist fertig
        return DownloadedUpdate(path=dest, sha256="ab" * 32)

    monkeypatch.setattr(tab_updates_module, "download_and_verify_update",
                        fake_download)

    tab = MagicMock()
    tab._settings = _FakeSettings()
    tab._auto_updater = AutoUpdater(tab._settings, runner, on_ready=lambda r: None)
    tab._runner = runner
    tab._updating = False
    tab.frame.winfo_exists.return_value = dialog_alive
    tab._start_self_update = MethodType(UpdatesTab._start_self_update, tab)
    return tab, local, downloads


def test_manual_click_does_not_start_a_second_download_beside_the_background_one(
        monkeypatch, tmp_path):
    """Verhaltensaenderung aus R9: laedt der Start-Check der App gerade still,
    startet „Update installieren" keinen zweiten ~65-MB-Download daneben. Der
    alte Weg liess sonst beim sofortigen Installieren den halben stillen
    Download in %TEMP% zurueck."""
    tab, _, downloads = _manual_tab(monkeypatch, tmp_path, runner=_HeldRunner())
    assert tab._auto_updater.acquire_manual()   # irgendein Download laeuft

    tab._start_self_update(_Rel())

    assert tab._runner.jobs == []
    assert downloads == []
    assert tab._updating is False, "die Knoepfe bleiben bedienbar"


def test_the_guard_is_free_again_after_a_manual_download(monkeypatch, tmp_path):
    """Ohne Freigabe blockierte ein einziger manueller Download jeden
    kuenftigen stillen Lauf bis zum Neustart."""
    import src.dialogs.settings_dialog.tab_updates as tab_updates_module

    tab, _, _ = _manual_tab(monkeypatch, tmp_path, runner=_ImmediateRunner())
    monkeypatch.setattr(tab_updates_module, "download_and_verify_update",
                        lambda *a, **k: "Der Download ist fehlgeschlagen.")
    tab._fail_update = MagicMock()

    tab._start_self_update(_Rel())

    tab._fail_update.assert_called_once_with("Der Download ist fehlgeschlagen.")
    assert tab._auto_updater.busy is False


def test_manual_download_is_discarded_if_the_dialog_was_closed(
        monkeypatch, tmp_path):
    """L2, manueller Weg: `_apply` wuerde sofort installieren und die App
    dabei beenden. Hinter dem Ruecken eines Nutzers, der den Dialog gerade
    zugemacht hat, ist das falsch — also verwerfen statt liegen lassen."""
    import src.dialogs.settings_dialog.tab_updates as tab_updates_module

    monkeypatch.setattr(
        tab_updates_module, "apply_windows",
        lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("bei geschlossenem Dialog nicht installieren")))
    tab, local, _ = _manual_tab(monkeypatch, tmp_path,
                                runner=_ImmediateRunner(), dialog_alive=False)

    tab._start_self_update(_Rel())

    assert not local.exists(), "die nicht angewendete Datei bleibt sonst liegen"
    assert tab._settings.set_many_calls == []
