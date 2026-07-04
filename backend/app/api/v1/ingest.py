import logging
import uuid
from pathlib import Path

logger = logging.getLogger(__name__)

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import get_db
from app.core.deps import get_current_user_id
from app.schemas.common import ApiResponse
from app.schemas.memory import MemoryDetail, TextIngestRequest, TextIngestResult, UrlIngestRequest
from app.services.ingestion_service import ingestion_service
from app.services.memory_service import memory_service
from app.services.insight_agent_service import insight_agent
from app.services.todo_service import todo_service

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


def _maybe_trigger_insight(db: Session, user_id: uuid.UUID):
    """在后台触发洞察生成，不阻塞请求。"""
    try:
        import asyncio
        asyncio.ensure_future(insight_agent.generate_insight(db=db, user_id=user_id, days=7))
    except Exception:
        pass


@router.post("/url")
def ingest_url(
    payload: UrlIngestRequest,
    background_tasks: BackgroundTasks,
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
    background_tasks.add_task(_maybe_trigger_insight, db, user_id)
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
    _maybe_trigger_insight(db, user_id)
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
    _maybe_trigger_insight(db, user_id)
    return ApiResponse(data=memory)


@router.post("/text")
def ingest_text(
    payload: TextIngestRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user_id=Depends(get_current_user_id),
) -> ApiResponse[TextIngestResult]:
    title = (payload.title or "").strip() or payload.content[:60]

    memory = memory_service.create_ingested_memory(
        db,
        user_id,
        title=title,
        content=payload.content,
        category="memo",
        source_type="text",
        time_info={},
    )

    todo_id: str | None = None
    if payload.record_type in ("todo", "reminder"):
        todo = todo_service.create_from_ingest(
            db,
            user_id=user_id,
            source_memory_id=memory.id,
            title=title,
            due_at=payload.due_at,
            remind_at=payload.remind_at if payload.record_type == "reminder" else None,
        )
        todo_id = str(todo.id)

    background_tasks.add_task(_maybe_trigger_insight, db, user_id)
    return ApiResponse(data=TextIngestResult(
        memory_id=str(memory.id),
        todo_id=todo_id,
        record_type=payload.record_type,
    ))


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
    _maybe_trigger_insight(db, user_id)
    return ApiResponse(data=memory)


@router.post("/capture")
async def ingest_capture(
    background_tasks: BackgroundTasks,
    content: str = Form(...),
    record_type: str = Form(default="memo"),
    title: str | None = Form(default=None),
    due_at: str | None = Form(default=None),
    remind_at: str | None = Form(default=None),
    files: list[UploadFile] = File(default=[]),
    db: Session = Depends(get_db),
    user_id=Depends(get_current_user_id),
) -> ApiResponse[TextIngestResult]:
    """Quick-capture endpoint that accepts text + optional file attachments via multipart."""
    from datetime import datetime as _dt

    parsed_due_at = None
    parsed_remind_at = None
    if due_at:
        try:
            parsed_due_at = _dt.fromisoformat(due_at.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            pass
    if remind_at:
        try:
            parsed_remind_at = _dt.fromisoformat(remind_at.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            pass

    # Process file attachments
    time_info: dict = {}
    attachment_lines: list[str] = []
    extracted_texts: list[str] = []
    saved_paths: list[Path] = []

    for upload in files:
        if not upload.filename:
            continue
        raw_bytes = await upload.read()
        if not raw_bytes:
            continue

        content_type = (upload.content_type or "").split(";", 1)[0].strip().lower()
        original_name = _safe_filename(upload.filename, "attachment")

        # Determine if this is an image
        is_image = content_type.startswith("image/")
        ext = ""
        if is_image:
            try:
                ext = _image_extension(upload)
            except HTTPException:
                ext = Path(original_name).suffix or ".png"
        else:
            ext = Path(original_name).suffix or ".bin"

        upload_dir = Path(settings.upload_root).resolve() / "memories" / str(user_id)
        upload_dir.mkdir(parents=True, exist_ok=True)
        stored_name = f"{uuid.uuid4().hex}{ext}"
        file_path = upload_dir / stored_name
        file_path.write_bytes(raw_bytes)
        saved_paths.append(file_path)

        public_url = f"/uploads/memories/{user_id}/{stored_name}"
        attachment_lines.append(f"附件：{original_name}（{content_type}）")

        # Extract text from non-image files
        file_extracted_text = ""
        if not is_image:
            try:
                if content_type == "application/pdf" or original_name.lower().endswith(".pdf"):
                    from pypdf import PdfReader as _PdfReader
                    import io as _io
                    reader = _PdfReader(_io.BytesIO(raw_bytes))
                    pages_text = []
                    for page in reader.pages:
                        t = page.extract_text()
                        if t:
                            pages_text.append(t)
                    file_extracted_text = "\n".join(pages_text)
                elif (
                    content_type.startswith("text/")
                    or Path(original_name).suffix.lower() in {".md", ".markdown", ".txt", ".csv", ".json", ".yaml", ".yml", ".log"}
                    or content_type in {"application/json", "text/csv"}
                    or content_type.startswith("application/vnd.openxmlformats-officedocument")
                ):
                    file_ext = Path(original_name).suffix.lower()
                    if file_ext == ".docx" or content_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
                        file_extracted_text = ingestion_service._extract_docx_text(raw_bytes)
                    else:
                        file_extracted_text = ingestion_service._decode_text_bytes(raw_bytes)
            except Exception as exc:
                logger.warning(f"Text extraction failed for {original_name}: {exc}")
                file_extracted_text = ""

        if file_extracted_text:
            # Normalize whitespace
            import re as _re
            lines = [_re.sub(r"\s+", " ", line).strip() for line in file_extracted_text.splitlines()]
            file_extracted_text = "\n".join(line for line in lines if line)
            extracted_texts.append(file_extracted_text)

        # Store the first file's metadata in time_info (primary attachment)
        if "file_name" not in time_info:
            time_info["file_name"] = original_name
            time_info["source_url"] = public_url
            time_info["mime_type"] = content_type
            time_info["file_size"] = len(raw_bytes)
            time_info["attachment_kind"] = "image" if is_image else "document"

    # Build content: user text + attachment lines + extracted document texts
    parts: list[str] = []
    if content.strip():
        parts.append(content.strip())
    parts.extend(attachment_lines)
    parts.extend(extracted_texts)
    full_content = "\n\n".join(parts)

    resolved_title = (title or "").strip() or content.strip()[:60] or "未命名记录"

    # Determine source_type based on primary attachment
    source_type = time_info.get("attachment_kind", "text") if time_info else "text"

    try:
        memory = memory_service.create_ingested_memory(
            db,
            user_id,
            title=resolved_title,
            content=full_content,
            category="memo",
            source_type=source_type,
            time_info=time_info,
        )
    except Exception:
        for p in saved_paths:
            p.unlink(missing_ok=True)
        raise

    todo_id: str | None = None
    if record_type in ("todo", "reminder"):
        todo = todo_service.create_from_ingest(
            db,
            user_id=user_id,
            source_memory_id=memory.id,
            title=resolved_title,
            due_at=parsed_due_at,
            remind_at=parsed_remind_at if record_type == "reminder" else None,
        )
        todo_id = str(todo.id)

    background_tasks.add_task(_maybe_trigger_insight, db, user_id)
    return ApiResponse(data=TextIngestResult(
        memory_id=str(memory.id),
        todo_id=todo_id,
        record_type=record_type,
    ))
