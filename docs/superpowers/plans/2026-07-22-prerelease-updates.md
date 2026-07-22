# Pre-Release-Updates (Opt-in) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Die App bietet auf Wunsch (Häkchen im Updates-Tab, Default aus) auch Pre-Releases als Update an — sichtbar im Tab, herunterladbar, und im Hintergrund-Check als Toast/Banner gemeldet.

**Architecture:** Versions-Semantik (Parsen/Ordnen von `X.Y.Z[-pre.N]`) zieht nach `src/version.py`, weil `src/updater.py` bereits von dort importiert (kein Zyklus). `updater.py` bekommt einen zweiten Fetch-Pfad (`/releases?per_page=10`) und wählt daraus selbst das Maximum; der Stable-Pfad (`/releases/latest`) bleibt unangetastet. Damit die App weiß, *welcher* Pre-Build sie ist, stempelt `release.yml` → `build.py` den Release-Tag als `RELEASE_TAG` in `build_info.py`.

**Tech Stack:** Python 3.10, stdlib-only für Netzwerk (`urllib`), Tkinter für die UI, pytest, ruff. Keine neuen Abhängigkeiten.

## Global Constraints

- Design-Grundlage ist `docs/superpowers/specs/2026-07-22-prerelease-updates-design.md`. Bei Widersprüchen gilt die Spec.
- Ordnung: `parse_release_id` bildet auf `(major, minor, patch, pre_rank)` ab, echtes Release hat `pre_rank = 0`, `-pre.N` hat Rang `N`. Es gilt `1.19.0 < 1.19.0-pre.1 < 1.19.0-pre.2 < 1.19.1`.
- `Release.version` bleibt **immer** die Basisversion ohne `-pre.N` (`pick_asset_url` baut daraus Asset-Namen). Die volle Kennung steht in `Release.release_id`.
- Netzwerk-Konvention: jeder Fehler (Netz, Timeout, kaputtes JSON, unerwartete Struktur) endet in `None`, **nie** eine Exception nach außen.
- Tk-Variablen werden ausschließlich im UI-Thread gelesen; Worker-Closures bekommen fertige Werte.
- Update-Settings sind gerätelokal: `prerelease_updates_enabled` kommt **nicht** in `SYNCED_SETTING_KEYS`.
- Tests sind Tk-frei (CI läuft ohne Display). Reine Logik wird getestet, Tk-Verdrahtung manuell verifiziert.
- Commit-Typ englisch (`feat:`/`fix:`/`docs:`/`test:`), Body deutsch. Nach jedem Task muss `pytest` grün und `ruff check .` sauber sein.
- Alle Arbeit passiert auf dem bestehenden Branch `feat/prerelease-updates`.

---

### Task 1: Versions-Ordnung mit Pre-Release-Rang

**Files:**
- Modify: `src/version.py` (neue Funktionen `parse_release_id`, `base_version`)
- Modify: `src/updater.py:16-22` (`_to_tuple`/`is_newer` ersetzen)
- Test: `tests/test_version_label.py`, `tests/test_updater.py`

**Interfaces:**
- Consumes: nichts (erster Task)
- Produces:
  - `src.version.parse_release_id(release_id: str) -> tuple[int, int, int, int] | None`
  - `src.version.base_version(release_id: str) -> str`
  - `src.updater.is_newer(current: str, latest: str) -> bool` (Signatur unverändert, Semantik erweitert)

- [ ] **Step 1: Write the failing tests**

Ans Ende von `tests/test_version_label.py` anhängen (der Import oben wird mit erweitert):

```python
from src.version import base_version, parse_release_id


class TestParseReleaseId:
    def test_plain_release_gets_rank_zero(self):
        assert parse_release_id("1.19.0") == (1, 19, 0, 0)

    def test_prerelease_gets_its_number_as_rank(self):
        assert parse_release_id("1.19.0-pre.2") == (1, 19, 0, 2)

    def test_prerelease_ranks_above_its_own_release(self):
        # Repo-Konvention: der Pre-Release entsteht NACH dem gleichnamigen
        # Release, aus neuerem Code (v1.18.2 am 16.07., v1.18.2-pre.1 am 20.07.).
        assert parse_release_id("1.18.2-pre.1") > parse_release_id("1.18.2")

    def test_next_patch_ranks_above_any_prerelease(self):
        assert parse_release_id("1.18.3") > parse_release_id("1.18.2-pre.5")

    def test_prerelease_numbers_compare_numerically_not_lex(self):
        assert parse_release_id("1.18.2-pre.10") > parse_release_id("1.18.2-pre.9")

    def test_garbage_returns_none(self):
        assert parse_release_id("nightly") is None

    def test_two_part_version_returns_none(self):
        # Bewusste Verschärfung gegenüber dem alten _to_tuple: exakt X.Y.Z[-pre.N].
        assert parse_release_id("1.9") is None

    def test_empty_returns_none(self):
        assert parse_release_id("") is None

    def test_none_returns_none(self):
        assert parse_release_id(None) is None

    def test_other_suffix_returns_none(self):
        assert parse_release_id("1.19.0-rc.1") is None


class TestBaseVersion:
    def test_strips_pre_suffix(self):
        assert base_version("1.19.0-pre.2") == "1.19.0"

    def test_plain_version_unchanged(self):
        assert base_version("1.19.0") == "1.19.0"

    def test_empty_stays_empty(self):
        assert base_version("") == ""
```

In `tests/test_updater.py` innerhalb der bestehenden Klasse `TestIsNewer` ergänzen:

```python
    def test_prerelease_of_same_base_is_newer_than_release(self):
        assert is_newer("1.18.2", "1.18.2-pre.1") is True

    def test_release_is_not_newer_than_its_own_prerelease(self):
        assert is_newer("1.18.2-pre.1", "1.18.2") is False

    def test_higher_prerelease_number_is_newer(self):
        assert is_newer("1.18.2-pre.1", "1.18.2-pre.2") is True

    def test_same_prerelease_is_not_newer(self):
        assert is_newer("1.18.2-pre.2", "1.18.2-pre.2") is False

    def test_next_patch_is_newer_than_prerelease(self):
        assert is_newer("1.18.2-pre.5", "1.18.3") is True

    def test_unparsable_latest_is_not_newer(self):
        # Kaputter Tag darf die Auswahl nicht sprengen — still ignorieren.
        assert is_newer("1.18.2", "nightly") is False

    def test_unparsable_current_is_not_newer(self):
        assert is_newer("nightly", "1.18.2") is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_version_label.py tests/test_updater.py -v`
Expected: FAIL — `ImportError: cannot import name 'base_version' from 'src.version'`

- [ ] **Step 3: Implement in `src/version.py`**

Ganz oben in `src/version.py` `import re` ergänzen (vor dem `try`-Import von `build_info`), danach direkt unter der `VERSION`-Zeile einfügen:

```python
# Kennung eines Releases: "1.19.0" (echtes Release) oder "1.19.0-pre.2"
# (Pre-Release, s. .github/workflows/release.yml). Kein anderes Suffix ist
# gültig — alles Übrige gilt als unbekannt und damit als "nicht neuer".
_RELEASE_ID = re.compile(r"^(\d+)\.(\d+)\.(\d+)(?:-pre\.(\d+))?$")


def parse_release_id(release_id):
    """Vergleichsschlüssel `(major, minor, patch, pre_rank)` einer Release-
    Kennung (ohne v-Prefix), oder None wenn sie nicht dem Muster folgt.

    Ein echtes Release bekommt `pre_rank = 0`, `-pre.N` den Rang `N`. Damit
    gilt `1.19.0 < 1.19.0-pre.1 < 1.19.1` — die Umkehrung der Semver-Regel,
    aber die Praxis dieses Repos: ein Pre-Release wird IMMER nach dem
    gleichnamigen echten Release aus neuerem Code gebaut (v1.18.2 am
    2026-07-16, v1.18.2-pre.1 am 2026-07-20). Wer daran etwas ändert, muss
    diese Ordnung mitändern — s. CLAUDE.md, Abschnitt Pre-Releases.
    """
    match = _RELEASE_ID.match(release_id or "")
    if match is None:
        return None
    major, minor, patch, pre = match.groups()
    return (int(major), int(minor), int(patch), int(pre) if pre else 0)


def base_version(release_id):
    """Basisversion einer Kennung: '1.19.0-pre.2' -> '1.19.0'. Die Artefakte
    eines Pre-Releases tragen die reine Version im Namen (build.py benennt sie
    unabhängig vom Kanal), darum braucht der Asset-Match diese Form."""
    return (release_id or "").split("-pre.")[0]
```

- [ ] **Step 4: Implement in `src/updater.py`**

`src/updater.py:13` erweitern zu:

```python
from src.version import VERSION, parse_release_id
```

`_to_tuple` (Zeilen 16-17) ersatzlos löschen und `is_newer` ersetzen durch:

