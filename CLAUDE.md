# Continuity Editor — CLAUDE.md

## Project Overview

A backend service for detecting continuity errors in long-form fiction manuscripts.
Writers ingest chapters one at a time; the system builds a knowledge graph of characters,
places, timeline facts, and props. On each new ingestion it cross-checks for contradictions
and returns flagged conflicts with source evidence.

**Target users:** Novelists, screenwriters, game-lore teams.
**Core pain point:** "Character's eyes were blue in ch.3, now they're green in ch.12."

---

## Tech Stack

| Layer | Choice | Why |
|---|---|---|
| Knowledge graph | [cognee](https://github.com/topoteretes/cognee) Python API | Graph extraction + semantic search |
| Backend API | FastAPI | Async, typed, self-documenting |
| LLM | `openai/gpt-oss-120b:free` via OpenRouter | Free tier, OpenAI-compatible API |
| Vector store | LanceDB (cognee default) | Zero-config, embedded, local |
| Graph DB | NetworkX / cognee built-in | In-process for dev; swap to Neo4j for prod |
| Database | SQLite (dev) / PostgreSQL (prod) | Project/chapter metadata |
| Auth | API keys (header `X-API-Key`) | Simple enough for v1 |

### OpenRouter Integration

OpenRouter exposes an OpenAI-compatible endpoint. Configure cognee and direct LLM calls like:

```python
# Direct LLM calls (contradiction analysis, entity extraction)
from openai import AsyncOpenAI

llm = AsyncOpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=os.environ["OPENROUTER_API_KEY"],
)

response = await llm.chat.completions.create(
    model="openai/gpt-oss-120b:free",
    messages=[...],
)
```

```python
# cognee LLM config — point at OpenRouter
import cognee
cognee.config.set_llm_config({
    "provider": "openai",          # OpenAI-compatible
    "model": "openai/gpt-oss-120b:free",
    "api_key": os.environ["OPENROUTER_API_KEY"],
    "base_url": "https://openrouter.ai/api/v1",
})
```

---

## Directory Layout

```
continuity-editor/
├── CLAUDE.md
├── README.md
├── pyproject.toml
├── .env.example
│
├── app/
│   ├── main.py              # FastAPI app factory
│   ├── config.py            # Settings (pydantic-settings)
│   ├── dependencies.py      # Shared FastAPI deps (db session, llm client)
│   │
│   ├── routers/
│   │   ├── projects.py      # CRUD for manuscripts/projects
│   │   ├── chapters.py      # remember() — ingest a chapter
│   │   ├── recall.py        # recall() — contradiction check
│   │   ├── improve.py       # improve() — canonicalize aliases
│   │   └── graph.py         # GET /graph — inspect the knowledge graph
│   │
│   ├── services/
│   │   ├── cognee_service.py   # Thin wrapper around cognee API
│   │   ├── contradiction.py    # Core conflict-detection logic
│   │   ├── canonicalize.py     # Alias merging ("the bar" → "Murphy's Pub")
│   │   └── timeline.py         # Chronological ordering / gap detection
│   │
│   ├── models/
│   │   ├── db.py            # SQLAlchemy ORM models
│   │   └── schemas.py       # Pydantic request/response schemas
│   │
│   └── utils/
│       ├── text.py          # Chapter pre-processing, chunking
│       └── diff.py          # Human-readable diff helpers
│
├── tests/
│   ├── conftest.py
│   ├── test_remember.py
│   ├── test_recall.py
│   └── test_canonicalize.py
│
└── scripts/
    ├── demo_dracula.py      # Public-domain demo: inject Dracula contradiction
    └── seed_project.py      # Seed a test project
```

---

## Core Endpoints

### `POST /projects`
Create a new manuscript project. Returns `project_id`.

### `POST /projects/{project_id}/chapters`  ← `remember()`
Ingest a chapter. Pipeline:
1. Pre-process text (strip formatting, split scenes)
2. `cognee.add()` → chunk and embed
3. `cognee.cognify()` → entity/relationship extraction
4. Store extracted entities in project-scoped namespace
5. Immediately run recall check against existing graph
6. Return `{entities_extracted, contradictions_found[], chapter_id}`

### `POST /projects/{project_id}/recall`  ← `recall()`
On-demand contradiction check across all chapters or a specific chapter pair.
Accepts optional `focus` (character name, place, timeline range) to narrow scope.

### `POST /projects/{project_id}/improve`  ← `improve()`
Consolidation pass:
1. Find entities with high semantic similarity (cosine > 0.85)
2. Present candidate alias groups to the LLM for confirmation
3. Merge aliases, back-fill canonical name across all chapter records
4. Re-run contradiction check after merge

### `GET /projects/{project_id}/graph`
Returns the full entity graph as `{nodes[], edges[]}` — suitable for a frontend
force-directed visualization (D3.js / Cytoscape).

### `GET /projects/{project_id}/timeline`
Returns events sorted chronologically with confidence scores and gap warnings.

---

## Data Model (key tables)

```
Project:       id, title, author, created_at
Chapter:       id, project_id, number, title, raw_text, ingested_at, cognee_dataset_id
Entity:        id, project_id, canonical_name, type (CHARACTER|PLACE|PROP|EVENT|DATE),
               first_seen_chapter_id, attributes (JSON)
Alias:         id, entity_id, raw_text, chapter_id, confidence
Contradiction: id, project_id, chapter_a_id, chapter_b_id, entity_id,
               field, value_a, value_b, severity, resolved, created_at
```

---

## Contradiction Detection Logic

For each new chapter ingestion:
1. Extract entities via cognee + LLM structured extraction
2. For each entity, search existing graph: `cognee.search(entity_name)`
3. Compare attribute dicts (eye color, hair, age, location, alive/dead, etc.)
4. If conflict found:
   - Create `Contradiction` record
   - Classify severity: `HARD` (alive vs dead) / `SOFT` (description drift)
   - Return with quote evidence from both chapters

### Contradiction types detected
- **Physical attribute drift** — appearance changes without in-story explanation
- **Timeline violations** — character in two places at once, event before its cause
- **Dead man walking** — character confirmed dead reappears without resurrection
- **Prop continuity** — object given away in ch.2 used again in ch.7
- **Relationship contradictions** — characters who've never met reference shared history
- **Setting geography** — travel time impossible given established distances

---

## Cognee Integration Notes

Cognee v1.0 exposes a high-level API used directly by our endpoints:

```python
# remember: datasets= (list[str])
await cognee.remember(text, datasets=[f"project_{project_id}"])

# recall: datasets= (list[str]); returns Pydantic objects — use result.text, NOT result["text"]
results = await cognee.recall(query, datasets=[...], top_k=10, only_context=True)

# improve: dataset= (singular, first positional arg)
await cognee.improve(f"project_{project_id}")

# forget: all-keyword, dataset= (singular)
await cognee.forget(dataset=f"project_{project_id}")
```

- `datasets=[f"project_{project_id}"]` scopes all memory to a single manuscript
- `cognee.remember()` is run as a FastAPI `BackgroundTask` (graph construction is slow)
- `cognee.recall()` returns `list[RecallResponse]` Pydantic objects — access `result.text`, `result.source`, `result.score` (never `result["text"]`)
- `cognee.improve()` first positional arg is dataset name (not keyword)
- `cognee.forget()` uses `dataset=` keyword (singular), not `datasets=`

Legacy API (`add`, `cognify`, `search`, `prune`) is NOT used — v1.0 high-level API only.

---

## Suggested Additional Features (Priority Order)

### v1 (MVP)
- [ ] `remember()` / `recall()` / `improve()` endpoints
- [ ] Physical attribute + dead-man-walking contradiction detection
- [ ] REST API with OpenAPI docs at `/docs`

### v1.5
- [ ] **Relationship map** — visual graph of who knows whom and when they met
- [ ] **Chapter diff** — what changed in the world between two chapters
- [ ] **Timeline view** — all datable events on a sortable timeline
- [ ] **Contradiction severity scoring** — HARD vs SOFT, sortable list

### v2
- [ ] **Streaming ingestion** — WebSocket for real-time feedback while writer types
- [ ] **Manuscript export** — annotated PDF/DOCX with contradiction highlights inline
- [ ] **World-building ledger** — auto-generated series bible from ingested chapters
- [ ] **Multi-book support** — link projects into a series, share entities across books
- [ ] **Screenplay mode** — parse Fountain format, detect scene continuity

### v3 / Moonshots
- [ ] **Foreshadowing tracker** — detect Chekhov's guns that were never fired
- [ ] **Pacing analysis** — tension curve from scene classification
- [ ] **VS Code / Scrivener plugin** — inline flagging while writing

---

## Environment Variables

```
OPENROUTER_API_KEY=...         # Required — OpenRouter key for LLM calls
COGNEE_VECTOR_DB=lancedb       # lancedb | pgvector | weaviate
DATABASE_URL=sqlite:///./dev.db
LOG_LEVEL=INFO
```

---

## Running Locally

```bash
pip install -e ".[dev]"
cp .env.example .env           # add your OPENROUTER_API_KEY
uvicorn app.main:app --reload
# Docs at http://localhost:8000/docs
```

## Demo Script

```bash
python scripts/demo_dracula.py
# Feeds Dracula chapters 1-5, injects an eye-color contradiction in ch.6, shows detection
```

---

## Key Design Decisions

1. **OpenRouter free tier** — `openai/gpt-oss-120b:free` via OpenAI-compatible endpoint; swap model by changing one env var
2. **Project-namespaced cognee datasets** — prevents cross-project contamination, enables per-project prune/reset
3. **Dual extraction pipeline** — cognee's built-in NER + a structured LLM pass with a fiction-specific schema (catches "the old man" === "Professor Van Helsing" which generic NER misses)
4. **Alias-first entity model** — never assume two mentions are the same entity; build confidence-scored alias groups, let `improve()` confirm merges
5. **Severity tiers** — HARD contradictions are flagged prominently; SOFT are warnings; writer can suppress per-entity
6. **Evidence quotes** — every contradiction links to the exact sentence from each chapter so the writer sees why it was flagged
