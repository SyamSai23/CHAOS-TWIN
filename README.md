# Chaos Twin

Chaos Twin is a codebase intelligence tool for junior developers.

You upload a ZIP of a repository, Chaos Twin scans it locally, builds a structural model, indexes important files for semantic search, generates high-level project documentation, and exposes the result through a React frontend with dashboard, architecture, API explorer, understanding, and AI chat workflows.

## What’s New

- Terra-style frontend with project landing, dashboard, understanding pages, and a floating AI Architect chat bubble.
- Background indexing pipeline that classifies files, builds a dependency graph, summarizes important files, and stores pgvector embeddings.
- Semantic project search endpoint powered by `text-embedding-3-small`.
- AI-generated project understanding with:
  - `project_story`
  - `system_map`
  - `data_journey`
  - `key_decisions`
  - `gotchas`
  - `glossary`
- Indexing status tracking and failure handling.
- Understanding auto-recovery for stale generations.
- Workspaces moved outside the backend directory to avoid dev-server reload loops.
- Hard indexing cap of 500 source files per project to avoid runaway processing.

## Core Capabilities

### 1. Scan and detect

Chaos Twin scans uploaded codebases and extracts:

- languages
- frameworks
- entry points
- components
- routes
- infrastructure signals
- imports and execution-flow evidence

This scan is deterministic and serves as the foundation for every downstream feature.

### 2. Build a code intelligence index

After a scan completes, Chaos Twin starts a background indexing pipeline in `backend/app/services/file_indexer.py` that:

- filters source files using `enry`
- skips vendor, generated, binary, and documentation files
- caps oversized files to a representative first/last-line window
- classifies files with `gpt-4o-mini`
- builds a dependency graph using `tree-sitter` with regex fallback
- calculates importance scores
- summarizes important files for junior developers
- generates embeddings with `text-embedding-3-small`
- stores results in PostgreSQL + pgvector

The indexing pipeline also powers later understanding generation.

### 3. Generate project understanding

Once indexing finishes, Chaos Twin generates a structured understanding model in `backend/app/services/understanding_generator.py`.

This is the human-friendly layer of the product:

- a plain-English project story
- a system map of major components
- a route-aware data journey
- architectural decisions and tradeoffs
- project-specific gotchas
- a domain glossary

If understanding generation gets stuck in `generating`, the backend can detect stale jobs and restart them.

### 4. Search semantically

Chaos Twin supports project-level semantic search:

- query: “how does authentication work?”
- retrieve matching files by vector similarity
- boost results using importance score
- show related dependency graph context for top hits

Endpoint:

- `GET /projects/{project_id}/search?q=...&limit=8`

### 5. Explore through the UI

The frontend includes:

- Terra landing page
- project dashboard
- understanding page
- architecture graph
- API explorer
- sequence diagrams
- deep dive view
- simulation view
- context-aware AI Architect chat

## Tech Stack

### Backend

- FastAPI
- SQLAlchemy
- PostgreSQL
- pgvector
- OpenAI API
- `tree-sitter`
- `tree-sitter-languages`
- `enry-python`

### Frontend

- React 19
- TypeScript
- Vite 7
- `@xyflow/react`
- `react-markdown`
- `lucide-react`

### Local infrastructure

- Docker Compose
- local ZIP storage
- local extracted workspaces

## Repository Layout

```text
chaos-twin/
├── backend/
│   ├── alembic/
│   ├── app/
│   │   ├── config.py
│   │   ├── db/
│   │   ├── domain/system_model/
│   │   ├── models/
│   │   ├── routers/
│   │   ├── schemas/
│   │   └── services/
│   ├── requirements.txt
│   └── .env.example
├── frontend/
│   ├── src/
│   │   ├── app/
│   │   ├── components/
│   │   └── views/
│   ├── package.json
│   └── index.html
├── sample-projects/
├── scripts/
├── docker-compose.yml
├── workspaces/
└── README.md
```

## Data Model Added for Indexing

Chaos Twin creates and uses these tables on startup:

- `file_index`
- `dependency_graph`
- `indexing_status`

It also enables:

- `pgcrypto`
- `vector`

The `file_index` table stores:

- file path
- file type
- domain area
- summary
- exports
- key concepts
- full content snapshot
- line count
- importance score
- embedding

## Quick Start

### 1. Start PostgreSQL with pgvector

From the repository root:

```bash
docker compose up -d db
```

This uses:

- `pgvector/pgvector:pg16`

### 2. Start the backend

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Important runtime note:

- extracted workspaces now live in `../workspaces` relative to `backend/`
- this prevents uvicorn/watchfiles reload loops during ZIP extraction

