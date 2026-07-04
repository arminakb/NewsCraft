from fastapi import FastAPI

from newscraft.api.routers import articles, assets, approved, content_pipeline, diagnostics, health, ingestion, review, sources
from newscraft.core.logging import configure_logging

configure_logging()

app = FastAPI(title="NewsCraft API", version="0.1.0")
app.include_router(health.router)
app.include_router(sources.router)
app.include_router(ingestion.router)
app.include_router(articles.router)
app.include_router(review.router)
app.include_router(approved.router)
app.include_router(assets.router)
app.include_router(content_pipeline.router)
app.include_router(diagnostics.router)
