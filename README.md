# Chaos Twin

**Codebase intelligence for developers joining an unfamiliar project.**

Upload any codebase as a ZIP. Chaos Twin automatically analyzes it and gives you a structured mental model — architecture, features, API routes, request flows, and the relationships between everything. No configuration. No annotations. Works on any language and framework.

---

## The Problem

A developer joins a new company. They get access to a 200-file Express + React Native monorepo they've never seen. The senior dev says "get familiar with the codebase." Three days later, they still don't know where authentication lives, which files are safe to touch, or how a booking request actually flows through the system.

Chaos Twin solves this in minutes.

---

## What It Does

| Page | What you get |
|---|---|
| **Dashboard** | Tech stack, entry points, external services, auth detection, complexity score |
| **Understanding** | 6-section AI-generated doc: project story, system map, data journey, key decisions, gotchas, glossary |
| **Feature Map** | Features as a constellation — connection lines show coupling, shared infrastructure layer, health indicators, related context per feature |
| **API Explorer** | Every route grouped by feature — inline trace, request schema tree, example response JSON, search |
| **Sequence Diagrams** | Per-route swimlane diagrams showing exact participants, phases, and call flow |

---

## How It Works

Every upload triggers a fully automatic pipeline:

```
ZIP upload
  ↓
Scanner        — enry language detection, route extraction, dependency parsing
  ↓
File Prioritizer  — GPT-4o-mini selects the 150 most important files from large repos
  ↓
File Classifier   — GPT-4o-mini classifies every file by purpose (route, controller, model, service, etc.)
  ↓
Dependency Graph  — tree-sitter + regex builds import relationships across all files
  ↓
File Summarizer   — GPT-4o-mini summarizes every file in plain English (parallel batches)
  ↓
Embedding Generator — text-embedding-3-small generates vectors, stored in pgvector
  ↓
Route Extractor   — 2-pass: deterministic detection for Next.js, GPT for Express/FastAPI/Django/Rails/Go/etc.
  ↓
Deep Route Analyzer — Python AST for .py files, GPT-4o fallback for everything else
  ↓
Phrase Generator  — enriches route phases with plain English descriptions
  ↓
Understanding Generator — GPT-4o produces 6-section documentation from the most important files
```

No hardcoded language rules. Enry detects the language. Tree-sitter parses imports. GPT handles the rest. It works on Python, JavaScript, TypeScript, Java, Go, Ruby, C#, and more.

---

## Feature Map — Feature Constellation

The Feature Map goes beyond a list of features. It shows how they relate:

- **Connection lines** between features that share files. Thicker line = more shared files. Hover to see coupling level (🔴 tightly coupled / 🟡 moderate / 🟢 loose) and which files are shared.
- **Shared Infrastructure layer** — files used in 3+ features surface as a foundation band. These are your cross-cutting concerns: database clients, auth middleware, logging.
- **Health indicators** on every card — file count, test coverage, external dependency count, risk level.
- **"Also used by" tags** on every file in the focus view — click to jump to the other feature.
- **Related context** button — shows which features are coupled, how many files they share, and the riskiest file in the cluster.

---

## API Explorer — API Command Center

- **Inline trace** — click ▶ Trace on any route to see a dark terminal-style breakdown of phases and steps, right inside the explorer. No page navigation.
- **Search** — filter routes by path, method, or description keyword.
- Route complexity indicators, DB/external flags, parameter tables, response fields.
- "Full page →" link to the dedicated Sequence Diagram view for deep dives.

---

## Tech Stack

**Backend**
- FastAPI (Python 3.11)
- PostgreSQL + pgvector (semantic search, embeddings)
- Docker Compose

**Frontend**
- React 19 + TypeScript + Vite
- React Flow (`@xyflow/react`) — system map
- Mermaid.js — sequence diagrams

**AI**
- GPT-4o — deep reasoning, understanding generation, depth tiers
- GPT-4o-mini — classification, summarization, route extraction, phrase generation
- `text-embedding-3-small` — file embeddings for semantic search

**Analysis**
- `enry-python` — language detection
- `tree-sitter` + `tree-sitter-languages` — import graph construction
- Python `ast` module — deep AST analysis for Python routes

---

## Running Locally

**Prerequisites:** Docker, Docker Compose, an OpenAI API key.

```bash
git clone https://github.com/SyamSai23/CHAOS-TWIN
cd CHAOS-TWIN
```

Create a `.env` file in the project root:

```env
OPENAI_API_KEY=your_key_here
DATABASE_URL=postgresql://postgres:postgres@db:5432/chaostwin
```

Start everything:

```bash
docker compose up --build
```

- Frontend: http://localhost:5173
- Backend API: http://localhost:8000
- API docs: http://localhost:8000/docs

Upload any project as a ZIP on the landing page. The full pipeline runs automatically in the background — indexing progress is shown live on the dashboard.

---

## Project Structure

```
CHAOS-TWIN/
├── app/
│   ├── main.py                     # FastAPI app, router registration
│   ├── routers/
│   │   └── projects.py             # All /projects/* endpoints
│   └── services/
│       ├── scanner_v3.py           # ZIP scanner, language + route detection
│       ├── file_indexer.py         # Full indexing pipeline
│       ├── ast_analyzer.py         # Deep route analysis (Python AST + GPT fallback)
│       ├── understanding_generator.py  # 6-section documentation
│       ├── phrase_generator.py     # Route phase enrichment
│       └── sequence_generator.py  # Per-route sequence diagrams
├── frontend/
│   └── src/
│       └── pages/
│           ├── TerraLandingView.tsx
│           ├── ProjectDashboard.tsx
│           ├── UnderstandingPage.tsx
│           ├── FeatureMapPage.tsx
│           ├── ApiExplorerPage.tsx
│           └── SequenceDiagramPage.tsx
└── docker-compose.yml
```

---

## Design Principles

- **Zero hardcoding** — no language-specific rules, no framework assumptions. Everything is detected or inferred.
- **Production quality** — not a demo. Handles real codebases up to 500 files, monorepos, multi-component projects.
- **Junior-first** — every insight is written in plain English. Technical jargon is explained. The goal is understanding, not just documentation.
- **Persistent** — analysis results are stored in PostgreSQL. Re-opening a project is instant. Nothing is regenerated unless you rescan.

---

## What's Next

- **Grounded AI Chat** — ask questions about the codebase, answers grounded on actual file embeddings (infrastructure already built, pgvector embeddings stored)
- **Blast Radius Analysis** — "if I change this file, what else breaks?" using the dependency graph
- **Code Peek** — click any step in a sequence diagram to see the actual lines of code
- **Convention Detector** — infer implicit coding patterns across files, generate a "How We Do Things Here" doc
- **GitHub integration** — connect a repo directly instead of uploading a ZIP