Useful backend URLs:

- API docs: `http://127.0.0.1:8000/docs`
- health: `http://127.0.0.1:8000/health`
- db health: `http://127.0.0.1:8000/health/db`

### 3. Start the frontend

```bash
cd frontend
npm install
npm run dev
```

Frontend URL:

- `http://localhost:5173`

## Environment Variables

Backend configuration lives in `backend/.env`.

An example file is included at [backend/.env.example](/Users/syamsaichippala/Projects/chaos-twin/backend/.env.example).

| Variable | Default | Description |
| --- | --- | --- |
| `DATABASE_URL` | `postgresql+psycopg://postgres:postgres@localhost:5432/chaostwin` | PostgreSQL connection string |
| `SQL_ECHO` | `false` | Enable SQLAlchemy SQL logging |
| `UPLOAD_DIR` | `../uploads` | ZIP archive storage |
| `WORKSPACE_DIR` | `../workspaces` | Extracted repository workspace storage |
| `OPENAI_API_KEY` | empty | Required for semantic search, indexing, and AI features |
| `OPENAI_MODEL` | `gpt-4o-mini` | Default chat/completion model |
| `FRONTEND_ORIGINS` | unset | Allowed frontend origins |
| `CORS_ALLOW_CREDENTIALS` | `true` | CORS credentials toggle |

Frontend configuration:

| Variable | Default | Description |
| --- | --- | --- |
| `VITE_API_BASE_URL` | `http://127.0.0.1:8000` | Backend base URL |

## Current Backend Routes

### Project and health

- `GET /health`
- `GET /health/db`
- `GET /projects`
- `POST /projects`
- `DELETE /projects/{project_id}`

### Upload, scan, and indexing

- `POST /projects/{project_id}/upload`
- `POST /projects/{project_id}/scan`
- `GET /projects/{project_id}/scan`
- `GET /projects/{project_id}/indexing-status`
- `GET /projects/{project_id}/search`

### Understanding

- `GET /projects/{project_id}/understanding`
- `POST /projects/{project_id}/understanding/generate`
- `POST /projects/{project_id}/understanding/chat`

### Additional exploration routes

- dashboard
- graph generation
- simulation
- deep dive
- routes
- route analysis
- sequence diagrams
- code peek
- system summary
- insights

## Frontend Product Flow

### New project flow

1. Create or upload a project from the Terra landing page.
2. Upload a ZIP archive.
3. Run scan.
4. Indexing starts in the background.
5. Understanding generation starts after indexing completes.
6. Dashboard and understanding views update as processing finishes.

### State persistence

The frontend persists:

- selected project id
- active view

This lets the app recover state across reloads.

### Duplicate project handling

If a user uploads a ZIP with the same project name twice, the UI can prompt to:

- replace the old project
- create a new one

## Important Limits and Safeguards

### Indexing hard cap

Chaos Twin currently supports up to 500 source files per project for indexing.

If more than 500 source files are extracted:

- indexing aborts early
- status is marked `failed`
- a clear error message is stored in `indexing_status`
- the frontend dashboard surfaces that failure

### OpenAI concurrency limit

To avoid OpenAI TPM spikes:

- file classification and summarization batches are parallelized
- concurrency is capped with a semaphore

### Local artifact safety

Ignored by git:

- `.env`
- local uploads
- extracted workspaces
- build output
- local node/python environments

Only example env files such as `.env.example` are tracked.

## Development Notes

### Why workspaces moved

Extracted ZIPs are stored outside the backend tree:

- old pattern: `backend/workspaces/`
- current pattern: `../workspaces/`

This prevents reload-triggered background task interruption in local dev.

### Why indexing happens before understanding

Understanding now depends on richer file context:

- file summaries
- dependency centrality
- semantic selection of important files

So the sequence is:

1. scan
2. index
3. understanding

### Search quality strategy

Chaos Twin does not hardcode language-specific business rules for indexing.

Instead it combines:

- `enry` for source filtering
- `tree-sitter` for import parsing where possible
- regex fallback for unsupported languages
- GPT classification and summarization based on actual code content

## Local Safety

- `backend/.env` is local-only and ignored by git.
- `workspaces/` is ignored by git.
- uploaded ZIPs are stored locally.
- build artifacts are ignored.

This repository is designed for local-first analysis unless you explicitly deploy it elsewhere.

## Known Limitations

- semantic search and AI features require `OPENAI_API_KEY`
- indexing is capped at 500 source files
- some route extraction and architecture inference is still heuristic
- cloud deployments with ephemeral disks will not persist local uploads/workspaces unless extra storage is added

## License

MIT License

Copyright (c) 2026 Chaos Twin
