# Chaos Twin

**Understand your codebase. Simulate failures. Ship with confidence.**

Chaos Twin is a local-first developer tool for codebase intelligence and failure impact analysis. Upload your codebase, analyze its architecture, and simulate what breaks when components fail.

## Features

### 📊 **Codebase Analysis**
- Upload ZIP archives of your projects
- Automatic language, framework, and project type detection
- Key file and entry point identification
- Component classification (frontend, backend, services, etc.)

### 🗺️ **Architecture Visualization**
- Auto-generate dependency graphs from scan data
- Interactive graph with React Flow
- Color-coded nodes by component type
- Clear visualization of connections and dependencies

### 💥 **Chaos Simulation**
- Select any component and simulate its failure
- Edge-type-aware impact propagation (uses, runs_on, contains, connects_to)
- Severity assessment (Low/Medium/High Risk)
- Plain-English blast radius summary
- See exactly which components are affected and how many hops away

## Tech Stack

**Backend:**
- FastAPI + SQLAlchemy + PostgreSQL
- Python 3.9+
- Heuristic-based scanning and graph generation

**Frontend:**
- React 19 + TypeScript
- Vite 7
- @xyflow/react for graph visualization
- Dark theme UI

**Infrastructure:**
- PostgreSQL 16 (Docker)
- Local file storage for uploads and workspaces

## Quick Start

1. **Start the database:** `docker compose up -d db`
2. **Run the backend:** `cd backend && source .venv/bin/activate && uvicorn app.main:app --port 8000`
3. **Run the frontend:** `cd frontend && npm run dev`
4. **Open the app:** http://localhost:5173

## Setup Instructions

### Project Structure
```
chaos-twin/
├── backend/          # FastAPI application
│   ├── app/
│   │   ├── models/      # SQLAlchemy models
│   │   ├── routers/     # API endpoints
│   │   ├── services/    # Business logic (scanner, graph builder, simulator)
│   │   └── schemas/     # Pydantic schemas
│   ├── uploads/         # Uploaded ZIP files (auto-created)
│   └── workspaces/      # Extracted codebases (auto-created)
├── frontend/         # React application
├── docker-compose.yml
└── README.md
```

### 1. Start PostgreSQL

From the repository root:

```bash
docker compose up -d db
```

The database will be available at `localhost:5432` with the default credentials.

### 2. Run the Backend

From the repository root:

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # Optional: Edit if you need custom settings
uvicorn app.main:app --reload --port 8000
```

**Health checks:**
- API: http://127.0.0.1:8000/health
- Database: http://127.0.0.1:8000/health/db
- API docs: http://127.0.0.1:8000/docs

### 3. Run the Frontend

From the repository root:

```bash
cd frontend
npm install
cp .env.example .env  # Optional: Edit if backend is not on default port
npm run dev
```

**Application:**
- Frontend: http://localhost:5173
- The app will connect to the backend at http://127.0.0.1:8000

## Configuration

### Backend Environment Variables (`backend/.env`)

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `postgresql+psycopg://postgres:postgres@localhost:5432/chaostwin` | PostgreSQL connection string |
| `SQL_ECHO` | `false` | Enable SQLAlchemy query logging |
| `UPLOAD_DIR` | `uploads` | Directory for uploaded ZIP files |
| `WORKSPACE_DIR` | `workspaces` | Directory for extracted codebases |

### Frontend Environment Variables (`frontend/.env`)

| Variable | Default | Description |
|----------|---------|-------------|
| `VITE_API_BASE_URL` | `http://127.0.0.1:8000` | Backend API URL |

## How It Works

1. **Create a project** — Define a logical project container
2. **Upload a codebase** — ZIP your source code and upload it
3. **Run analysis** — Automatic detection of languages, frameworks, components, and entry points
4. **Build the graph** — Generate a visual architecture map with dependencies
5. **Simulate failures** — Pick any component and see what breaks when it fails

The simulation engine uses edge-type-aware traversal:
- `runs_on` edges propagate failures from runtimes to apps
- `uses` edges propagate from dependencies to consumers
- `contains` edges propagate bidirectionally between parents and children
- `connects_to` edges propagate in both directions for network links

## Development Notes

- **Local-first:** All data stays on your machine. No cloud, no telemetry.
- **Heuristic-based:** Analysis uses pattern matching and file structure detection, not deep AST parsing.
- **Beginner-friendly:** Simple, readable code with clear separation of concerns.
- **Incremental:** Features built step-by-step with minimal complexity.

### Database Schema

- `projects` — Project metadata
- `uploads` — Uploaded ZIP files
- `scans` — Scan results with detected languages, frameworks, components
- `graph_nodes` — Architecture graph nodes (components, runtimes, tools)
- `graph_edges` — Connections between nodes (uses, runs_on, contains, connects_to)
- `simulation_runs` — Failure simulation results with impact analysis

### Key Services

- **Scanner** (`app/services/scanner.py`) — Analyzes uploaded codebases
- **Graph Builder** (`app/services/graph_builder.py`) — Generates architecture graphs from scan data
- **Simulator** (`app/services/simulator.py`) — Runs failure simulations with BFS traversal

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