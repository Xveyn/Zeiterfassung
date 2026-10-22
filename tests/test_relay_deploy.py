# tests/test_relay_deploy.py
"""Der Workflow, der den Push-Relay nach Cloudflare ausrollt (#343). Er läuft ohne zweite
Freigabe — das Gate ist der Merge auf `master` —, deshalb halten diese Tests fest, was ihn
trotzdem sicher macht: nur von `master`, erst nach den Tests, Secrets nur im Environment,
Token nie in eine Ausgabe, und der Smoke-Check muss den Relay erreichen."""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
WORKFLOW_PATH = ROOT / ".github" / "workflows" / "relay-deploy.yml"
WORKFLOW = WORKFLOW_PATH.read_text(encoding="utf-8")
TEST_YML = (ROOT / ".github" / "workflows" / "test.yml").read_text(encoding="utf-8")


def steps_text():
    return WORKFLOW.split("steps:", 1)[1]


def test_it_runs_on_master_changes_of_the_relay_and_by_hand():
    assert re.search(r"branches:\s*\[master\]", WORKFLOW)
    assert "'relay/**'" in WORKFLOW
    assert "'.github/workflows/relay-deploy.yml'" in WORKFLOW
    assert "workflow_dispatch" in WORKFLOW
    assert "pull_request" not in WORKFLOW.split("jobs:")[0], "ein PR darf nie mit dem Token laufen"


def test_the_job_uses_the_environment_that_holds_the_secrets():
    assert re.search(r"environment:\s*relay-production", WORKFLOW)
    assert "secrets.CLOUDFLARE_API_TOKEN" in WORKFLOW
    assert "secrets.CLOUDFLARE_ACCOUNT_ID" in WORKFLOW


def test_the_secrets_are_passed_only_to_the_deploy_step():
    # Nicht auf Job-Ebene: `npm ci` und die Tests laufen fremden Code aus node_modules und
    # brauchen den Token nicht.
    head = WORKFLOW.split("steps:", 1)[0]
    assert "secrets." not in head.split("jobs:", 1)[-1]
    assert "env:" not in head.split("jobs:", 1)[-1].split("steps:", 1)[0]
    before_deploy_step = steps_text().split("- name: Ausrollen", 1)[0]
    assert "secrets.CLOUDFLARE" not in before_deploy_step
    assert steps_text().count("secrets.CLOUDFLARE_API_TOKEN") == 1


def test_the_tests_run_before_the_deploy():
    steps = steps_text()
    assert steps.index("npm ci") < steps.index("node --test") < steps.index("wrangler deploy")


def test_a_missing_secret_fails_loudly_before_the_deploy():
    steps = steps_text()
    assert "CLOUDFLARE_API_TOKEN" in steps and "::error" in steps
    assert steps.index("::error") < steps.index("wrangler deploy")


def test_the_deploy_is_pinned_to_the_checked_in_wrangler_and_node_22():
    steps = steps_text()
    assert "npx wrangler deploy" in steps
    assert "wrangler@" not in steps, "die in package.json gepinnte Version, kein eigenes @latest"
    assert "node-version: '22'" in steps
    assert "working-directory: relay" in steps


def test_deploys_do_not_overlap_and_a_running_one_is_not_cancelled():
    assert "concurrency:" in WORKFLOW and "group: relay-deploy" in WORKFLOW
    assert "cancel-in-progress: false" in WORKFLOW


def test_the_permissions_are_minimal_and_nothing_is_pushed():
    top = WORKFLOW.split("jobs:")[0]
    assert "contents: read" in top
    assert "write" not in top
    assert "git push" not in WORKFLOW


def test_the_smoke_check_reads_the_url_from_the_code_and_expects_401():
    steps = steps_text()
    assert "src/push_relay.py" in steps, "dieselbe Adresse wie im Desktop, nicht ein zweites Mal getippt"
    assert "401" in steps and "/v1/device" in steps
    assert "curl" in steps


def test_the_smoke_url_pattern_matches_the_constant_in_the_code():
    source = (ROOT / "src" / "push_relay.py").read_text(encoding="utf-8")
    assert re.search(r'^RELAY_URL = "(https://[^"]+)"$', source, re.MULTILINE)


def test_the_pull_request_job_checks_the_configuration_without_a_token():
    relay_job = TEST_YML.split("\n  relay:", 1)[1]
    assert "wrangler deploy --dry-run" in relay_job
    assert "CLOUDFLARE_API_TOKEN" not in relay_job
