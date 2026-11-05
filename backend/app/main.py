from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1.admin import router as admin_router
from app.api.v1.analysis import router as analysis_router
from app.api.v1.auth import router as auth_router
from app.api.v1.chat import router as chat_router
from app.api.v1.datasets import router as datasets_router
from app.api.v1.documents import router as documents_router
from app.api.v1.health import router as health_router
from app.api.v1.importing import router as importing_router
from app.api.v1.metrics import router as metrics_router
from app.api.v1.purchasing import router as purchasing_router
from app.api.v1.reports import router as reports_router
from app.api.v1.shared import router as shared_router
from app.core.config import get_settings
from app.db.bootstrap import seed_initial_admin
from app.db.session import engine

settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI):
    await seed_initial_admin()
    yield
    await engine.dispose()


app = FastAPI(
    title=settings.app_name,
    description="面向 LLM 采购场景的 BI 数据智能体",
    version="0.1.0",
    lifespan=lifespan,
)


FIELD_LABELS = {
    "username": "用户名",
    "password": "密码",
    "new_password": "新密码",
    "current_password": "当前密码",
    "display_name": "显示名",
    "role": "角色",
    "is_active": "账号状态",
    "question": "问题",
    "dataset_id": "数据集",
    "dataset_ids": "数据集",
    "start_date": "开始日期",
    "end_date": "结束日期",
    "expires_in_days": "有效期",
    "file": "文件",
    "page": "页码",
    "page_size": "每页数量",
    "provider": "供应商",
    "title": "报表名称",
    "force": "强制导入",
    "format": "导出格式",
}


def validation_message(error: dict) -> str:
    """把 Pydantic 的英文校验消息转成统一的中文提示。"""
    kind = str(error.get("type", ""))
    location = [
        str(part) for part in error.get("loc", ()) if part not in {"body", "query", "path"}
    ]
    field = FIELD_LABELS.get(location[-1], location[-1]) if location else "请求参数"
    context = error.get("ctx") or {}

    if kind == "missing":
        return f"缺少必填字段：{field}。"
    if kind == "string_too_short":
        return f"{field}长度不足（至少 {context.get('min_length')} 个字符）。"
    if kind == "string_too_long":
        return f"{field}过长（最多 {context.get('max_length')} 个字符）。"
    if kind == "string_type":
        return f"{field}必须是文本。"
    if kind in {"int_parsing", "float_parsing", "decimal_parsing"}:
        return f"{field}必须是数字。"
    if kind == "bool_parsing":
        return f"{field}必须是布尔值。"
    if kind == "json_invalid":
        return "请求体不是合法的 JSON。"
    if kind in {"literal_error", "enum"}:
        return f"{field}取值不合法。"

    message = str(error.get("msg", "")).removeprefix("Value error, ").strip()
    return message or f"{field}不合法。"


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    _request: Request, exc: RequestValidationError
) -> JSONResponse:
    messages: list[str] = []
    for error in exc.errors():
        message = validation_message(error)
        if message and message not in messages:
            messages.append(message)
    return JSONResponse(
        status_code=422,
        content={"detail": "；".join(messages) or "请求参数不合法。"},
    )

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    """基础安全响应头：分享链接尤其不应通过 Referer 外泄。"""
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("X-Frame-Options", "DENY")
    return response

app.include_router(health_router, prefix="/api/v1")
app.include_router(importing_router, prefix="/api/v1")
app.include_router(metrics_router, prefix="/api/v1")
app.include_router(analysis_router)
app.include_router(purchasing_router)
app.include_router(auth_router, prefix="/api/v1")
app.include_router(admin_router, prefix="/api/v1")
app.include_router(datasets_router, prefix="/api/v1")
app.include_router(documents_router, prefix="/api/v1")
app.include_router(chat_router, prefix="/api/v1")
app.include_router(reports_router, prefix="/api/v1")
app.include_router(shared_router, prefix="/api/v1")


@app.get("/")
async def root() -> dict[str, str]:
    return {"name": settings.app_name, "docs": "/docs"}