```python
def is_newer(current: str, latest: str) -> bool:
    """True, wenn `latest` strikt neuer ist als `current`. Beide sind
    Release-Kennungen ohne v-Prefix ('1.19.0' oder '1.19.0-pre.2').

    Ist eine Seite nicht parsebar, gilt "nicht neuer" — ein kaputter oder
    fremder Tag im Release-Feed darf weder crashen noch ein Update auslösen.
    """
    current_key = parse_release_id(current)
    latest_key = parse_release_id(latest)
    if current_key is None or latest_key is None:
        return False
    return latest_key > current_key
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_version_label.py tests/test_updater.py -v`
Expected: PASS (alle, inkl. der bestehenden `TestIsNewer`-Fälle)

- [ ] **Step 6: Full suite + lint**

Run: `python -m pytest -q` → Expected: alle grün
Run: `ruff check .` → Expected: `All checks passed!`

- [ ] **Step 7: Commit**

```bash
git add src/version.py src/updater.py tests/test_version_label.py tests/test_updater.py
git commit -m "feat(updater): Versions-Ordnung mit Pre-Release-Rang"
```

---

### Task 2: Build-Identität — Release-Tag in `build_info` stempeln

**Files:**
- Modify: `src/version.py` (`_stamped_release_id`, `installed_release_id`, `_format_version_label`, `version_label`)
- Modify: `build.py:228-266` (`generate_build_info`)
- Modify: `.github/workflows/release.yml:128-132,151-155,181-185` (drei `env`-Blöcke)
- Test: `tests/test_version_label.py`

**Interfaces:**
- Consumes: `src.version.parse_release_id` (Task 1)
- Produces:
  - `src.version.installed_release_id() -> str` — Kennung des laufenden Builds (`"1.19.0-pre.2"` oder `VERSION`)
  - `src.version._format_version_label(version, channel, sha, release_id="")` — vierter Parameter neu, Default hält bestehende Aufrufer gültig

- [ ] **Step 1: Write the failing tests**

Ans Ende von `tests/test_version_label.py` anhängen:

```python
from unittest.mock import patch

from src.version import VERSION, _format_version_label, installed_release_id


class _FakeBuildInfo:
    def __init__(self, channel="release", sha="abc1234", release_tag=None):
        self.CHANNEL = channel
        self.GIT_SHA = sha
        if release_tag is not None:
            self.RELEASE_TAG = release_tag


class TestFormatVersionLabelWithStampedTag:
    def test_prerelease_with_stamped_tag_shows_number(self):
        assert _format_version_label(
            "1.19.0", "prerelease", "abc1234", "1.19.0-pre.2",
        ) == "1.19.0-pre.2"

    def test_prerelease_without_stamped_tag_falls_back_to_plain_marker(self):
        # Alt-Build ohne Stempel: heutiges Verhalten bleibt.
        assert _format_version_label("1.19.0", "prerelease", "abc1234", "") == "1.19.0-pre"

    def test_release_ignores_stamped_tag(self):
        assert _format_version_label("1.19.0", "release", "", "1.19.0") == "1.19.0"


class TestInstalledReleaseId:
    def test_stamped_prerelease_tag_wins(self):
        with patch("src.version._build_info",
                   _FakeBuildInfo(channel="prerelease", release_tag="v1.19.0-pre.2")):
            assert installed_release_id() == "1.19.0-pre.2"

    def test_uppercase_v_prefix_is_stripped(self):
        with patch("src.version._build_info",
                   _FakeBuildInfo(channel="prerelease", release_tag="V1.19.0-pre.2")):
            assert installed_release_id() == "1.19.0-pre.2"

    def test_missing_attribute_falls_back_to_version(self):
        # Alt-Build: build_info ohne RELEASE_TAG.
        with patch("src.version._build_info", _FakeBuildInfo(channel="release")):
            assert installed_release_id() == VERSION

    def test_empty_tag_falls_back_to_version(self):
        with patch("src.version._build_info",
                   _FakeBuildInfo(channel="dev", release_tag="")):
            assert installed_release_id() == VERSION

    def test_unparsable_tag_falls_back_to_version(self):
        with patch("src.version._build_info",
                   _FakeBuildInfo(channel="release", release_tag="v-nightly")):
            assert installed_release_id() == VERSION

    def test_no_build_info_falls_back_to_version(self):
        # Start aus dem Quellcode (python -m src.main).
        with patch("src.version._build_info", None):
            assert installed_release_id() == VERSION
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_version_label.py -v`
Expected: FAIL — `ImportError: cannot import name 'installed_release_id' from 'src.version'`

- [ ] **Step 3: Implement in `src/version.py`**

`_format_version_label` um den vierten Parameter erweitern:

```python
def _format_version_label(version, channel, sha, release_id=""):
    """Anzeige-Label für den Fenstertitel. Release → reine Version; Pre-Release
    (plattformübergreifender Test-Build) → die gestempelte Kennung inkl. Nummer
    ('1.19.0-pre.2'), ohne Stempel der alte '-pre'-Marker; jeder andere Kanal
    (dev/source) → '-dev'-Suffix, mit Kurz-SHA in Klammern falls vorhanden."""
    if channel == "release":
        return version
    if channel == "prerelease":
        return release_id or f"{version}-pre"
    if sha:
        return f"{version}-dev ({sha})"
    return f"{version}-dev"
```

Darunter die beiden neuen Funktionen und das angepasste `version_label`:

```python
def _stamped_release_id():
    """Release-Kennung aus dem beim Build gestempelten Tag ('v1.19.0-pre.2'
    -> '1.19.0-pre.2'). Leer, wenn kein Stempel existiert (Alt-Builds vor
    diesem Feature, Dev-/Repo-Modus) oder der Tag nicht dem Muster folgt."""
    tag = "" if _build_info is None else getattr(_build_info, "RELEASE_TAG", "")
    tag = (tag or "").strip()
    if tag[:1] in ("v", "V"):
        tag = tag[1:]
    return tag if parse_release_id(tag) is not None else ""


def installed_release_id():
    """Kennung des laufenden Builds für den Update-Vergleich. Ohne Stempel
    gilt die reine VERSION (Rang 0) — für ein echtes Release ist das exakt
    richtig, für einen Alt-Pre-Build die dokumentierte Grenze (er bekommt
    einmalig auch seinen eigenen Build angeboten)."""
    return _stamped_release_id() or VERSION


def version_label():
    """Versions-Label inkl. Kanal-Marker für die Titelzeile. Liest den beim Build
    gestempelten Kanal; fehlt build_info (Quellcode-Start), gilt 'source'."""
    if _build_info is None:
        channel, sha = "source", ""
    else:
        channel = getattr(_build_info, "CHANNEL", "dev")
        sha = getattr(_build_info, "GIT_SHA", "")
    return _format_version_label(VERSION, channel, sha, _stamped_release_id())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_version_label.py -v`
Expected: PASS

- [ ] **Step 5: Stempel in `build.py` schreiben**

In `build.py::generate_build_info` den Docstring-Absatz

```
    Der Release-Tag vX.Y.Z entsteht erst nach dem Build, taugt daher nicht zur
    Kanal-Erkennung — daher die expliziten Flags."""
```

ersetzen durch:

```
    Der Release-Tag taugt nicht zur Kanal-Erkennung (er wird erst nach dem Build
    gepusht) — daher die expliziten Flags. Für die Update-Prüfung reicht der
    Workflow ihn aber als ZEIT_RELEASE_TAG durch (Job `pre-check` berechnet ihn
    vor den Build-Jobs); ohne die Variable bleibt RELEASE_TAG leer."""
```

Direkt nach der `channel`-Ermittlung ergänzen:

```python
    release_tag = os.environ.get("ZEIT_RELEASE_TAG", "")
```

Den `f.write(...)`-Block um eine Zeile erweitern (nach `GIT_SHA`):

```python
            f'RELEASE_TAG = "{release_tag}"\n'
```

Und die Abschluss-Ausgabe:

```python
    print(f"build_info: CHANNEL={channel} TAG={release_tag or '-'} SHA={sha or '-'} DIRTY={dirty}")
```

- [ ] **Step 6: Stempel lokal verifizieren**

Run:
```bash
ZEIT_RELEASE=1 ZEIT_PRERELEASE=1 ZEIT_RELEASE_TAG=v1.19.0-pre.7 python -c "import build; build.generate_build_info()" && cat src/build_info.py
```
Expected: Ausgabe enthält `CHANNEL=prerelease TAG=v1.19.0-pre.7`, und die Datei enthält `RELEASE_TAG = "v1.19.0-pre.7"`.

Anschließend prüfen, dass das Label die Nummer zeigt:
```bash
python -c "from src.version import version_label, installed_release_id; print(version_label(), installed_release_id())"
```
Expected: `1.19.0-pre.7 1.19.0-pre.7` (die `VERSION` aus `src/version.py` kann abweichen — entscheidend ist das `-pre.7`).

