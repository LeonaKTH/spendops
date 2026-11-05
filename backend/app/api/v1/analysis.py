"""SpendOps G5 受控经营问数 API。

只读：任何登录用户均可问数，但结果只来自可信 metrics 计算，无写权限。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import AuthUser, get_current_user
from app.db.models import Supplier
from app.db.session import SessionLocal
from app.services import analysis

router = APIRouter(tags=["analysis"], prefix="/api/v1")

EXAMPLES = [
    "2026 年采购订单金额是多少？",
    "今年已收货金额和已开票金额分别是多少？",
    "哪些供应商采购金额最高？",
    "华东电子今年的采购金额变化如何？",
    "哪些订单存在交付延期？",
    "当前有多少待核对发票，涉及多少金额？",
    "哪些订单存在收货与开票差异？",
    "2026 年 3 月的采购金额为什么变化？",
]


class AnalysisRequest(BaseModel):
    question: str = Field(min_length=1, max_length=500)
    mode: str = Field(default="offline", pattern="^(offline|llm)$")


async def _suppliers(session: AsyncSession) -> list[dict]:
    rows = (await session.execute(select(Supplier.id, Supplier.code, Supplier.name))).all()
    return [{"id": str(r[0]), "code": r[1], "name": r[2]} for r in rows]


@router.get("/analysis/examples")
async def analysis_examples(_current: AuthUser = Depends(get_current_user)) -> dict:
    return {"examples": EXAMPLES}


@router.post("/analysis")
async def ask_analysis(
    body: AnalysisRequest,
    _current: AuthUser = Depends(get_current_user),
) -> dict:
    try:
        async with SessionLocal() as session:
            suppliers = await _suppliers(session)
            result = await analysis.run_analysis(
                session, body.question, suppliers, mode=body.mode
            )
            return result
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
