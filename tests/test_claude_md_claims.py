"""Schutztest für die harten Behauptungen der CLAUDE.md (#110, Option A aus #109).

Die CLAUDE.md nennt an einigen Stellen **exakte** Werte, die woanders im Repo
noch einmal stehen: die Required-Check-Liste, den `AppMutex`-String, die
Python-Matrix, zwei Tool-Pins, zwei Schema-Versionen. Solche Doppelungen
driften lautlos — ein umbenannter Job, ein Schema-Bump, ein Pin-Update, und die
Doku behauptet etwas, das der Code nicht mehr tut. Auffallen würde das erst
dem, der sich auf sie verlässt.

Die Messung in #109 fand über ~180 maschinell prüfbare Referenzen **keine
einzige** echte Drift. Dieser Test ist deshalb keine Reparatur, sondern eine
**Ratsche gegen künftige**: er hält den Stand fest, der heute stimmt.

Warum ein Test und kein Linter/eigener CI-Job: dasselbe Muster gibt es im Repo
schon zweimal (`test_catch_all_handlers.py`, `test_type_annotations.py`) — eine
dokumentierte Konvention als Assertion, ausdrücklich weil ein Linter-Gate zu
viel Rauschen erzeugte. Doku-Drift gehört in dieselbe Familie und läuft so
kostenlos in der bestehenden `test-matrix` mit. Kein Netz, kein Modell, keine
neue Dependency — reine stdlib.

Drei Bauregeln, die beim Erweitern gelten:

* **Quelle ist die CLAUDE.md, nicht eine Kopie.** Jeder Erwartungswert wird
  aus der Markdown-Datei geparst. Stünde er hier als Literal, prüfte der Test
  seine eigene Kopie, und die Doku dürfte weiter driften.
* **Scheitert der Parser, ist das rot** (`_claim`). Ein stillschweigend leerer
  Assertion-Satz wäre schlimmer als kein Test: er wäre grün.
* **Fehlermeldungen nennen beide Seiten** — was die CLAUDE.md behauptet und
  was der Code sagt. Sonst ist unklar, welche Seite nachzuziehen ist.
"""

import pathlib
import re
import subprocess

import pytest

from tests.test_catch_all_handlers import _catch_all_handlers

ROOT = pathlib.Path(__file__).resolve().parent.parent
CLAUDE_MD = ROOT / "CLAUDE.md"

TEXT = CLAUDE_MD.read_text(encoding="utf-8")
# Die CLAUDE.md ist auf ~78 Zeichen umbrochen; mehrere Behauptungen laufen über
# einen Zeilenumbruch ("`PAYLOAD_SCHEMA_VERSION`\nsteht … auf `2`"). Gesucht
# wird deshalb im flachgezogenen Text, nicht zeilenweise.
FLAT = re.sub(r"\s+", " ", TEXT)


def _claim(pattern, was):
    """Der eine Erwartungswert aus der CLAUDE.md — oder ein roter Test.

    Findet das Muster nichts, ist die Behauptung umformuliert oder entfernt
    worden. Beides muss auffallen: ein Test, der seine Erwartung nicht mehr
    findet und deshalb schweigt, prüft nichts mehr.
    """
    match = re.search(pattern, FLAT)
    assert match, (
        f"Parser gescheitert: die CLAUDE.md-Behauptung über {was} steht nicht "
        f"mehr in der erwarteten Form (Muster: {pattern!r}).\n"
        "Wurde der Abschnitt nur umformuliert, gehört das Muster nachgezogen; "
        "wurde die Behauptung entfernt, gehört auch diese Assertion weg.")
    return match


