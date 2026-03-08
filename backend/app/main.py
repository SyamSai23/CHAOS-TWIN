from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from app.db.session import check_db_connection, engine
from app.db.base import Base
from app.models.project import Project  # noqa: F401 — registers the model
from app.models.upload import Upload  # noqa: F401 — registers the model
from app.models.scan import Scan  # noqa: F401 — registers the model
from app.routers import projects, uploads, scans

app = FastAPI(title="Chaos Twin API")

app.include_router(projects.router)
app.include_router(uploads.router)
app.include_router(scans.router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup():
    Base.metadata.create_all(bind=engine)

    # Keep scans table aligned when adding simple JSON summary fields.
    with engine.begin() as connection:
        connection.execute(
            text("ALTER TABLE scans ADD COLUMN IF NOT EXISTS key_files JSON NOT NULL DEFAULT '[]'::json")
        )
        connection.execute(
            text("ALTER TABLE scans ADD COLUMN IF NOT EXISTS top_level_dirs JSON NOT NULL DEFAULT '[]'::json")
        )
        connection.execute(
            text("ALTER TABLE scans ADD COLUMN IF NOT EXISTS extension_counts JSON NOT NULL DEFAULT '{}'::json")
        )
        connection.execute(
            text("ALTER TABLE scans ADD COLUMN IF NOT EXISTS project_type VARCHAR NOT NULL DEFAULT 'script/data project'")
        )
        connection.execute(
            text("ALTER TABLE scans ADD COLUMN IF NOT EXISTS entry_points JSON NOT NULL DEFAULT '[]'::json")
        )


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