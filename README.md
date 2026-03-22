# Image upload API (FastAPI + Cloudinary + Firestore)

Images go to **Cloudinary** (free tier). Metadata goes to **Firebase Firestore** (works on **Spark** — no Firebase Storage needed).

## Render — environment variables

| Variable | Description |
|----------|-------------|
| `CLOUDINARY_CLOUD_NAME` | From Cloudinary dashboard |
| `CLOUDINARY_API_KEY` | From Cloudinary dashboard |
| `CLOUDINARY_API_SECRET` | From Cloudinary dashboard |
| `FIREBASE_KEY_PATH` | Path to Firebase **service account** JSON (Secret File on Render) |
| `FRONTEND_ORIGIN` | Your Vercel URL or `*` |

`FIREBASE_BUCKET` is **optional** (not used for file storage anymore).

## Render — deploy

1. **Build:** `pip install -r requirements.txt`
2. **Start:** `uvicorn main:app --host 0.0.0.0 --port $PORT`
3. **Health check path:** `/health`

## Local

```bash
python -m venv .venv
.venv\Scripts\activate   # Windows
pip install -r requirements.txt
copy .env.example .env   # fill Cloudinary + FIREBASE_KEY_PATH
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

Place `firebase_key.json` in this directory (not committed) for Firestore.
