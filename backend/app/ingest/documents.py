"""PDF / Word / 文本合同解析与切块。

合同属于非结构化数据，不建业务表，而是抽取文本后按语义块存入
document_chunks，供 Agent 检索条款原文。
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass
from pathlib import Path

SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".txt"}
MAX_CHARS = 420
OVERLAP = 80


@dataclass
class TextChunk:
    index: int
    content: str
    page: int | None = None


@dataclass
class ParsedDocument:
    name: str
    doc_type: str
    page_count: int
    char_count: int
    chunks: list[TextChunk]


def _normalize(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _split_paragraphs(text: str, size: int = MAX_CHARS) -> list[str]:
    paragraphs = [item.strip() for item in re.split(r"\n+", text) if item.strip()]
    pieces: list[str] = []
    for paragraph in paragraphs:
        if len(paragraph) <= size:
            pieces.append(paragraph)
            continue
        start = 0
        while start < len(paragraph):
            pieces.append(paragraph[start : start + size])
            start += size - OVERLAP
    return pieces


def _chunk_text(text: str, page: int | None = None, start_index: int = 0) -> list[TextChunk]:
    pieces = _split_paragraphs(_normalize(text))
    chunks: list[TextChunk] = []
    buffer = ""

    def flush() -> None:
        nonlocal buffer
        if buffer.strip():
            chunks.append(
                TextChunk(index=start_index + len(chunks), content=buffer.strip(), page=page)
            )
        buffer = ""

    for piece in pieces:
        if not buffer:
            buffer = piece
        elif len(buffer) + len(piece) + 1 <= MAX_CHARS:
            buffer = f"{buffer}\n{piece}"
        else:
            flush()
            buffer = piece
    flush()
    return chunks


def _parse_pdf(content: bytes) -> tuple[int, list[TextChunk]]:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(content))
    chunks: list[TextChunk] = []
    for page_number, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        chunks.extend(_chunk_text(text, page=page_number, start_index=len(chunks)))
    return len(reader.pages), chunks


def _parse_docx(content: bytes) -> tuple[int, list[TextChunk]]:
    from docx import Document as DocxDocument

    document = DocxDocument(io.BytesIO(content))
    parts = [paragraph.text for paragraph in document.paragraphs if paragraph.text.strip()]
    for table in document.tables:
        for row in table.rows:
            cells = [cell.text.strip() for cell in row.cells if cell.text.strip()]
            if cells:
                parts.append(" | ".join(cells))
    # Word 没有稳定的页概念，page 留空。
    return 0, _chunk_text("\n".join(parts))


def parse_document(filename: str, content: bytes) -> ParsedDocument:
    extension = Path(filename).suffix.lower()
    if extension not in SUPPORTED_EXTENSIONS:
        raise ValueError("文档仅支持 .pdf / .docx / .txt 格式。")

    if extension == ".pdf":
        page_count, chunks = _parse_pdf(content)
    elif extension == ".docx":
        page_count, chunks = _parse_docx(content)
    else:
        text = None
        for encoding in ("utf-8-sig", "utf-8", "gbk"):
            try:
                text = content.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        if text is None:
            raise ValueError("无法识别文本编码，请另存为 UTF-8。")
        page_count, chunks = 0, _chunk_text(text)

    char_count = sum(len(chunk.content) for chunk in chunks)
    if not chunks:
        raise ValueError("没有从文档中提取到可用文本（可能是扫描版 PDF）。")

    return ParsedDocument(
        name=Path(filename).stem or "未命名文档",
        doc_type=extension.lstrip("."),
        page_count=page_count,
        char_count=char_count,
        chunks=chunks,
    )
