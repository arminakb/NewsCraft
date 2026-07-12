from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.core.config import settings
from app.core.logging import configure_logging
from app.db.session import async_session
from app.generation.default_prompts import (
    seed_default_telegram_configuration,
    seed_default_telegram_prompt,
)

configure_logging()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    async with async_session() as session:
        await seed_default_telegram_prompt(session)
        await seed_default_telegram_configuration(session)
        await session.commit()
    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in settings.cors_origins.split(",") if origin.strip()],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
