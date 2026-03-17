import os
from typing import Optional, Tuple

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.db.schema import initialize_schema
from app.db.session import check_db_connection
from app.models.project import Project  # noqa: F401 — registers the model
from app.models.upload import Upload  # noqa: F401 — registers the model
from app.models.scan import Scan  # noqa: F401 — registers the model
from app.models.graph_node import GraphNode  # noqa: F401 — registers the model
from app.models.graph_edge import GraphEdge  # noqa: F401 — registers the model
from app.models.simulation_run import SimulationRun  # noqa: F401 — registers the model
from app.models.sequence_diagram import SequenceDiagram  # noqa: F401 — registers the model
from app.models.route_analysis import RouteAnalysis  # noqa: F401 — registers the model
from app.models.project_model_snapshot import ProjectModelSnapshot  # noqa: F401 — registers the model
from app.routers import projects, uploads, scans, graphs, simulations, briefs, deep_dive, sequences, routes, analyze, system_summary, system_insights, code_peek, explanations

app = FastAPI(title="Chaos Twin API")


def _cors_config() -> Tuple[list[str], Optional[str], bool]:
    """Compute CORS settings.

    The intended configuration path is via environment variables:
    - `FRONTEND_ORIGINS` (preferred)
    - `ALLOWED_ORIGINS` (alternative)
    - `CHAOS_TWIN_CORS_ORIGINS` (legacy)

    Values are comma-separated lists of allowed origins. A value of "*" allows all origins.
    If no env var is provided, we still allow localhost origins for local development and
    additionally accept `*.onrender.com` for Render-hosted frontends.
    """

    configured = os.getenv("FRONTEND_ORIGINS") or os.getenv("ALLOWED_ORIGINS") or os.getenv(
        "CHAOS_TWIN_CORS_ORIGINS", ""
    )

    raw_origins = [origin.strip() for origin in configured.split(",") if origin.strip()]

    # Allow a simple all-origins opt-in via `*` (use with care in production).
    if "*" in raw_origins:
        allow_origins = ["*"]
    else:
        defaults = [
            "http://localhost:5173",
            "http://localhost:5174",
            "http://localhost:5175",
            "http://127.0.0.1:5173",
            "http://127.0.0.1:5174",
            "http://127.0.0.1:5175",
            "http://localhost:4173",
            "http://localhost:4174",
            "http://localhost:4175",
            "http://127.0.0.1:4173",
            "http://127.0.0.1:4174",
            "http://127.0.0.1:4175",
        ]
        # Use either configured values or defaults when not configured.
        allow_origins = raw_origins or defaults

    # FastAPI/Starlette does not allow `allow_credentials=True` when origins are set to "*".
    allow_credentials = os.getenv("CORS_ALLOW_CREDENTIALS", "true").lower() in {
        "1",
        "true",
        "yes",
    }
    if allow_origins == ["*"] and allow_credentials:
        allow_credentials = False

    # Helpful default for Render: allow any `*.onrender.com` frontend origin unless overridden.
    allow_origin_regex = None
    if not raw_origins:
        allow_origin_regex = r"^https://.*\.onrender\.com$"

    return allow_origins, allow_origin_regex, allow_credentials

app.include_router(projects.router)
app.include_router(uploads.router)
app.include_router(scans.router)
app.include_router(graphs.router)
app.include_router(simulations.router)
app.include_router(briefs.router)
app.include_router(deep_dive.router)
app.include_router(sequences.router)
app.include_router(routes.router)
app.include_router(analyze.router)
app.include_router(system_summary.router)
app.include_router(system_insights.router)
app.include_router(code_peek.router)
app.include_router(explanations.router)

allow_origins, allow_origin_regex, allow_credentials = _cors_config()

app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_origin_regex=allow_origin_regex,
    allow_credentials=allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup():
    initialize_schema()


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/health/db")
def health_db():
    db_ok = check_db_connection()
    return {
        "status": "ok" if db_ok else "error",
        "database": "connected" if db_ok else "not_connected",
    }