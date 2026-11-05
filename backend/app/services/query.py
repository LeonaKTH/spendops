"""只读 SQL 校验与执行。

多层防护：
1. sqlglot 解析，只允许单条 SELECT / UNION；
2. 表名必须在已注册数据集白名单内，且必须带 ds schema；
3. 禁止写操作与危险函数；
4. 事务级只读 + statement_timeout；
5. 强制 LIMIT。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any
from uuid import UUID

import sqlglot
from sqlglot import exp

from app.core.config import get_settings
from app.db.session import engine
from app.db.sql import qualified
from app.services.datasets import SCHEMA, DatasetMeta

WRITE_NODES = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Create,
    exp.Drop,
    exp.Alter,
    exp.TruncateTable,
    exp.Into,
    exp.Command,
)

DANGEROUS_FUNCTIONS = (
    "pg_read_file",
    "pg_read_binary_file",
    "pg_ls_dir",
    "pg_sleep",
    "pg_terminate_backend",
    "pg_cancel_backend",
    "lo_import",
    "lo_export",
    "dblink",
    "current_setting",
    "set_config",
    "pg_stat_file",
)


class SqlValidationError(ValueError):
    """SQL 未通过安全校验。"""


@dataclass
class QueryResult:
    columns: list[str]
    rows: list[list[Any]] = field(default_factory=list)
    truncated: bool = False


def validate_readonly_sql(sql: str, allowed_tables: set[str]) -> str:
    text = (sql or "").strip()
    if not text:
        raise SqlValidationError("模型没有生成 SQL。")

    text = text.rstrip(";").strip()

    try:
        statements = [item for item in sqlglot.parse(text, read="postgres") if item is not None]
    except sqlglot.errors.ParseError as exc:
        raise SqlValidationError(f"SQL 语法解析失败：{exc}") from exc

    if len(statements) != 1:
        raise SqlValidationError("只允许执行一条 SQL。")

    expression = statements[0]
    if not isinstance(expression, (exp.Select, exp.Union, exp.Intersect, exp.Except)):
        raise SqlValidationError("只允许 SELECT 查询。")

    for forbidden in WRITE_NODES:
        if expression.find(forbidden):
            raise SqlValidationError("检测到写操作，已拒绝执行。")

    cte_names = {cte.alias_or_name for cte in expression.find_all(exp.CTE)}

    for table in expression.find_all(exp.Table):
        if table.name in cte_names and not table.db:
            continue
        if table.catalog:
            raise SqlValidationError("不允许跨库查询。")
        schema = table.db
        name = table.name
        if schema != SCHEMA:
            raise SqlValidationError(f"表 {table.sql()} 必须带 ds. 前缀。")
        if f"{schema}.{name}" not in allowed_tables:
            raise SqlValidationError(f"表 {schema}.{name} 未注册，禁止访问。")

    lowered = text.lower()
    for function in DANGEROUS_FUNCTIONS:
        if re.search(rf"\b{function}\s*\(", lowered):
            raise SqlValidationError(f"禁止调用函数 {function}。")

    limit = get_settings().query_row_limit
    limit_expr = expression.args.get("limit")
    if limit_expr is None:
        # 没有 LIMIT：追加安全上限。
        expression = expression.limit(limit)
    else:
        # 有显式 LIMIT：仍受上界约束，防止 LIMIT 999999 / LIMIT ALL 绕过行数限制。
        value_text = limit_expr.expression.sql() if limit_expr.expression else ""
        try:
            requested = int(value_text)
        except (ValueError, TypeError):
            requested = None
        if requested is None or requested > limit:
            expression = expression.limit(limit)

    return expression.sql(dialect="postgres")


def _to_jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, (bytes, bytearray, memoryview)):
        return bytes(value).decode("utf-8", errors="replace")[:200]
    return str(value)


async def fetch_dataset_rows(
    dataset: DatasetMeta, limit: int, offset: int
) -> QueryResult:
    """按数据集注册信息分页读取物理表，供「查看数据」使用。

    表名只来自注册表，不拼接任何用户输入；limit / offset 强制为整数并做上限约束。
    """
    settings = get_settings()
    limit = max(1, min(int(limit), 100))
    offset = max(0, int(offset))
    timeout_ms = max(1000, settings.query_timeout_seconds * 1000)
    table = qualified(SCHEMA, dataset.physical_table)

    async with engine.connect() as connection:
        async with connection.begin():
            await connection.exec_driver_sql("SET TRANSACTION READ ONLY")
            await connection.exec_driver_sql(f"SET LOCAL statement_timeout = {timeout_ms}")
            result = await connection.exec_driver_sql(
                f"SELECT * FROM {table} ORDER BY ctid LIMIT {limit} OFFSET {offset}"
            )
            raw_columns = list(result.keys())
            rows = [[_to_jsonable(value) for value in row] for row in result.fetchall()]

    display = {column.physical: column.display for column in dataset.columns}
    columns = [display.get(name, name) for name in raw_columns]
    return QueryResult(columns=columns, rows=rows, truncated=False)


def display_map(datasets: list[DatasetMeta]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for dataset in datasets:
        for column in dataset.columns:
            mapping.setdefault(column.physical, column.display)
    return mapping


async def execute_readonly(sql: str, mapping: dict[str, str] | None = None) -> QueryResult:
    settings = get_settings()
    limit = settings.query_row_limit
    timeout_ms = max(1000, settings.query_timeout_seconds * 1000)

    async with engine.connect() as connection:
        async with connection.begin():
            # 必须是事务内的第一条语句。
            await connection.exec_driver_sql("SET TRANSACTION READ ONLY")
            await connection.exec_driver_sql(f"SET LOCAL statement_timeout = {timeout_ms}")

            result = await connection.exec_driver_sql(sql)
            raw_columns = list(result.keys())
            fetched = result.fetchmany(limit + 1)

    truncated = len(fetched) > limit
    rows = [
        [_to_jsonable(value) for value in row]
        for row in fetched[:limit]
    ]

    resolve = mapping or {}
    columns = [resolve.get(name, name) for name in raw_columns]

    return QueryResult(columns=columns, rows=rows, truncated=truncated)
