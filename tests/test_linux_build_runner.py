"""Der Linux-Build läuft auf einem festen Ubuntu, nicht auf `ubuntu-latest`.

Eine AppImage läuft nur auf Systemen mit mindestens der glibc des Build-Rechners.
Als `ubuntu-latest` auf 26.04 (glibc 2.42) wechselte, startete die AppImage von
1.29.0 unter Debian 13 und Ubuntu 24.04 nicht mehr. Ein Wechsel des Images ist
deshalb eine bewusste Entscheidung im Workflow, kein stiller Nebeneffekt.
"""

import pathlib
import re

WORKFLOWS = pathlib.Path(__file__).resolve().parent.parent / ".github" / "workflows"
PINNED = "ubuntu-24.04"


def _runner_of_job(workflow: str, job: str) -> str:
    text = (WORKFLOWS / workflow).read_text(encoding="utf-8")
    block = re.search(rf"^  {re.escape(job)}:\n(.*?)(?=^  [\w-]+:\n|\Z)", text, re.M | re.S)
    assert block, f"Job {job} fehlt in {workflow}"
    runner = re.search(r"^    runs-on:\s*(\S+)", block.group(1), re.M)
    assert runner, f"Job {job} in {workflow} ohne runs-on"
    return runner.group(1)


def test_release_builds_linux_on_a_pinned_ubuntu():
    assert _runner_of_job("release.yml", "build-linux") == PINNED


def test_manual_build_uses_the_same_linux_image_as_the_release():
    assert _runner_of_job("build.yml", "build-linux") == PINNED
