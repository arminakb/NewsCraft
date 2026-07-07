from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def test_dockerfile_runs_backend_api():
    dockerfile = (ROOT / "backend/Dockerfile").read_text(encoding="utf-8")

    assert "FROM python:3.14-slim" in dockerfile
    assert "uvicorn" in dockerfile
    assert "app.main:app" in dockerfile


def test_compose_defines_postgres_api_and_worker():
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert "postgres:18" in compose
    assert "DATABASE_URL: postgresql+asyncpg://newscraft:newscraft@newscraft-postgres:5432/newscraft" in compose
    assert "API_INTERNAL_BASE_URL: http://api:8000" in compose
    assert "python -m app.worker" in compose
    assert "--download-media" in compose


def test_daily_bundle_command_is_documented_for_docker():
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "python -m app.daily_bundle" in readme
    assert "/workspace/today-news" in readme
    assert ".:/workspace" in compose


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


def test_dockerignore_excludes_local_build_noise():
    dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8")

    assert "**/.venv/" in dockerignore
    assert "**/.pytest_cache/" in dockerignore
    assert "data/" in dockerignore
