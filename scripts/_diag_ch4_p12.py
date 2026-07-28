import httpx, json, sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

client = httpx.Client(base_url="http://localhost:8000", timeout=30)
# Get project 12 chapters to find the chapter IDs
r = client.get("/projects/12/chapters")
chapters = r.json()

# Let's find chapter 4's ID
ch4_id = None
for ch in chapters:
    if ch["number"] == 4:
        ch4_id = ch["id"]
        break

print(f"Chapter 4 ID: {ch4_id}")
