# Backend Deployment & Extension Connection Guide

This guide is for the developer responsible for taking the Continuity Editor FastAPI backend from `localhost` and deploying it to a remote server (e.g., AWS EC2, Render, Heroku).

## 1. Extension <-> Backend Architecture

The Google Docs Chrome Extension is completely stateless and serverless. All logic, memory graph management, and LLM processing happens on the FastAPI backend.

The extension communicates with the backend exclusively via REST API. 

The primary endpoints used by the extension are:
- `GET /health`: Used to verify the backend is online when the popup opens.
- `GET /projects`: Fetches the list of manuscript projects to display in the dropdown.
- `POST /projects`: Creates a new project from the extension popup.
- `POST /projects/{project_id}/extension/sync`: Syncs new document text to the knowledge graph.
- `POST /projects/{project_id}/recall`: Fetches all permanent, confirmed project contradictions to display in the extension sidebar.

## 2. CORS Configuration (CRITICAL)

Because the Chrome Extension runs inside a Google Docs tab, its origin is `https://docs.google.com`. 
To allow the extension to communicate with your deployed backend, **CORS must be correctly configured**.

The backend already handles this in `app/main.py`:
```python
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:8000",
        "https://docs.google.com" # Required for the Chrome Extension content scripts!
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```
*Note: If you change domains or want to allow other frontends, ensure you update the `allow_origins` list before deploying.*

## 3. Deploying the Backend

1. **Environment Variables**: Ensure you securely provide the `.env` variables on your production server.
   - `OPENAI_API_KEY` or `LLM_API_KEY` (depending on your setup)
   - `OPENAI_BASE_URL` (if using custom inference endpoints like AWS Bedrock)
   - `DATABASE_URL` (SQLite is fine for dev, but consider PostgreSQL for prod: `postgresql+asyncpg://user:pass@host/db`)
   - `DATA_ROOT_DIRECTORY` (Ensure this directory exists and is writable on your server).

2. **Running the Server**: 
   - Locally, you use `uvicorn app.main:app --reload`.
   - In production, it's recommended to run with Gunicorn + Uvicorn workers:
     `gunicorn app.main:app -w 4 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:80`

3. **HTTPS / SSL**:
   Chrome Extensions **block mixed content**. If you deploy the backend, it **must** be served over HTTPS (e.g., `https://api.yourdomain.com`). If you try to connect the extension on `https://docs.google.com` to an `http://` IP address, Chrome will block the requests.
   - Use an Application Load Balancer, Nginx reverse proxy with Certbot, or a PaaS like Render that handles SSL automatically.

## 4. Connecting the Extension

Once your backend is deployed and accessible via HTTPS:
1. Open Google Chrome.
2. Click the Continuity Editor extension icon to open the popup.
3. In the **Backend URL** field, replace `http://localhost:8000` with your new production URL (e.g., `https://api.yourdomain.com`).
4. Click **Save**.
5. The badge below it should change to a green **Connected** status. The extension is now successfully routing all traffic to the remote server!