Danach den Stempel wieder entfernen, damit der Repo-Modus sauber bleibt:
```bash
rm src/build_info.py
```
(`src/build_info.py` ist gitignored — der Schritt schützt nur die laufende Dev-Instanz.)

- [ ] **Step 7: Workflow durchreichen**

In `.github/workflows/release.yml` in **allen drei** Build-Jobs (`build-windows`, `build-macos-arm`, `build-linux`) den `env`-Block des `Build`-Steps um eine Zeile ergänzen, sodass er lautet:

```yaml
        env:
          ZEIT_RELEASE: "1"
          ZEIT_PRERELEASE: ${{ needs.pre-check.outputs.is_prerelease == 'true' && '1' || '' }}
          ZEIT_RELEASE_TAG: ${{ needs.pre-check.outputs.tag }}
```

- [ ] **Step 8: Full suite + lint**

Run: `python -m pytest -q` → Expected: alle grün
Run: `ruff check .` → Expected: `All checks passed!`

- [ ] **Step 9: Commit**

```bash
git add src/version.py build.py .github/workflows/release.yml tests/test_version_label.py
git commit -m "feat(build): Release-Tag als RELEASE_TAG in build_info stempeln"
```

---

### Task 3: Release-Payload parsen und Pre-Release-Kanal abfragen

**Files:**
- Modify: `src/updater.py:70-81` (Dataclass `Release`), `:141-176` (`check_latest_release`)
- Test: `tests/test_updater.py`

**Interfaces:**
- Consumes: `src.version.base_version`, `src.version.parse_release_id` (Task 1)
- Produces:
  - `Release(version, html_url, assets, release_id="", is_prerelease=False, notes="")` — `release_id` fällt ohne Angabe auf `version` zurück
  - `src.updater.release_from_payload(payload: dict) -> Release | None`
  - `src.updater.select_newest_payload(payloads: list) -> dict | None`
  - `src.updater.check_latest_release_any(repo: str, timeout: float = 5.0) -> Release | None`
  - `src.updater.check_for_update(repo: str, include_prereleases: bool, timeout: float = 5.0) -> Release | None`

- [ ] **Step 1: Write the failing tests**

Ans Ende von `tests/test_updater.py` anhängen (die bestehenden Helfer `_api_response`/`HAPPY_PAYLOAD` oben werden mitgenutzt; den Import in Zeile 8-12 um die neuen Namen erweitern):

```python
PRERELEASE_PAYLOAD = {
    "tag_name": "v1.19.0-pre.2",
    "html_url": "https://github.com/MargenHeld/Zeiterfassung/releases/tag/v1.19.0-pre.2",
    "prerelease": True,
    "body": "## What's Changed\n* feat: etwas Neues by @someone in #170",
    "assets": [
        {"name": "Zeiterfassung_Setup.exe", "browser_download_url": "https://example.com/pre-exe"},
        {"name": "Zeiterfassung-1.19.0-arm64.dmg", "browser_download_url": "https://example.com/pre-dmg"},
    ],
}


class TestReleaseIdentity:
    def test_release_id_defaults_to_version(self):
        # Alt-Konstruktion ohne release_id (Tests, echte Releases): die
        # Kennung IST die Version.
        release = Release(version="1.19.0", html_url="x", assets=())
        assert release.release_id == "1.19.0"
        assert release.is_prerelease is False
        assert release.notes == ""


class TestReleaseFromPayload:
    def test_prerelease_payload_splits_id_and_base_version(self):
        release = release_from_payload(PRERELEASE_PAYLOAD)
        assert release is not None
        assert release.release_id == "1.19.0-pre.2"
        # version = Basisversion, weil die Assets so heißen
        assert release.version == "1.19.0"
        assert release.is_prerelease is True
        assert release.notes.startswith("## What's Changed")
        assert len(release.assets) == 2

    def test_real_release_payload_has_matching_id_and_version(self):
        release = release_from_payload(HAPPY_PAYLOAD)
        assert release is not None
        assert release.release_id == "1.9.0"
        assert release.version == "1.9.0"
        assert release.is_prerelease is False
        assert release.notes == ""

    def test_missing_tag_returns_none(self):
        assert release_from_payload({"html_url": "x"}) is None

    def test_missing_html_url_returns_none(self):
        assert release_from_payload({"tag_name": "v1.9.0"}) is None

    def test_non_dict_returns_none(self):
        assert release_from_payload("not-a-dict") is None


def _entry(tag, prerelease=False, draft=False):
    return {
        "tag_name": tag, "html_url": f"https://x/{tag}",
        "prerelease": prerelease, "draft": draft, "assets": [],
    }


class TestSelectNewestPayload:
    def test_picks_prerelease_over_its_own_release(self):
        newest = select_newest_payload([
            _entry("v1.19.0"),
            _entry("v1.19.0-pre.2", prerelease=True),
            _entry("v1.19.0-pre.1", prerelease=True),
        ])
        assert newest["tag_name"] == "v1.19.0-pre.2"

    def test_picks_higher_release_over_older_prerelease(self):
        newest = select_newest_payload([
            _entry("v1.18.2-pre.5", prerelease=True),
            _entry("v1.19.0"),
        ])
        assert newest["tag_name"] == "v1.19.0"

    def test_order_in_list_does_not_matter(self):
        newest = select_newest_payload([
            _entry("v1.19.0-pre.1", prerelease=True),
            _entry("v1.19.0-pre.10", prerelease=True),
            _entry("v1.18.0"),
        ])
        assert newest["tag_name"] == "v1.19.0-pre.10"

    def test_drafts_are_skipped(self):
        newest = select_newest_payload([
            _entry("v1.20.0", draft=True),
            _entry("v1.19.0"),
        ])
        assert newest["tag_name"] == "v1.19.0"

    def test_unparsable_tags_are_skipped(self):
        newest = select_newest_payload([
            _entry("nightly"),
            _entry("v1.19.0"),
        ])
        assert newest["tag_name"] == "v1.19.0"

    def test_empty_list_returns_none(self):
        assert select_newest_payload([]) is None

    def test_only_unparsable_returns_none(self):
        assert select_newest_payload([_entry("nightly")]) is None


class TestCheckForUpdate:
    def test_without_prereleases_uses_latest_endpoint(self):
        seen = {}

        def fake_urlopen(request, timeout=None):
            seen["url"] = request.full_url
            return _api_response(HAPPY_PAYLOAD)

        with patch("src.updater.urlopen", side_effect=fake_urlopen):
            release = check_for_update("any/repo", include_prereleases=False)
        assert seen["url"].endswith("/releases/latest")
        assert release.release_id == "1.9.0"

    def test_with_prereleases_uses_list_endpoint_and_picks_maximum(self):
        seen = {}

        def fake_urlopen(request, timeout=None):
            seen["url"] = request.full_url
            return _api_response([HAPPY_PAYLOAD, PRERELEASE_PAYLOAD])

        with patch("src.updater.urlopen", side_effect=fake_urlopen):
            release = check_for_update("any/repo", include_prereleases=True)
        assert "/releases?per_page=10" in seen["url"]
        assert release.release_id == "1.19.0-pre.2"

    def test_list_endpoint_network_error_returns_none(self):
        with patch("src.updater.urlopen", side_effect=URLError("offline")):
            assert check_for_update("any/repo", include_prereleases=True) is None

    def test_list_endpoint_unexpected_shape_returns_none(self):
        # API liefert wider Erwarten ein Objekt statt einer Liste.
        with patch("src.updater.urlopen", return_value=_api_response({"message": "rate limited"})):
            assert check_for_update("any/repo", include_prereleases=True) is None

    def test_list_endpoint_empty_returns_none(self):
        with patch("src.updater.urlopen", return_value=_api_response([])):
            assert check_for_update("any/repo", include_prereleases=True) is None


class TestPickAssetUrlForPrerelease:
    def test_prerelease_assets_carry_base_version_in_name(self):
        release = release_from_payload(PRERELEASE_PAYLOAD)
        url = pick_asset_url(release.assets, "Darwin", release.version)
        assert url == "https://example.com/pre-dmg"
```

Den Import-Block oben in `tests/test_updater.py` ersetzen durch:

```python
from src.updater import (
    Asset, Release, check_for_update, check_latest_release, frequency_for_label,
    is_newer, pick_asset_url, release_from_payload, resolve_check_result,
    select_newest_payload, should_check, today_iso, update_toast_text,
)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_updater.py -v`
Expected: FAIL — `ImportError: cannot import name 'check_for_update' from 'src.updater'`

- [ ] **Step 3: Implement in `src/updater.py`**

Import-Zeile erweitern:

```python
from src.version import VERSION, base_version, parse_release_id
```

Die Dataclass `Release` ersetzen durch:

