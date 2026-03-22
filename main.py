"""
FastAPI: receive image → upload to Cloudinary → save metadata on disk → return URL.
Logs each successful upload to stdout (Render logs).
"""

from __future__ import annotations

import json
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


def _resolve_records_path() -> Path:
    """
    Where to store upload metadata JSON.
    Env RECORDS_PATH:
      - Absolute: e.g. /var/data/records.json (Render persistent disk mount)
      - Relative: relative to this app folder, e.g. data/records.json
    If unset: backend/data/records.json (default).
    """
    raw = os.getenv("RECORDS_PATH", "").strip()
    if raw:
        p = Path(raw)
        if not p.is_absolute():
            p = (BASE_DIR / p).resolve()
    else:
        p = BASE_DIR / "data" / "records.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


RECORDS_PATH = _resolve_records_path()

_cloudinary_configured = False


def init_cloudinary() -> None:
    global _cloudinary_configured
    if _cloudinary_configured:
        return
    name = os.getenv("CLOUDINARY_CLOUD_NAME", "").strip()
    key = os.getenv("CLOUDINARY_API_KEY", "").strip()
    secret = os.getenv("CLOUDINARY_API_SECRET", "").strip()
    if not (name and key and secret):
        raise RuntimeError(
            "Set CLOUDINARY_CLOUD_NAME, CLOUDINARY_API_KEY, CLOUDINARY_API_SECRET"
        )
    cloudinary.config(cloud_name=name, api_key=key, api_secret=secret)
    _cloudinary_configured = True


def load_records() -> list[dict]:
    if not RECORDS_PATH.is_file():
        return []
    try:
        with RECORDS_PATH.open(encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def save_records(records: list[dict]) -> None:
    with RECORDS_PATH.open("w", encoding="utf-8") as f:
        json.dump(records, f, indent=2)


def safe_filename(name: str) -> str:
    base = Path(name).name
    base = re.sub(r"[^\w.\-]", "_", base)
    return base or "image"


def parse_origins() -> list[str]:
    raw = os.getenv("FRONTEND_ORIGIN", "*").strip()
    if not raw:
        return ["*"]
    return [o.strip() for o in raw.split(",") if o.strip()]


app = FastAPI(title="Image Upload API", version="3-cloudinary-only")

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
        "version": "3-cloudinary-only",
        "status": "running",
        "storage": "cloudinary",
        "metadata": "local_json_file",
        "records_path": str(RECORDS_PATH),
        "docs": "/docs",
        "health": "/health",
    }


@app.head("/")
def head_root():
    return Response(status_code=200)


@app.head("/health")
def head_health():
    return Response(status_code=200)


@app.on_event("startup")
def startup() -> None:
    print(f"[startup] Cloudinary-only API; RECORDS_PATH={RECORDS_PATH}")
    try:
        init_cloudinary()
        print("[startup] Cloudinary OK")
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
    record_id = str(uuid.uuid4())

    try:
        with local_path.open("wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
    finally:
        await file.close()

    try:
        init_cloudinary()
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

        ts = datetime.now(timezone.utc).isoformat()
        row = {
            "id": record_id,
            "filename": orig,
            "timestamp": ts,
            "image_url": image_url,
            "public_id": public_id,
        }
        recs = load_records()
        recs.insert(0, row)
        save_records(recs)

        print(
            f"[upload] OK id={record_id} file={orig} url={image_url}",
            flush=True,
        )
    except Exception as e:
        print(f"[upload] error: {e!r}", flush=True)
        raise HTTPException(
            status_code=500,
            detail=f"Upload failed (check CLOUDINARY_* env). Error: {e!s}",
        ) from e
    finally:
        try:
            local_path.unlink(missing_ok=True)
        except OSError:
            pass

    return {
        "success": True,
        "message": "Image uploaded successfully",
        "id": record_id,
        "image_url": image_url,
    }


@app.get("/records")
def list_records():
    records = load_records()
    out = []
    for r in records:
        out.append(
            {
                "id": r.get("id"),
                "filename": r.get("filename"),
                "timestamp": r.get("timestamp"),
                "image_url": r.get("image_url"),
                "public_id": r.get("public_id"),
            }
        )
    return {"records": out}
