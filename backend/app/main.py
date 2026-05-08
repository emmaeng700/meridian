"""FastAPI application entrypoint for Meridian."""
from contextlib import asynccontextmanager
import math
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import json


def _clean(obj: Any) -> Any:
    """Recursively replace NaN/Inf floats with None for safe JSON serialization."""
    if isinstance(obj, float):
        return None if (math.isnan(obj) or math.isinf(obj)) else obj
    if isinstance(obj, dict):
        return {k: _clean(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_clean(v) for v in obj]
    return obj


class SafeJSONResponse(JSONResponse):
    """JSONResponse that replaces NaN/Inf with null before encoding."""
    def render(self, content: Any) -> bytes:
        return json.dumps(_clean(content), allow_nan=False).encode("utf-8")

from app.core.config import settings
from app.core.database import create_all_tables

# Import models so that SQLAlchemy registers them before create_all
import app.models.source  # noqa: F401
import app.models.profile  # noqa: F401
import app.models.anomaly  # noqa: F401

from app.api.sources import router as sources_router
from app.api.profiles import router as profiles_router
from app.api.anomalies import router as anomalies_router
from app.api.reports import router as reports_router
from app.api.ingest import router as ingest_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Create DB tables on startup."""
    await create_all_tables()
    yield


app = FastAPI(
    title="Meridian — Data Observability Platform",
    description=(
        "Meridian monitors data pipelines for anomalies, schema drift, "
        "null-rate spikes, volume drops, and data quality issues."
    ),
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    default_response_class=SafeJSONResponse,
)

# Allow all origins — this is an open-source dev tool
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
prefix = settings.API_PREFIX
app.include_router(sources_router, prefix=prefix)
app.include_router(profiles_router, prefix=prefix)
app.include_router(anomalies_router, prefix=prefix)
app.include_router(reports_router, prefix=prefix)
app.include_router(ingest_router, prefix=prefix)


@app.get("/health", tags=["health"])
async def health_check():
    return {"status": "ok", "version": "1.0.0"}


@app.get("/", tags=["root"])
async def root():
    return {
        "name": "Meridian Data Observability",
        "version": "1.0.0",
        "docs": "/docs",
        "health": "/health",
    }
