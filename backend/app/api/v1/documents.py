from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.schemas import DocumentOut, DocumentPageOut, DocumentPagesOut
from app.core.config import get_settings
from app.core.security import AuthUser, client_ip, get_current_user, require_admin
from app.db.models import Document
from app.db.session import SessionLocal, get_db
from app.ingest.documents import SUPPORTED_EXTENSIONS, parse_document
from app.services.audit import DOCUMENT_DELETE, DOCUMENT_UPLOAD, log_action
from app.services.documents import (
    DocumentMeta,
    create_document,
    delete_document,
    document_pages,
    list_documents,
)

router = APIRouter(tags=["documents"])


def _to_out(document: DocumentMeta) -> DocumentOut:
    return DocumentOut(
        id=document.id,
        name=document.name,
        source_file=document.source_file,
        doc_type=document.doc_type,
        page_count=document.page_count,
        char_count=document.char_count,
        chunk_count=document.chunk_count,
        created_at=document.created_at,
        status=document.status,
    )


@router.get("/documents", response_model=list[DocumentOut])
async def get_documents(
    db: AsyncSession = Depends(get_db),
    _current: AuthUser = Depends(get_current_user),
) -> list[DocumentOut]:
    return [_to_out(document) for document in await list_documents(db)]


@router.post("/documents", response_model=DocumentOut, status_code=201)
async def upload_document(
    request: Request,
    file: UploadFile = File(...),
    admin: AuthUser = Depends(require_admin),
) -> DocumentOut:
    filename = file.filename or "document"
    extension = Path(filename).suffix.lower()
    if extension not in SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail="仅支持 .pdf / .docx / .txt（旧版 .doc 请先另存为 .docx）。",
        )

    settings = get_settings()
    content = await file.read()
    if len(content) == 0:
        raise HTTPException(status_code=400, detail="文件为空。")
    if len(content) > settings.upload_max_mb * 1024 * 1024:
        raise HTTPException(
            status_code=413, detail=f"文件超过 {settings.upload_max_mb} MB 限制。"
        )

    try:
        parsed = parse_document(filename, content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"文档解析失败：{exc}") from exc

    try:
        async with SessionLocal() as session:
            async with session.begin():
                document = await create_document(session, filename, parsed)
                await log_action(
                    session,
                    actor=admin,
                    action=DOCUMENT_UPLOAD,
                    target_type="document",
                    target_id=document.id,
                    detail={
                        "name": document.name,
                        "filename": filename,
                        "chunk_count": document.chunk_count,
                    },
                    ip=client_ip(request),
                )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"写入数据库失败：{exc}") from exc

    return _to_out(document)


@router.get("/documents/{document_id}/pages", response_model=DocumentPagesOut)
async def get_document_pages(
    document_id: str,
    db: AsyncSession = Depends(get_db),
    _current: AuthUser = Depends(get_current_user),
) -> DocumentPagesOut:
    meta, pages = await document_pages(db, document_id)
    if meta is None:
        raise HTTPException(status_code=404, detail="文档不存在。")
    return DocumentPagesOut(
        id=meta.id,
        name=meta.name,
        page_count=meta.page_count,
        pages=[DocumentPageOut(page=int(item["page"]), content=str(item["content"])) for item in pages],
    )


@router.delete("/documents/{document_id}", status_code=204)
async def remove_document(
    document_id: str,
    request: Request,
    admin: AuthUser = Depends(require_admin),
) -> None:
    try:
        uuid.UUID(document_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="无效的文档 ID。") from exc

    async with SessionLocal() as session:
        async with session.begin():
            document = await session.get(Document, uuid.UUID(document_id))
            if document is None:
                raise HTTPException(status_code=404, detail="文档不存在。")
            detail = {
                "name": document.name,
                "source_file": document.source_file,
                "chunk_count": document.chunk_count,
            }
            removed = await delete_document(session, document_id)
            if removed:
                await log_action(
                    session,
                    actor=admin,
                    action=DOCUMENT_DELETE,
                    target_type="document",
                    target_id=document_id,
                    detail=detail,
                    ip=client_ip(request),
                )

    if not removed:
        raise HTTPException(status_code=404, detail="文档不存在。")
