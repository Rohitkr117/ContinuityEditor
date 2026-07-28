"""
Chapter text pre-processing utilities.

Used before entity extraction and cognee ingestion to:
- Strip markdown / HTML formatting
- Detect and split scenes at scene-break markers
- Chunk long text into LLM-friendly segments
"""
from __future__ import annotations
import re

# Scene-break patterns common in fiction manuscripts
_SCENE_BREAK_RE = re.compile(r"(?m)^[ \t]*[*\-~=#]{3,}[ \t]*$")

# Default chunk size (chars) — leaves room for system prompt + output tokens
DEFAULT_CHUNK_SIZE = 10_000
DEFAULT_CHUNK_OVERLAP = 500


def strip_formatting(text: str) -> str:
    """Remove common markdown and HTML formatting from raw chapter text."""
    # Strip HTML tags
    text = re.sub(r"<[^>]+>", "", text)
    # Strip markdown headers (## Title → Title)
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
    # Strip bold / italic markers (**bold**, *italic*, __bold__, _italic_)
    text = re.sub(r"\*{1,3}([^*\n]+)\*{1,3}", r"\1", text)
    text = re.sub(r"_{1,3}([^_\n]+)_{1,3}", r"\1", text)
    # Collapse multiple blank lines to a single blank line
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def split_scenes(text: str) -> list[str]:
    """
    Split chapter text at scene-break markers (e.g. '***', '---', '~~~').

    Returns a list of non-empty scene strings, each stripped of leading /
    trailing whitespace.
    """
    scenes = _SCENE_BREAK_RE.split(text)
    return [s.strip() for s in scenes if s.strip()]


def chunk_text(
    text: str,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    overlap: int = DEFAULT_CHUNK_OVERLAP,
) -> list[str]:
    """
    Split *text* into overlapping chunks of at most *chunk_size* characters.

    Tries to break on paragraph boundaries (double newline) to preserve
    narrative context.  Falls back to a hard character split for paragraphs
    that are longer than *chunk_size* on their own.
    """
    if len(text) <= chunk_size:
        return [text]

    chunks: list[str] = []
    paragraphs = text.split("\n\n")
    current = ""

    for para in paragraphs:
        candidate = (current + "\n\n" + para).lstrip() if current else para
        if len(candidate) <= chunk_size:
            current = candidate
        else:
            if current:
                chunks.append(current)
                # Carry an overlap tail into the next chunk for context
                current = (current[-overlap:] + "\n\n" + para) if overlap else para
            else:
                # Single paragraph larger than chunk_size — hard split
                for i in range(0, len(para), chunk_size - overlap):
                    chunks.append(para[i : i + chunk_size])
                current = ""

    if current:
        chunks.append(current)

    return chunks


def preprocess_chapter(text: str) -> str:
    """
    Full pre-processing pipeline for a raw chapter string.

    Strips formatting and collapses whitespace.  Returns a clean string
    ready for LLM entity extraction or cognee ingestion.
    """
    return strip_formatting(text)
