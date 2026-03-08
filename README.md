# Chaos Twin

Chaos Twin is a local-first codebase intelligence app.

Current capabilities:
- Create projects
- Upload ZIP codebases
- Run scan pipeline
- View rich scan summary
- Generate and fetch backend architecture graph (Graph v1)

## Tech Stack
- Backend: FastAPI + SQLAlchemy
- Frontend: React + TypeScript + Vite
- Database: PostgreSQL (Docker)

## Project Structure
- `backend/` FastAPI app and data pipeline
- `frontend/` React app
- `docker-compose.yml` local Postgres only

Generated local storage:
- Uploads: `backend/uploads/`
- Extracted workspaces: `backend/workspaces/`

## 1) Start Postgres
From repo root:

```bash
docker compose up -d db
```

## 2) Run Backend
From repo root:

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload --port 8000
```

Backend health checks:
- `http://127.0.0.1:8000/health`
- `http://127.0.0.1:8000/health/db`

## 3) Run Frontend
From repo root:

```bash
cd frontend
npm install
cp .env.example .env
npm run dev
```

Frontend app:
- `http://127.0.0.1:5173`

## Environment Files

Backend (`backend/.env`):
- `DATABASE_URL` default: `postgresql+psycopg://postgres:postgres@localhost:5432/chaostwin`
- `SQL_ECHO` default: `false`
- `UPLOAD_DIR` default: `uploads` (stored at `backend/uploads`)
- `WORKSPACE_DIR` default: `workspaces` (stored at `backend/workspaces`)

Frontend (`frontend/.env`):
- `VITE_API_BASE_URL` default used in app: `http://127.0.0.1:8000`

## Notes
- Graph generation uses scan summary heuristics (no deep AST parsing yet).
- Docker is currently used only for PostgreSQL.