```python
@dataclass(frozen=True)
class Release:
    version: str            # Basisversion ohne v/-pre, z.B. "1.19.0" (Asset-Namen)
    html_url: str           # Release-Page auf GitHub
    assets: tuple[Asset, ...]
    release_id: str = ""    # volle Kennung ohne v: "1.19.0" | "1.19.0-pre.2"
    is_prerelease: bool = False
    notes: str = ""         # API-`body`; bei Pre-Releases die einzige Inhaltsquelle

    def __post_init__(self):
        # Ohne explizite Kennung IST die Version die Kennung (echtes Release,
        # Alt-Konstruktionen). frozen=True erlaubt kein normales Setzen.
        if not self.release_id:
            object.__setattr__(self, "release_id", self.version)
```

`check_latest_release` (Zeilen 141-176) ersetzen durch den folgenden Block:

```python
_API_ROOT = "https://api.github.com/repos"

# URLError fängt auch HTTPError (4xx/5xx); OSError fängt socket.timeout etc.
# TypeError/KeyError/AttributeError fangen kaputte Payload-Strukturen ab.
_FETCH_ERRORS = (URLError, OSError, json.JSONDecodeError, TypeError, KeyError, AttributeError)


def _fetch_json(url: str, timeout: float):
    request = Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"Zeiterfassung/{VERSION}",
        },
    )
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def release_from_payload(payload) -> Release | None:
    """Ein Release-Objekt der GitHub-API -> Release. None, wenn Tag oder
    html_url fehlen. Tk-frei und ohne Netzwerk testbar."""
    if not isinstance(payload, dict):
        return None
    tag = payload.get("tag_name")
    html_url = payload.get("html_url")
    if not tag or not html_url:
        return None
    # Sowohl 'v' als auch 'V' strippen; Tags sind normiert, defensiv ist billig.
    if tag[:1] in ("v", "V"):
        tag = tag[1:]
    raw_assets = payload.get("assets") or []
    assets = tuple(
        Asset(name=a["name"], url=a["browser_download_url"])
        for a in raw_assets
        if isinstance(a, dict) and "name" in a and "browser_download_url" in a
    )
    return Release(
        version=base_version(tag),
        html_url=html_url,
        assets=assets,
        release_id=tag,
        is_prerelease=bool(payload.get("prerelease")),
        notes=payload.get("body") or "",
    )


def select_newest_payload(payloads) -> dict | None:
    """Wählt aus einer /releases-Liste den Eintrag mit der höchsten Kennung.
    Drafts und Einträge mit unparsebarem Tag werden übersprungen. Wir
    maximieren selbst statt uns auf die API-Sortierung zu verlassen (die nach
    created_at sortiert, nicht nach Publish-Datum)."""
    best, best_key = None, None
    for payload in payloads or []:
        if not isinstance(payload, dict) or payload.get("draft"):
            continue
        tag = payload.get("tag_name") or ""
        if tag[:1] in ("v", "V"):
            tag = tag[1:]
        key = parse_release_id(tag)
        if key is None:
            continue
        if best_key is None or key > best_key:
            best, best_key = payload, key
    return best


def check_latest_release(repo: str, timeout: float = 5.0) -> Release | None:
    """Fragt die GitHub-API nach dem neuesten ECHTEN Release (Pre-Releases
    liefert /releases/latest nie mit).

    Liefert `None` bei jedem Fehler (Netzwerk, Timeout, kaputtes JSON,
    fehlendes `tag_name`). Caller darf sich darauf verlassen, dass keine
    Exception bubbled — Update-Hinweis ist nice-to-have.
    """
    try:
        return release_from_payload(_fetch_json(f"{_API_ROOT}/{repo}/releases/latest", timeout))
    except _FETCH_ERRORS:
        return None


def check_latest_release_any(repo: str, timeout: float = 5.0) -> Release | None:
    """Wie check_latest_release, aber inklusive Pre-Releases: die Liste
    /releases enthält beide Sorten, das Maximum wählen wir selbst.

    per_page=10 deckt bei der Release-Kadenz dieses Repos mehrere Wochen bis
    Monate ab — dass das neueste Release außerhalb der ersten Seite liegt, ist
    praktisch ausgeschlossen."""
    try:
        payloads = _fetch_json(f"{_API_ROOT}/{repo}/releases?per_page=10", timeout)
        if not isinstance(payloads, list):
            return None
        newest = select_newest_payload(payloads)
        return release_from_payload(newest) if newest is not None else None
    except _FETCH_ERRORS:
        return None


def check_for_update(repo: str, include_prereleases: bool,
                     timeout: float = 5.0) -> Release | None:
    """Der eine Einstieg für beide Aufrufer (Updates-Tab + Hintergrund-Check).
    Ohne Opt-in bleibt es exakt beim bisherigen /releases/latest."""
    if include_prereleases:
        return check_latest_release_any(repo, timeout)
    return check_latest_release(repo, timeout)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_updater.py -v`
Expected: PASS (inkl. der bestehenden `TestCheckLatestRelease`-Fälle — der Stable-Pfad ist unverändert)

- [ ] **Step 5: Full suite + lint**

Run: `python -m pytest -q` → Expected: alle grün
Run: `ruff check .` → Expected: `All checks passed!`

- [ ] **Step 6: Commit**

```bash
git add src/updater.py tests/test_updater.py
git commit -m "feat(updater): Pre-Release-Kanal über /releases abfragen"
```

---

### Task 4: Ergebnis-Aufbereitung für Pre-Releases

**Files:**
- Modify: `src/updater.py:83-123` (`update_toast_text`, `resolve_check_result`)
- Test: `tests/test_updater.py`

**Interfaces:**
- Consumes: `Release.release_id`/`is_prerelease`/`notes` (Task 3), `base_version` (Task 1)
- Produces: `resolve_check_result(installed_id: str, release: Release | None) -> dict` mit den Keys `status_text`, `show_download`, `changelog_version`, `changelog_notes`, `persist`, `latest_release`

- [ ] **Step 1: Write the failing tests**

In `tests/test_updater.py` die bestehende Klasse `TestResolveCheckResult` um `changelog_notes` erweitern und die neuen Fälle ergänzen. Die drei bestehenden Tests werden ersetzt durch:

```python
class TestResolveCheckResult:
    def test_no_connection_returns_failure_status_without_changelog(self):
        result = resolve_check_result("1.18.0", None)
        assert result == {
            "status_text": "Prüfung fehlgeschlagen — keine Verbindung?",
            "show_download": False,
            "changelog_version": None,
            "changelog_notes": None,
            "persist": None,
            "latest_release": None,
        }

    def test_current_version_shows_changelog_of_installed_version(self):
        release = Release(version="1.18.0", html_url="https://x", assets=())
        result = resolve_check_result("1.18.0", release)
        assert result["status_text"] == "Du hast die aktuelle Version (1.18.0)."
        assert result["show_download"] is False
        assert result["changelog_version"] == "1.18.0"
        assert result["changelog_notes"] is None
        assert result["persist"] is None
        assert result["latest_release"] is None

    def test_newer_release_shows_download_and_persists_dismissal(self):
        release = Release(version="1.19.0", html_url="https://x", assets=())
        result = resolve_check_result("1.18.0", release)
        assert result["status_text"] == "Version 1.19.0 verfügbar"
        assert result["show_download"] is True
        assert result["changelog_version"] == "1.19.0"
        assert result["changelog_notes"] is None
        assert result["persist"] == {
            "dismissed_version": "1.19.0",
            "update_toast_shown_version": "1.19.0",
        }
        assert result["latest_release"] is release

    def test_newer_prerelease_labels_status_and_uses_release_notes(self):
        release = Release(
            version="1.19.0", html_url="https://x", assets=(),
            release_id="1.19.0-pre.2", is_prerelease=True, notes="## What's Changed",
        )
        result = resolve_check_result("1.19.0", release)
        assert result["status_text"] == "Vorabversion 1.19.0-pre.2 verfügbar"
        assert result["show_download"] is True
        assert result["changelog_version"] is None
        assert result["changelog_notes"] == "## What's Changed"
        assert result["persist"] == {
            "dismissed_version": "1.19.0-pre.2",
            "update_toast_shown_version": "1.19.0-pre.2",
        }
        assert result["latest_release"] is release

    def test_own_prerelease_build_shows_its_own_notes(self):
        # Der Tester läuft auf genau diesem Build: der CHANGELOG der
        # Basisversion wäre der Stand, den er NICHT mehr hat.
        release = Release(
            version="1.19.0", html_url="https://x", assets=(),
            release_id="1.19.0-pre.2", is_prerelease=True, notes="## What's Changed",
        )
        result = resolve_check_result("1.19.0-pre.2", release)
        assert result["status_text"] == "Du hast die aktuelle Version (1.19.0-pre.2)."
        assert result["show_download"] is False
        assert result["changelog_version"] is None
        assert result["changelog_notes"] == "## What's Changed"
        assert result["persist"] is None

    def test_older_prerelease_than_installed_shows_installed_changelog(self):
        # Pre-Nutzer auf pre.3 bekommt pre.2 angeboten (kann bei Alt-Builds
        # passieren): kein Download, Changelog der eigenen Basisversion.
        release = Release(
            version="1.19.0", html_url="https://x", assets=(),
            release_id="1.19.0-pre.2", is_prerelease=True, notes="## What's Changed",
        )
        result = resolve_check_result("1.19.0-pre.3", release)
        assert result["show_download"] is False
        assert result["changelog_version"] == "1.19.0"
        assert result["changelog_notes"] is None

    def test_prerelease_user_is_not_offered_the_plain_release(self):
        # Nach der Ordnung ist der Pre-Build neuer als sein echtes Release.
        release = Release(version="1.19.0", html_url="https://x", assets=())
        result = resolve_check_result("1.19.0-pre.2", release)
        assert result["status_text"] == "Du hast die aktuelle Version (1.19.0-pre.2)."
        assert result["show_download"] is False
        assert result["changelog_version"] == "1.19.0"
```

