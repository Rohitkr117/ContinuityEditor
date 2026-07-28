"""
Demo: Fantasy detective story in the Elven city of Aethelgard.
Plants three distinct contradictions in chapter 4:

  1. HARD — Prop continuity:
     The Sunstone Amulet is shattered into pieces in the gardens in ch.2.
     In ch.4, Lord Elidor is wearing it fully intact.

  2. SOFT — Relationship contradiction:
     In ch.3, Lady Seraphina describes Elidor as her older brother.
     In ch.4, she claims she is an only child with no siblings.

  3. SOFT — Physical feature contradiction:
     In ch.1, Inspector Valen is described as having midnight-black hair.
     In ch.4, his hair is described as silver-white.

Run: python scripts/demo_fantasy_detective.py
Requires: server running at http://localhost:8000
"""
import httpx
import json
import sys
import time

# Force UTF-8 output
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = "http://localhost:8000"

CHAPTERS = [
    (1, "The Banquet at Aethelgard",
     """Inspector Valen arrived at the grand manor of Aethelgard under a clear starlit sky.
     He was a renowned elven detective, known for his sharp mind and striking midnight-black hair.
     Lord Elidor hosted the banquet to celebrate the summer solstice.
     Lady Seraphina, the Lord's guest, wore the Sunstone Amulet around her neck.
     The amulet was a sapphire-blue gem that cast a warm light over the ballroom.
     Valen watched the guests, sensing tension in the air."""),

    (2, "The Theft and Shattered Stone",
     """Disaster struck in the middle of the night. A scream echoed from the conservatory.
     The Sunstone Amulet had been stolen from Lady Seraphina's chambers.
     Inspector Valen searched the grounds immediately. In the high grass of the southern gardens,
     he found the remnants of the amulet. The sapphire-blue gem was shattered into a hundred
     fine pieces, its magical glow completely extinguished. Valen collected the fragments,
     concluding the legendary artifact was destroyed beyond any hope of repair."""),

    (3, "Interrogating the Lady",
     """The next morning, Inspector Valen questioned Lady Seraphina in the library.
     She was distraught over the theft. During the questioning, she revealed details of her past,
     mentioning that Lord Elidor was her older brother, and they had grown up together in the
     docks of Aethelgard. Valen made a note of this family connection.
     He also noticed a peculiar sigil carved into the library table."""),
]

# Chapter 4: Three deliberate contradictions planted
CONTRADICTION_CHAPTER = (4, "The Revelation",
    """Inspector Valen convened all suspects in the drawing room.
    His silver-white hair caught the morning light as he paced the room.
    
    Lord Elidor sat by the fire, calmly wearing the sapphire-blue Sunstone Amulet
    around his neck. It was completely intact, shining as brightly as it had at the banquet.
    
    When Valen pointed to it, Lady Seraphina scoffed. 'Why look at me? I am an only child
    who grew up alone in the mountains, with no siblings or family to help me.'
    
    Valen smiled. The pieces of the puzzle were finally falling into place.""")


def main():
    client = httpx.Client(base_url=BASE, timeout=300)

    print("=== Creating project: Aethelgard Mystery ===")
    r = client.post("/projects", json={"title": "Aethelgard Mystery", "author": "Demo"})
    r.raise_for_status()
    pid = r.json()["id"]
    print(f"Project ID: {pid}")

    print("\n=== Ingesting chapters 1-3 (establishing facts) ===")
    for num, title, text in CHAPTERS:
        r = client.post(f"/projects/{pid}/chapters", json={
            "number": num, "title": title, "text": text
        })
        r.raise_for_status()
        data = r.json()
        entities = [e["canonical_name"] for e in data["entities_extracted"]]
        contradictions = data["contradictions_found"]
        print(f"  Ch.{num} '{title}': {len(entities)} entities, "
              f"{len(contradictions)} contradictions")
        time.sleep(5)

    print("\n=== Ingesting chapter 4 (THREE deliberate contradictions) ===")
    num, title, text = CONTRADICTION_CHAPTER
    r = client.post(f"/projects/{pid}/chapters", json={
        "number": num, "title": title, "text": text
    })
    r.raise_for_status()
    data = r.json()
    print(f"  Ch.{num}: {len(data['entities_extracted'])} entities extracted")
    print(f"  Contradictions found: {len(data['contradictions_found'])}")

    expected = {
        "prop continuity (Sunstone Amulet)": False,
        "relationship contradiction (Seraphina/Elidor)": False,
        "physical feature contradiction (Valen's hair)": False,
    }

    for c in data["contradictions_found"]:
        field = c["field"]
        val_a = c["value_a"]
        val_b = c["value_b"]
        sev = c["severity"]
        print(f"\n  *** CONTRADICTION [{sev}] ***")
        print(f"     Field    : {field}")
        print(f"     Was      : {val_a!r}")
        print(f"     Now      : {val_b!r}")
        if c.get("reason"):
            print(f"     Reason   : {c['reason']}")
        if c.get("quote_a"):
            print(f"     Evidence A: \"{c['quote_a']}\"")
        if c.get("quote_b"):
            print(f"     Evidence B: \"{c['quote_b']}\"")

        f = field.lower()
        v_a = val_a.lower()
        v_b = val_b.lower()

        if "status" in f and ("destroyed" in v_a or "shattered" in v_a) and "intact" in v_b:
            expected["prop continuity (Sunstone Amulet)"] = True
        if "relationship" in f or "elidor" in f or "only child" in v_b or "brother" in v_a:
            expected["relationship contradiction (Seraphina/Elidor)"] = True
        if "hair" in f and "black" in v_a and "white" in v_b:
            expected["physical feature contradiction (Valen's hair)"] = True

    print("\n=== Expected contradictions caught? ===")
    for label, caught in expected.items():
        status = "[CAUGHT]" if caught else "[MISSED]"
        print(f"  {status}  {label}")

    print("\n=== Running improve() ===")
    r = client.post(f"/projects/{pid}/improve")
    r.raise_for_status()
    imp = r.json()
    print(f"  Alias groups merged  : {len(imp['alias_groups_merged'])}")

    print("\n=== Full recall() ===")
    r = client.post(f"/projects/{pid}/recall", json={})
    r.raise_for_status()
    rec = r.json()
    print(f"  Chapters checked    : {rec['checked_chapters']}")
    print(f"  Entities checked    : {rec['checked_entities']}")
    print(f"  Unresolved contradictions: {len(rec['contradictions'])}")
    for c in rec["contradictions"]:
        print(f"    [{c['severity']}] {c['field']}  Ch.{c.get('chapter_a_number')} vs Ch.{c.get('chapter_b_number')}")

    print(f"\n=== Done. Docs at http://localhost:8000/docs ===")


if __name__ == "__main__":
    main()
