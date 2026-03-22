"""
FastAPI image upload API: Cloudinary (images) + Firestore (metadata).
"""

from __future__ import annotations

import os
import re
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

import cloudinary
import cloudinary.uploader
from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# Firebase Admin (Firestore only — no Firebase Storage required on Spark)
_firebase_ready = False
_cloudinary_configured = False


def _resolve_key_path() -> Path:
    raw = os.getenv("FIREBASE_KEY_PATH", "./firebase_key.json")
    p = Path(raw)
    if not p.is_absolute():
        p = (BASE_DIR / p).resolve()
    return p


def init_cloudinary() -> None:
    global _cloudinary_configured
    if _cloudinary_configured:
        return
    name = os.getenv("CLOUDINARY_CLOUD_NAME", "").strip()
    key = os.getenv("CLOUDINARY_API_KEY", "").strip()
    secret = os.getenv("CLOUDINARY_API_SECRET", "").strip()
    if not (name and key and secret):
        raise RuntimeError(
            "Set CLOUDINARY_CLOUD_NAME, CLOUDINARY_API_KEY, CLOUDINARY_API_SECRET on Render"
        )
    cloudinary.config(cloud_name=name, api_key=key, api_secret=secret)
    _cloudinary_configured = True


def init_firebase() -> None:
    global _firebase_ready
    if _firebase_ready:
        return
    import firebase_admin
    from firebase_admin import credentials

    key_path = _resolve_key_path()
    if not key_path.is_file():
        raise RuntimeError(f"Firebase key not found at: {key_path}")

    if not firebase_admin._apps:
        cred = credentials.Certificate(str(key_path))
        bucket = os.getenv("FIREBASE_BUCKET", "").strip()
        if bucket:
            firebase_admin.initialize_app(cred, {"storageBucket": bucket})
        else:
            firebase_admin.initialize_app(cred)
    _firebase_ready = True


def get_db():
    from firebase_admin import firestore

    init_firebase()
    return firestore.client()


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
    return {
        "service": "image-upload-api",
        "version": "2-cloudinary",
        "status": "running",
        "storage": "cloudinary",
        "docs": "/docs",
        "health": "/health",
        "hint": "The React UI is separate: run `npm run dev` in frontend/ (port 5173) or open your Vercel URL.",
    }


@app.head("/")
def head_root():
    return Response(status_code=200)


@app.head("/health")
def head_health():
    return Response(status_code=200)


@app.on_event("startup")
def startup() -> None:
    if os.getenv("SKIP_FIREBASE_INIT", "").lower() in ("1", "true", "yes"):
        return
    try:
        init_firebase()
    except Exception as e:
        print(f"[startup] Firebase (Firestore) not initialized: {e}")
    try:
        init_cloudinary()
    except Exception as e:
        print(f"[startup] Cloudinary not configured: {e}")


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
        init_cloudinary()
        init_firebase()

        result = cloudinary.uploader.upload(
            str(local_path),
            folder="uploads",
            resource_type="image",
            use_filename=True,
            unique_filename=True,
        )
        image_url = result.get("secure_url") or result.get("url")
        public_id = result.get("public_id", "")

        if not image_url:
            raise RuntimeError("Cloudinary did not return a URL")

        from firebase_admin import firestore as fs

        db = get_db()
        doc_ref = db.collection("uploads").document()
        doc_ref.set(
            {
                "filename": orig,
                "timestamp": fs.SERVER_TIMESTAMP,
                "firebase_url": image_url,
                "storage_path": public_id,
                "provider": "cloudinary",
            }
        )
    except Exception as e:
        print(f"[upload] error: {e!r}")
        raise HTTPException(
            status_code=500,
            detail=(
                "Upload failed (check CLOUDINARY_* and FIREBASE_KEY_PATH on Render). "
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
        "firebase_url": image_url,
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
                "provider": data.get("provider"),
            }
        )
    records.sort(key=lambda r: r.get("timestamp") or "", reverse=True)
    return {"records": records}