Und die bestehende Toast-Text-Erwartung erweitern — ans Ende der Datei:

```python
class TestUpdateToastTextForPrerelease:
    def test_prerelease_toast_names_it_a_vorabversion(self):
        release = Release(
            version="1.19.0", html_url="https://x", assets=(),
            release_id="1.19.0-pre.2", is_prerelease=True,
        )
        text = update_toast_text(release)
        assert text.startswith("Vorabversion 1.19.0-pre.2 verfügbar")
        assert "Einstellungen → Updates" in text

    def test_real_release_toast_unchanged(self):
        release = Release(version="1.19.0", html_url="https://x", assets=())
        assert update_toast_text(release).startswith("Version 1.19.0 verfügbar")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_updater.py -k "ResolveCheckResult or ToastText" -v`
Expected: FAIL — `KeyError: 'changelog_notes'` bzw. Status-Text-Assertions schlagen fehl

- [ ] **Step 3: Implement in `src/updater.py`**

`update_toast_text` ersetzen:

```python
def update_toast_text(release: "Release") -> str:
    """Deutscher Toast-Text für ein gefundenes Update (kein Klick-Handler —
    der Toast verweist auf den Updates-Tab)."""
    kind = "Vorabversion" if release.is_prerelease else "Version"
    return (
        f"{kind} {release.release_id} verfügbar — "
        "Details unter Einstellungen → Updates."
    )
```

`resolve_check_result` ersetzen:

```python
def resolve_check_result(installed_id: str, release: "Release | None") -> dict:
    """Reine Entscheidungslogik für das Ergebnis eines Update-Checks.

    `installed_id` ist die Kennung des laufenden Builds
    (`version.installed_release_id()`), nicht bloß die Version.

    Der Changelog kommt aus zwei Quellen: für echte Releases aus CHANGELOG.md
    am Tag (`changelog_version` -> changelog.fetch_changelog_entry), für
    Pre-Releases aus den Release-Notes der API (`changelog_notes`, liegt dem
    Payload bereits bei). CHANGELOG.md kennt am Pre-Tag nur die zuletzt
    veröffentlichte Version — also genau das, was der Nutzer schon hat.

    Tk-frei, daher ohne Widgets testbar."""
    if release is None:
        return {
            "status_text": "Prüfung fehlgeschlagen — keine Verbindung?",
            "show_download": False,
            "changelog_version": None,
            "changelog_notes": None,
            "persist": None,
            "latest_release": None,
        }
    if not is_newer(installed_id, release.release_id):
        # Läuft der Nutzer auf genau dem angebotenen Pre-Build, zeigen dessen
        # Notes, was sein Testbuild enthält.
        own_build = release.is_prerelease and release.release_id == installed_id
        return {
            "status_text": f"Du hast die aktuelle Version ({installed_id}).",
            "show_download": False,
            "changelog_version": None if own_build else base_version(installed_id),
            "changelog_notes": release.notes if own_build else None,
            "persist": None,
            "latest_release": None,
        }
    kind = "Vorabversion" if release.is_prerelease else "Version"
    return {
        "status_text": f"{kind} {release.release_id} verfügbar",
        "show_download": True,
        "changelog_version": None if release.is_prerelease else release.version,
        "changelog_notes": release.notes if release.is_prerelease else None,
        "persist": {
            "dismissed_version": release.release_id,
            "update_toast_shown_version": release.release_id,
        },
        "latest_release": release,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_updater.py -v`
Expected: PASS

- [ ] **Step 5: Full suite + lint**

Run: `python -m pytest -q` → Expected: alle grün (`tab_updates.py` liest `changelog_notes` noch nicht — das ist Task 6, hier bricht nichts)
Run: `ruff check .` → Expected: `All checks passed!`

- [ ] **Step 6: Commit**

```bash
git add src/updater.py tests/test_updater.py
git commit -m "feat(updater): Status, Merker und Changelog-Quelle für Pre-Releases"
```

---

### Task 5: Changelog-Parser versteht GitHub-Release-Notes

**Files:**
- Modify: `src/changelog.py:64-118` (`parse_changelog_markdown`)
- Test: `tests/test_changelog.py`

**Interfaces:**
- Consumes: nichts aus vorherigen Tasks
- Produces: `parse_changelog_markdown(text)` rendert zusätzlich `* `-Bullets und `## `-Überschriften; Rückgabeformat unverändert (`None` für Absatzlücke, sonst `{"segments": [(text, tags)], "hanging_indent": bool}`)

- [ ] **Step 1: Write the failing tests**

Ans Ende von `tests/test_changelog.py` anhängen:

```python
# Wie GitHub die Notes eines Pre-Releases liefert: ## -Überschrift,
# * -Bullets, Full-Changelog-Zeile — und CRLF-Zeilenenden.
GITHUB_NOTES_FIXTURE = (
    "## What's Changed\r\n"
    "* feat: Netto-Stunden je Tag by @margenheld in "
    "https://github.com/MargenHeld/Zeiterfassung/pull/162\r\n"
    "* fix: Footer-Rundung by @margenheld in "
    "https://github.com/MargenHeld/Zeiterfassung/pull/163\r\n"
    "\r\n"
    "**Full Changelog**: "
    "https://github.com/MargenHeld/Zeiterfassung/compare/v1.19.0...v1.19.0-pre.2\r\n"
)


def _plain(line):
    return "".join(text for text, _tags in line["segments"])


class TestParseGithubNotes:
    def test_double_hash_heading_is_kept_and_styled(self):
        lines = parse_changelog_markdown(GITHUB_NOTES_FIXTURE)
        first = lines[0]
        assert _plain(first) == "What's Changed"
        assert first["segments"][0][1] == ("heading",)

    def test_star_bullets_are_rendered_as_bullets(self):
        lines = parse_changelog_markdown(GITHUB_NOTES_FIXTURE)
        bullets = [ln for ln in lines if ln and ln["hanging_indent"]]
        assert len(bullets) == 2
        assert _plain(bullets[0]).startswith("• feat: Netto-Stunden je Tag")

    def test_full_changelog_line_stays_text_with_bold_segment(self):
        lines = parse_changelog_markdown(GITHUB_NOTES_FIXTURE)
        last = [ln for ln in lines if ln][-1]
        assert last["hanging_indent"] is False
        assert ("Full Changelog", ("bold",)) in last["segments"]

    def test_crlf_does_not_leak_into_output(self):
        lines = parse_changelog_markdown(GITHUB_NOTES_FIXTURE)
        assert not any("\r" in _plain(ln) for ln in lines if ln)


class TestVersionHeadingStrippingIsScoped:
    def test_changelog_version_heading_is_still_dropped(self):
        section = extract_version_section(CHANGELOG_FIXTURE, "1.18.0")
        lines = parse_changelog_markdown(section)
        assert not any(_plain(ln).startswith("1.18.0") for ln in lines if ln)

    def test_non_version_first_heading_is_not_dropped(self):
        lines = parse_changelog_markdown("## What's Changed\n* etwas\n")
        assert _plain(lines[0]) == "What's Changed"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_changelog.py -k "GithubNotes or HeadingStripping" -v`
Expected: FAIL — die `## What's Changed`-Zeile wird von der bestehenden „erste Zeile weglassen"-Regel verschluckt, `* `-Zeilen landen als Fließtext

- [ ] **Step 3: Implement in `src/changelog.py`**

Bei den Modul-Konstanten (nach `_BOLD`) ergänzen:

```python
# Nur eine Versions-Überschrift ("## 1.18.0 — …") ist redundant zum Status-Text
# darüber. Die Notes eines Pre-Releases beginnen mit "## What's Changed" — die
# muss stehen bleiben.
_VERSION_HEADING_LINE = re.compile(r"^##\s+\d+\.\d+\.\d+")
```

