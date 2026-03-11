import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BACKEND_DIR = Path(__file__).resolve().parent.parent

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg://postgres:postgres@localhost:5432/chaostwin",
)

SQL_ECHO = os.getenv("SQL_ECHO", "false").lower() in {"1", "true", "yes"}
ENABLE_LEGACY_STARTUP_SCHEMA_PATCHES = os.getenv(
    "ENABLE_LEGACY_STARTUP_SCHEMA_PATCHES", "true"
).lower() in {"1", "true", "yes"}


def _resolve_storage_dir(env_name: str, default_dir: str) -> Path:
    raw_value = os.getenv(env_name, default_dir)
    candidate = Path(raw_value)
    if not candidate.is_absolute():
        candidate = BACKEND_DIR / candidate
    return candidate.resolve()


UPLOAD_DIR = _resolve_storage_dir("UPLOAD_DIR", "uploads")
WORKSPACE_DIR = _resolve_storage_dir("WORKSPACE_DIR", "workspaces")

# --- LLM / AI Brief settings ---
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
