# Image upload API (FastAPI + Cloudinary only)

1. Browser sends image to this API (`POST /upload`).
2. API uploads to **Cloudinary** and appends a row to **`data/records.json`** on disk.
3. **Render logs** print a line like `[upload] OK id=... url=https://res.cloudinary.com/...`

**No Firebase.** On Render, remove any `FIREBASE_*` env vars.

## Environment

| Variable | Description |
|----------|-------------|
| `CLOUDINARY_CLOUD_NAME` | Cloudinary dashboard |
| `CLOUDINARY_API_KEY` | Cloudinary dashboard |
| `CLOUDINARY_API_SECRET` | Cloudinary dashboard |
| `FRONTEND_ORIGIN` | Your Vercel URL or `*` |
| `RECORDS_PATH` | **Optional.** Full path to `records.json`. Default: `data/records.json` next to `main.py`. Set a path under a **persistent disk** on Render if you need history to survive restarts. |

## Render

- **Root Directory:** empty (repo root = this folder).
- **Build:** `pip install -r requirements.txt`
- **Start:** `uvicorn main:app --host 0.0.0.0 --port $PORT`

Disk is ephemeral on free tier; `records.json` resets if the instance is wiped. For durable history, add a DB later.

## API

- `GET /health` → `{"status":"ok"}`
- `POST /upload` (multipart `file`) → `{ success, message, id, image_url }`
- `GET /records` → `{ records: [...] }`