Im Docstring von `parse_changelog_markdown` den Absatz über Markdown-Syntax um einen Satz ergänzen:

```
    Verstanden werden beide Quellen: der kuratierte CHANGELOG.md-Abschnitt
    (`### `-Überschriften, `- `-Bullets) und die von GitHub generierten
    Release-Notes eines Pre-Releases (`## `-Überschriften, `* `-Bullets).
```

Den Block „Versions-Überschrift weglassen" ersetzen:

```python
    raw_lines = text.splitlines()
    # Die Versions-Überschrift ("## 1.18.0 — ...") ist redundant zum Status-
    # Text darüber (z.B. "Du hast die aktuelle Version …") und wird nicht
    # mit angezeigt. Andere "## "-Überschriften (GitHub-Notes) bleiben.
    if raw_lines and _VERSION_HEADING_LINE.match(raw_lines[0]):
        raw_lines = raw_lines[1:]
```

In der Block-Schleife die beiden Erkennungen erweitern — `### `-Zweig bleibt, davor/danach ergänzen:

```python
        if line.startswith("### "):
            blocks.append(("heading", line[4:].strip()))
            continue
        if line.startswith("## "):
            blocks.append(("heading", line[3:].strip()))
            continue
        if line.startswith("- ") or line.startswith("* "):
            blocks.append(("bullet", line[2:].strip()))
            continue
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_changelog.py -v`
Expected: PASS (inkl. aller bestehenden CHANGELOG-Fälle)

- [ ] **Step 5: Full suite + lint**

Run: `python -m pytest -q` → Expected: alle grün
Run: `ruff check .` → Expected: `All checks passed!`

- [ ] **Step 6: Commit**

```bash
git add src/changelog.py tests/test_changelog.py
git commit -m "feat(changelog): GitHub-Release-Notes im Parser unterstützen"
```

---

### Task 6: Setting und Updates-Tab

**Files:**
- Modify: `src/settings.py:36-39` (DEFAULTS)
- Modify: `src/dialogs/settings_dialog/tab_updates.py`
- Modify: `src/dialogs/settings_dialog/dialog.py:185` (save_settings)
- Test: `tests/test_settings.py`

**Interfaces:**
- Consumes: `check_for_update` (Task 3), `resolve_check_result` mit `changelog_notes` (Task 4), `installed_release_id` (Task 2)
- Produces: `UpdatesTab.prerelease_var` (`tk.BooleanVar`) für `save_settings`; Settings-Key `prerelease_updates_enabled`

**Abweichung von der Spec-Testtabelle:** Der Settings-Key wird in
`tests/test_settings.py` geprüft (Default + Nicht-Sync), nicht in
`tests/test_settings_dialog.py`. Grund: `save_settings` dort zu testen hieße,
den kompletten Tk-Dialog zu bauen — die Datei testet heute ausschließlich
Tk-freie Teile (`oauth_task`). Die Speicher-Verdrahtung deckt Step 9 manuell ab.

- [ ] **Step 1: Write the failing test**

Ans Ende von `tests/test_settings.py` anhängen:

```python
def test_prerelease_updates_disabled_by_default():
    from src.settings import DEFAULTS

    assert DEFAULTS["prerelease_updates_enabled"] is False


def test_prerelease_updates_flag_is_device_local():
    # Update-Einstellungen werden bewusst nicht synchronisiert: der Rechner,
    # auf dem ein Testbuild geprüft wird, soll die anderen Geräte nicht in
    # den Pre-Kanal ziehen.
    from src.settings import SYNCED_SETTING_KEYS

    assert "prerelease_updates_enabled" not in SYNCED_SETTING_KEYS
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_settings.py -k prerelease -v`
Expected: FAIL — `KeyError: 'prerelease_updates_enabled'`

- [ ] **Step 3: Setting anlegen**

In `src/settings.py` in `DEFAULTS` direkt nach `"update_toast_shown_version": "",` einfügen:

```python
    "prerelease_updates_enabled": False,
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_settings.py -k prerelease -v`
Expected: PASS

- [ ] **Step 5: Checkbox im Updates-Tab**

In `src/dialogs/settings_dialog/tab_updates.py` die Imports anpassen:

```python
from src.theme import (
    BG, CELL_BG, FONT, FONT_BOLD, FONT_SMALL, TEXT, TEXT_MUTED,
    dark_combo, dark_text, primary_button, secondary_button,
    set_button_text, set_primary_button_enabled,
)
from src.updater import (
    FREQUENCY_OPTIONS, REPO, check_for_update, pick_asset_url,
    resolve_check_result,
)
from src.version import installed_release_id
```

(`from src.version import VERSION` entfällt — die installierte Kennung ist ab jetzt die Anzeige- und Vergleichsgrundlage.)

Die Zeile mit der installierten Version ersetzen:

```python
        label(frame, f"Installierte Version: {installed_release_id()}", row=0)
```

Direkt nach dem `freq_row`-Block (der auf `row=3` gridded) einfügen:

```python
        # Opt-in für Pre-Releases: ohne Häkchen verhält sich der Tab exakt wie
        # bisher (nur echte Releases über /releases/latest).
        self.prerelease_var = tk.BooleanVar(
            value=settings.get("prerelease_updates_enabled"),
        )
        tk.Checkbutton(
            frame, text="Auch Vorabversionen (Pre-Releases) anbieten",
            variable=self.prerelease_var, font=FONT, bg=BG, fg=TEXT,
            selectcolor=CELL_BG, activebackground=BG, activeforeground=TEXT,
            cursor="hand2",
        ).grid(row=4, column=0, columnspan=2, padx=10, pady=(8, 0), sticky="w")
        tk.Label(
            frame, text="Testbuilds vor dem echten Release — können Fehler enthalten.",
            font=FONT_SMALL, bg=BG, fg=TEXT_MUTED,
        ).grid(row=5, column=0, columnspan=2, padx=10, pady=(0, 4), sticky="w")
```

Die beiden Changelog-Widgets rutschen um zwei Zeilen nach unten:

```python
        self._changelog_label.grid(row=6, column=0, padx=10, pady=(12, 4), sticky="nw")
        ...
        self._changelog_text.grid(
            row=7, column=0, columnspan=2, padx=10, pady=4,
        )
```

- [ ] **Step 6: Check-Pfad auf Kanal und Notes umstellen**

In `_check_now` den Worker-Block ersetzen:

```python
        # Tk-Variable im UI-Thread lesen und als Wert in die Closure geben —
        # nie aus dem Daemon-Thread. Bewusst der AKTUELLE Checkbox-Zustand,
        # nicht der gespeicherte: sonst wirkt das Häkchen erst nach Speichern
        # und erneutem Öffnen des Dialogs.
        include_prereleases = bool(self.prerelease_var.get())

        def fn():
            return check_for_update(REPO, include_prereleases)

        def on_done(release):
            if not self.frame.winfo_exists():
                return
            result = resolve_check_result(installed_release_id(), release)
            self._latest_release = result["latest_release"]
            self._status_label.config(text=result["status_text"])
            if result["show_download"]:
                self._download_btn.pack(side=tk.LEFT, padx=(8, 0))
            if result["persist"]:
                self._settings.set_many(result["persist"])
            if result["changelog_notes"] is not None:
                # Pre-Release: die Notes liegen dem Payload bereits bei,
                # kein zweiter Netzwerk-Call nötig.
                self._finish_checking()
                self._set_changelog(
                    result["changelog_notes"] or "Changelog konnte nicht geladen werden.",
                )
                return
            if result["changelog_version"] is None:
                self._finish_checking()
                return
            self._fetch_changelog(result["changelog_version"])

        self._runner.run(fn, on_done)
```

- [ ] **Step 7: Speichern verdrahten**

In `src/dialogs/settings_dialog/dialog.py` direkt nach der `update_check_frequency`-Zeile einfügen:

```python
            "prerelease_updates_enabled": updates_tab.prerelease_var.get(),
```

- [ ] **Step 8: Full suite + lint**

Run: `python -m pytest -q` → Expected: alle grün
Run: `ruff check .` → Expected: `All checks passed!`

- [ ] **Step 9: Manuell verifizieren (Tk-Verdrahtung, kein Unit-Test)**

**Wichtig zum Erwartungswert:** Zum Zeitpunkt dieses Plans existiert **kein**
Pre-Release zur installierten Version — die neuesten Pre-Tags sind
`v1.18.2-pre.1` und `v1.16.1-pre.2`, beide älter als `1.19.0`. Mit Häkchen darf
also **kein** Update erscheinen; das ist der korrekte Ausgang, kein Fehler. Den
Pre-Pfad Ende-zu-Ende prüft die Abschluss-Verifikation nach einem echten
Pre-Release-Lauf.

