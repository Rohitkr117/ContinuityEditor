import httpx, json, sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

client = httpx.Client(base_url="http://localhost:8000", timeout=30)
r = client.get("/projects/12/graph")
data = r.json()

print("=== NODES ===")
for n in data["nodes"]:
    attrs = n.get("attributes", {})
    if attrs:
        print(f"  [{n['entity_type']:10s}] {n['label']}")
        for k, v in attrs.items():
            print(f"    {k}: {v}")
