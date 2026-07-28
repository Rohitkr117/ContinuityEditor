import httpx, json, sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

client = httpx.Client(base_url="http://localhost:8000", timeout=30)
r = client.post("/projects/12/recall", json={})
data = r.json()

print("=== PROJECT 12 CONTRADICTIONS ===")
for c in data.get("contradictions", []):
    print(f"\n[{c['severity']}] Field: {c['field']}")
    print(f"  Ch.{c['chapter_a_number']} ({c['value_a']!r}) -> Ch.{c['chapter_b_number']} ({c['value_b']!r})")
    print(f"  Reason: {c.get('reason')}")
    print(f"  Quote A: {c.get('quote_a')!r}")
    print(f"  Quote B: {c.get('quote_b')!r}")
