from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.generation_settings import seed_codex_provider_profile
from app.api.routes import router
from app.core.config import settings
from app.core.logging import configure_logging
from app.db.session import async_session
from app.generation.default_prompts import (
    seed_default_editorial_prompts,
    seed_default_telegram_configuration,
    seed_default_telegram_prompt,
)
from app.jobs.capability_gate import safe_gate_code, safe_gate_job_type
from app.jobs.errors import JobCapabilityUnavailable
from app.llm_providers.service import seed_legacy_provider_compatibility
from app.security.middleware import SecurityAuthorizationMiddleware

configure_logging()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    async with async_session() as session:
        await seed_default_telegram_prompt(session)
        await seed_default_editorial_prompts(session)
        await seed_default_telegram_configuration(session)
        await seed_codex_provider_profile(
            session,
            enabled=settings.codex_enabled,
            model="gpt-5.4",
        )
        await seed_legacy_provider_compatibility(session)
        await session.commit()
    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan)


@app.exception_handler(JobCapabilityUnavailable)
async def job_capability_unavailable(
    _request: Request,
    exc: JobCapabilityUnavailable,
) -> JSONResponse:
    return JSONResponse(
        status_code=503,
        headers={"Retry-After": str(exc.retry_after_seconds)},
        content={
            "detail": {
                "code": safe_gate_code(exc.code),
                "job_type": safe_gate_job_type(exc.job_type),
                "retry_after_seconds": exc.retry_after_seconds,
            }
        },
    )


app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in settings.cors_origins.split(",") if origin.strip()],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(SecurityAuthorizationMiddleware, config=settings)
app.include_router(router)
