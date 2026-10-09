# tests/test_pwa_pages.py
"""Der Pages-Workflow und die Laufzeitdateien der PWA müssen zusammenpassen: ohne den
Platzhalter in `sw-core.js` oder ohne den `sed`-Aufruf bekäme jeder Deploy denselben Cache,
und neue Versionen kämen nie auf den Handys an."""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
WORKFLOW = (ROOT / ".github" / "workflows" / "pages.yml").read_text(encoding="utf-8")


def test_the_build_placeholder_is_replaced_by_the_workflow():
    core = (ROOT / "pwa" / "sw-core.js").read_text(encoding="utf-8")
    assert core.count("__BUILD__") == 1
    assert "sed -i" in WORKFLOW and "__BUILD__" in WORKFLOW and "sw-core.js" in WORKFLOW
    assert re.search(r"grep -q .*sw-core\.js", WORKFLOW), "der Workflow muss prüfen, dass der Platzhalter ersetzt wurde"


def test_only_runtime_files_are_published():
    assert re.search(r"--exclude\s+'?test/'?", WORKFLOW)
    assert re.search(r"--exclude\s+'?package\.json'?", WORKFLOW)
    assert re.search(r"--exclude\s+'?memory-adapter\.js'?", WORKFLOW)   # Testhilfe, nicht im PRECACHE
    assert "path: _site" in WORKFLOW


def test_the_workflow_triggers_on_pwa_changes_and_manually_and_pushes_nothing():
    assert re.search(r"branches:\s*\[master\]", WORKFLOW)
    assert "'pwa/**'" in WORKFLOW
    assert "workflow_dispatch" in WORKFLOW
    assert "git push" not in WORKFLOW


def test_the_permissions_are_minimal():
    top = WORKFLOW.split("jobs:")[0]
    for line in ("contents: read", "pages: write", "id-token: write"):
        assert line in top, line
    assert "contents: write" not in WORKFLOW


def test_deploys_do_not_overlap():
    assert "concurrency:" in WORKFLOW and "group: pages" in WORKFLOW
    assert "cancel-in-progress: false" in WORKFLOW


def test_the_desktop_knows_the_address_the_workflow_publishes():
    # Die Seite erscheint unter https://<owner>.github.io/<repo>/; der Desktop trägt dieselbe
    # Origin als einzig erlaubte und denselben Pfad im Koppel-Link.
    from src import mobile_routes
    assert mobile_routes.PWA_ORIGIN == "https://xveyn.github.io"
    assert mobile_routes.PWA_URL == "https://xveyn.github.io/Zeiterfassung/"


def test_the_service_worker_precaches_past_the_http_cache():
    # GitHub Pages liefert mit max-age=600; ohne cache: 'reload' könnte ein neuer Worker Dateien
    # der vorigen Installation einsammeln und eine Version-Mischung festschreiben.
    worker = (ROOT / "pwa" / "sw.js").read_text(encoding="utf-8")
    assert "cache: 'reload'" in worker