Run: `python -m src.main`, dann ⚙ → Tab „Updates".
Prüfen:
1. Zeile „Installierte Version: …" zeigt die Kennung (im Repo-Modus die reine `VERSION`, aktuell `1.19.0`).
2. Checkbox „Auch Vorabversionen (Pre-Releases) anbieten" ist **aus**, Hinweistext darunter sichtbar, Changelog-Box darunter vollständig sichtbar (nichts abgeschnitten, Dialogbreite unverändert).
3. Ohne Häkchen „Jetzt prüfen" → Status „Du hast die aktuelle Version (1.19.0)."; Changelog-Box zeigt den CHANGELOG-Abschnitt von 1.19.0.
4. Häkchen setzen, **ohne** zu speichern, erneut „Jetzt prüfen" → wieder „Du hast die aktuelle Version (1.19.0)." (kein Crash, kein leerer Status) — der Listen-Endpunkt liefert als Maximum das echte `v1.19.0`.
5. Speichern, Dialog neu öffnen → Häkchen ist noch gesetzt.

Zusätzlich den Pre-Anzeigepfad ohne echten Pre-Release gegenprüfen (Statustext
+ Notes-Rendering), per Scratch-Skript im Scratchpad-Verzeichnis:

```python
# probe_pre_ui.py — zeigt, was der Tab bei einem Pre-Release-Fund anzeigen würde
from src.updater import Release, resolve_check_result

rel = Release(
    version="1.19.0", html_url="https://x", assets=(),
    release_id="1.19.0-pre.1", is_prerelease=True,
    notes="## What's Changed\r\n* feat: Testbuild by @margenheld in #170\r\n",
)
print(resolve_check_result("1.19.0", rel)["status_text"])
from src.changelog import parse_changelog_markdown
for line in parse_changelog_markdown(rel.notes):
    print("" if line is None else "".join(t for t, _ in line["segments"]))
```

Run: `python <scratchpad>/probe_pre_ui.py`
Expected:
```
Vorabversion 1.19.0-pre.1 verfügbar
What's Changed
• feat: Testbuild by @margenheld in #170
```

- [ ] **Step 10: Commit**

```bash
git add src/settings.py src/dialogs/settings_dialog/tab_updates.py src/dialogs/settings_dialog/dialog.py tests/test_settings.py
git commit -m "feat(updates): Opt-in für Pre-Releases im Updates-Tab"
```

---

### Task 7: Hintergrund-Check, Toast-Routing und Banner

**Files:**
- Modify: `src/background_tasks.py:16-17,113-138` (`check_update`)
- Modify: `src/ui.py:57-63` (`_route_update_notification`), `:516-530` (`_on_update_check_result`)
- Modify: `src/update_banner.py:29-52,92-93`
- Test: `tests/test_background_tasks.py`, `tests/test_ui_update_routing.py`, `tests/test_update_banner.py`

**Interfaces:**
- Consumes: `check_for_update` (Task 3), `installed_release_id` (Task 2), `Release.release_id`/`is_prerelease` (Task 3), `update_toast_text` (Task 4)
- Produces: keine neuen öffentlichen Namen — `_route_update_notification` und `UpdateBanner` vergleichen ab jetzt `release_id`

- [ ] **Step 1: Write the failing tests**

In `tests/test_background_tasks.py` die beiden bestehenden `check_update`-Tests unverändert lassen und ergänzen:

```python
def test_check_update_uses_stable_channel_by_default(monkeypatch):
    import src.background_tasks as bg
    seen = {}

    def fake_check(repo, include):
        seen["include"] = include
        return None            # None, damit der Worker sauber abbricht

    monkeypatch.setattr(bg, "should_check", lambda last, freq: True)
    monkeypatch.setattr(bg, "check_for_update", fake_check)
    r = _runner(settings={
        "last_update_check_at": None, "update_check_frequency": "daily",
        "prerelease_updates_enabled": False,
    })
    r.check_update(on_result=lambda rel, newer: None)
    import time
    time.sleep(0.2)
    assert seen["include"] is False


def test_check_update_passes_prerelease_flag_from_settings(monkeypatch):
    import src.background_tasks as bg
    seen = {}

    def fake_check(repo, include):
        seen["include"] = include
        return None

    monkeypatch.setattr(bg, "should_check", lambda last, freq: True)
    monkeypatch.setattr(bg, "check_for_update", fake_check)
    r = _runner(settings={
        "last_update_check_at": None, "update_check_frequency": "daily",
        "prerelease_updates_enabled": True,
    })
    r.check_update(on_result=lambda rel, newer: None)
    import time
    time.sleep(0.2)
    assert seen["include"] is True


def test_check_update_compares_against_installed_release_id(monkeypatch):
    import src.background_tasks as bg
    from src.updater import Release

    release = Release(
        version="1.19.0", html_url="x", assets=(),
        release_id="1.19.0-pre.2", is_prerelease=True,
    )
    monkeypatch.setattr(bg, "should_check", lambda last, freq: True)
    monkeypatch.setattr(bg, "check_for_update", lambda repo, include: release)
    monkeypatch.setattr(bg, "installed_release_id", lambda: "1.19.0-pre.1")
    got = {}
    r = _runner(settings={
        "last_update_check_at": None, "update_check_frequency": "daily",
        "prerelease_updates_enabled": True,
    })
    r.check_update(on_result=lambda rel, newer: got.update(rel=rel, newer=newer))
    import time
    time.sleep(0.3)
    assert got["newer"] is True
    assert got["rel"] is release
```

In `tests/test_ui_update_routing.py` den Fake und die neuen Fälle anpassen — `_Rel` ersetzen durch:

```python
class _Rel:
    def __init__(self, release_id, is_prerelease=False):
        self.release_id = release_id
        self.version = release_id.split("-pre.")[0]
        self.is_prerelease = is_prerelease
```

und ergänzen:

```python
def test_new_prerelease_number_fires_toast_again():
    # pre.1 wurde bereits gemeldet, pre.2 ist ein neuer Build.
    action, text = _route_update_notification(
        _Rel("1.19.0-pre.2", is_prerelease=True), True, "1.19.0-pre.1",
    )
    assert action == "toast"
    assert "Vorabversion 1.19.0-pre.2" in text


def test_same_prerelease_number_does_nothing():
    action, text = _route_update_notification(
        _Rel("1.19.0-pre.2", is_prerelease=True), True, "1.19.0-pre.2",
    )
    assert action == "none"
    assert text is None


def test_on_update_check_result_persists_release_id_not_base_version(monkeypatch):
    import src.ui as ui_module

    monkeypatch.setattr(ui_module, "today_iso", lambda: "2026-07-22")
    tray = _FakeTray()
    fake = _FakeApp(tray=tray, settings_data={"update_toast_shown_version": ""})
    App._on_update_check_result(fake, _Rel("1.19.0-pre.2", is_prerelease=True), True)
    assert fake.settings.get("update_toast_shown_version") == "1.19.0-pre.2"
```

In `tests/test_update_banner.py` den Helfer `_release` ersetzen durch:

```python
def _release(version="1.2.0", html_url="https://example/r", assets=None,
             release_id=None, is_prerelease=False):
    r = MagicMock()
    r.version = version
    r.release_id = release_id if release_id is not None else version
    r.is_prerelease = is_prerelease
    r.html_url = html_url
    r.assets = assets if assets is not None else []
    return r
```

und ergänzen:

```python
def test_show_if_newer_compares_release_id_for_prereleases():
    # pre.1 wurde ausgeblendet, pre.2 ist ein neuer Build -> anzeigen.
    b = _banner(_FakeSettings(dismissed_version="1.2.0-pre.1"))
    rel = _release(version="1.2.0", release_id="1.2.0-pre.2", is_prerelease=True)
    b.show_if_newer(rel)
    b._show.assert_called_once_with(rel)


def test_show_if_newer_dismissed_prerelease_does_not_show():
    b = _banner(_FakeSettings(dismissed_version="1.2.0-pre.2"))
    rel = _release(version="1.2.0", release_id="1.2.0-pre.2", is_prerelease=True)
    b.show_if_newer(rel)
    b._show.assert_not_called()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_background_tasks.py tests/test_ui_update_routing.py tests/test_update_banner.py -v`
Expected: FAIL — `AttributeError: <module 'src.background_tasks'> does not have the attribute 'check_for_update'` und Assertion-Fehler in den Routing-Tests

- [ ] **Step 3: Implement in `src/background_tasks.py`**

Imports ersetzen:

```python
from src.updater import REPO, check_for_update, is_newer, should_check
from src.version import installed_release_id
```

(`from src.version import VERSION` entfällt — `VERSION` wird hier sonst nicht genutzt.)

`check_update` ersetzen:

