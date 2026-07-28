"""
Demo: Western frontier story — bounty hunter Cassidy Rourke tracks the outlaw
Silas Crane through the town of Dustwood. Plants three deliberate contradictions
in chapter 4:

  1. HARD — Dead man walking:
     Silas Crane is shot in ch.2, his body recovered downriver and buried in
     the Dustwood cemetery. In ch.4, he walks into the saloon alive.

  2. HARD — Prop continuity:
     Crane's revolver, "the Widowmaker," is lost with him in the river current
     in ch.2 — never recovered. In ch.4, it's holstered at his hip, untouched
     by rust or river-rot.

  3. SOFT — Relationship contradiction:
     In ch.3, Dot Reyes tells Cassidy that Sheriff Whitlock and Crane rode the
     outlaw trail together as young men. In ch.4, Whitlock insists under oath
     that he has never laid eyes on Crane before.

A fourth, unplanted physical-attribute drift (Cassidy's eye color) is also
seeded to check the pipeline doesn't need a "planted" label to catch it.

This exercises the full proposer -> arbiter pipeline (see app/services/
contradiction.py) rather than mocking any part of it, and reports each
candidate's severity/confidence/verdict — not just whether something was
flagged, since low-confidence REJECTed candidates are expected and are not
failures.

Run: python scripts/demo_dustwood.py
Requires: server running at http://localhost:8000
"""
import httpx
import json
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = "http://localhost:8000"

CHAPTERS = [
    (1, "The Wanted Poster",
     """Cassidy Rourke rode into Dustwood under a bleached-white noon sun, dust caked
     thick on her duster coat. She was a bounty hunter with sharp, ice-blue eyes and a
     reputation for bringing men in whole or not at all. The wanted poster nailed to the
     jailhouse door named Silas Crane — five hundred dollars, dead or alive, for the
     Coppervale train robbery. Sheriff Amos Whitlock met her on the porch, thumbs hooked
     in his belt. "Can't say I've ever crossed paths with that man," he told her. "Don't
     know what makes a fella turn to robbery like that. Just bad blood, I suppose.\"""" ),

    (2, "The River Crossing",
     """Cassidy tracked Crane three days to the Copperhead River crossing. He turned
     and fired first; she put him down with a single shot. Crane staggered backward into
     the churning rapids, the Widowmaker — his late father's silver-plated revolver —
     still clenched in his fist, and the current swallowed him whole. His body surfaced
     two days later, tangled in driftwood four miles downstream. The town buried Silas
     Crane in the Dustwood cemetery that Friday. Sheriff Whitlock closed the bounty file
     himself. The Widowmaker was never recovered; the river had claimed it for good."""),

    (3, "Dot's Whiskey and an Old Story",
     """That evening Cassidy took a whiskey at the Blind Mule saloon, run by a sharp-eyed
     woman named Dolores "Dot" Reyes. Dot leaned on the bar and told her a story from
     years back: before Amos Whitlock ever pinned on a badge, he and a young Silas Crane
     had ridden the outlaw trail together, robbing coach lines up and down the territory
     like a pair of brothers. Whitlock had gone straight; Crane never did. Cassidy turned
     the whiskey glass slowly in her hand, surprised the sheriff had never once mentioned
     it."""),
]

# Chapter 4: three deliberate contradictions planted, plus an unplanted eye-color drift
CONTRADICTION_CHAPTER = (4, "The Man in the Doorway",
    """Three weeks later, Cassidy was back at the Blind Mule when the saloon doors
    creaked open. Silas Crane walked in, alive, boots dragging river silt across the
    floorboards. The Widowmaker sat holstered at his hip, its silver plating gleaming,
    untouched by rust or the river's rot. Cassidy's storm-grey eyes narrowed as her hand
    drifted to her own sidearm.

    Sheriff Whitlock burst through the doors a moment later, revolver drawn, shouting
    for the room to stay calm. "I've never laid eyes on this man before in my life," he
    said, loud enough for every drinker in the saloon to hear. "Whoever he is, he's no
    one to me."

    Dot Reyes said nothing, just poured herself a drink and watched the two men circle
    each other like they were picking up an old argument neither had ever finished.""")


def main():
    client = httpx.Client(base_url=BASE, timeout=300)

    print("=== Creating project: Dustwood ===")
    r = client.post("/projects", json={"title": "Dustwood", "author": "Demo"})
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
        confirmed = [c for c in data["contradictions_found"] if c.get("verdict") == "CONFIRM"]
        print(f"  Ch.{num} '{title}': {len(entities)} entities, "
              f"{len(confirmed)} confirmed contradiction(s)")
        time.sleep(5)

    print("\n=== Ingesting chapter 4 (THREE deliberate contradictions) ===")
    num, title, text = CONTRADICTION_CHAPTER
    r = client.post(f"/projects/{pid}/chapters", json={
        "number": num, "title": title, "text": text
    })
    r.raise_for_status()
    data = r.json()
    print(f"  Ch.{num}: {len(data['entities_extracted'])} entities extracted")
    print(f"  Candidates considered: {len(data['contradictions_found'])}")

    expected = {
        "dead man walking (Silas Crane)": False,
        "prop continuity (the Widowmaker)": False,
        "relationship contradiction (Whitlock/Crane)": False,
    }

    for c in data["contradictions_found"]:
        field = c["field"]
        val_a = c["value_a"]
        val_b = c["value_b"]
        sev = c["severity"]
        verdict = c["verdict"]
        conf = c["confidence"]
        tag = "CONFIRMED" if verdict == "CONFIRM" else "rejected "
        print(f"\n  *** {tag} [{sev}] confidence={conf:.2f} ***")
        print(f"     Field    : {field}")
        print(f"     Was      : {val_a!r}")
        print(f"     Now      : {val_b!r}")
        if c.get("reason"):
            print(f"     Reason   : {c['reason']}")
        if c.get("quote_a"):
            print(f"     Evidence A: \"{c['quote_a']}\"")
        if c.get("quote_b"):
            print(f"     Evidence B: \"{c['quote_b']}\"")

        if verdict != "CONFIRM":
            continue

        f = field.lower()
        v_a = val_a.lower()
        v_b = val_b.lower()

        if "status" in f and "dead" in v_a and "alive" in v_b:
            expected["dead man walking (Silas Crane)"] = True
        if ("widowmaker" in f or "status" in f or "revolver" in f) and \
           ("lost" in v_a or "river" in v_a or "unrecovered" in v_a or "never recovered" in v_a) and \
           "intact" in v_b:
            expected["prop continuity (the Widowmaker)"] = True
        if "relationship" in f or "whitlock" in v_a.lower() or "crane" in v_a.lower() or "never" in v_b.lower():
            expected["relationship contradiction (Whitlock/Crane)"] = True

    print("\n=== Expected contradictions caught (CONFIRMed only)? ===")
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
    print(f"  Unresolved candidates: {len(rec['contradictions'])}")
    for c in rec["contradictions"]:
        print(f"    [{c['verdict']:7s}] [{c['severity']}] {c['field']}  "
              f"Ch.{c.get('chapter_a_number')} vs Ch.{c.get('chapter_b_number')}  "
              f"confidence={c['confidence']:.2f}")

    print(f"\n=== Done. Docs at http://localhost:8000/docs ===")


if __name__ == "__main__":
    main()
