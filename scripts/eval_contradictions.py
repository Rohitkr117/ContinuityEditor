"""
Hallucination eval — a small labeled set of chapter pairs with KNOWN ground truth,
run end-to-end against the live proposer/arbiter pipeline (real extraction, real
LLM calls, no mocking) so prompt/model changes can be checked for regressions
instead of judged by vibes.

Each case is a pair of short chapters plus a verdict this system SHOULD reach:
  - positive cases: a genuine, unexplained contradiction that must be CONFIRMed
  - negative cases: a near-miss that must NOT be CONFIRMed (synonym, death as
    plot progression, added descriptive detail, ordinary time/travel drift) —
    these are exactly the situations the old hardcoded NEVER/ALWAYS rule lists
    used to hardcode; here the model has to get them right through judgment.

For each case: create a fresh project, ingest chapter A then chapter B, and
check whether a CONFIRMed contradiction on the expected field exists (positive
cases) or whether NO CONFIRMed contradiction exists at all (negative cases).
Prints a per-case PASS/FAIL report plus aggregate precision/recall/false-positive
rate, and exits non-zero if anything failed.

Run: python scripts/eval_contradictions.py
Requires: server running at http://localhost:8000
"""
from __future__ import annotations
import sys
import time
from dataclasses import dataclass, field

import httpx

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = "http://localhost:8000"
RATE_LIMIT_SLEEP = 5  # seconds between calls, to respect the free-tier LLM


@dataclass
class Case:
    name: str
    ch_a_text: str
    ch_b_text: str
    expect_contradiction: bool
    expected_field: str = ""   # substring match against c["field"]; only used when expect_contradiction
    note: str = ""


CASES: list[Case] = [
    # ── Positive cases: genuine, unexplained contradictions ──────────────────
    Case(
        name="eye color changes with no explanation",
        ch_a_text="Marcus is a young guard with sharp blue eyes and short black hair. "
                   "He stands watch at the north gate every night.",
        ch_b_text="Marcus paced along the north gate, his grey eyes scanning the horizon for movement.",
        expect_contradiction=True,
        expected_field="eye_color",
        note="blue -> grey, no in-story reason",
    ),
    Case(
        name="dead man walking",
        ch_a_text="Old Tomas the blacksmith fell from the tower and was pronounced dead at dawn. "
                   "His funeral was held by the river.",
        ch_b_text="Tomas the blacksmith hammered away at his forge, sparks flying, as busy as ever.",
        expect_contradiction=True,
        expected_field="status",
        note="confirmed dead, then alive and working with no resurrection explained",
    ),
    Case(
        name="destroyed prop reappears intact",
        ch_a_text="The soldiers burned the ancient banner of House Voss to ashes in the courtyard, "
                   "ending its three-hundred-year history.",
        ch_b_text="Lord Voss raised the ancient banner high above the battlements, its fabric unmarked by flame.",
        expect_contradiction=True,
        expected_field="status",
        note="banner destroyed, then intact with no explanation",
    ),
    Case(
        name="hair color changes with no explanation",
        ch_a_text="Elena wore her long red hair in a braid as she crossed the market square.",
        ch_b_text="Elena brushed a strand of jet-black hair from her face and smiled.",
        expect_contradiction=True,
        expected_field="hair_color",
        note="red -> black, no in-story reason",
    ),

    # ── Negative cases: near-misses that must NOT be confirmed ───────────────
    Case(
        name="synonym / rephrasing of occupation",
        ch_a_text="Captain Reyes was the ship's stern detective, always suspicious of the crew.",
        ch_b_text="Reyes, the ship's shrewd investigator, questioned every sailor twice.",
        expect_contradiction=False,
        note="detective / investigator — same role, reworded",
    ),
    Case(
        name="death as ordinary plot progression",
        ch_a_text="Sir Aldric fought bravely at the gates, his sword flashing in the torchlight.",
        ch_b_text="Sir Aldric succumbed to his wounds that night and was buried beneath the old oak.",
        expect_contradiction=False,
        note="alive -> dead is a plot event, not a contradiction",
    ),
    Case(
        name="description gains detail",
        ch_a_text="They approached a stone cottage at the edge of the forest.",
        ch_b_text="They approached the stone cottage, its walls grown thick with ivy and its chimney "
                   "streaked with soot, nestled at the edge of the forest.",
        expect_contradiction=False,
        note="richer description of the same place, not a conflict",
    ),
    Case(
        name="ordinary age drift after time passes",
        ch_a_text="Wren, twenty-five years old, sharpened her twin blades before the tournament.",
        ch_b_text="A year had passed. Wren, twenty-six now, entered the arena once more.",
        expect_contradiction=False,
        note="one year of age drift, explicitly explained by elapsed time",
    ),
    Case(
        name="location change via travel",
        ch_a_text="Captain Reyes stood on the deck as the ship left the harbor of Port Callow.",
        ch_b_text="Three days later, Captain Reyes walked the crowded streets of Ashford, far from the sea.",
        expect_contradiction=False,
        note="location differs because the character traveled, not a contradiction",
    ),
]


