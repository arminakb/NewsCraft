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
    assert "DATABASE_URL: postgresql+asyncpg://newscraft:newscraft@postgres:5432/newscraft" in compose
    assert "python -m app.worker" in compose
    assert "--download-media" in compose


def test_api_service_runs_alembic_before_uvicorn():
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    command = compose["services"]["api"]["command"]

    assert command == 'sh -c "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"'


def test_dockerignore_excludes_local_build_noise():
    dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8")

    assert "**/.venv/" in dockerignore
    assert "**/.pytest_cache/" in dockerignore
    assert "data/" in dockerignore
