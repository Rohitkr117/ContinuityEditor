"""
Demo: feed Project Gutenberg's Dracula (chapters 1-5), inject a deliberate
eye-color contradiction in chapter 6, watch it get caught.

Run: python scripts/demo_dracula.py
Requires: server running at http://localhost:8000
"""
import httpx
import json
import time

BASE = "http://localhost:8000"

CHAPTERS = [
    (1, "Jonathan Harker's Journal (kept in shorthand)",
     """Jonathan Harker travels by train through Eastern Europe toward Count Dracula's castle.
     He is a young solicitor with brown eyes and dark hair. He notes strange customs among the locals.
     The villagers seem frightened when he mentions his destination. He arrives at a mountain pass
     where a coach picks him up. The driver's eyes gleam red in the darkness."""),

    (2, "Jonathan Harker's Journal (continued)",
     """Jonathan arrives at Castle Dracula. The Count greets him — a tall old man, clean-shaven
     save for a long white moustache, clad in black from head to foot. The Count's eyes are red,
     his hands cold as ice. Jonathan notices the castle has no mirrors. He begins to feel uneasy.
     Mina, Jonathan's fiancée, has blue eyes and golden hair — he misses her terribly."""),

    (3, "Jonathan Harker's Journal (continued)",
     """Jonathan discovers he is a prisoner. The Count's three female vampires nearly attack him.
     Dracula warns them off. Jonathan writes desperate letters home. He explores the castle at night.
     He finds the Count sleeping in a box of earth in the chapel. The Count looks younger, his white
     hair now streaked with iron-grey, his cheeks fuller, his lips redder than before."""),

    (4, "Jonathan Harker's Journal (continued)",
     """Jonathan attempts escape. He climbs the castle walls. He witnesses Dracula crawl face-down
     along the sheer wall like a lizard. A box of earth is loaded onto a cart heading for England.
     Jonathan resolves to escape or die trying. He fears he is going mad."""),

    (5, "Letters — Lucy and Mina",
     """Mina Murray writes to her friend Lucy Westenra. Mina is engaged to Jonathan Harker.
     Lucy has three suitors: Dr. John Seward, Arthur Holmwood (Lord Godalming), and Quincey Morris.
     Lucy is described as beautiful with grey eyes and light brown hair. She is cheerful and kind.
     Mina mentions her own brown eyes and hopes Jonathan writes soon."""),
]

# Deliberate contradiction: Mina's eyes were brown in ch.2 and ch.5, now they're green
CONTRADICTION_CHAPTER = (6, "Mina's Journal",
    """Mina Harker (née Murray) has settled in Exeter. She is a resourceful woman with striking
    green eyes and golden hair. She has heard nothing from Jonathan for weeks and is worried sick.
    She keeps a careful journal as Jonathan taught her. Dr. Seward's asylum is nearby.
    She and Lucy correspond frequently about their respective anxieties.""")


def pretty(data):
    print(json.dumps(data, indent=2, default=str))


def main():
    client = httpx.Client(base_url=BASE, timeout=300)

    print("=== Creating project ===")
    r = client.post("/projects", json={"title": "Dracula", "author": "Bram Stoker"})
    r.raise_for_status()
    project = r.json()
    pid = project["id"]
    print(f"Project ID: {pid}")

    print("\n=== Ingesting chapters 1-5 (establishing facts) ===")
    for num, title, text in CHAPTERS:
        r = client.post(f"/projects/{pid}/chapters", json={
            "number": num, "title": title, "text": text
        })
        r.raise_for_status()
        data = r.json()
        entities = [e["canonical_name"] for e in data["entities_extracted"]]
        contradictions = data["contradictions_found"]
        print(f"  Ch.{num}: {len(entities)} entities extracted, "
              f"{len(contradictions)} contradictions")
        if contradictions:
            for c in contradictions:
                print(f"    [!] {c['field']}: '{c['value_a']}' vs '{c['value_b']}' "
                      f"[{c['severity']}]")
        time.sleep(5)  # respect free-tier rate limit

    print("\n=== Ingesting chapter 6 (WITH deliberate contradiction) ===")
    num, title, text = CONTRADICTION_CHAPTER
    r = client.post(f"/projects/{pid}/chapters", json={
        "number": num, "title": title, "text": text
    })
    r.raise_for_status()
    data = r.json()
    print(f"  Ch.{num}: {len(data['entities_extracted'])} entities extracted")
    print(f"  Contradictions found: {len(data['contradictions_found'])}")
    for c in data["contradictions_found"]:
        print(f"\n  *** CONTRADICTION DETECTED ***")
        print(f"     Entity field : {c['field']}")
        print(f"     Chapter {c['chapter_a_id']}    : {c['value_a']}")
        print(f"     Chapter {c['chapter_b_id']}    : {c['value_b']}")
        print(f"     Severity     : {c['severity']}")

    print("\n=== Running improve() to consolidate aliases ===")
    r = client.post(f"/projects/{pid}/improve")
    r.raise_for_status()
    improve_data = r.json()
    print(f"  Alias groups merged: {len(improve_data['alias_groups_merged'])}")
    for g in improve_data["alias_groups_merged"]:
        print(f"    '{g['canonical_name']}' <- {g['aliases']}")

    print("\n=== Full recall() scan ===")
    r = client.post(f"/projects/{pid}/recall", json={})
    r.raise_for_status()
    recall_data = r.json()
    print(f"  Checked {recall_data['checked_chapters']} chapters, "
          f"{recall_data['checked_entities']} entities")
    print(f"  Total unresolved contradictions: {len(recall_data['contradictions'])}")

    print("\n=== Done. Visit http://localhost:8000/docs to explore the API. ===")


if __name__ == "__main__":
    main()