```python
    def check_update(self, on_result):
        """Fragt laut `update_check_frequency`-Setting nach einer neueren
        Version (Default: 1x pro Kalendertag). Der Kanal haengt an
        `prerelease_updates_enabled`: ohne Opt-in nur echte Releases.
        `is_newer` wird bereits im Worker ausgewertet, damit
        on_result(release, newer) im UI-Thread keine ungeschuetzte Logik mehr
        ausfuehrt. Fehler still."""
        frequency = self._settings.get("update_check_frequency")
        if not should_check(self._settings.get("last_update_check_at"), frequency):
            return
        include_prereleases = bool(self._settings.get("prerelease_updates_enabled"))

        def fn():
            try:
                release = check_for_update(REPO, include_prereleases)
                if release is None:
                    return None
                return (release, is_newer(installed_release_id(), release.release_id))
            except Exception:
                log.exception("Update-Check fehlgeschlagen")
                return None

        def on_done(result):
            if result is None:
                return
            release, newer = result
            on_result(release, newer)

        self.run(fn, on_done)
```

- [ ] **Step 4: Implement in `src/ui.py`**

`_route_update_notification` ersetzen:

```python
def _route_update_notification(release, tray_active, toast_shown_version):
    """Entscheidet zwischen Toast, Banner oder No-op für eine neue Version.

    Verglichen wird die volle Kennung (`release_id`), nicht die Basisversion —
    sonst würde ein zweiter Pre-Release derselben Version (pre.1 -> pre.2)
    als "schon gemeldet" durchfallen."""
    if tray_active:
        if release.release_id == toast_shown_version:
            return "none", None
        return "toast", update_toast_text(release)
    return "banner", None
```

In `_on_update_check_result` die Persistenz-Zeile ersetzen:

```python
            self.settings.set("update_toast_shown_version", release.release_id)
```

- [ ] **Step 5: Implement in `src/update_banner.py`**

In `show_if_newer` die Vergleichszeile ersetzen:

```python
        if release.release_id == self._settings.get("dismissed_version"):
```

In `_show` das Label und den Dismiss-Handler ersetzen:

```python
        kind = "Vorabversion" if release.is_prerelease else "Version"
        tk.Label(
            self._banner,
            text=f"{kind} {release.release_id} verfügbar",
            bg=ACCENT, fg="#ffffff", font=FONT_BOLD,
        ).pack(side=tk.LEFT, padx=10, pady=6)

        dismiss_btn = label_button(
            self._banner, "✕",
            lambda: self._dismiss(release.release_id),
            bg=ACCENT, fg="#ffffff",
            hover_bg=ACCENT_HOVER, hover_fg="#ffffff",
            font=FONT_BOLD,
            label_padx=8,
        )
```

`_open_download` bleibt unverändert (`release.version` ist die Basisversion und damit der richtige Asset-Match).

- [ ] **Step 6: Run tests to verify they pass**

Run: `python -m pytest tests/test_background_tasks.py tests/test_ui_update_routing.py tests/test_update_banner.py -v`
Expected: PASS

- [ ] **Step 7: Full suite + lint**

Run: `python -m pytest -q` → Expected: alle grün
Run: `ruff check .` → Expected: `All checks passed!`

- [ ] **Step 8: Commit**

```bash
git add src/background_tasks.py src/ui.py src/update_banner.py tests/test_background_tasks.py tests/test_ui_update_routing.py tests/test_update_banner.py
git commit -m "feat(updates): Hintergrund-Check und Benachrichtigungen kennen Pre-Releases"
```

---

### Task 8: Dokumentation

**Files:**
- Modify: `CLAUDE.md` (Abschnitt „Pre-Releases (plattformübergreifende Test-Builds)")
- Modify: `README.md` (Feature-Liste, Einstellungs-Tabelle)

**Interfaces:**
- Consumes: das fertige Verhalten aus Task 1-7
- Produces: nichts (Doku)

- [ ] **Step 1: `CLAUDE.md` ergänzen**

Im Abschnitt „Pre-Releases (plattformübergreifende Test-Builds)" nach dem Aufzählungspunkt zum Auto-Updater (`… normale Nutzer bekommen sie nicht als Update angeboten.`) einfügen:

```markdown
- **Opt-in im Updates-Tab:** Wer die Einstellung „Auch Vorabversionen
  (Pre-Releases) anbieten" aktiviert, bekommt Pre-Releases im Updates-Tab
  angezeigt und als Toast/Banner gemeldet (`updater.check_for_update` fragt
  dann `/releases` statt `/releases/latest`). Die Einstellung ist gerätelokal
  (nicht in `SYNCED_SETTING_KEYS`).
- **Reihenfolge-Regel (wichtig):** Ein Pre-Release wird **immer nach** dem
  gleichnamigen echten Release gebaut, aus neuerem Code. Die App ordnet
  entsprechend `X.Y.Z < X.Y.Z-pre.1 < X.Y.Z-pre.2 < X.Y.Z+1`
  (`version.parse_release_id`). Wer künftig erst `src/version.py` bumpt und
  dann einen Pre-Release baut, dreht diese Annahme um — dann böte die App nach
  dem echten Release weiter den älteren Pre an. In dem Fall die Ordnung in
  `version.parse_release_id` mitändern.
- **Build-Stempel:** `release.yml` reicht den berechneten Tag als
  `ZEIT_RELEASE_TAG` an die Build-Jobs; `build.py` schreibt ihn als
  `RELEASE_TAG` nach `src/build_info.py`. Daraus kennt die App ihre exakte
  Identität (`version.installed_release_id()`) und zeigt im Titel
  `X.Y.Z-pre.N` statt nur `X.Y.Z-pre`. Fehlt der Stempel (Alt-Build, Dev-Modus),
  gilt die reine `VERSION`.
```

- [ ] **Step 2: `README.md` ergänzen**

Die Update-Check-Zeile in der Feature-Liste ersetzen:

```markdown
- **Update-Check** — Konfigurierbare Hintergrund-Prüfung auf neue Releases; Updates-Tab mit manuellem Check, Changelog und Direkt-Download, bei aktivem Tray als einmaliger Toast statt Banner. Optional lassen sich auch Vorabversionen (Pre-Releases) anbieten — Testbuilds vor dem echten Release
```

In der Einstellungs-Tabelle nach der Zeile `| **Pausenpflicht-Warnung** | … |` ergänzen:

```markdown
| **Vorabversionen anbieten** | Auch Pre-Releases als Update anbieten und melden (Standard: aus, gerätelokal) |
```

- [ ] **Step 3: Verify**

Run: `python -m pytest -q` → Expected: alle grün (Doku-Änderung, nichts sollte sich bewegen)
Run: `ruff check .` → Expected: `All checks passed!`

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md README.md
git commit -m "docs: Pre-Release-Opt-in und Reihenfolge-Regel dokumentieren"
```

---

## Abschluss-Verifikation (nach Task 8)

- [ ] **Voller Lauf:** `python -m pytest -q` → alle grün, `ruff check .` → sauber
- [ ] **Repo-Modus** (`python -m src.main`, ⚙ → Updates): die fünf Punkte aus Task 6, Step 9
- [ ] **PR öffnen** mit Verweis auf Spec und diesen Plan; **kein** Versionsbump, **kein** CHANGELOG-Eintrag, **kein** `release:*`-Label (Release läuft separat)

Die folgenden Punkte lassen sich erst **nach** einem Pre-Release-Lauf aus diesem
Branch prüfen (Actions → Release → „Run workflow" mit gesetztem `prerelease`).
Der Lauf erzeugt `v1.19.0-pre.1`. Er verifiziert genau das, was lokal
prinzipiell nicht entstehen kann — den Stempel aus dem Workflow:

- [ ] **Stempel:** Das Windows-Artefakt aus dem Lauf installieren/starten → Fenstertitel zeigt `Zeiterfassung v1.19.0-pre.1` (**mit** Nummer, nicht nur `-pre`).
- [ ] **Eigener Build im Tab:** In diesem Build ⚙ → Updates, Häkchen setzen, „Jetzt prüfen" → Status „Du hast die aktuelle Version (1.19.0-pre.1)." und die Changelog-Box zeigt die **Release-Notes dieses Pre-Releases** (nicht den CHANGELOG von 1.19.0). Das ist der `own_build`-Fall aus Task 4.
- [ ] **Nächster Pre wird erkannt:** Zweiten Pre-Release-Lauf starten (`v1.19.0-pre.2`) → im pre.1-Build mit Häkchen „Jetzt prüfen" → „Vorabversion 1.19.0-pre.2 verfügbar" + Download-Button; Klick landet auf `Zeiterfassung_Setup.exe` des pre.2-Releases, nicht bloß auf der Release-Seite.
- [ ] **Stable bleibt stumm:** Im selben pre.2-Build Häkchen entfernen, „Jetzt prüfen" → „Du hast die aktuelle Version (1.19.0-pre.2)." (kein Downgrade-Angebot auf `1.19.0`).