def _create_project(client: httpx.Client, title: str) -> int:
    r = client.post("/projects", json={"title": title})
    r.raise_for_status()
    return r.json()["id"]


def _ingest(client: httpx.Client, pid: int, number: int, text: str) -> dict:
    r = client.post(f"/projects/{pid}/chapters", json={"number": number, "text": text})
    r.raise_for_status()
    return r.json()


@dataclass
class CaseResult:
    case: Case
    passed: bool
    confirmed: list[dict] = field(default_factory=list)
    rejected: list[dict] = field(default_factory=list)
    error: str = ""


def run_case(client: httpx.Client, case: Case) -> CaseResult:
    try:
        pid = _create_project(client, f"Eval — {case.name}")
        _ingest(client, pid, 1, case.ch_a_text)
        time.sleep(RATE_LIMIT_SLEEP)
        data = _ingest(client, pid, 2, case.ch_b_text)
    except httpx.HTTPStatusError as exc:
        return CaseResult(case=case, passed=False, error=f"HTTP error: {exc}")
    except Exception as exc:
        return CaseResult(case=case, passed=False, error=f"{type(exc).__name__}: {exc}")

    contradictions = data.get("contradictions_found", [])
    confirmed = [c for c in contradictions if c.get("verdict") == "CONFIRM"]
    rejected = [c for c in contradictions if c.get("verdict") != "CONFIRM"]

    if case.expect_contradiction:
        passed = any(case.expected_field.lower() in c["field"].lower() for c in confirmed)
    else:
        passed = len(confirmed) == 0

    return CaseResult(case=case, passed=passed, confirmed=confirmed, rejected=rejected)


def print_case_result(result: CaseResult) -> None:
    status = "PASS" if result.passed else "FAIL"
    kind = "POSITIVE" if result.case.expect_contradiction else "NEGATIVE"
    print(f"\n[{status}] ({kind}) {result.case.name}")
    print(f"    note: {result.case.note}")

    if result.error:
        print(f"    ERROR: {result.error}")
        return

    if result.confirmed:
        for c in result.confirmed:
            print(
                f"    CONFIRMED  field={c['field']!r} severity={c['severity']} "
                f"confidence={c['confidence']:.2f}  '{c['value_a']}' -> '{c['value_b']}'"
            )
    if result.rejected:
        for c in result.rejected:
            print(
                f"    rejected   field={c['field']!r} severity={c['severity']} "
                f"confidence={c['confidence']:.2f}  '{c['value_a']}' -> '{c['value_b']}'"
            )
    if not result.confirmed and not result.rejected:
        print("    (no candidates proposed)")


def print_summary(results: list[CaseResult]) -> None:
    tp = sum(1 for r in results if r.case.expect_contradiction and r.passed)
    fn = sum(1 for r in results if r.case.expect_contradiction and not r.passed)
    tn = sum(1 for r in results if not r.case.expect_contradiction and r.passed)
    fp = sum(1 for r in results if not r.case.expect_contradiction and not r.passed)

    precision = tp / (tp + fp) if (tp + fp) else float("nan")
    recall = tp / (tp + fn) if (tp + fn) else float("nan")
    fp_rate = fp / (tn + fp) if (tn + fp) else float("nan")

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"  True positives (caught real contradictions) : {tp}")
    print(f"  False negatives (missed real contradictions): {fn}")
    print(f"  True negatives (correctly stayed silent)    : {tn}")
    print(f"  False positives (hallucinated contradictions): {fp}")
    print(f"  Precision: {precision:.2f}   Recall: {recall:.2f}   "
          f"Hallucination rate on negatives: {fp_rate:.2f}")

    failed = [r for r in results if not r.passed]
    if failed:
        print(f"\n  {len(failed)}/{len(results)} case(s) FAILED:")
        for r in failed:
            print(f"    - {r.case.name}")
    else:
        print(f"\n  All {len(results)} cases passed.")


def main():
    client = httpx.Client(base_url=BASE, timeout=300)
    results: list[CaseResult] = []

    print(f"Running {len(CASES)} eval cases against {BASE} ...")
    for case in CASES:
        result = run_case(client, case)
        results.append(result)
        print_case_result(result)
        time.sleep(RATE_LIMIT_SLEEP)

    print_summary(results)

    if any(not r.passed for r in results):
        sys.exit(1)


if __name__ == "__main__":
    main()
