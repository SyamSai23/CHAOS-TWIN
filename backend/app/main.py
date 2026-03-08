from fastapi import FastAPI
from app.db.session import check_db_connection

app = FastAPI(title="Chaos Twin API")


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