import asyncio
import uuid
from datetime import UTC, datetime

from starlette.requests import Request

from app.core import security
from app.core.config import Settings
from app.core.security import AuthUser
from app.db.models import AuditLog
from app.services import audit


def _request(headers=None, client=("10.0.0.1", 1234)) -> Request:
    raw_headers = [(key.lower().encode(), value.encode()) for key, value in (headers or {}).items()]
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": raw_headers,
            "client": client,
        }
    )


def _actor(**overrides) -> AuthUser:
    values = {
        "id": uuid.uuid4(),
        "username": "admin",
        "display_name": "Admin",
        "role": "admin",
        "is_active": True,
        "token_version": 1,
        "must_change_password": False,
        "last_login_at": None,
        "created_at": datetime.now(UTC),
    }
    values.update(overrides)
    return AuthUser(**values)


class _CaptureSession:
    def __init__(self):
        self.added: list[AuditLog] = []

    def add(self, item):
        self.added.append(item)


def test_client_ip_ignores_forwarded_header_by_default(monkeypatch):
    monkeypatch.setattr(
        security, "get_settings", lambda: Settings(trust_proxy_headers=False)
    )

    ip = security.client_ip(_request({"x-forwarded-for": "9.9.9.9"}))

    assert ip == "10.0.0.1"


def test_client_ip_uses_first_hop_when_trusted(monkeypatch):
    monkeypatch.setattr(security, "get_settings", lambda: Settings(trust_proxy_headers=True))

    ip = security.client_ip(_request({"x-forwarded-for": "9.9.9.9, 10.1.1.1"}))

    assert ip == "9.9.9.9"


def test_client_ip_without_client_returns_empty(monkeypatch):
    monkeypatch.setattr(
        security, "get_settings", lambda: Settings(trust_proxy_headers=False)
    )
    request = _request(client=None)

    assert security.client_ip(request) == ""


def test_jsonable_converts_uuid_recursively():
    target = uuid.uuid4()

    result = audit._jsonable({"id": target, "rows": [{"id": target}], "count": 2})

    assert result == {"id": str(target), "rows": [{"id": str(target)}], "count": 2}


def test_log_action_records_actor_and_detail():
    session = _CaptureSession()
    actor = _actor()
    target = uuid.uuid4()

    asyncio.run(
        audit.log_action(
            session,
            actor=actor,
            action=audit.USER_UPDATE,
            target_type="user",
            target_id=str(target),
            detail={"id": target, "role": "admin"},
            ip="10.0.0.1",
        )
    )

    assert len(session.added) == 1
    entry = session.added[0]
    assert entry.actor_id == actor.id
    assert entry.actor_username == "admin"
    assert entry.action == "user.update"
    assert entry.target_id == str(target)
    assert entry.detail == {"id": str(target), "role": "admin"}


def test_log_action_keeps_username_for_deleted_actor():
    session = _CaptureSession()

    asyncio.run(
        audit.log_action(
            session,
            actor=None,
            actor_username="ghost",
            action=audit.AUTH_LOGIN,
            status="failure",
        )
    )

    entry = session.added[0]
    assert entry.actor_id is None
    assert entry.actor_username == "ghost"
    assert entry.status == "failure"


def test_standalone_audit_swallows_failures(monkeypatch):
    def boom():
        raise RuntimeError("database down")

    monkeypatch.setattr(audit, "SessionLocal", boom)

    # 审计失败不能影响登录等主流程。
    asyncio.run(
        audit.log_action_standalone(
            actor=None,
            actor_username="alice",
            action=audit.AUTH_LOGIN,
            status="failure",
        )
    )
