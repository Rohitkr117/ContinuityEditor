from typing import AsyncGenerator
from openai import AsyncOpenAI
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from app.config import settings
from app.models.db import Base

engine = create_async_engine(settings.database_url, echo=False)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session


def get_llm() -> AsyncOpenAI:
    return AsyncOpenAI(
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
        project=settings.openai_project_id,
    )


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Safe migrations: add new columns that may not exist in existing DBs
        await _safe_add_columns(conn)


async def _safe_add_columns(conn):
    """Add missing columns to existing tables without dropping data."""
    from sqlalchemy import text
    migrations = [
        ("contradictions", "reason", "TEXT"),
        ("contradictions", "confidence", "REAL"),
        ("contradictions", "verdict", "TEXT"),
    ]
    for table, column, col_type in migrations:
        result = await conn.execute(text(f"PRAGMA table_info({table})"))
        existing = [r[1] for r in result.fetchall()]
        if column not in existing:
            await conn.execute(
                text(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
            )
