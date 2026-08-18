# Continuity Editor

> **Intelligent continuity conflict detection for long-form fiction, screenplays, and world-building.**

Continuity Editor is an AI-powered backend service and writing companion that helps authors, screenwriters, and narrative designers maintain strict world-building and character continuity across massive manuscripts (100k+ words). By pairing structured knowledge graphs with an LLM-based contradiction judge, it catches inconsistencies—such as physical attribute drift, timeline paradoxes, and dead-man-walking errors—before manuscripts go to print.

---

## 1. The Problem

Writing long-form fiction is a complex state-management challenge. Over the course of dozens of chapters and hundreds of pages:
- **Massive Entity Drift**: Minor characters, props, locations, and rules change without the writer realizing (*"Lucy's eyes were blue in Chapter 2, but hazel in Chapter 14"*).
- **Timeline & State Violations**: Characters travel impossible distances, use items they previously gave away, or reference events they weren't present for.
- **Dead Man Walking**: Characters killed off in early acts inadvertently reappear in background crowd scenes later.
- **Cognitive Overload**: Human working memory cannot reliably index thousands of interconnected micro-facts across a 120,000-word manuscript. Traditional manual "series bibles" quickly fall out of sync with drafts.

---

## 2. Why Ordinary RAG Isn't Enough

Standard Retrieval-Augmented Generation (RAG) uses vector embeddings to calculate semantic similarity over raw text chunks. While effective for answering localized search questions, **naive RAG fails catastrophically at continuity verification**:

| Dimension | Standard Vector RAG | Continuity Editor (Graph Memory) |
|---|---|---|
| **Attribute State Tracking** | Treats text as static bags of words. Cannot track state mutations or chronological transitions over time. | Builds a structured world model tracking exact entity properties (`eye_color: blue` → `eye_color: green`) per chapter. |
| **Alias Resolution** | `"The Professor"`, `"Van Helsing"`, and `"Abraham"` may map to distant embeddings depending on context. | Explicit alias consolidation (`improve()`) clusters and links aliases to a single canonical entity. |
| **Implicit Contradictions** | Semantic search only finds passages that *sound similar*, not passages that are *logically incompatible*. | Compares structured entity state diffs and uses a dedicated LLM judge to evaluate logical mutual exclusivity. |
| **Absence vs. Negation** | If a character isn't mentioned in a chapter, vector search often hallucinates that their status changed or ceased to exist. | Triple-layer anti-hallucination filtering ensures silence/omission is never flagged as a contradiction. |

---

## 3. Architecture Overview

```
 ┌─────────────────────────────────────────────────────────────┐
 │                      Writers' Clients                       │
 │   Google Docs Chrome Extension   │   Interactive Graph UI   │
 └──────────────────────────────┬──────────────────────────────┘
                                │ HTTP / REST
 ┌──────────────────────────────▼──────────────────────────────┐
 │                    FastAPI Application                      │
 ├──────────────────────────────┬──────────────────────────────┤
 │  /projects    /chapters      │  /recall         /improve    │
 └──────────────┬───────────────┴──────────────┬───────────────┘
                │ Ingestion                    │ Query & Merge
 ┌──────────────▼───────────────┐ ┌────────────▼───────────────┐
 │   Dual Extraction Pipeline   │ │   Contradiction Engine     │
 │ 1. Fiction-Tuned LLM Schema  │ │ 1. Attribute State Diff    │
 │ 2. Cognee Semantic NER       │ │ 2. Null/Omission Filter    │
 └──────────────┬───────────────┘ │ 3. LLM Contradiction Judge │
                │                 └────────────┬───────────────┘
 ┌──────────────▼──────────────────────────────▼───────────────┐
 │                     Persistence Layer                       │
 │  • LanceDB: Vector embeddings & semantic recall             │
 │  • NetworkX / Cognee Graph: Entity & relationship graph     │
 │  • SQLite / PostgreSQL: Projects, chapters, contradictions  │
 └─────────────────────────────────────────────────────────────┘
```

The system operates via two parallel, complementary paths:
1. **Synchronous Fast Path**: Runs fast structured entity extraction and cross-checks attributes against existing database records for immediate author feedback.
2. **Asynchronous Memory Path**: Dispatches `cognee.remember()` into background tasks to incrementally chunk, embed, and expand the long-term semantic knowledge graph without blocking the writer.

---

## 4. Knowledge Graph & Memory Layer

