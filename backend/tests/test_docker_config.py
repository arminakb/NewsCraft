import json
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def _compose_config() -> dict:
    result = subprocess.run(
        ["docker", "compose", "config", "--format", "json"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def _compose_yaml() -> dict:
    return yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))


def test_local_service_ports_bind_to_loopback():
    compose = _compose_config()

    assert compose["services"]["postgres"]["ports"][0]["host_ip"] == "127.0.0.1"
    assert compose["services"]["api"]["ports"][0]["host_ip"] == "127.0.0.1"
    assert compose["services"]["frontend"]["ports"][0]["host_ip"] == "127.0.0.1"


def test_dockerfile_runs_backend_api():
    dockerfile = (ROOT / "backend/Dockerfile").read_text(encoding="utf-8")

    assert "FROM python:3.14-slim" in dockerfile
    assert "uvicorn" in dockerfile
    assert "app.main:app" in dockerfile


def test_compose_defines_exact_normal_runtime_services_and_test_profile():
    services = _compose_yaml()["services"]
    normal_services = {name for name, service in services.items() if not service.get("profiles")}

    assert normal_services == {"postgres", "api", "frontend", "worker", "scheduler"}
    assert services["postgres-test"]["profiles"] == ["test"]


def test_worker_and_scheduler_are_long_running_backend_services():
    services = _compose_yaml()["services"]
    api = services["api"]
    worker = services["worker"]
    scheduler = services["scheduler"]

    assert worker["command"] == "python -m app.jobs.worker"
    assert scheduler["command"] == "python -m app.jobs.scheduler"
    assert "--trigger manual" not in worker["command"]
    assert "--download-media" not in worker["command"]

    for service in (worker, scheduler):
        assert service["build"] == api["build"]
        assert service["image"] == api["image"]
        assert "media_data:/data/media" in service["volumes"]
        assert service["depends_on"]["postgres"]["condition"] == "service_healthy"
        assert service["depends_on"]["api"]["condition"] == "service_healthy"
        assert set(service["depends_on"]) == {"postgres", "api"}
        assert "ports" not in service
        for setting in (
            "DATABASE_URL",
            "HTTP_PROXY",
            "HTTPS_PROXY",
            "ALL_PROXY",
            "NO_PROXY",
            "MEDIA_ROOT",
        ):
            assert service["environment"][setting] == api["environment"][setting]

    secret_markers = ("PUBLISH", "TELEGRAM", "TOKEN", "SECRET")
    assert not any(
        marker in name.upper()
        for name in scheduler["environment"]
        for marker in secret_markers
    )


def test_api_healthcheck_waits_for_post_migration_uvicorn_without_dependency_cycle():
    services = _compose_yaml()["services"]
    api = services["api"]

    assert api["healthcheck"]["test"] == [
        "CMD",
        "python",
        "-c",
        "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2).close()",
    ]
    assert api["depends_on"] == {"postgres": {"condition": "service_healthy"}}
    assert "worker" not in api["depends_on"]
    assert "scheduler" not in api["depends_on"]


def test_daily_bundle_command_is_documented_for_docker():
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "python -m app.daily_bundle" in readme
    assert "/workspace/today-news" in readme
    assert ".:/workspace" in compose


def test_manual_ingest_example_includes_required_request_id():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert '"request_id":"123e4567-e89b-42d3-a456-426614174000"' in readme


def test_api_and_worker_default_to_dockerized_xray_proxy():
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert "HTTP_PROXY: ${HTTP_PROXY:-http://xray-proxy:10808}" in compose
    assert "HTTPS_PROXY: ${HTTPS_PROXY:-http://xray-proxy:10808}" in compose
    assert "ALL_PROXY: ${ALL_PROXY:-http://xray-proxy:10808}" in compose
    assert "xray_proxy:" in compose
    assert "name: ${XRAY_PROXY_NETWORK:-contenthub_default}" in compose


def test_database_url_uses_newscraft_specific_postgres_alias():
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert "DATABASE_URL: postgresql+asyncpg://newscraft:newscraft@newscraft-postgres:5432/newscraft" in compose
    assert "aliases:" in compose
    assert "newscraft-postgres" in compose


def test_api_service_runs_alembic_before_uvicorn():
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    command = compose["services"]["api"]["command"]

    assert command == 'sh -c "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"'


def test_postgres_18_volume_uses_supported_data_parent():
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    postgres = compose["services"]["postgres"]

    assert postgres["image"] == "postgres:18"
    assert "postgres_data:/var/lib/postgresql" in postgres["volumes"]
    assert "postgres_data:/var/lib/postgresql/data" not in postgres["volumes"]


def test_compose_has_ephemeral_postgres_test_profile():
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    service = compose["services"]["postgres-test"]

    assert service["image"] == "postgres:18"
    assert service["profiles"] == ["test"]
    assert service["environment"]["POSTGRES_DB"] == "newscraft_test"
    assert service["ports"] == ["127.0.0.1:55432:5432"]
    assert "/var/lib/postgresql" in service["tmpfs"]


def test_dockerignore_excludes_local_build_noise():
    dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8")

    assert "**/.venv/" in dockerignore
    assert "**/.pytest_cache/" in dockerignore
    assert "data/" in dockerignore


def test_backend_dockerignore_excludes_backend_build_noise():
    dockerignore = (ROOT / "backend/.dockerignore").read_text(encoding="utf-8")

    assert ".venv/" in dockerignore
    assert "tests/" in dockerignore
    assert ".pytest_cache/" in dockerignore
    assert "*.db" in dockerignore
