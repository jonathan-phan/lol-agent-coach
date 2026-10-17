"""
Container checks. The static ones always run; the build-and-run smoke test
needs Docker and is opt-in: RUN_DOCKER_TESTS=1 pytest tests/test_docker.py
"""
import os
import shutil
import subprocess
import time
import urllib.request

import pytest

ROOT = os.path.join(os.path.dirname(__file__), "..")
IMAGE = "lol-agent-coach-test"


def _read(name: str) -> str:
    with open(os.path.join(ROOT, name), encoding="utf-8") as f:
        return f.read()


def test_dockerignore_keeps_secrets_and_local_data_out_of_the_image():
    ignored = _read(".dockerignore").split()
    for entry in (".env", "venv/", "cache/", ".git"):
        assert entry in ignored


def test_container_runs_as_non_root_without_secrets():
    dockerfile = _read("Dockerfile")
    assert "\nUSER app" in dockerfile
    assert "HEALTHCHECK" in dockerfile
    for secret in ("RIOT_API_KEY", "LLM_API_KEY"):
        assert secret not in dockerfile


def test_runtime_dependencies_are_pinned():
    for line in _read("requirements.txt").split():
        assert "==" in line, f"{line} is not pinned"


def test_compose_defaults_to_demo_mode():
    assert "RIOT_MODE: ${RIOT_MODE:-demo}" in _read("docker-compose.yml")


@pytest.mark.skipif(
    not (os.getenv("RUN_DOCKER_TESTS") == "1" and shutil.which("docker")),
    reason="set RUN_DOCKER_TESTS=1 with Docker installed",
)
def test_image_builds_serves_health_and_contains_no_secrets():
    subprocess.run(["docker", "build", "-t", IMAGE, ROOT], check=True)
    container = subprocess.run(
        ["docker", "run", "-d", "-p", "18501:8501", IMAGE], check=True, capture_output=True, text=True
    ).stdout.strip()
    try:
        status = None
        for _ in range(30):
            try:
                status = urllib.request.urlopen("http://localhost:18501/_stcore/health", timeout=2).status
                break
            except OSError:
                time.sleep(1)
        assert status == 200

        listing = subprocess.run(
            ["docker", "exec", container, "ls", "-a", "/app"], check=True, capture_output=True, text=True
        ).stdout.split()
        assert ".env" not in listing
        assert "tests" not in listing
        user = subprocess.run(
            ["docker", "exec", container, "id", "-u"], check=True, capture_output=True, text=True
        ).stdout.strip()
        assert user != "0"
    finally:
        subprocess.run(["docker", "rm", "-f", container], capture_output=True)
