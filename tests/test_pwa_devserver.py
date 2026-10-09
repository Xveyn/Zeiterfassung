# tests/test_pwa_devserver.py
import importlib.util
import json
import pathlib
import urllib.error
import urllib.request

import pytest

SCRIPT = pathlib.Path(__file__).resolve().parent.parent / "scripts" / "pwa_devserver.py"


@pytest.fixture(scope="module")
def devserver():
    spec = importlib.util.spec_from_file_location("pwa_devserver", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def get(url):
    with urllib.request.urlopen(url, timeout=5) as response:
        return response.status, response.headers, response.read()


def test_the_static_server_serves_the_pwa_with_module_friendly_types(devserver, tmp_path):
    with devserver.running(tmp_path, web_port=0, api_port=0, address="127.0.0.1") as dev:
        status, headers, body = get(f"http://127.0.0.1:{dev.web_port}/index.html")
        assert status == 200 and b'<div id="app">' in body
        assert get(f"http://127.0.0.1:{dev.web_port}/app.js")[1]["Content-Type"].startswith("text/javascript")
        assert "manifest+json" in get(f"http://127.0.0.1:{dev.web_port}/manifest.webmanifest")[1]["Content-Type"]
        assert headers["Cache-Control"] == "no-store"


def test_the_static_server_does_not_leak_outside_the_pwa_folder(devserver, tmp_path):
    with devserver.running(tmp_path, web_port=0, api_port=0, address="127.0.0.1") as dev:
        for path in ("/../src/main.py", "/%2e%2e/src/main.py", "/test/../../CLAUDE.md"):
            with pytest.raises(urllib.error.HTTPError):
                get(f"http://127.0.0.1:{dev.web_port}{path}")


def test_the_phone_server_accepts_exactly_the_dev_origin(devserver, tmp_path):
    with devserver.running(tmp_path, web_port=0, api_port=0, address="127.0.0.1") as dev:
        origin = f"http://localhost:{dev.web_port}"
        request = urllib.request.Request(
            f"http://127.0.0.1:{dev.api_port}/v1/sync", method="OPTIONS",
            headers={"Origin": origin, "Access-Control-Request-Method": "POST"})
        with urllib.request.urlopen(request, timeout=5) as response:
            assert response.status == 204
            assert response.headers["Access-Control-Allow-Origin"] == origin
        bad = urllib.request.Request(
            f"http://127.0.0.1:{dev.api_port}/v1/sync", method="OPTIONS",
            headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"})
        with pytest.raises(urllib.error.HTTPError) as excinfo:
            urllib.request.urlopen(bad, timeout=5)
        assert excinfo.value.code == 403


def test_a_pair_code_is_available_and_the_link_points_at_the_dev_site(devserver, tmp_path):
    with devserver.running(tmp_path, web_port=0, api_port=0, address="127.0.0.1") as dev:
        code = dev.new_code()
        link = dev.pair_link(code)
        assert link.startswith(f"http://localhost:{dev.web_port}/#pair=127.0.0.1:{dev.api_port}:")
        body = json.dumps({"protocol": 1, "code": code, "device_name": "Dev", "device_id": "dev-device-0001"}).encode()
        request = urllib.request.Request(
            f"http://127.0.0.1:{dev.api_port}/v1/pair", data=body, method="POST",
            headers={"Content-Type": "application/json", "Origin": f"http://localhost:{dev.web_port}"})
        with urllib.request.urlopen(request, timeout=5) as response:
            assert response.status == 200 and "token" in json.loads(response.read())


def test_the_dev_origin_does_not_leak_into_the_process(devserver, tmp_path):
    from src import mobile_routes
    before = (mobile_routes.PWA_ORIGIN, mobile_routes.PWA_URL)
    with devserver.running(tmp_path, web_port=0, api_port=0, address="127.0.0.1"):
        assert mobile_routes.PWA_ORIGIN != before[0]
    assert (mobile_routes.PWA_ORIGIN, mobile_routes.PWA_URL) == before