def _workflow(name):
    return (ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")


def _job_names(name):
    """Die Job-Namen eines Workflows (2-Space-Schlüssel unterhalb von `jobs:`).

    Bewusst per Regex statt per YAML-Parser: `requirements-test.txt` führt
    kein PyYAML, und diese Datei soll keine Dependency dafür nötig machen.
    """
    body = _workflow(name)
    start = body.index("\njobs:")
    jobs = [m.group(1) for m in re.finditer(r"^  ([a-z][\w-]*):$", body[start:], re.M)]
    assert jobs, f"Parser gescheitert: keine Job-Namen in {name} gefunden"
    return jobs


class TestRequiredChecks:
    """Die in „Branch Protection" genannten Required Checks."""

    def _documented(self):
        raw = _claim(r"Required Checks: ((?:[a-z][\w-]*, )+[a-z][\w-]*)",
                     "die Required-Check-Liste").group(1)
        return [name.strip() for name in raw.split(",")]

    def test_every_documented_check_is_a_job_in_test_yml(self):
        jobs = _job_names("test.yml")
        missing = [name for name in self._documented() if name not in jobs]
        assert not missing, (
            f"CLAUDE.md nennt Required Checks, die es in test.yml nicht (mehr) "
            f"gibt: {missing}\n  dokumentiert: {self._documented()}\n"
            f"  Jobs in test.yml: {jobs}\n"
            "Ein Required Check ohne Job bleibt ewig „pending“ und blockiert "
            "jeden PR dauerhaft.")

    def test_no_matrix_context_is_documented(self):
        """Ein Matrix-Job meldet seine Contexts nur mit Suffix (`test-matrix
        (3.10)`), und der Suffix hängt an der Matrix. Wer 3.10 herausnimmt,
        hinterlässt einen Required Check, der nie wieder gemeldet wird — genau
        die Falle, gegen die der `test`-Sammel-Job existiert. Die CLAUDE.md
        verbietet solche Contexts ausdrücklich; hier steht, dass sie sich nicht
        doch wieder in die Liste schleichen."""
        matrix = [name for name in self._documented() if name.startswith("test-matrix")]
        assert not matrix, f"`test-matrix (…)`-Context in der Required-Liste: {matrix}"

    def test_the_collecting_job_is_documented(self):
        """`test` ist der Sammel-Job über `test-matrix` und existiert **nur**
        für die Branch Protection. Verschwindet er aus der Liste, ist die
        gesamte Matrix ungedeckt."""
        assert "test" in self._documented()


class TestAppMutex:
    """`AppMutex` in `installer.iss` == `_APP_MUTEX_NAME` in `src/main.py`.

    Die Gleichheit ist keine Kosmetik: über diesen Namen erkennt Inno Setup
    eine laufende Instanz. Driften die beiden auseinander, installiert das
    Setup stillschweigend gegen die laufende App.
    """

    def _documented(self):
        names = set(re.findall(r"`AppMutex=(\w+)`", FLAT))
        assert names, "Parser gescheitert: kein `AppMutex=…` in CLAUDE.md gefunden"
        assert len(names) == 1, f"CLAUDE.md nennt widersprüchliche AppMutex-Werte: {names}"
        return names.pop()

    def test_installer_matches_the_documented_value(self):
        match = re.search(r"^AppMutex=(\S+)$", (ROOT / "installer.iss").read_text(
            encoding="utf-8"), re.M)
        assert match, "Parser gescheitert: keine `AppMutex=`-Zeile in installer.iss"
        assert match.group(1) == self._documented(), (
            f"CLAUDE.md sagt AppMutex={self._documented()}, "
            f"installer.iss sagt AppMutex={match.group(1)}")

    def test_main_py_matches_the_installer(self):
        match = re.search(r'^_APP_MUTEX_NAME = "([^"]+)"$',
                          (ROOT / "src" / "main.py").read_text(encoding="utf-8"), re.M)
        assert match, "Parser gescheitert: kein `_APP_MUTEX_NAME` in src/main.py"
        assert match.group(1) == self._documented(), (
            f"CLAUDE.md sagt AppMutex={self._documented()}, "
            f"src/main.py sagt _APP_MUTEX_NAME={match.group(1)!r}")


class TestPythonMatrix:
    """Die dokumentierte Spanne „Python 3.10–3.13" == `python-version` in test.yml."""

    def test_documented_span_matches_the_matrix(self):
        # „–" ist ein Halbgeviertstrich, kein Bindestrich — beide zulassen.
        span = _claim(r"Matrix über \*\*Python (\d+)\.(\d+)[–-](\d+)\.(\d+)\*\*",
                      "die Python-Matrix")
        major, first, major_last, last = (int(g) for g in span.groups())
        assert major == major_last, (
            f"Dokumentierte Spanne überspringt einen Major ({span.group(0)}) — "
            "dafür ist dieser Test nicht gebaut.")
        documented = [f"{major}.{minor}" for minor in range(first, last + 1)]

        raw = re.search(r"python-version: \[([^\]]+)\]", _workflow("test.yml"))
        assert raw, "Parser gescheitert: keine `python-version: [...]`-Zeile in test.yml"
        actual = re.findall(r"'([\d.]+)'", raw.group(1))
        assert actual, "Parser gescheitert: leere Matrix-Liste in test.yml"

        assert documented == actual, (
            f"CLAUDE.md dokumentiert {major}.{first}–{major}.{last} "
            f"(= {documented}), test.yml fährt {actual}")


class TestPins:
    """Die beiden in der CLAUDE.md genannten Tool-Pins == die Workflow-Zeilen."""

    def test_pyright_pin_matches_test_yml(self):
        version = _claim(r"`pyright` \(gepinnt `([\d.]+)`\)", "den pyright-Pin").group(1)
        actual = re.search(r"pyright==([\d.]+)", _workflow("test.yml"))
        assert actual, "Parser gescheitert: keine `pyright==`-Zeile in test.yml"
        assert actual.group(1) == version, (
            f"CLAUDE.md sagt pyright=={version}, test.yml installiert "
            f"pyright=={actual.group(1)}")

    def test_pip_licenses_pin_matches_release_yml(self):
        version = _claim(r"`pip-licenses==([\d.]+)`", "den pip-licenses-Pin").group(1)
        actual = set(re.findall(r"pip-licenses==([\d.]+)", _workflow("release.yml")))
        assert actual, "Parser gescheitert: keine `pip-licenses==`-Zeile in release.yml"
        assert actual == {version}, (
            f"CLAUDE.md sagt pip-licenses=={version}, release.yml installiert {actual}")


class TestSchemaVersions:
    """`SCHEMA_VERSION` und `PAYLOAD_SCHEMA_VERSION` == die Zahlen in der Doku.

    Beide tragen in der CLAUDE.md eine ausdrückliche Begründung, warum sie
    *nicht* gebumpt werden (ein Bump pausierte den Sync älterer Geräte bzw.
    zwänge bestehende Webhook-Empfänger zum Nachziehen). Genau deshalb ist ein
    stiller Bump prüfenswert: er entwertet die Begründung, ohne sie anzufassen.
    """

    def _constant(self, module, name):
        source = (ROOT / "src" / module).read_text(encoding="utf-8")
        match = re.search(rf"^{name} = (\d+)$", source, re.M)
        assert match, f"Parser gescheitert: kein `{name}` in src/{module}"
        return int(match.group(1))

    def test_sync_schema_version(self):
        documented = int(_claim(r"`SCHEMA_VERSION` bleibt (\d+)",
                                "SCHEMA_VERSION").group(1))
        actual = self._constant("sync.py", "SCHEMA_VERSION")
        assert actual == documented, (
            f"CLAUDE.md sagt SCHEMA_VERSION bleibt {documented}, "
            f"src/sync.py steht auf {actual}")

    def test_webhook_payload_schema_version(self):
        documented = int(_claim(
            r"`PAYLOAD_SCHEMA_VERSION` steht seit dem Urlaubs-Feature auf `(\d+)`",
            "PAYLOAD_SCHEMA_VERSION").group(1))
        actual = self._constant("webhook.py", "PAYLOAD_SCHEMA_VERSION")
        assert actual == documented, (
            f"CLAUDE.md sagt PAYLOAD_SCHEMA_VERSION {documented}, "
            f"src/webhook.py steht auf {actual}")


class TestNoSpecFile:
    """„Es gibt **keine** `Zeiterfassung.spec`-Datei" — geprüft gegen die
    **versionierten** Dateien, nicht gegen das Dateisystem.

    Der Unterschied ist keine Feinheit: PyInstaller *erzeugt* die `.spec` bei
    jedem `scripts/build.py`-Lauf im Repo-Root. Auf jeder Maschine, auf der
    einmal gebaut wurde, liegt sie also da — `.gitignore` führt sie deshalb
    unter `*.spec`. Ein Dateisystem-Check wäre dort dauerhaft rot und in der CI
    grün, also genau die Sorte Test, die man nach zwei Läufen löscht. Die
    Behauptung meint das Repo, und das ist der Git-Index.
    """

    def test_no_spec_file_is_tracked(self):
        name = _claim(r"Es gibt \*\*keine\*\* `([\w.-]+\.spec)`-Datei",
                      "die fehlende .spec-Datei").group(1)
        try:
            tracked = subprocess.run(
                ["git", "ls-files", "*.spec"], cwd=ROOT, capture_output=True,
                text=True, check=True).stdout.split()
        except (OSError, subprocess.CalledProcessError) as exc:
            pytest.skip(f"git nicht verfügbar: {exc}")
        assert tracked == [], (
            f"CLAUDE.md sagt, es gebe keine `{name}`, versioniert sind aber: "
            f"{tracked}\nBuild läuft über scripts/build.py mit expliziten "
            "PyInstaller-Args — eine eingecheckte .spec wäre eine zweite, "
            "stille Quelle der Build-Argumente.")


class TestCatchAllCount:
    """„`src/` hält rund 90 Handler" — mit Toleranz, nicht auf Gleichheit.

    Die Zahl ist eine Größenordnung, keine Invariante: sie steht in der
    CLAUDE.md, um zu sagen „die Dichte ist gemessen, nicht übersehen". Auf
    Gleichheit geprüft würde der Test bei jedem hinzugefügten Handler rot und
    die Doku-Zahl zur Wartungslast — die Regel selbst (jeder Catch-all loggt,
    meldet oder begründet sich) hält `test_catch_all_handlers.py`.
    """

    TOLERANCE = 15

    def test_documented_order_of_magnitude_still_holds(self):
        documented = int(_claim(r"`src/` hält rund (\d+) Handler",
                                "die Catch-all-Zahl").group(1))
        actual = sum(1 for _ in _catch_all_handlers())
        assert abs(actual - documented) <= self.TOLERANCE, (
            f"CLAUDE.md sagt „rund {documented}“ Catch-all-Handler, gezählt "
            f"wurden {actual} (Toleranz ±{self.TOLERANCE}).\n"
            "Die Zahl in der CLAUDE.md („Ein Catch-all loggt, meldet oder "
            "trägt eine Begründung“) auf die neue Größenordnung nachziehen.")
