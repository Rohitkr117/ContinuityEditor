import httpx
client = httpx.Client(base_url="http://localhost:8000")
try:
    print("Projects:", client.get("/projects").json())
except Exception as e:
    print("Error:", e)
