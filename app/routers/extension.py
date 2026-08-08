from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db, get_llm
from app.models.db import Project
from app.models.schemas import (
    ExtensionCheckResponse,
    ExtensionDocumentRequest,
    ExtensionStatusResponse,
    ExtensionSyncResponse,
)
from app.services.extension import (
    analyze_document_check,
    build_status_response,
    normalize_document_text,
    sync_document_to_project,
)

router = APIRouter(prefix="/projects/{project_id}/extension", tags=["extension"])


async def _get_project_or_404(db: AsyncSession, project_id: int) -> Project:
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    return project


@router.get("/status", response_model=ExtensionStatusResponse)
async def get_extension_status(
    project_id: int,
    document_id: str = Query(...),
    document_title: str | None = Query(default=None),
    current_hash: str | None = Query(default=None),
    current_revision: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    project = await _get_project_or_404(db, project_id)
    response = await build_status_response(
        db=db,
        project=project,
        document_id=document_id,
        document_title=document_title,
        current_hash=current_hash,
        current_revision=current_revision,
    )
    await db.commit()
    return response


@router.post("/check", response_model=ExtensionCheckResponse)
async def check_document_continuity(
    project_id: int,
    body: ExtensionDocumentRequest,
    db: AsyncSession = Depends(get_db),
    llm=Depends(get_llm),
):
    project = await _get_project_or_404(db, project_id)
    if not normalize_document_text(body.document_text):
        raise HTTPException(400, "Document text is empty")
    response = await analyze_document_check(db, project, body, llm)
    await db.commit()
    return response


@router.post("/sync", response_model=ExtensionSyncResponse)
async def sync_document(
    project_id: int,
    body: ExtensionDocumentRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    llm=Depends(get_llm),
):
    project = await _get_project_or_404(db, project_id)
    if not normalize_document_text(body.document_text):
        raise HTTPException(400, "Document text is empty")
    response = await sync_document_to_project(db, project, body, llm, background_tasks)
    await db.commit()
    return response
