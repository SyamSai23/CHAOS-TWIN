# Chaos Twin

Understand your codebase, inspect request flows, and simulate failure impact locally.

Chaos Twin is a local-first codebase intelligence workbench. You upload a repository archive, the backend produces deterministic scan artifacts, the frontend surfaces routes and architecture detail, and you can explore blast radius through graph-backed failure simulation.

## What It Does

- Detects languages, frameworks, entry points, components, routes, and infrastructure signals from an uploaded codebase.
- Produces deterministic route-level request flow summaries directly on scan routes as `request_flow`.
- Builds a canonical system model with stable IDs so downstream features can reuse consistent entities and relations.
- Exposes project summary, insights, code-peek, graph, and simulation views from the latest scan.
- Renders route details in the API Explorer with the direct request flow chain instead of requiring stored per-route analysis rows.
- Keeps uploads, extracted workspaces, and local environment files on your machine.

## Current Feature Set

### Analysis pipeline

- ZIP upload and project-based scan workflow.
- Deterministic scan enrichment for components, routes, infrastructure, and evidence.
- Canonical model adapter in `backend/app/domain/system_model/` for stable project entities and relations.
- On-demand system summary and insights derived from the latest scan artifacts.
- Evidence-aware code peek for jumping from findings back to supporting files.

### API and route exploration

- Route extraction across common backend patterns.
- Request flow extraction attached directly to each route as `request_flow`.
- API Explorer route detail view in the frontend.
- Fallback path that can derive route analysis from the scan route even when `route_analyses` rows are absent.

### Graph and simulation

- Graph generation from scan and canonical-backed artifacts.
- Interactive graph UI with React Flow.
- Failure simulation with graph edge semantics such as `uses`, `runs_on`, `contains`, and `connects_to`.
- Summary of impacted components and blast radius from the selected failure point.

### Validation tooling

- Focused validators in `scripts/` for route extraction, route request flow, infrastructure detection, component detection, and evidence targeting.
- Matrix evaluation script for running backend flow checks across multiple repository shapes.

## Tech Stack

### Backend

- FastAPI
- SQLAlchemy
- PostgreSQL
- Python 3.9+
- `tree-sitter` and `tree-sitter-languages` for structured code parsing where needed

### Frontend

- React 19
- TypeScript
- Vite 7
- `@xyflow/react`

### Local infrastructure

- Docker Compose for PostgreSQL
- Local filesystem storage for uploaded archives and extracted workspaces

## Repository Layout

```text
chaos-twin/
├── backend/
│   ├── app/
│   │   ├── db/
│   │   ├── domain/system_model/
│   │   ├── routers/
│   │   └── services/
│   └── requirements.txt
├── docs/
├── frontend/
│   ├── public/
│   └── src/
├── sample-projects/
├── scripts/
├── docker-compose.yml
└── README.md
```

## Quick Start

### 1. Start PostgreSQL

From the repository root:

```bash
docker compose up -d db
```

### 2. Start the backend

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Backend endpoints:

- API docs: `http://127.0.0.1:8000/docs`
- Health: `http://127.0.0.1:8000/health`
- Database health: `http://127.0.0.1:8000/health/db`

### 3. Start the frontend

```bash
cd frontend
npm install
npm run dev
```

Frontend app:

- `http://localhost:5173`

## Configuration

### Backend environment

Local backend configuration lives in `backend/.env` when you need to override defaults.

| Variable | Default | Description |
| --- | --- | --- |
| `DATABASE_URL` | `postgresql+psycopg://postgres:postgres@localhost:5432/chaostwin` | PostgreSQL connection string |
| `SQL_ECHO` | `false` | Enable SQLAlchemy SQL logging |
| `UPLOAD_DIR` | `uploads` | Directory for uploaded ZIP files |
| `WORKSPACE_DIR` | `workspaces` | Directory for extracted repositories |

### Frontend environment

The frontend reads `frontend/.env` for local overrides.

| Variable | Default | Description |
| --- | --- | --- |
| `VITE_API_BASE_URL` | `http://127.0.0.1:8000` | Backend base URL |

An example file is provided at `frontend/.env.example`.

## Local Data and Safety

- `backend/.env` is local-only and ignored by git.
- `backend/uploads/` and `backend/workspaces/` are generated locally and ignored by git.
- Frontend build output and `node_modules/` are ignored.
- Sample archives under `sample-projects/` are intentionally kept; other ZIP outputs are ignored.

This repository is designed to keep analysis artifacts local unless you explicitly export or commit them.

## Development Workflow

### Run the app locally

1. Start Postgres with Docker Compose.
2. Run the FastAPI backend.
3. Run the Vite frontend.
4. Create a project, upload a ZIP, and trigger analysis.

### Run validation scripts

From the repository root, after the backend environment is active:

```bash
python scripts/validate_route_extraction.py
python scripts/validate_route_flow_extraction.py
python scripts/validate_infrastructure_detection.py
python scripts/validate_component_detection.py
python scripts/validate_evidence_target_selection.py
python scripts/validate_route_api_explorer.py
python scripts/evaluate_backend_matrix.py
```

Use the validators selectively when you touch only one subsystem.

## Implementation Notes

- The canonical backend model is dataclass-based and dependency-light.
- Stable IDs are reused or derived deterministically from canonical attributes.
- Infrastructure detection is additive: it enriches scan data rather than introducing dedicated scan columns.
- Route request flow extraction is intentionally conservative and avoids weak data-access guesses.
- Summary and insights are currently on-demand views over the latest scan artifacts rather than separately persisted documents.

## Known Limitations

- Sparse repositories can still produce an empty graph, which means simulation may be unavailable.
- Some degraded fallback paths produce lower-confidence summaries than canonical-backed scans.
- Route extraction has been hardened for more frameworks, but it remains heuristic and should be validated against unfamiliar repo layouts.

## License

MIT License

Copyright (c) 2026 Chaos Twin

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.