Continuity Editor uses **[cognee](https://github.com/topoteretes/cognee)** v1.0 as its cognitive memory engine, backed by LanceDB and relational metadata storage:

- **Project-Scoped Memory Graphs**: Memory is strictly isolated by manuscript namespace (`datasets=[f"project_{project_id}"]`), preventing cross-story hallucination and enabling per-project resets.
- **Structured Entity Ontology**: Classifies story elements into five core types:
  - `CHARACTER`: Physical appearance, status (`ALIVE`/`DEAD`), relationships, location history.
  - `PLACE`: Geography, atmospheric traits, connected locations.
  - `PROP`: Ownership, physical state, location.
  - `EVENT`: Temporal ordering, participants, outcomes.
  - `DATE`: Explicit and relative timeline markers.
- **Graph Enrichment & Canonicalization (`/improve`)**:
  - Scans entity clusters for high semantic similarity.
  - LLM confirms whether disparate names refer to the same individual (e.g., `"the count"` ↔ `"Count Dracula"`).
  - Automatically merges nodes, updates alias mappings, and cleans historical contradiction records.

---

## 5. Contradiction Detection Engine

When a chapter is ingested or checked via `/recall`:

1. **Extraction**: The dual pipeline extracts all entity mentions and their current attributes with strict schema enforcement.
2. **Differential Comparison**: Newly extracted attributes are diffed against the cumulative state in the database and knowledge graph.
3. **Anti-Hallucination Null Filter**: Strips uninformative entries (`"unknown"`, `"n/a"`, `"none"`, omissions) to prevent false positives when an author simply omits a detail.
4. **LLM Contradiction Judge**: Evaluates every genuine attribute conflict with full chapter context, classifying by severity:
   - **`HARD`**: Logically impossible (e.g., dead character acting without explanation, physical impossibility).
   - **`SOFT`**: Drift or potential continuity slips (e.g., eye/hair color change, wardrobe inconsistency).

---

## 6. Evidence & Source Citations

No contradiction is flagged without verifiable grounding. Every reported issue includes exact sentence citations from both the established text and the new chapter:

```json
{
  "field": "physical.eye_color",
  "value_a": "piercing blue",
  "value_b": "deep emerald green",
  "severity": "SOFT",
  "quote_a": "Jonathan looked into the Count's piercing blue eyes as the carriage halted.",
  "quote_b": "His deep emerald green eyes flashed with sudden fury in the candlelight.",
  "explanation": "Jonathan Harker's eye color was established as piercing blue in Chapter 1, but is described as deep emerald green in Chapter 4."
}
```

This eliminates guesswork and lets authors instantly navigate to the exact offending lines in their manuscript.

---

## 7. Example: Input → Detected Contradiction

### Manuscript Inputs

**Chapter 1 Text (`POST /projects/1/chapters`):**
> *Jonathan Harker adjusted his spectacles and stepped into the carriage. He met Count Dracula at the castle threshold, noting the host's piercing blue eyes and tall, imposing stature.*

**Chapter 4 Text (`POST /projects/1/chapters`):**
> *The Count stood before the great hearth. His deep emerald green eyes flashed with sudden fury as he watched Jonathan reach for the forbidden journal on the mantle.*

### Ingestion Response Output

```json
{
  "chapter_id": 4,
  "chapter_number": 4,
  "entities_extracted": [
    {
      "name": "Count Dracula",
      "type": "CHARACTER",
      "attributes": {
        "physical": {
          "eye_color": "deep emerald green",
          "stature": "tall, imposing"
        },
        "status": "ALIVE"
      }
    },
    {
      "name": "Jonathan Harker",
      "type": "CHARACTER",
      "attributes": {
        "props": ["spectacles"],
        "status": "ALIVE"
      }
    }
  ],
  "contradictions_found": [
    {
      "id": 12,
      "entity_name": "Count Dracula",
      "field": "physical.eye_color",
      "value_a": "piercing blue",
      "value_b": "deep emerald green",
      "severity": "SOFT",
      "chapter_a_id": 1,
      "chapter_b_id": 4,
      "quote_a": "He met Count Dracula at the castle threshold, noting the host's piercing blue eyes and tall, imposing stature.",
      "quote_b": "His deep emerald green eyes flashed with sudden fury as he watched Jonathan reach for the forbidden journal on the mantle.",
      "explanation": "Count Dracula's eye color is established as piercing blue in Chapter 1, but described as deep emerald green in Chapter 4 with no narrative explanation for the change."
    }
  ]
}
```

---

## 8. How It Was Built & Iterated

The development of Continuity Editor evolved through several key engineering challenges:

1. **Overcoming Naive Vector RAG**:
   - *Initial attempt*: Direct vector search over raw text chunks returned relevant passages but hallucinated contradictions when text was merely stylistically diverse.
   - *Iteration*: Transitioned to a dual extraction pipeline combining Cognee's graph memory with a fiction-tuned structured JSON extraction layer.
2. **Eliminating False-Positive Hallucinations on Silence**:
   - *Initial challenge*: When a chapter omitted an attribute (e.g., didn't mention a character's suitor), models often output `suitor: "none"`, triggering false `HARD` relationship contradictions against prior chapters.
   - *Solution*: Implemented a 3-layer guardrail: (1) Extraction prompt strictly forbids emitting null/empty keys; (2) `_strip_null_like()` filters out placeholder strings before judging; (3) The LLM Judge prompt enforces a "silence is not a contradiction" policy.
3. **Decoupling Graph Construction from Ingestion Latency**:
   - *Challenge*: Full graph embedding and indexing via Cognee takes several seconds per chapter, degrading editor responsiveness.
   - *Solution*: Dual-path execution. Structured extraction and contradiction checking run synchronously in <1.5s, while heavy Cognee graph ingestion runs safely in a non-blocking FastAPI `BackgroundTask`.
4. **Native Google Docs Extension (Zero OAuth Friction)**:
   - *Challenge*: Standard Google Docs integrations require complex Google Cloud OAuth consent screens and verification.
   - *Solution*: Developed a Manifest V3 Chrome Extension that leverages native browser export streams to read active document text directly, requiring zero API setup from authors.

---

## 9. Tech Stack

| Layer | Technology | Purpose |
|---|---|---|
| **Knowledge Graph** | [cognee](https://github.com/topoteretes/cognee) v1.0 | Graph extraction, semantic memory, and entity relationship mapping |
| **Backend Framework** | FastAPI (Python 3.11+) | Async REST API, Pydantic validation, background task orchestration |
| **LLM Engine** | `openai/gpt-oss-120b:free` (via OpenRouter) | Fiction NER, state extraction, contradiction judging, alias matching |
| **Vector Store** | LanceDB | Embedded zero-config vector database for semantic chunk retrieval |
| **Metadata Database** | SQLite (`aiosqlite`) / PostgreSQL | Relational project, chapter, entity, and contradiction records |
| **Client Interfaces** | Chrome Extension (Manifest V3) & Force-Directed Graph Viewer | In-editor Google Docs sidebar and interactive graph exploration |

---

## Quick Start

### 1. Installation

```bash
# Clone the repository
git clone https://github.com/Chitransh2309/ContinuityEditor.git
cd ContinuityEditor

# Install dependencies in editable mode
pip install -e ".[dev]"
```

### 2. Environment Configuration

Create a `.env` file from the example:

```bash
cp .env.example .env
```

Set your required environment variables in `.env`:

```env
OPENROUTER_API_KEY=your_openrouter_api_key_here
DATABASE_URL=sqlite+aiosqlite:///./dev.db
COGNEE_VECTOR_DB=lancedb
LOG_LEVEL=INFO
```

### 3. Run the Server

```bash
uvicorn app.main:app --reload
```

Interactive OpenAPI documentation is available at `http://localhost:8000/docs`.  
The interactive graph viewer is available at `http://localhost:8000/viewer`.

---

## API Endpoints Summary

### Projects (`/projects`)
- `POST /projects` — Create a new manuscript project
- `GET /projects` — List all projects
- `GET /projects/{id}` — Retrieve project metadata and chapter list
- `DELETE /projects/{id}` — Delete project and purge its Cognee graph memory

### Chapters (`/projects/{id}/chapters`) — `remember()`
- `POST /projects/{id}/chapters` — Ingest a chapter (runs extraction, graph indexing, and immediate contradiction checks)
- `GET /projects/{id}/chapters` — List all ingested chapters

### Recall & Contradictions (`/projects/{id}/recall`) — `recall()`
- `POST /projects/{id}/recall` — On-demand contradiction scan across chapters (supports `focus` on specific characters/places)
- `PATCH /projects/{id}/recall/{cid}/resolve` — Mark a flagged contradiction as resolved

### Canonicalization (`/projects/{id}/improve`) — `improve()`
- `POST /projects/{id}/improve` — Run alias consolidation pass to merge near-duplicate entities

### Graph & Timeline (`/projects/{id}/graph` & `/timeline`)
- `GET /projects/{id}/graph` — Full knowledge graph `{ nodes: [], edges: [] }`
- `GET /projects/{id}/timeline` — Chronologically sorted event timeline with gap warnings

---

## Google Docs Chrome Extension

Continuity Editor includes a Chrome Extension for real-time analysis while typing in Google Docs.

### Setup & Installation
1. Open Chrome and navigate to `chrome://extensions/`.
2. Enable **Developer mode** in the upper right.
3. Click **Load unpacked** and select the `extension/` directory.
4. Open the extension popup, enter your backend URL (`http://localhost:8000`), and click **Save**.

### Extension Workflow
- **Map Document**: Select an existing Continuity Editor project or create one directly from the document.
- **Sync Document**: Commits the current manuscript text to the backend knowledge graph.
- **Check Continuity**: Compares unsaved/new drafts against established knowledge graph facts without permanently mutating the graph, displaying flagged issues in the sidebar.

---

## Running Tests & Demos

```bash
# Run automated test suite
pytest tests/ -v

# Run Dracula demo (injects eye-color contradiction into chapter 6)
python scripts/demo_dracula.py

# Seed a sample project with known test data
python scripts/seed_project.py
```
