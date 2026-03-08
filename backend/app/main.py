from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.db.session import check_db_connection, engine
from app.db.base import Base
from app.models.project import Project  # noqa: F401 — registers the model
from app.routers import projects

app = FastAPI(title="Chaos Twin API")

app.include_router(projects.router)

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