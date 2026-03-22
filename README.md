# Image upload API (FastAPI + Firebase)

## Render

1. **New Web Service** → connect this repo (root = this folder if Render allows, or repo contains only `backend` files at root).
2. **Build:** `pip install -r requirements.txt`
3. **Start:** `uvicorn main:app --host 0.0.0.0 --port $PORT`
4. **Environment:** copy from `.env.example` — set `FIREBASE_BUCKET`, `FIREBASE_KEY_PATH` (path to service account JSON on the server), `FRONTEND_ORIGIN` (your Vercel URL).

## Local

```bash
python -m venv .venv
.venv\Scripts\activate   # Windows
pip install -r requirements.txt
copy .env.example .env   # then edit
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

Place `firebase_key.json` in this directory (not committed).
