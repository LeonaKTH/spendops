"""数据集注册表与物理表反射。

物理表由上传流程动态创建，列信息从 information_schema 读取，
不在代码里维护任何固定 schema。
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Dataset
from app.db.sql import comment_payload, parse_comment, qualified, quote_ident
from app.ingest.excel import ParsedSheet

SCHEMA = "ds"
NUMERIC_TYPES = {
    "smallint",
    "integer",
    "bigint",
    "decimal",
    "numeric",
    "real",
    "double precision",
    "money",
}
DATE_TYPES = {"date", "timestamp", "timestamp with time zone", "timestamp without time zone"}


@dataclass
class ReflectedColumn:
    physical: str
    display: str
    sql_type: str
    kind: str  # number | text | date
    sample: str = ""


@dataclass
class DatasetMeta:
    id: str
    name: str
    physical_table: str
    source_file: str
    sheet_name: str | None
    row_count: int
    created_at: datetime
    status: str
    owner_id: str | None = None
    content_hash: str | None = None
    quality: dict | None = None
    columns: list[ReflectedColumn] = field(default_factory=list)

    @property
    def full_table(self) -> str:
        return f"{SCHEMA}.{self.physical_table}"


def kind_of(sql_type: str) -> str:
    lowered = sql_type.lower()
    if lowered in NUMERIC_TYPES:
        return "number"
    if lowered in DATE_TYPES or lowered.startswith("timestamp"):
        return "date"
    return "text"


async def reflect_columns(session: AsyncSession) -> dict[str, list[ReflectedColumn]]:
    """一次性读取 ds schema 下所有表的列与注释，按表名分组。"""
    result = await session.execute(
        text(
            """
            SELECT c.relname AS table_name,
                   a.attname AS column_name,
                   format_type(a.atttypid, a.atttypmod) AS data_type,
                   col_description(c.oid, a.attnum) AS col_comment
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum > 0 AND NOT a.attisdropped
            WHERE n.nspname = :schema AND c.relkind = 'r'
            ORDER BY c.relname, a.attnum
            """
        ),
        {"schema": SCHEMA},
    )

    grouped: dict[str, list[ReflectedColumn]] = {}
    for table_name, column_name, data_type, comment in result.all():
        display, sample = parse_comment(comment, column_name)
        grouped.setdefault(table_name, []).append(
            ReflectedColumn(
                physical=column_name,
                display=display,
                sql_type=data_type,
                kind=kind_of(data_type),
                sample=sample,
            )
        )
    return grouped


async def load_datasets(
    session: AsyncSession,
    dataset_ids: list[str] | None = None,
    active_only: bool = True,
) -> list[DatasetMeta]:
    statement = select(Dataset).order_by(Dataset.created_at)
    if active_only:
        statement = statement.where(Dataset.status == "active")

    rows = list((await session.execute(statement)).scalars())

    if dataset_ids:
        wanted = {str(item) for item in dataset_ids}
        rows = [row for row in rows if str(row.id) in wanted]

    reflected = await reflect_columns(session)

    return [
        DatasetMeta(
            id=str(row.id),
            name=row.name,
            physical_table=row.physical_table,
            source_file=row.source_file,
            sheet_name=row.sheet_name,
            row_count=row.row_count,
            created_at=row.created_at,
            status=row.status,
            owner_id=str(row.owner_id) if row.owner_id else None,
            content_hash=row.content_hash,
            quality=row.quality,
            columns=reflected.get(row.physical_table, []),
        )
        for row in rows
    ]


async def find_dataset_by_hash(session: AsyncSession, content_hash: str) -> Dataset | None:
    """按文件指纹查已导入的数据集，用于上传幂等。"""
    if not content_hash:
        return None
    statement = (
        select(Dataset)
        .where(Dataset.content_hash == content_hash, Dataset.status == "active")
        .order_by(Dataset.created_at.desc())
        .limit(1)
    )
    return (await session.execute(statement)).scalar_one_or_none()


def _table_slug(filename: str) -> str:
    stem = filename.rsplit("/", 1)[-1].rsplit("\\", 1)[-1].rsplit(".", 1)[0]
    slug = re.sub(r"[^a-z0-9]+", "_", stem.lower()).strip("_")
    return (slug or "data")[:24]


async def create_dataset(
    session: AsyncSession,
    filename: str,
    sheet: ParsedSheet,
    owner_id: str | None = None,
    content_hash: str | None = None,
    quality: dict | None = None,
) -> DatasetMeta:
    if not sheet.columns:
        raise ValueError("没有可写入的字段。")

    table_name = f"t_{_table_slug(filename)}_{uuid.uuid4().hex[:6]}"
    full_table = qualified(SCHEMA, table_name)

    column_defs = ", ".join(
        f"{quote_ident(column.physical)} {column.sql_type}" for column in sheet.columns
    )

    await session.execute(text(f"CREATE SCHEMA IF NOT EXISTS {quote_ident(SCHEMA)}"))
    await session.execute(text(f"CREATE TABLE {full_table} ({column_defs})"))

    for column in sheet.columns:
        # COMMENT 是工具语句，不接受绑定参数，这里对内容做字面量转义。
        comment_literal = comment_payload(column.display, column.sample).replace("'", "''")
        await session.execute(
            text(
                f"COMMENT ON COLUMN {full_table}.{quote_ident(column.physical)} "
                f"IS '{comment_literal}'"
            )
        )

    await _insert_rows(session, full_table, sheet)

    stem = filename.rsplit("/", 1)[-1].rsplit("\\", 1)[-1].rsplit(".", 1)[0].strip()
    name = stem or "未命名数据集"
    dataset = Dataset(
        name=name,
        physical_table=table_name,
        source_file=filename,
        sheet_name=sheet.sheet_name,
        row_count=sheet.row_count,
        status="active",
        owner_id=owner_id,
        content_hash=content_hash,
        quality=quality if quality is not None else sheet.quality(),
        created_at=datetime.now(UTC),
    )
    session.add(dataset)
    await session.flush()

    return DatasetMeta(
        id=str(dataset.id),
        name=dataset.name,
        physical_table=dataset.physical_table,
        source_file=dataset.source_file,
        sheet_name=dataset.sheet_name,
        row_count=dataset.row_count,
        created_at=dataset.created_at,
        status=dataset.status,
        owner_id=str(dataset.owner_id) if dataset.owner_id else None,
        content_hash=dataset.content_hash,
        quality=dataset.quality,
        columns=[
            ReflectedColumn(
                physical=column.physical,
                display=column.display,
                sql_type=column.sql_type,
                kind=column.kind,
                sample=column.sample,
            )
            for column in sheet.columns
        ],
    )


async def _insert_rows(session: AsyncSession, full_table: str, sheet: ParsedSheet) -> None:
    if not sheet.rows:
        return

    column_sql = ", ".join(quote_ident(column.physical) for column in sheet.columns)
    width = len(sheet.columns)
    # asyncpg 单条语句最多 32767 个参数，预留余量。
    batch_size = max(50, min(1000, 30000 // max(1, width)))

    for start in range(0, len(sheet.rows), batch_size):
        batch = sheet.rows[start : start + batch_size]
        placeholders: list[str] = []
        params: dict[str, object] = {}
        for row_index, row in enumerate(batch):
            names: list[str] = []
            for column_index, value in enumerate(row):
                key = f"p_{row_index}_{column_index}"
                names.append(f":{key}")
                params[key] = value
            placeholders.append("(" + ", ".join(names) + ")")

        statement = (
            f"INSERT INTO {full_table} ({column_sql}) VALUES " + ", ".join(placeholders)
        )
        await session.execute(text(statement), params)


async def delete_dataset(session: AsyncSession, dataset_id: str) -> bool:
    try:
        key = uuid.UUID(dataset_id)
    except ValueError:
        return False

    dataset = await session.get(Dataset, key)
    if dataset is None:
        return False

    await session.execute(
        text(f"DROP TABLE IF EXISTS {qualified(SCHEMA, dataset.physical_table)}")
    )
    await session.delete(dataset)
    return True
