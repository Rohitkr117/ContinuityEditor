"""
Demo: sci-fi space opera — ISS Meridian crew on a deep-space mission.
Plants three non-trivial contradictions in chapter 6:

  1. HARD — Dead man walking:
     Dr. Yusuf Reyes is explicitly killed when the med-bay explodes in ch.4.
     He appears alive and gives a briefing in ch.6.

  2. HARD — Prop continuity:
     The Meridian's quantum relay beacon is burned out and jettisoned into space
     in ch.2. In ch.6, Dex uses it to contact Earth.

  3. SOFT — Relationship contradiction:
     Lt. Voss tells Commander Osei in ch.3 that she has never met Director Hallan
     and knows nothing about him. In ch.6, Voss greets Hallan as an old colleague
     from her time at Kepler Station.

Run: python scripts/demo_meridian.py
Requires: server running at http://localhost:8000
"""
import httpx
import json
import sys
import time

# Windows cp1252 can't print non-breaking hyphens that LLMs sometimes emit
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = "http://localhost:8000"

CHAPTERS = [
    (1, "Launch",
     """The ISS Meridian departed Proxima Dock at 0600 hours. Commander Zara Osei
     stood on the bridge, watching the station shrink behind them. The ship was a
     Horizon-class explorer, outfitted with a cutting-edge quantum relay beacon for
     long-range communication with Earth Command. The beacon was their only link home.
     Chief Engineer Dex Huang ran final diagnostics and confirmed all systems nominal.
     Dr. Yusuf Reyes, the ship's medic, was calibrating the med-bay's surgical units.
     Lieutenant Kira Voss locked in their heading: deep space sector 7-Gamma, bearing
     toward the newly detected Lethis signal. Estimated travel time to Kepler Station:
     fourteen days."""),

    (2, "Solar Interference",
     """On day three, a solar flare struck the Meridian broadside. The quantum relay
     beacon took a direct hit — its primary coil fused and the housing cracked open.
     Dex assessed the damage and shook his head. The quantum relay beacon was beyond
     repair. Commander Osei ordered it jettisoned before the fused core could contaminate
     the hull plating. The beacon tumbled away into the void. They were now out of contact
     with Earth Command for the duration of the mission.

     Lt. Voss noted in her log that she had never heard of Director Hallan, who supposedly
     ran Kepler Station. Commander Osei replied she knew nothing about him either — the
     station had only been commissioned six months ago and neither of them had any prior
     contact with its director."""),

    (3, "Kepler Station",
     """The Meridian docked at Kepler Station on day fourteen. The crew had never visited
     the station before. Director Hallan met them in the airlock — a gaunt man with sharp
     eyes and a clipped manner. Lt. Voss introduced herself formally; it was their first
     meeting. Director Hallan provided the Meridian crew with updated star charts and
     resupplied their coolant reserves. The visit was brief and professional.
     Dex requisitioned replacement parts for the damaged hull plating."""),

    (4, "The Incident",
     """On day twenty-one, a cascade failure in the reactor coupling triggered an explosion
     in the med-bay. Dr. Yusuf Reyes was inside at the time, running routine blood cultures.
     The explosion was catastrophic. When the emergency bulkheads sealed, the med-bay was
     fully pressurized with fire-suppressant foam. Dex cut open the door forty minutes later.
     Dr. Reyes was gone — the body had been vented when the outer wall gave way. Commander Osei
     logged the death formally: Reyes, Yusuf — killed in action, stardate 7-21. The crew held
     a brief memorial. His personal effects were sealed in a cargo locker."""),

    (5, "The Signal",
     """The Lethis signal resolved into a repeating mathematical sequence — unmistakably
     artificial. Commander Osei ordered a full sensor sweep. Dex worked around the clock
     reconfiguring the long-range array. Lt. Voss plotted an intercept course. The crew
     of three worked in near silence, the absence of Dr. Reyes still raw.
     Osei recorded in the ship's log that they were proceeding without a medic and
     that any serious injury would be mission-ending. The signal's origin appeared to be
     a structure in low orbit around Lethis Prime."""),
]

# Chapter 6: three deliberate contradictions planted
CONTRADICTION_CHAPTER = (6, "First Contact",
    """Commander Osei called a full crew briefing in the main cabin. Dr. Yusuf Reyes
    was the first to speak, presenting his analysis of the Lethis signal frequency
    from a medical-pattern-recognition perspective. His presence lifted the mood —
    the crew had missed his steady calm.

    Dex pulled up the long-range contact channel and activated the quantum relay
    beacon, patching through a live feed to Earth Command. Director Chen acknowledged
    their transmission from mission control.

    Lt. Voss smiled when she saw Director Hallan's face appear on the secondary
    screen. "Good to see you again," she said. "It has been too long since Kepler
    Station." Hallan laughed — they went back years.

    The structure on Lethis Prime was responding to their hails. Commander Osei
    prepared her first-contact protocol. History, she thought, was being made.""")


def pretty(label, data):
    print(f"\n  {label}")
    print(json.dumps(data, indent=4, default=str))


def main():
    client = httpx.Client(base_url=BASE, timeout=300)

    print("=== Creating project: ISS Meridian ===")
    r = client.post("/projects", json={"title": "ISS Meridian", "author": "Demo"})
    r.raise_for_status()
    pid = r.json()["id"]
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
        print(f"  Ch.{num} '{title}': {len(entities)} entities, "
              f"{len(contradictions)} contradictions")
        if contradictions:
            for c in contradictions:
                print(f"    [!] {c['field']}: '{c['value_a']}' vs '{c['value_b']}' [{c['severity']}]")
        time.sleep(5)

    print("\n=== Ingesting chapter 6 (THREE deliberate contradictions) ===")
    num, title, text = CONTRADICTION_CHAPTER
    r = client.post(f"/projects/{pid}/chapters", json={
        "number": num, "title": title, "text": text
    })
    r.raise_for_status()
    data = r.json()
    print(f"  Ch.{num}: {len(data['entities_extracted'])} entities extracted")
    print(f"  Contradictions found: {len(data['contradictions_found'])}")

    expected = {
        "dead man walking": False,
        "prop continuity (quantum relay beacon)": False,
        "relationship contradiction (Voss/Hallan)": False,
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
        if c.get("quote_a"):
            print(f"     Evidence A: \"{c['quote_a']}\"")
        if c.get("quote_b"):
            print(f"     Evidence B: \"{c['quote_b']}\"")

        f = field.lower()
        v_a = val_a.lower()
        v_b = val_b.lower()

        if "status" in f and ("dead" in v_a or "killed" in v_a) and "alive" in v_b:
            expected["dead man walking"] = True
        if ("relay" in f or "beacon" in f or "status" in f) and ("destroyed" in v_a or "jettisoned" in v_a or "lost" in v_a):
            expected["prop continuity (quantum relay beacon)"] = True
        if "relationship" in f or "hallan" in v_a.lower() or "hallan" in v_b.lower():
            expected["relationship contradiction (Voss/Hallan)"] = True

    print("\n=== Expected contradictions caught? ===")
    for label, caught in expected.items():
        status = "[CAUGHT]" if caught else "[MISSED]"
        print(f"  {status}  {label}")

    print("\n=== Running improve() ===")
    r = client.post(f"/projects/{pid}/improve")
    r.raise_for_status()
    imp = r.json()
    print(f"  Alias groups merged  : {len(imp['alias_groups_merged'])}")
    print(f"  Contradictions resolved: {imp['contradictions_resolved']}")
    for g in imp["alias_groups_merged"]:
        print(f"    '{g['canonical_name']}' <- {g['aliases']}")

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
