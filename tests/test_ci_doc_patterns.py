"""Welche geänderten Dateien zählen im `changes`-Job von `.github/workflows/test.yml` als reine Doku?

Ein PR, der nur Doku anfasst, überspringt die Tests. `docs/datenschutz.md` ist aber **keine** Doku mehr: die App
bündelt sie (`scripts/build.py`), der Dialog „Datenschutzhinweise“ zeigt sie, und `tests/test_privacy_doc.py`
prüft den Parser gegen die echte Datei. Ein PR nur auf diese Datei darf die Tests deshalb nicht überspringen.

Der Test liest das Muster aus der Workflow-Datei (statt es zu kopieren) und rechnet die Entscheidung nach:
findet er Muster oder Ausnahme nicht mehr, ist er rot, nicht grün (Muster wie `test_claude_md_claims`).
Grenze: er hält Muster und Ausnahme gegen Drift fest; die Kontrollfluss-Logik der Shell (`if`/`elif`) rechnet
der Test nach und kann ein vertauschtes `elif` im Workflow nicht erkennen.
"""
import pathlib
import re

WORKFLOW = (pathlib.Path(__file__).resolve().parent.parent / ".github" / "workflows" / "test.yml").read_text(
    encoding="utf-8")


def _changes_job():
    start = WORKFLOW.index("  changes:")
    end = WORKFLOW.index("  test-matrix:")
    return WORKFLOW[start:end]


def _doc_pattern():
    match = re.search(r"grep -qvE '([^']+)'", _changes_job())
    assert match, "Parser gescheitert: das Doku-Muster (`grep -qvE '…'`) steht nicht mehr im changes-Job."
    return re.compile(match.group(1))


def _code_exceptions():
    found = re.findall(r"grep -qxF '([^']+)'", _changes_job())
    assert found, "Parser gescheitert: die Ausnahme `grep -qxF '…'` steht nicht mehr im changes-Job."
    return set(found)


def touches_code(files):
    """Die Entscheidung des Jobs: Ausnahme-Datei oder irgendeine Datei ohne Doku-Muster ⇒ Code."""
    pattern = _doc_pattern()
    exceptions = _code_exceptions()
    return any(f in exceptions or not pattern.search(f) for f in files)


def test_plain_documentation_skips_the_tests():
    for files in (["README.md"], ["docs/known-limitations.md"], ["docs/superpowers/plans/x.md"],
                  [".superpowers/sdd/x/progress.md"], ["LICENSE"], ["docs/a.md", "README.md"]):
        assert touches_code(files) is False, files


def test_the_bundled_privacy_document_counts_as_code():
    assert "docs/datenschutz.md" in _code_exceptions()
    assert touches_code(["docs/datenschutz.md"]) is True
    assert touches_code(["README.md", "docs/datenschutz.md"]) is True


def test_source_and_workflow_changes_count_as_code():
    for files in (["src/privacy_doc.py"], [".github/workflows/test.yml"], ["pwa/app.js"], ["docs/a.md", "src/x.py"]):
        assert touches_code(files) is True, files


def test_the_diff_lists_renamed_files_under_both_names():
    """Ohne `--no-renames` nennt `git diff --name-only` bei einer Umbenennung nur den neuen Pfad: aus
    `docs/datenschutz.md → docs/privacy.md` würde „reine Doku“, obwohl Build und Parser-Test an der alten Datei
    hängen."""
    job = _changes_job()
    assert "git diff --name-only --no-renames" in job
