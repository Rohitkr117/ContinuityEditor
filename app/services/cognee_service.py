"""
Cognee v1.2.2 wrapper — verified signatures from inspect.signature():

  remember(data, dataset_name='main_dataset', *, ...)   dataset_name: str  (NOT datasets=)
  recall(query_text, *, datasets=[name], top_k=, ...)   datasets: list[str], returns Pydantic objects
  improve(dataset='main_dataset', *, ...)                dataset: str | UUID, first positional
  forget(*, dataset=name, ...)                           dataset: str | UUID, keyword-only

Result objects from recall() are Pydantic — use result.text, result.source, result.score.
Do NOT use result["text"] or result.get("text").
"""
import cognee
from app.config import settings


def _dataset(project_id: int) -> str:
    return f"project_{project_id}"


async def setup_cognee():
    """Point cognee at AWS Mantle. Storage path is set via DATA_ROOT_DIRECTORY in .env."""
    cognee.config.set_llm_config({
        "llm_provider": "openai",
        "llm_model": settings.openai_model,
        "llm_api_key": settings.openai_api_key,
        "llm_endpoint": settings.openai_base_url,
    })


async def remember(project_id: int, chapter_num: int, text: str) -> None:
    """
    Store a chapter as permanent graph memory scoped to this project.

    Runs as a Starlette BackgroundTask — MUST NOT raise.  Any exception here
    propagates to the ASGI runner and can corrupt HTTP keep-alive connections,
    causing the next request on the same connection to get 'Server disconnected'.
    """
    import logging
    logger = logging.getLogger(__name__)
    try:
        # cognee v1.2.2: second positional arg is dataset_name (str), NOT datasets= (list)
        await cognee.remember(text, _dataset(project_id))
    except Exception as exc:
        logger.warning("cognee.remember failed for project %s ch.%s: %s", project_id, chapter_num, exc)


async def recall(project_id: int, query: str, top_k: int = 10) -> list:
    """
    Semantic search across the project's knowledge graph.
    Returns list of RecallResponse Pydantic objects.
    Each result: result.text, result.source ("graph"|"session"|...), result.score
    """
    results = await cognee.recall(
        query,
        datasets=[_dataset(project_id)],
        top_k=top_k,
        only_context=True,
    )
    return results if isinstance(results, list) else []


async def improve(project_id: int) -> None:
    """
    Enrich the knowledge graph — bridges session→permanent memory
    and runs additional enrichment tasks.
    dataset is the first positional argument.
    """
    await cognee.improve(_dataset(project_id))


async def forget_project(project_id: int) -> None:
    """
    Remove all cognee memory for a project.
    forget() is all-keyword — use dataset= (singular), not datasets=.
    """
    await cognee.forget(dataset=_dataset(project_id))
