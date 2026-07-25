import json
import os
import subprocess
from pathlib import Path

import yaml

from app.core.config import Settings

ROOT = Path(__file__).resolve().parents[2]


PROXY_ENVIRONMENT_NAMES = {
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "NO_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
    "no_proxy",
}

API_ENVIRONMENT_NAMES = {
    "DATABASE_URL",
    "MEDIA_ROOT",
    "EXPORT_ROOT",
    "READINESS_REQUIRED_CAPABILITIES",
    "CAPABILITY_QUEUE_CEILING",
    "CAPABILITY_RETRY_AFTER_SECONDS",
    "CAPABILITY_OBSERVATION_TTL_SECONDS",
    "SECURITY_ADMIN_TOKEN",
    "CODEX_GATEWAY_HASH_KEY",
    "CODEX_GATEWAY_PUBLIC_URL",
    "SECRET_KEY_VERSION",
    "SECRET_MASTER_KEY",
    "SECRET_PREVIOUS_KEYS",
}
SOURCE_WORKER_ENVIRONMENT_NAMES = {
    "NEWSCRAFT_COMPONENT_ID",
    "DATABASE_URL",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "NO_PROXY",
    "MEDIA_ROOT",
    "EXPORT_ROOT",
    "TELEGRAM_MEDIA_STAGING_ROOT",
    "OPENROUTER_API_KEY",
    "OPENROUTER_BASE_URL",
    "SECRET_KEY_VERSION",
    "SECRET_MASTER_KEY",
    "SECRET_PREVIOUS_KEYS",
    "SECURITY_INTERNAL_SCOPES",
    "TELEGRAM_SOURCE_EDITOR_API_ID",
    "TELEGRAM_SOURCE_EDITOR_API_HASH",
    "TELEGRAM_SOURCE_EDITOR_SESSION",
}
PUBLISHING_WORKER_ENVIRONMENT_NAMES = {
    "NEWSCRAFT_COMPONENT_ID",
    "DATABASE_URL",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "NO_PROXY",
    "MEDIA_ROOT",
    "SECRET_KEY_VERSION",
    "SECRET_MASTER_KEY",
    "SECRET_PREVIOUS_KEYS",
    "SECURITY_INTERNAL_SCOPES",
    "TELEGRAM_PROXY_ALLOWED_PORTS",
    "TELEGRAM_PROXY_CONNECT_TIMEOUT_SECONDS",
    "TELEGRAM_API_READ_TIMEOUT_SECONDS",
    "TELEGRAM_DESTINATION_NEWS_TOKEN",
}
SCHEDULER_ENVIRONMENT_NAMES = {"NEWSCRAFT_COMPONENT_ID", "DATABASE_URL"}
ALL_COMPOSE_SERVICES = {
    "backup",
    "postgres",
    "postgres-test",
    "migrate",
    "api",
    "frontend",
    "worker-source-generation",
    "worker-publishing",
    "scheduler",
}
PRODUCTION_LONG_RUNNING_SERVICES = ALL_COMPOSE_SERVICES - {"backup", "postgres-test", "migrate"}


