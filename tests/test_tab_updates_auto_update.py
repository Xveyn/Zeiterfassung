"""Der stille Automatik-Download aus dem Updates-Tab: der Einstieg
`UpdatesTab._maybe_start_auto_update` (Abschluss-Review F2) und der
Abschluss `_start_self_update.done` bei geschlossenem Dialog (L2).

Gegenstueck zu `test_ui_update_routing.py::
test_maybe_auto_update_reuses_pending_download_without_redownloading` — die
Regel „liegt schon eine geprüfte Datei, wird NICHT erneut geladen" galt bis
zum Abschluss-Review nur auf der ui.py-Seite. Duck-Typed Stand-in wie in
test_tab_updates_apply.py: die Methode fasst nur `self._settings` und
`self._start_self_update` an.
"""

from types import MethodType
from unittest.mock import MagicMock

from src.dialogs.settings_dialog.tab_updates import UpdatesTab


class _FakeSettings:
    def __init__(self, data=None):
        self._data = data or {}

    def get(self, key):
        return self._data.get(key, "")


def _fake_tab(settings_data):
    fake = MagicMock()
    fake._settings = _FakeSettings(settings_data)
    fake._can_self_update = True
    fake._updating = False
    fake._maybe_start_auto_update = MethodType(
        UpdatesTab._maybe_start_auto_update, fake)
    return fake


class _Rel:
    version = "1.9.0"


def test_auto_update_starts_when_enabled_and_nothing_is_pending():
    fake = _fake_tab({"auto_update_enabled": True})
    rel = _Rel()

    fake._maybe_start_auto_update(rel)

    fake._start_self_update.assert_called_once_with(rel, auto=True)


def test_auto_update_skips_when_a_verified_download_is_already_pending():
    """Kern von F2: ohne diesen Guard laedt jedes Oeffnen des Updates-Tabs
    dieselben ~65 MB erneut, obwohl die geprüfte Datei laengst bereitliegt
    und beim naechsten Beenden installiert wird."""
    fake = _fake_tab({
        "auto_update_enabled": True,
        "pending_update_path": r"C:\Temp\Zeiterfassung_Setup-4711-ab12cd34.exe",
    })

    fake._maybe_start_auto_update(_Rel())

    fake._start_self_update.assert_not_called()


def test_auto_update_skips_when_the_setting_is_off():
    fake = _fake_tab({"auto_update_enabled": False})

    fake._maybe_start_auto_update(_Rel())

    fake._start_self_update.assert_not_called()


def test_auto_update_skips_when_the_platform_cannot_self_update():
    fake = _fake_tab({"auto_update_enabled": True})
    fake._can_self_update = False

    fake._maybe_start_auto_update(_Rel())

    fake._start_self_update.assert_not_called()


# --- UpdatesTab._start_self_update: Dialog waehrend des Downloads zu (L2) ---
#
# Der Runner ist `App._bg` und ueberlebt den Dialog — ein ~65-MB-Download
# laeuft nach dem Schliessen fertig und ruft `done()` auf einem toten Frame.


class _ImmediateRunner:
    """Fuehrt Worker und on_done sofort und synchron aus (wie der echte
    Runner, nur ohne Thread und ohne root.after)."""

    def run(self, fn, on_done):
        on_done(fn())


class _WritableSettings(_FakeSettings):
    def __init__(self, data=None):
        super().__init__(data)
        self.set_many_calls = []

    def set_many(self, updates):
        self.set_many_calls.append(dict(updates))
        self._data.update(updates)


def _run_download_with_closed_dialog(monkeypatch, tmp_path, auto):
    """Laesst `_start_self_update` durchlaufen, waehrend `frame.winfo_exists()`
    False liefert — der Dialog wurde also mitten im Download geschlossen.
    Liefert (fake, geladene_datei)."""
    import platform

    import src.dialogs.settings_dialog.tab_updates as tab_updates_module
    from src.self_update import DownloadedUpdate, UpdatePlan

    monkeypatch.setattr(platform, "system", lambda: "Windows")
    monkeypatch.setattr(tab_updates_module, "set_primary_button_enabled",
                        lambda *a, **k: None)
    monkeypatch.setattr(tab_updates_module, "set_secondary_button_enabled",
                        lambda *a, **k: None)
    plan = UpdatePlan(asset_url="https://x/exe",
                      asset_name="Zeiterfassung_Setup.exe",
                      sums_url="https://x/sums", target=r"C:\Apps\Z.exe")
    monkeypatch.setattr(tab_updates_module, "plan_update", lambda *a, **k: plan)

    local = tmp_path / "Zeiterfassung_Setup-4711-ab12cd34.exe"
    monkeypatch.setattr(tab_updates_module, "download_dest",
                        lambda *a, **k: str(local))

    def fake_download(plan_arg, dest, **kwargs):
        local.write_bytes(b"geprueftes Update")   # der Download ist fertig
        return DownloadedUpdate(path=dest, sha256="ab" * 32)

    monkeypatch.setattr(tab_updates_module, "download_and_verify_update",
                        fake_download)
    monkeypatch.setattr(
        tab_updates_module, "apply_windows",
        lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("bei geschlossenem Dialog nicht installieren")))

    fake = MagicMock()
    fake._settings = _WritableSettings()
    fake._can_self_update = True
    fake._updating = False
    fake._runner = _ImmediateRunner()
    fake.frame.winfo_exists.return_value = False   # Dialog ist zu
    fake._start_self_update = MethodType(UpdatesTab._start_self_update, fake)

    fake._start_self_update(_Rel(), auto=auto)
    return fake, local


def test_auto_download_is_persisted_even_if_the_dialog_was_closed(
        monkeypatch, tmp_path):
    """L2, Automatik-Weg: die Datei ist fertig geprueft — sie beim naechsten
    Beenden anzuwenden ist genau das gewuenschte Verhalten. Ein Guard vor dem
    `set_many` liesse sie weder persistiert noch geloescht zurueck, und seit
    `download_dest` raeumt kein spaeterer Lauf sie mehr weg."""
    fake, local = _run_download_with_closed_dialog(monkeypatch, tmp_path,
                                                   auto=True)

    assert fake._settings.set_many_calls == [{
        "pending_update_path": str(local),
        "pending_update_sha256": "ab" * 32,
    }]
    assert local.exists(), "die vorbereitete Datei darf NICHT geloescht werden"


def test_manual_download_is_discarded_if_the_dialog_was_closed(
        monkeypatch, tmp_path):
    """L2, manueller Weg: `_apply` wuerde sofort installieren und die App
    dabei beenden. Hinter dem Ruecken eines Nutzers, der den Dialog gerade
    zugemacht hat, ist das falsch — also verwerfen statt liegen lassen."""
    fake, local = _run_download_with_closed_dialog(monkeypatch, tmp_path,
                                                   auto=False)

    assert not local.exists(), "die nicht angewendete Datei bleibt sonst liegen"
    assert fake._settings.set_many_calls == []
