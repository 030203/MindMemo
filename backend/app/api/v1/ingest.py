import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import get_db
from app.core.deps import get_current_user_id
from app.schemas.common import ApiResponse
from app.schemas.memory import MemoryDetail, UrlIngestRequest
from app.services.ingestion_service import ingestion_service
from app.services.memory_service import memory_service

router = APIRouter()

IMAGE_EXTENSIONS_BY_MIME = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "image/bmp": ".bmp",
}
IMAGE_EXTENSIONS = set(IMAGE_EXTENSIONS_BY_MIME.values()) | {".jpeg"}


def _safe_filename(file_name: str | None, fallback: str) -> str:
    safe = Path((file_name or fallback).strip() or fallback).name
    return safe[:120] or fallback


def _image_extension(file: UploadFile) -> str:
    content_type = (file.content_type or "").split(";", 1)[0].strip().lower()
    if content_type in IMAGE_EXTENSIONS_BY_MIME:
        return IMAGE_EXTENSIONS_BY_MIME[content_type]

    suffix = Path(file.filename or "").suffix.lower()
    if suffix in IMAGE_EXTENSIONS:
        return ".jpg" if suffix == ".jpeg" else suffix

    raise HTTPException(status_code=400, detail="Only PNG, JPEG, WebP, GIF, and BMP images are supported")


@router.post("/url")
def ingest_url(
    payload: UrlIngestRequest,
    db: Session = Depends(get_db),
    user_id=Depends(get_current_user_id),
) -> ApiResponse[MemoryDetail]:
    try:
        extracted = ingestion_service.ingest_url(payload.url, payload.title)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    memory = memory_service.create_ingested_memory(
        db,
        user_id,
        title=extracted.title,
        content=extracted.content,
        category=payload.category,
        source_type="url",
        time_info={"source_url": extracted.source_url},
    )
    return ApiResponse(data=memory)


@router.post("/pdf")
async def ingest_pdf(
    file: UploadFile = File(...),
    title: str | None = Form(default=None),
    category: str = Form(default="learning"),
    db: Session = Depends(get_db),
    user_id=Depends(get_current_user_id),
) -> ApiResponse[MemoryDetail]:
    try:
        extracted = await ingestion_service.ingest_pdf(file, title)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    memory = memory_service.create_ingested_memory(
        db,
        user_id,
        title=extracted.title,
        content=extracted.content,
        category=category,
        source_type="pdf",
        time_info={
            "file_name": extracted.file_name,
            "page_count": extracted.page_count,
        },
    )
    return ApiResponse(data=memory)


@router.post("/document")
async def ingest_document(
    file: UploadFile = File(...),
    title: str | None = Form(default=None),
    note: str | None = Form(default=None),
    category: str = Form(default="memo"),
    db: Session = Depends(get_db),
    user_id=Depends(get_current_user_id),
) -> ApiResponse[MemoryDetail]:
    try:
        extracted = await ingestion_service.ingest_document(file, title, note)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    memory = memory_service.create_ingested_memory(
        db,
        user_id,
        title=extracted.title,
        content=extracted.content,
        category=category,
        source_type="file",
        time_info={
            "file_name": extracted.file_name,
            "mime_type": extracted.mime_type,
            "file_size": extracted.file_size,
            "attachment_kind": "document",
        },
    )
    return ApiResponse(data=memory)


@router.post("/image")
async def ingest_image(
    file: UploadFile = File(...),
    title: str | None = Form(default=None),
    note: str | None = Form(default=None),
    category: str = Form(default="memo"),
    db: Session = Depends(get_db),
    user_id=Depends(get_current_user_id),
) -> ApiResponse[MemoryDetail]:
    extension = _image_extension(file)
    original_name = _safe_filename(file.filename, f"screenshot{extension}")
    raw_bytes = await file.read()
    if not raw_bytes:
        raise HTTPException(status_code=400, detail="Image file is empty")
    if len(raw_bytes) > settings.max_image_upload_bytes:
        raise HTTPException(status_code=413, detail="Image file is too large")

    upload_dir = Path(settings.upload_root).resolve() / "memories" / str(user_id)
    upload_dir.mkdir(parents=True, exist_ok=True)
    stored_name = f"{uuid.uuid4().hex}{extension}"
    (upload_dir / stored_name).write_bytes(raw_bytes)

    content_type = (file.content_type or "").split(";", 1)[0].strip().lower() or "image/unknown"
    public_url = f"/uploads/memories/{user_id}/{stored_name}"
    attachment_line = f"附件：{original_name}（{content_type}）"
    content = "\n\n".join(part for part in [(note or "").strip(), attachment_line] if part)
    try:
        memory = memory_service.create_ingested_memory(
            db,
            user_id,
            title=(title or "").strip() or f"截图：{original_name}",
            content=content,
            category=category,
            source_type="image",
            time_info={
                "file_name": original_name,
                "source_url": public_url,
                "mime_type": content_type,
                "file_size": len(raw_bytes),
                "attachment_kind": "image",
            },
        )
    except Exception:
        (upload_dir / stored_name).unlink(missing_ok=True)
        raise
    return ApiResponse(data=memory)
