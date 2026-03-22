"""
FastAPI image upload API: local save, Firebase Storage + Firestore.
"""

from __future__ import annotations

import os
import re
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# Firebase (lazy init)
_firebase_ready = False


def _resolve_key_path() -> Path:
    raw = os.getenv("FIREBASE_KEY_PATH", "./firebase_key.json")
    p = Path(raw)
    if not p.is_absolute():
        p = (BASE_DIR / p).resolve()
    return p


def init_firebase() -> None:
    global _firebase_ready
    if _firebase_ready:
        return
    import firebase_admin
    from firebase_admin import credentials

    bucket = os.getenv("FIREBASE_BUCKET", "").strip()
    key_path = _resolve_key_path()
    if not bucket:
        raise RuntimeError("FIREBASE_BUCKET is not set")
    if not key_path.is_file():
        raise RuntimeError(f"Firebase key not found at: {key_path}")

    if not firebase_admin._apps:
        cred = credentials.Certificate(str(key_path))
        firebase_admin.initialize_app(cred, {"storageBucket": bucket})
    _firebase_ready = True


def get_db():
    from firebase_admin import firestore

    init_firebase()
    return firestore.client()


def get_bucket():
    from firebase_admin import storage

    init_firebase()
    return storage.bucket()


def safe_filename(name: str) -> str:
    base = Path(name).name
    base = re.sub(r"[^\w.\-]", "_", base)
    return base or "image"


def firestore_ts_to_iso(ts) -> str | None:
    if ts is None:
        return None
    if hasattr(ts, "to_datetime"):
        return ts.to_datetime().replace(tzinfo=timezone.utc).isoformat()
    if hasattr(ts, "isoformat"):
        return ts.isoformat()
    return str(ts)


def parse_origins() -> list[str]:
    raw = os.getenv("FRONTEND_ORIGIN", "*").strip()
    if not raw:
        return ["*"]
    return [o.strip() for o in raw.split(",") if o.strip()]


app = FastAPI(title="Image Upload API", version="1.0.0")

# allow_credentials=False so allow_origins=["*"] works with browsers (Vercel + Render).
# allow_origin_regex: any Vercel preview/production URL works even if FRONTEND_ORIGIN has a typo.
app.add_middleware(
    CORSMiddleware,
    allow_origins=parse_origins(),
    allow_origin_regex=r"https://.*\.vercel\.app",
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def root():
    """So opening the API base URL in a browser is not a blank 404."""
    return {
        "service": "image-upload-api",
        "status": "running",
        "docs": "/docs",
        "health": "/health",
        "hint": "The React UI is separate: run `npm run dev` in frontend/ (port 5173) or open your Vercel URL.",
    }


@app.head("/")
def head_root():
    """Render health probes use HEAD; avoid 405 on GET-only routes."""
    return Response(status_code=200)


@app.head("/health")
def head_health():
    return Response(status_code=200)


@app.on_event("startup")
def startup() -> None:
    """Fail fast if Firebase env is wrong (optional dry-run: skip if SKIP_FIREBASE_INIT=1)."""
    if os.getenv("SKIP_FIREBASE_INIT", "").lower() in ("1", "true", "yes"):
        return
    try:
        init_firebase()
    except Exception as e:
        # Allow server to start for health checks; upload will error until configured
        print(f"[startup] Firebase not initialized: {e}")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/upload")
async def upload(file: UploadFile = File(...)):
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="File must be an image")

    orig = safe_filename(file.filename or "upload.bin")
    unique = f"{uuid.uuid4().hex}_{orig}"
    local_path = UPLOAD_DIR / unique

    try:
        with local_path.open("wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
    finally:
        await file.close()

    try:
        init_firebase()

        storage_path = f"uploads/{unique}"
        bucket = get_bucket()
        blob = bucket.blob(storage_path)
        blob.upload_from_filename(str(local_path), content_type=file.content_type)
        try:
            blob.make_public()
        except Exception as e:
            # Uniform bucket-level access may block object ACLs; URL may still work with Storage rules
            print(f"[upload] make_public warning: {e}")
        firebase_url = blob.public_url
        if not firebase_url:
            firebase_url = (
                f"https://firebasestorage.googleapis.com/v0/b/{bucket.name}/o/"
                f"{storage_path.replace('/', '%2F')}?alt=media"
            )

        from firebase_admin import firestore as fs

        db = get_db()
        doc_ref = db.collection("uploads").document()
        doc_ref.set(
            {
                "filename": orig,
                "timestamp": fs.SERVER_TIMESTAMP,
                "firebase_url": firebase_url,
                "storage_path": storage_path,
            }
        )
    except Exception as e:
        print(f"[upload] error: {e!r}")
        raise HTTPException(
            status_code=500,
            detail=(
                "Upload failed (check FIREBASE_BUCKET, service account key, and Firebase Console). "
                f"Error: {e!s}"
            ),
        ) from e
    finally:
        try:
            local_path.unlink(missing_ok=True)
        except OSError:
            pass

    return {
        "success": True,
        "firebase_url": firebase_url,
        "message": "Image uploaded successfully",
        "document_id": doc_ref.id,
    }


@app.get("/records")
def list_records():
    init_firebase()
    db = get_db()
    records = []
    for doc in db.collection("uploads").stream():
        data = doc.to_dict() or {}
        records.append(
            {
                "id": doc.id,
                "filename": data.get("filename"),
                "timestamp": firestore_ts_to_iso(data.get("timestamp")),
                "firebase_url": data.get("firebase_url"),
                "storage_path": data.get("storage_path"),
            }
        )
    records.sort(key=lambda r: r.get("timestamp") or "", reverse=True)
    return {"records": records}
