import os

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


def _allowed_origins() -> list[str]:
    configured = os.getenv("CHAOS_TWIN_CORS_ORIGINS", "")

    # Allow a simple all-origins opt-in via `*` (use with care in production).
    if "*" in [origin.strip() for origin in configured.split(",") if origin.strip()]:
        return ["*"]

    extra = [origin.strip() for origin in configured.split(",") if origin.strip()]
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
    seen: set[str] = set()
    ordered: list[str] = []
    for origin in [*defaults, *extra]:
        if origin in seen:
            continue
        seen.add(origin)
        ordered.append(origin)
    return ordered

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

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins(),
    allow_credentials=True,
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