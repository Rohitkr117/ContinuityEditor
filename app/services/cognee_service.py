"""
Cognee v1.0 wrapper — correct signatures from docs:

  remember(text, datasets=[name])                    datasets: list[str]
  recall(query, datasets=[name], top_k=, ...)        datasets: list[str], returns Pydantic objects
  improve(dataset=name, ...)                          dataset: str | UUID, positional
  forget(*, dataset=name)                             dataset: str | UUID, keyword-only

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
    """Store a chapter as permanent graph memory scoped to this project."""
    await cognee.remember(text, dataset_name=_dataset(project_id))


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
