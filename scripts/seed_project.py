"""
Seed script — creates a test project and ingests two short chapters that contain
a known eye-color contradiction, so the database has real data to work with.

Usage:
    python scripts/seed_project.py

Requires the server to be running at http://localhost:8000.
"""
import asyncio
import httpx

BASE = "http://localhost:8000"
TIMEOUT = 120.0  # cognee graph construction can be slow


CH1 = """\
Chapter One — Arrival

Jonathan Harker stepped off the train at Bistritz. He was a young solicitor,
with clear blue eyes and neat brown hair. The innkeeper greeted him warmly and
pressed a crucifix into his hand before he boarded the coach to Castle Dracula.

The coach rattled through the Carpathian passes as night fell. Jonathan noted
in his journal that the driver seemed to know the road by instinct alone.
"""

CH2 = """\
Chapter Two — The Count

The great doors of Castle Dracula swung open. Count Dracula stood in the arch,
a tall old man clad in black. He shook Jonathan's hand with a grip of iron.

Later that evening Jonathan caught his reflection — or rather, he noticed that
the Count cast none. His own face stared back at him: those same grey eyes,
the same tired expression. He frowned. Hadn't they always been blue?
"""


async def main():
    async with httpx.AsyncClient(base_url=BASE, timeout=TIMEOUT) as client:
        # 1. Create project
        r = await client.post("/projects", json={"title": "Dracula (seed)", "author": "Bram Stoker"})
        r.raise_for_status()
        project = r.json()
        pid = project["id"]
        print(f"Created project id={pid}: {project['title']}")

        # 2. Ingest chapter 1
        r = await client.post(
            f"/projects/{pid}/chapters",
            json={"number": 1, "title": "Arrival", "text": CH1},
        )
        r.raise_for_status()
        ch1 = r.json()
        print(f"\nChapter 1 ingested — entities: {len(ch1['entities_extracted'])}")
        for e in ch1["entities_extracted"]:
            print(f"  {e['entity_type']:10s}  {e['canonical_name']}")

        # 3. Ingest chapter 2 — should detect eye-color contradiction
        r = await client.post(
            f"/projects/{pid}/chapters",
            json={"number": 2, "title": "The Count", "text": CH2},
        )
        r.raise_for_status()
        ch2 = r.json()
        print(f"\nChapter 2 ingested — entities: {len(ch2['entities_extracted'])}")
        for e in ch2["entities_extracted"]:
            print(f"  {e['entity_type']:10s}  {e['canonical_name']}")

        contradictions = ch2["contradictions_found"]
        if contradictions:
            print(f"\n[!] {len(contradictions)} contradiction(s) detected:")
            for c in contradictions:
                print(
                    f"  [{c['severity']}] {c['field']}: "
                    f"{c['value_a']!r} (ch.{c['chapter_a_number']}) → "
                    f"{c['value_b']!r} (ch.{c['chapter_b_number']})"
                )
                if c.get("quote_a"):
                    print(f"    Evidence A: \"{c['quote_a']}\"")
                if c.get("quote_b"):
                    print(f"    Evidence B: \"{c['quote_b']}\"")
        else:
            print("\n[OK] No contradictions detected at ingest time.")

        # 4. On-demand recall
        r = await client.post(f"/projects/{pid}/recall", json={"focus": "Jonathan"})
        r.raise_for_status()
        recall = r.json()
        print(f"\nRecall for 'Jonathan': {len(recall['contradictions'])} contradiction(s) on record.")

        print(f"\nDone. Visit http://localhost:8000/viewer to inspect the graph.")
        print(f"API docs: http://localhost:8000/docs")


if __name__ == "__main__":
    asyncio.run(main())
