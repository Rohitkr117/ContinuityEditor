import logging
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

# Load .env before importing cognee - it reads DATA_ROOT_DIRECTORY and
# COGNEE_LOGS_DIR at module import time, so they must be in os.environ first.
load_dotenv(Path(__file__).parent.parent / ".env")

from app.config import settings
from app.dependencies import init_db
from app.routers import chapters, extension, graph, improve, projects, recall
from app.services.cognee_service import setup_cognee

logging.basicConfig(level=settings.log_level)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    await setup_cognee()
    yield


app = FastAPI(
    title="Continuity Editor",
    description="Detect contradictions in long-form fiction manuscripts using a knowledge graph.",
    version="0.1.0",
    lifespan=lifespan,
)

cors_origin_regex = settings.cors_extension_origin_regex if settings.cors_allow_extension_regex else None
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allowed_origins,
    allow_origin_regex=cors_origin_regex,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(projects.router)
app.include_router(chapters.router)
app.include_router(recall.router)
app.include_router(improve.router)
app.include_router(graph.router)
app.include_router(extension.router)


@app.get("/viewer", include_in_schema=False)
async def graph_viewer():
    return FileResponse(Path(__file__).parent.parent / "graph_viewer.html")


@app.get("/health")
async def health():
    return {"status": "ok"}
