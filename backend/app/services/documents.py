from __future__ import annotations

import math
import re
import uuid
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Document, DocumentChunk
from app.ingest.documents import ParsedDocument

CONTRACT_KEYWORDS = (
    "合同",
    "条款",
    "配额",
    "违约",
    "付款",
    "发票",
    "招标",
    "报价",
    "承诺",
    "折扣",
    "有效期",
    "续约",
    "单价",
)


@dataclass
class DocumentMeta:
    id: str
    name: str
    source_file: str
    doc_type: str
    page_count: int
    char_count: int
    chunk_count: int
    status: str
    created_at: datetime


def wants_contracts(question: str) -> bool:
    return any(keyword in question for keyword in CONTRACT_KEYWORDS)


async def create_document(
    session: AsyncSession,
    filename: str,
    parsed: ParsedDocument,
) -> DocumentMeta:
    document = Document(
        name=parsed.name,
        source_file=filename,
        doc_type=parsed.doc_type,
        page_count=parsed.page_count,
        char_count=parsed.char_count,
        chunk_count=len(parsed.chunks),
        status="active",
        created_at=datetime.now(UTC),
    )
    session.add(document)
    await session.flush()

    session.add_all(
        [
            DocumentChunk(
                document_id=document.id,
                chunk_index=chunk.index,
                page=chunk.page,
                content=chunk.content,
            )
            for chunk in parsed.chunks
        ]
    )

    return DocumentMeta(
        id=str(document.id),
        name=document.name,
        source_file=document.source_file,
        doc_type=document.doc_type,
        page_count=document.page_count,
        char_count=document.char_count,
        chunk_count=document.chunk_count,
        status=document.status,
        created_at=document.created_at,
    )


async def list_documents(session: AsyncSession) -> list[DocumentMeta]:
    rows = list(
        (await session.execute(select(Document).order_by(Document.created_at.desc()))).scalars()
    )
    return [
        DocumentMeta(
            id=str(row.id),
            name=row.name,
            source_file=row.source_file,
            doc_type=row.doc_type,
            page_count=row.page_count,
            char_count=row.char_count,
            chunk_count=row.chunk_count,
            status=row.status,
            created_at=row.created_at,
        )
        for row in rows
    ]


async def delete_document(session: AsyncSession, document_id: str) -> bool:
    try:
        key = uuid.UUID(document_id)
    except ValueError:
        return False
    document = await session.get(Document, key)
    if document is None:
        return False
    await session.delete(document)
    return True


_CJK_RUN = re.compile(r"[一-鿿]+")
_ASCII_TOKEN = re.compile(r"[a-z0-9][a-z0-9_.+\-]*")

# 问句里的高频虚词不参与匹配，避免把无关条款也召回。
_QUESTION_FILLERS = frozenset(
    "多少 怎么 什么 哪些 哪个 哪里 为什么 为何 是否 分别 请问 一下 可以 如何 "
    "以及 我们 你们 他们 这个 那个 目前 现在 情况 相关 具体".split()
)

MAX_CHUNKS = 2000
MIN_SCORE = 0.15


def _terms(value: str) -> set[str]:
    """中文按字符二元组切分，英文/型号按词切分。"""
    normalized = value.lower()
    terms: set[str] = set()
    for run in _CJK_RUN.findall(normalized):
        terms.update(run[index : index + 2] for index in range(len(run) - 1))
    terms.difference_update(_QUESTION_FILLERS)
    terms.update(
        token for token in _ASCII_TOKEN.findall(normalized) if len(token) >= 2
    )
    return terms


def _term_weight(term: str) -> float:
    # 模型名、合同编号等英文标识比中文二元组更有区分度。
    return 2.0 if _ASCII_TOKEN.fullmatch(term) else 1.0


async def search_chunks(
    session: AsyncSession, question: str, limit: int = 5
) -> list[dict[str, object]]:
    """轻量中文条款检索：bigram 覆盖率 + IDF 加权。

    本地 PostgreSQL 以 C locale 初始化时，pg_trgm 不会为中文生成三元组，
    word_similarity 恒为 0；因此这里把候选块取回后在 Python 侧打分。
    个人项目文档量很小，最多读取 MAX_CHUNKS 个块，够用且不依赖 locale。
    """
    try:
        result = await session.execute(
            text(
                """
                SELECT d.id, d.name, c.page, c.content
                FROM document_chunks c
                JOIN documents d ON d.id = c.document_id
                WHERE d.status = 'active'
                ORDER BY d.created_at DESC, c.chunk_index
                LIMIT :max_chunks
                """
            ),
            {"max_chunks": MAX_CHUNKS},
        )
        rows = result.all()
    except Exception:
        # 文档表不存在时不影响主流程。
        return []

    question_terms = _terms(question)
    if not question_terms or not rows:
        return []

    chunks = [
        {
            "document_id": str(document_id),
            "document": name,
            "page": page,
            "content": content,
            "terms": _terms(content),
        }
        for document_id, name, page, content in rows
    ]

    # 只在问题词与文档有交集时计算 IDF，避免未命中的词稀释分数。
    document_frequency = Counter(
        term for term in question_terms for chunk in chunks if term in chunk["terms"]
    )
    total = len(chunks)

    def idf(term: str) -> float:
        return math.log((total + 1) / (document_frequency[term] + 1)) + 1.0

    denominator = sum(
        idf(term) * _term_weight(term)
        for term in question_terms
        if document_frequency[term] > 0
    )
    if denominator <= 0:
        return []

    hits: list[dict[str, object]] = []
    for chunk in chunks:
        matched = question_terms & chunk["terms"]
        if not matched:
            continue
        score = (
            sum(idf(term) * _term_weight(term) for term in matched) / denominator
        )
        if score < MIN_SCORE:
            continue
        hits.append(
            {
                "document_id": chunk["document_id"],
                "document": chunk["document"],
                "page": chunk["page"],
                "content": chunk["content"],
                "score": round(score, 4),
            }
        )

    hits.sort(key=lambda hit: float(hit["score"]), reverse=True)
    return hits[:limit]


async def document_pages(
    session: AsyncSession, document_id: str
) -> tuple[DocumentMeta | None, list[dict[str, object]]]:
    """按页聚合文档内容，供前端在引用处打开原文预览。"""
    try:
        key = uuid.UUID(document_id)
    except ValueError:
        return None, []

    document = await session.get(Document, key)
    if document is None or document.status != "active":
        return None, []

    rows = (
        await session.execute(
            select(DocumentChunk.page, DocumentChunk.content).where(
                DocumentChunk.document_id == key
            ).order_by(DocumentChunk.chunk_index)
        )
    ).all()
    pages: dict[int, list[str]] = {}
    for page, content in rows:
        pages.setdefault(int(page or 1), []).append(str(content))

    meta = DocumentMeta(
        id=str(document.id),
        name=document.name,
        source_file=document.source_file,
        doc_type=document.doc_type,
        page_count=document.page_count,
        char_count=document.char_count,
        chunk_count=document.chunk_count,
        status=document.status,
        created_at=document.created_at,
    )
    return meta, [
        {"page": page, "content": "\n".join(parts)[:20000]}
        for page, parts in sorted(pages.items())
    ]
