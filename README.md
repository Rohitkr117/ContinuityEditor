# Continuity Editor

A backend service for detecting continuity errors in long-form fiction manuscripts.
Writers ingest chapters one at a time; the system builds a knowledge graph of characters,
places, timeline facts, and props. On each new ingestion it cross-checks for contradictions
and returns flagged conflicts with source evidence.

**Target users:** Novelists, screenwriters, game-lore teams.  
**Core pain point:** *"Character's eyes were blue in ch.3, now they're green in ch.12."*

---

## Tech Stack

| Layer | Choice |
|---|---|
| Knowledge graph | [cognee](https://github.com/topoteretes/cognee) v1.0 |
| Backend API | FastAPI |
| LLM | `openai/gpt-oss-120b:free` via OpenRouter |
| Vector store | LanceDB (cognee default) |
| Database | SQLite (dev) / PostgreSQL (prod) |
| Auth | API keys via `X-API-Key` header (planned v1.1) |

---

## Quick Start

```bash
# 1. Install
pip install -e ".[dev]"

# 2. Configure
cp .env.example .env
# Edit .env — add your OPENROUTER_API_KEY

# 3. Run
uvicorn app.main:app --reload

# 4. Open docs
# http://localhost:8000/docs
```

---

## Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `OPENROUTER_API_KEY` | ✅ | — | OpenRouter key for all LLM calls |
| `DATABASE_URL` | | `sqlite+aiosqlite:///./dev.db` | DB connection string |
| `COGNEE_VECTOR_DB` | | `lancedb` | Vector store backend |
| `LOG_LEVEL` | | `INFO` | Logging level |

---

## API Endpoints

### Projects

| Method | Path | Description |
|---|---|---|
| `POST` | `/projects` | Create a new manuscript project |
| `GET` | `/projects` | List all projects |
| `GET` | `/projects/{id}` | Get a project |
| `DELETE` | `/projects/{id}` | Delete project + all its graph memory |

### Chapters — `remember()`

| Method | Path | Description |
|---|---|---|
| `POST` | `/projects/{id}/chapters` | Ingest a chapter; returns entities + contradictions |
| `GET` | `/projects/{id}/chapters` | List all chapters |

**Ingest pipeline:**
1. Persist `Chapter` row
2. `cognee.remember()` in background — builds knowledge graph
3. LLM structured entity extraction (synchronous)
4. Upsert entities; diff attributes against existing graph
5. Return `{ chapter_id, entities_extracted[], contradictions_found[] }`

### Recall — `recall()`

| Method | Path | Description |
|---|---|---|
| `POST` | `/projects/{id}/recall` | On-demand contradiction check |
| `PATCH` | `/projects/{id}/recall/{cid}/resolve` | Mark a contradiction as resolved |

Request body:
```json
{
  "focus": "Jonathan Harker",   // optional — narrow to one entity
  "chapter_ids": [1, 3]         // optional — limit to specific chapters
}
```

### Improve — `improve()`

| Method | Path | Description |
|---|---|---|
| `POST` | `/projects/{id}/improve` | Canonicalize aliases + enrich graph |

Finds entities with similar names (`"the pub"` / `"Murphy's Pub"`), confirms merges
via LLM, re-points all aliases and contradiction records, and returns a summary.

### Graph & Timeline

| Method | Path | Description |
|---|---|---|
| `GET` | `/projects/{id}/graph` | Entity graph `{ nodes[], edges[] }` |
| `GET` | `/projects/{id}/timeline` | Chronological events with gap warnings |
| `GET` | `/viewer` | Interactive force-directed graph viewer |

---

## Contradiction Types Detected

| Type | Example |
|---|---|
| Physical attribute drift | Eye color changes without explanation |
| Dead man walking | Character confirmed dead reappears alive |
| Prop continuity | Object given away in ch.2 reappears in ch.7 |
| Timeline violations | Character in two places at once |
| Relationship contradictions | Characters who've never met reference shared history |

Contradictions are classified as **HARD** (logically impossible) or **SOFT** (possible drift).
Every contradiction includes `quote_a` / `quote_b` — the exact sentence from each chapter
that triggered the flag.

---

## Google Docs Chrome Extension

Continuity Editor includes a Chrome Extension that acts as a client for writers directly within Google Docs. It allows you to analyze newly written text against the previously synced knowledge graph of your manuscript.

### Architecture
- **extension/manifest.json**: Manifest V3 configuration.
- **extension/background.js**: Service worker handling tab events and side panel toggling.
- **extension/content.js**: Injected into Google Docs to extract document IDs and titles.
- **extension/lib/**: Reusable JS logic, including OAuth flow, Docs JSON parsing, and state derivation.
- **extension/popup/** & **extension/sidebar/**: UI components built with HTML, CSS, and Vanilla JS.

### Extension Setup
The extension reads your Google Docs natively via the browser's own export feature, meaning **no OAuth or Google Cloud configuration is required!** All you need to do is load the extension.

### Loading the Extension in Chrome
1. Open Chrome and go to `chrome://extensions/`.
2. Enable **Developer Mode** in the top right.
3. Click **Load unpacked** and select the `continuity-editor/extension/` directory.

### Backend Setup
Ensure the backend is running locally or deployed.
1. Start the backend: `uvicorn app.main:app --reload`
2. Open the extension popup, enter your backend URL (e.g., `http://localhost:8000`), and click **Save**.

### Usage
- **Map to Project**: Open a Google Doc. In the extension popup, select an existing ContinuityEditor project or create a new one.
- **Sync Document**: Sends your current manuscript content to the backend. The text is saved into the vector store and the knowledge graph. *Use this when you are happy with the content and want it established as permanent context.*
- **Check Continuity**: Compares the latest unsynced changes in your document against the established knowledge graph. Any found contradictions will be displayed in the **Continuity Panel** (sidebar). *This does NOT permanently save the new content to memory.*

### Troubleshooting
- **Backend Offline**: Ensure FastAPI is running and CORS is configured (handled automatically by `app/main.py`).
- **OAuth Errors**: Ensure your Chrome browser profile matches the Google Cloud project test users if the OAuth app is not published.

---

## Demo Scripts

```bash
# Inject a Dracula eye-color contradiction and watch it get detected
python scripts/demo_dracula.py

# Seed a quick test project with a known contradiction
python scripts/seed_project.py
```

---

## Running Tests

```bash
pytest tests/ -v
```

---

## Project Structure

```
continuity-editor/
├── CLAUDE.md                  # Full project spec and design decisions
├── IMPLEMENTATION_STATUS.md   # Current implementation status
├── app/
│   ├── main.py                # FastAPI app factory
│   ├── config.py              # Settings (pydantic-settings)
│   ├── dependencies.py        # Shared FastAPI deps
│   ├── routers/
│   │   ├── projects.py        # CRUD for manuscripts/projects
│   │   ├── chapters.py        # remember() — ingest a chapter
│   │   ├── recall.py          # recall() — contradiction check
│   │   ├── improve.py         # improve() — canonicalize aliases
│   │   └── graph.py           # GET /graph and GET /timeline
│   ├── services/
│   │   ├── cognee_service.py  # Thin wrapper around cognee API
│   │   ├── contradiction.py   # Core conflict-detection logic
│   │   ├── canonicalize.py    # Alias merging
│   │   └── timeline.py        # Chronological ordering / gap detection
│   ├── models/
│   │   ├── db.py              # SQLAlchemy ORM models
│   │   └── schemas.py         # Pydantic request/response schemas
│   └── utils/
│       ├── text.py            # Chapter pre-processing, chunking
│       └── diff.py            # Human-readable diff helpers
├── tests/
│   ├── conftest.py
│   ├── test_remember.py
│   ├── test_recall.py
│   └── test_canonicalize.py
└── scripts/
    ├── demo_dracula.py        # Public-domain demo
    └── seed_project.py        # Seed a test project
```