def _compose_config(
    proxy_environment: dict[str, str] | None = None,
    *,
    files: tuple[str, ...] = ("docker-compose.yml",),
) -> dict:
    environment = {key: value for key, value in os.environ.items() if key not in PROXY_ENVIRONMENT_NAMES}
    environment.update(proxy_environment or {})
    argv = ["docker", "compose", "--env-file", "/dev/null", "--profile", "*"]
    for file_name in files:
        argv.extend(("-f", file_name))
    argv.extend(("config", "--format", "json"))
    result = subprocess.run(
        argv,
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        env=environment,
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

    assert "python:3.14.6-slim-bookworm@sha256:" in dockerfile
    assert "ghcr.io/astral-sh/uv:0.11.29@sha256:" in dockerfile
    assert "uv sync --locked --no-dev --no-editable" in dockerfile
    assert "USER newscraft" in dockerfile
    assert ".[dev]" not in dockerfile
    assert "pip install" not in dockerfile
    assert "uvicorn" in dockerfile
    assert "app.main:app" in dockerfile


def test_compose_defines_exact_normal_runtime_services_and_test_profile():
    services = _compose_yaml()["services"]
    normal_services = {name for name, service in services.items() if not service.get("profiles")}

    assert normal_services == {
        "postgres",
        "migrate",
        "api",
        "frontend",
        "worker-source-generation",
        "worker-publishing",
        "scheduler",
    }
    assert services["postgres-test"]["profiles"] == ["test"]
    assert services["backup"]["profiles"] == ["operations"]


def test_backup_service_is_credential_minimal_and_storage_read_only():
    service = _compose_yaml()["services"]["backup"]

    assert service["environment"] == {
        "PGHOST": "postgres",
        "PGUSER": "newscraft",
        "PGPASSWORD": "newscraft",
        "PGDATABASE": "newscraft",
    }
    assert service["volumes"] == ["media_data:/data/media:ro", "export_data:/data/exports:ro"]
    assert not any(
        marker in name
        for name in service["environment"]
        for marker in ("OPENROUTER", "TELEGRAM", "TOKEN", "API_KEY", "SESSION")
    )


def test_worker_and_scheduler_are_long_running_backend_services():
    services = _compose_yaml()["services"]
    api = services["api"]
    source_worker = services["worker-source-generation"]
    publishing_worker = services["worker-publishing"]
    scheduler = services["scheduler"]

    assert source_worker["command"] == (
        "python -m app.jobs.worker --capability ingestion --capability source --capability generation"
    )
    assert publishing_worker["command"] == "python -m app.jobs.worker --capability publishing"
    assert scheduler["command"] == "python -m app.jobs.scheduler"
    assert source_worker["environment"]["NEWSCRAFT_COMPONENT_ID"] == "worker-source-generation"
    assert publishing_worker["environment"]["NEWSCRAFT_COMPONENT_ID"] == "worker-publishing"
    assert scheduler["environment"]["NEWSCRAFT_COMPONENT_ID"] == "scheduler"

    for service in (source_worker, publishing_worker, scheduler):
        assert service["build"] == api["build"]
        assert service["image"] == api["image"]
        assert service["depends_on"]["postgres"]["condition"] == "service_healthy"
        assert service["depends_on"]["api"]["condition"] == "service_healthy"
        assert set(service["depends_on"]) == {"postgres", "api"}
        assert "ports" not in service
        assert service["environment"]["DATABASE_URL"] == api["environment"]["DATABASE_URL"]

    assert "media_data:/data/media" in source_worker["volumes"]
    assert "media_staging:/data/media-staging" in source_worker["volumes"]
    assert publishing_worker["volumes"] == ["media_data:/data/media:ro"]
    assert "volumes" not in scheduler

    source_secret_names = {
        "OPENROUTER_API_KEY",
        "OPENROUTER_BASE_URL",
        "TELEGRAM_SOURCE_EDITOR_API_ID",
        "TELEGRAM_SOURCE_EDITOR_API_HASH",
        "TELEGRAM_SOURCE_EDITOR_SESSION",
    }
    destination_secret_names = {"TELEGRAM_DESTINATION_NEWS_TOKEN"}
    assert source_secret_names <= set(source_worker["environment"])
    assert not destination_secret_names & set(source_worker["environment"])
    assert destination_secret_names <= set(publishing_worker["environment"])
    assert not source_secret_names & set(publishing_worker["environment"])

    secret_markers = ("OPENROUTER", "TELEGRAM", "TOKEN", "SECRET")
    assert not any(marker in name.upper() for name in scheduler["environment"] for marker in secret_markers)


def test_expected_runtime_components_match_release_two_compose_identities():
    expected = Settings().expected_runtime_component_ids
    services = _compose_yaml()["services"]

    assert expected == "worker-source-generation,worker-publishing,scheduler"
    assert services["worker-source-generation"]["environment"]["NEWSCRAFT_COMPONENT_ID"] == ("worker-source-generation")
    assert services["worker-publishing"]["environment"]["NEWSCRAFT_COMPONENT_ID"] == ("worker-publishing")
    assert services["scheduler"]["environment"]["NEWSCRAFT_COMPONENT_ID"] == "scheduler"


def test_compose_contains_no_literal_runtime_secret_values():
    compose = _compose_yaml()
    for name in ("api", "worker-source-generation", "worker-publishing", "scheduler"):
        for key, value in compose["services"][name]["environment"].items():
            if any(marker in key for marker in ("API_KEY", "API_HASH", "SESSION", "TOKEN")):
                assert value == "${" + key + ":-}"


def test_only_owning_workers_receive_external_credential_references():
    services = _compose_yaml()["services"]
    api_environment = services["api"]["environment"]
    source_environment = services["worker-source-generation"]["environment"]
    publishing_environment = services["worker-publishing"]["environment"]
    scheduler_environment = services["scheduler"]["environment"]
    reference_names = {
        "OPENROUTER_API_KEY",
        "TELEGRAM_SOURCE_EDITOR_API_ID",
        "TELEGRAM_SOURCE_EDITOR_API_HASH",
        "TELEGRAM_SOURCE_EDITOR_SESSION",
        "TELEGRAM_DESTINATION_NEWS_TOKEN",
    }

    assert not reference_names & set(api_environment)
    assert {
        "OPENROUTER_API_KEY",
        "TELEGRAM_SOURCE_EDITOR_API_ID",
        "TELEGRAM_SOURCE_EDITOR_API_HASH",
        "TELEGRAM_SOURCE_EDITOR_SESSION",
    } <= set(source_environment)
    assert "TELEGRAM_DESTINATION_NEWS_TOKEN" not in source_environment
    assert {"TELEGRAM_DESTINATION_NEWS_TOKEN"} <= set(publishing_environment)
    assert not (reference_names - {"TELEGRAM_DESTINATION_NEWS_TOKEN"}) & set(publishing_environment)
    assert not reference_names & set(scheduler_environment)


def test_phase_six_base_compose_has_exact_service_environment_boundaries():
    services = _compose_yaml()["services"]

    assert set(services["api"]["environment"]) == API_ENVIRONMENT_NAMES
    assert set(services["worker-source-generation"]["environment"]) == (SOURCE_WORKER_ENVIRONMENT_NAMES)
    assert set(services["worker-publishing"]["environment"]) == (PUBLISHING_WORKER_ENVIRONMENT_NAMES)
    assert set(services["scheduler"]["environment"]) == SCHEDULER_ENVIRONMENT_NAMES
    assert set(services["frontend"]["environment"]) == {"API_INTERNAL_BASE_URL"}


def test_phase_six_base_compose_mounts_only_role_owned_storage():
    services = _compose_yaml()["services"]

    assert services["api"]["volumes"] == [
        "media_data:/data/media:ro",
        "export_data:/data/exports:ro",
    ]
    assert services["worker-source-generation"]["volumes"] == [
        "media_data:/data/media",
        "export_data:/data/exports",
        "media_staging:/data/media-staging",
    ]
    assert services["worker-publishing"]["volumes"] == [
        "media_data:/data/media:ro",
    ]
    assert "volumes" not in services["scheduler"]
    assert all(mount != ".:/workspace" for service in services.values() for mount in service.get("volumes", []) or [])


def test_production_secrets_are_role_owned_read_only_files():
    production = yaml.safe_load((ROOT / "docker-compose.production.yml").read_text(encoding="utf-8"))
    services = production["services"]

    assert set(services) == ALL_COMPOSE_SERVICES
    api_targets = {item["target"] for item in services["api"]["secrets"]}
    source_targets = {item["target"] for item in services["worker-source-generation"]["secrets"]}
    publishing_targets = {item["target"] for item in services["worker-publishing"]["secrets"]}
    assert api_targets == {
        "SECURITY_ADMIN_TOKEN",
        "CODEX_GATEWAY_HASH_KEY",
        "SECRET_MASTER_KEY",
        "SECRET_PREVIOUS_KEYS",
    }
    assert source_targets == {
        "SECRET_MASTER_KEY",
        "SECRET_PREVIOUS_KEYS",
        "OPENROUTER_API_KEY",
        "TELEGRAM_SOURCE_EDITOR_API_ID",
        "TELEGRAM_SOURCE_EDITOR_API_HASH",
        "TELEGRAM_SOURCE_EDITOR_SESSION",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
    }
    assert publishing_targets == {
        "SECRET_MASTER_KEY",
        "SECRET_PREVIOUS_KEYS",
        "TELEGRAM_DESTINATION_NEWS_TOKEN",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
    }
    for service_name in ("api", "worker-source-generation", "worker-publishing"):
        assert services[service_name]["environment"]["APP_ENV"] == "production"
        for mounted_secret in services[service_name]["secrets"]:
            assert mounted_secret["mode"] == 0o400


def test_export_storage_is_persistent_and_shared_only_with_the_builder_and_api():
    compose = _compose_yaml()
    services = compose["services"]

    assert "export_data:/data/exports:ro" in services["api"]["volumes"]
    assert "export_data:/data/exports" in services["worker-source-generation"]["volumes"]
    assert services["api"]["environment"]["EXPORT_ROOT"] == "/data/exports"
    assert services["worker-source-generation"]["environment"]["EXPORT_ROOT"] == "/data/exports"
    assert "export_data:/data/exports" not in services["worker-publishing"].get("volumes", [])
    assert "EXPORT_ROOT" not in services["worker-publishing"]["environment"]
    assert "export_data" in compose["volumes"]


def test_runtime_environment_names_and_review_first_dry_run_are_documented():
    env_example = (ROOT / ".env.example").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    for line in (
        "OPENROUTER_API_KEY=",
        "OPENROUTER_BASE_URL=https://openrouter.ai/api/v1",
        "TELEGRAM_SOURCE_EDITOR_API_ID=",
        "TELEGRAM_SOURCE_EDITOR_API_HASH=",
        "TELEGRAM_SOURCE_EDITOR_SESSION=",
        "TELEGRAM_DESTINATION_NEWS_TOKEN=",
        "TELEGRAM_MEDIA_STAGING_ROOT=/data/media-staging",
    ):
        assert line in env_example
    for phrase in (
        "configure credential references",
        "destination check",
        "gap-free new-only",
        "fake provider",
        "dry run",
        "review",
        "opt in to real credentials",
        "restart only the relevant worker",
        "No live credentials or publishing are used by default tests",
    ):
        assert phrase in readme


def test_api_healthcheck_uses_readiness_without_dependency_cycle():
    services = _compose_yaml()["services"]
    api = services["api"]

    assert api["healthcheck"]["test"] == [
        "CMD",
        "python",
        "-c",
        "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/ready', timeout=2).close()",
    ]
    assert api["depends_on"] == {"migrate": {"condition": "service_completed_successfully"}}
    assert "worker" not in api["depends_on"]
    assert "scheduler" not in api["depends_on"]


def test_worker_and_scheduler_healthchecks_verify_identity_capability_and_job_coverage():
    services = _compose_yaml()["services"]

    expected = {
        "worker-source-generation": {
            "--component-id": "worker-source-generation",
            "--component-type": "worker",
            "--expected-capabilities": "generation,ingestion,source",
            "--expected-job-types": (
                "build_export,content_pack.generate,content_pack.generate_telegram,"
                "content_pack.regenerate,execute_retention,ingest.collect,manual_intake,"
                "operations.canary.source_generation,research_story,story.group_pending,"
                "telegram.route.backfill,"
                "telegram.route.dry_run,telegram.route.initialize,telegram.route.poll,"
                "telegram.route.process"
            ),
            "--max-age-seconds": "120",
        },
        "worker-publishing": {
            "--component-id": "worker-publishing",
            "--component-type": "worker",
            "--expected-capabilities": "publishing",
            "--expected-job-types": (
                "operations.canary.publishing,telegram.destination.check,telegram.proxy.check,telegram.publish"
            ),
            "--max-age-seconds": "120",
        },
        "scheduler": {
            "--component-id": "scheduler",
            "--component-type": "scheduler",
            "--expected-capabilities": "scheduling",
            "--expected-job-types": "",
            "--max-age-seconds": "90",
        },
    }
    for name, expected_options in expected.items():
        command = services[name]["healthcheck"]["test"]
        assert command[:4] == ["CMD", "python", "-m", "app.jobs.healthcheck"]
        assert dict(zip(command[4::2], command[5::2], strict=True)) == expected_options


def test_frontend_healthcheck_targets_the_process_only_route():
    frontend = _compose_yaml()["services"]["frontend"]

    assert frontend["depends_on"] == {"api": {"condition": "service_healthy"}}
    assert frontend["healthcheck"]["test"][:3] == ["CMD", "node", "-e"]
    assert "http://127.0.0.1:3000/health" in frontend["healthcheck"]["test"][3]


def test_daily_bundle_command_is_documented_for_docker():
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "python -m app.daily_bundle" in readme
    assert "/output/today-news" in readme
    assert "worker-source-generation" in readme
    assert ".:/workspace" not in compose


def test_manual_ingest_example_includes_required_request_id():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert '"request_id":"123e4567-e89b-42d3-a456-426614174000"' in readme


def test_base_compose_unset_and_empty_proxy_values_are_direct_without_external_network():
    for proxy_environment in ({}, {name: "" for name in PROXY_ENVIRONMENT_NAMES}):
        compose = _compose_config(proxy_environment)
        assert "xray_proxy" not in compose.get("networks", {})
        for name in ("worker-source-generation", "worker-publishing"):
            service = compose["services"][name]
            assert service["environment"]["HTTP_PROXY"] == ""
            assert service["environment"]["HTTPS_PROXY"] == ""
            assert service["environment"]["ALL_PROXY"] == ""
            assert "xray_proxy" not in service.get("networks", {})
        for name in ("api", "scheduler"):
            service = compose["services"][name]
            assert not PROXY_ENVIRONMENT_NAMES & set(service["environment"])
            assert "xray_proxy" not in service.get("networks", {})


def test_proxy_network_override_is_explicit_and_preserves_valid_configuration():
    compose = _compose_config(
        {
            "HTTP_PROXY": "http://proxy.example:18080",
            "HTTPS_PROXY": "https://proxy.example:18443",
            "ALL_PROXY": "socks5://proxy.example:1080",
            "NO_PROXY": "postgres,localhost",
        },
        files=("docker-compose.yml", "docker-compose.proxy.yml"),
    )

    assert compose["networks"]["xray_proxy"]["external"] is True
    for name in ("worker-source-generation", "worker-publishing"):
        service = compose["services"][name]
        assert service["environment"]["HTTP_PROXY"] == "http://proxy.example:18080"
        assert service["environment"]["HTTPS_PROXY"] == "https://proxy.example:18443"
        assert service["environment"]["ALL_PROXY"] == "socks5://proxy.example:1080"
        assert service["environment"]["NO_PROXY"] == "postgres,localhost"
        assert "xray_proxy" in service["networks"]
    for name in ("api", "scheduler"):
        service = compose["services"][name]
        assert not PROXY_ENVIRONMENT_NAMES & set(service["environment"])
        assert "xray_proxy" not in service.get("networks", {})


def test_database_url_uses_newscraft_specific_postgres_alias():
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert "DATABASE_URL: postgresql+asyncpg://newscraft:newscraft@newscraft-postgres:5432/newscraft" in compose
    assert "aliases:" in compose
    assert "newscraft-postgres" in compose


def test_migration_is_one_shot_and_api_waits_for_success_before_uvicorn():
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    services = compose["services"]

    assert services["migrate"]["command"] == "alembic upgrade head"
    assert services["migrate"]["restart"] == "no"
    assert services["migrate"]["depends_on"] == {"postgres": {"condition": "service_healthy"}}
    assert services["api"]["command"] == ("uvicorn app.main:app --host 0.0.0.0 --port 8000")
    assert "alembic" not in services["api"]["command"]
    assert services["api"]["depends_on"] == {"migrate": {"condition": "service_completed_successfully"}}


def test_restart_policies_are_exact_in_every_supported_compose_mode():
    modes = {
        "base": ("docker-compose.yml",),
        "development": ("docker-compose.yml", "docker-compose.dev.yml"),
        "test": ("docker-compose.yml", "docker-compose.test.yml"),
        "acceptance": ("docker-compose.yml", "docker-compose.acceptance.yml"),
        "production": ("docker-compose.yml", "docker-compose.production.yml"),
    }

    for mode, files in modes.items():
        services = _compose_config(files=files)["services"]
        assert set(services) == ALL_COMPOSE_SERVICES, mode
        expected = {
            name: ("unless-stopped" if mode == "production" and name in PRODUCTION_LONG_RUNNING_SERVICES else "no")
            for name in ALL_COMPOSE_SERVICES
        }
        assert {name: service["restart"] for name, service in services.items()} == expected


def test_production_app_processes_run_beneath_docker_init():
    services = _compose_config(files=("docker-compose.yml", "docker-compose.production.yml"))["services"]

    for name in (
        "api",
        "frontend",
        "worker-source-generation",
        "worker-publishing",
        "scheduler",
    ):
        assert services[name]["init"] is True
    for name in ("backup", "postgres", "postgres-test", "migrate"):
        assert "init" not in services[name]


def test_all_supported_compose_modes_render_with_valid_dependency_conditions():
    for files in (
        ("docker-compose.yml",),
        ("docker-compose.yml", "docker-compose.dev.yml"),
        ("docker-compose.yml", "docker-compose.test.yml"),
        ("docker-compose.yml", "docker-compose.acceptance.yml"),
        ("docker-compose.yml", "docker-compose.production.yml"),
    ):
        services = _compose_config(files=files)["services"]
        assert services["api"]["depends_on"]["migrate"]["condition"] == ("service_completed_successfully")
        assert services["migrate"]["depends_on"]["postgres"]["condition"] == ("service_healthy")


def test_postgres_18_volume_uses_supported_data_parent():
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    postgres = compose["services"]["postgres"]

    assert postgres["image"].startswith("postgres:18.3-bookworm@sha256:")
    assert "postgres_data:/var/lib/postgresql" in postgres["volumes"]
    assert "postgres_data:/var/lib/postgresql/data" not in postgres["volumes"]


def test_compose_has_ephemeral_postgres_test_profile():
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    service = compose["services"]["postgres-test"]

    assert service["image"].startswith("postgres:18.3-bookworm@sha256:")
    assert service["profiles"] == ["test"]
    assert service["environment"]["POSTGRES_DB"] == "newscraft_test"
    assert service["ports"] == ["127.0.0.1:55432:5432"]
    assert "/var/lib/postgresql" in service["tmpfs"]


def test_acceptance_compose_enables_fixture_only_for_source_worker():
    acceptance = yaml.safe_load((ROOT / "docker-compose.acceptance.yml").read_text(encoding="utf-8"))
    source_worker = acceptance["services"]["worker-source-generation"]

    assert source_worker["environment"] == {
        "APP_ENV": "test",
        "TELEGRAM_ACCEPTANCE_FIXTURE_PATH": ("/acceptance-fixtures/telegram_public_album.html"),
    }
    assert source_worker["volumes"] == ["./backend/tests/fixtures:/acceptance-fixtures:ro"]
    assert set(acceptance["services"]) == ALL_COMPOSE_SERVICES
    assert all(service["restart"] == "no" for service in acceptance["services"].values())


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
