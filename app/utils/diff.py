"""
Human-readable diff helpers for contradiction display.

Used to format contradiction records into readable summaries for CLI output,
demo scripts, and future report generation.
"""
from __future__ import annotations
from app.models.db import Severity


def format_contradiction(
    entity_name: str,
    field: str,
    value_a: str,
    value_b: str,
    chapter_a: int,
    chapter_b: int,
    severity: "Severity",
    quote_a: str | None = None,
    quote_b: str | None = None,
) -> str:
    """
    Return a human-readable single-contradiction summary.

    Example output::

        🔴 HARD  Dracula / status
          Ch.3 : "alive"
          Ch.6 : "dead"
          Evidence (ch.3): "The Count smiled and stepped forward."
          Evidence (ch.6): "Dracula crumbled to ash and was no more."
    """
    label = "🔴 HARD" if severity == Severity.HARD else "🟡 SOFT"
    lines = [
        f"{label}  {entity_name} / {field}",
        f"  Ch.{chapter_a} : {value_a!r}",
        f"  Ch.{chapter_b} : {value_b!r}",
    ]
    if quote_a:
        lines.append(f'  Evidence (ch.{chapter_a}): "{quote_a}"')
    if quote_b:
        lines.append(f'  Evidence (ch.{chapter_b}): "{quote_b}"')
    return "\n".join(lines)


def format_alias_merge(canonical: str, aliases: list[str]) -> str:
    """Return a human-readable alias-merge summary line."""
    members = ", ".join(repr(a) for a in aliases if a != canonical)
    return f"Merged → {canonical!r}  ←  {members}"


def format_contradiction_list(contradictions: list[dict]) -> str:
    """
    Format a list of contradiction dicts (as returned by the API) into a
    multi-line human-readable report.

    Each dict should have keys: entity_id, field, value_a, value_b,
    chapter_a_number, chapter_b_number, severity, quote_a, quote_b.
    """
    if not contradictions:
        return "✅  No contradictions found."

    lines = [f"Found {len(contradictions)} contradiction(s):\n"]
    for i, c in enumerate(contradictions, 1):
        sev = Severity(c.get("severity", "SOFT"))
        lines.append(f"[{i}] " + format_contradiction(
            entity_name=str(c.get("entity_id", "?")),
            field=c.get("field", "?"),
            value_a=c.get("value_a", ""),
            value_b=c.get("value_b", ""),
            chapter_a=c.get("chapter_a_number", c.get("chapter_a_id", "?")),
            chapter_b=c.get("chapter_b_number", c.get("chapter_b_id", "?")),
            severity=sev,
            quote_a=c.get("quote_a"),
            quote_b=c.get("quote_b"),
        ))
        lines.append("")
    return "\n".join(lines).rstrip()
