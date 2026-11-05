import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi import HTTPException, Response
from starlette.requests import Request

from app.core import security
from app.core.config import Settings
from app.core.security import (
    AuthError,
    AuthUser,
    clear_auth_cookie,
    create_access_token,
    decode_access_token,
    get_current_user,
    hash_password,
    require_admin,
    resolve_user,
    set_auth_cookie,
    validate_password,
    verify_password,
)

FAST_BCRYPT = 4
TEST_SECRET = "test-secret-" + "x" * 32


@pytest.fixture
def fast_bcrypt(monkeypatch):
    monkeypatch.setattr(security, "get_settings", lambda: Settings(bcrypt_rounds=FAST_BCRYPT))


def _auth_user(**overrides) -> AuthUser:
    values = {
        "id": uuid.uuid4(),
        "username": "alice",
        "display_name": "Alice",
        "role": "viewer",
        "is_active": True,
        "token_version": 1,
        "must_change_password": False,
        "last_login_at": None,
        "created_at": datetime.now(UTC),
    }
    values.update(overrides)
    return AuthUser(**values)


def _request(headers=None, cookies=None, client=("127.0.0.1", 5000)) -> Request:
    raw_headers = [(key.lower().encode(), value.encode()) for key, value in (headers or {}).items()]
    if cookies:
        cookie_header = "; ".join(f"{key}={value}" for key, value in cookies.items())
        raw_headers.append((b"cookie", cookie_header.encode()))
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": raw_headers,
            "client": client,
        }
    )


def test_password_hash_roundtrip(fast_bcrypt):
    digest = hash_password("s3cret-pass", rounds=FAST_BCRYPT)

    assert digest.startswith("$2b$")
    assert verify_password("s3cret-pass", digest) is True
    assert verify_password("wrong-pass", digest) is False


def test_password_hashes_use_distinct_salts(fast_bcrypt):
    first = hash_password("same-password", rounds=FAST_BCRYPT)
    second = hash_password("same-password", rounds=FAST_BCRYPT)

    assert first != second
    assert verify_password("same-password", first)
    assert verify_password("same-password", second)


def test_verify_password_rejects_corrupted_hash():
    assert verify_password("whatever", "not-a-bcrypt-hash") is False


@pytest.mark.parametrize(
    "password",
    ["", "   ", "short7c", "a" * 73, "中" * 25],
)
def test_validate_password_rejects_invalid(password):
    with pytest.raises(ValueError):
        validate_password(password)


def test_validate_password_accepts_boundaries():
    validate_password("12345678")
    validate_password("a" * 72)
    validate_password("中" * 24)


def test_long_password_is_rejected_by_hash(fast_bcrypt):
    with pytest.raises(ValueError):
        hash_password("a" * 73, rounds=FAST_BCRYPT)


def test_access_token_roundtrip():
    user = _auth_user()
    token = create_access_token(user, secret=TEST_SECRET)
    payload = decode_access_token(token, secret=TEST_SECRET)

    assert payload["sub"] == str(user.id)
    assert payload["ver"] == user.token_version
    assert payload["exp"] > payload["iat"]


def test_access_token_rejects_wrong_secret():
    token = create_access_token(_auth_user(), secret="right-secret-" + "x" * 32)

    with pytest.raises(AuthError):
        decode_access_token(token, secret="wrong-secret-" + "x" * 32)


def test_access_token_rejects_expired_token():
    user = _auth_user()
    now = datetime.now(UTC) - timedelta(minutes=10)
    token = create_access_token(user, secret=TEST_SECRET, now=now, expires_minutes=1)

    with pytest.raises(AuthError):
        decode_access_token(token, secret=TEST_SECRET)


def test_access_token_rejects_tampering():
    token = create_access_token(_auth_user(), secret=TEST_SECRET)
    header, payload, signature = token.split(".")
    tampered = f"{header}.{payload}.{signature[:-2]}xx"

    with pytest.raises(AuthError):
        decode_access_token(tampered, secret=TEST_SECRET)


def test_cookie_helpers_set_secure_attributes():
    response = Response()
    set_auth_cookie(response, "token-value")
    header = response.headers["set-cookie"].lower()

    assert "httponly" in header
    assert "samesite=lax" in header
    assert "path=/" in header
    assert "max-age=" in header

    response = Response()
    clear_auth_cookie(response)
    assert "max-age=0" in response.headers["set-cookie"].lower()


class _FakeSession:
    def __init__(self, user):
        self.user = user

    async def get(self, _model, user_id):
        if self.user is not None and self.user.id == user_id:
            return self.user
        return None


def _db_user(**overrides) -> SimpleNamespace:
    values = {
        "id": uuid.uuid4(),
        "username": "alice",
        "display_name": "Alice",
        "role": "viewer",
        "is_active": True,
        "token_version": 1,
        "must_change_password": False,
        "last_login_at": None,
        "created_at": datetime.now(UTC),
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_resolve_user_returns_active_user():
    user = _db_user()
    payload = {"sub": str(user.id), "ver": 1}

    resolved = asyncio.run(resolve_user(_FakeSession(user), payload))

    assert resolved.username == "alice"
    assert resolved.role == "viewer"


def test_resolve_user_rejects_missing_user():
    with pytest.raises(AuthError):
        asyncio.run(resolve_user(_FakeSession(None), {"sub": str(uuid.uuid4()), "ver": 1}))


def test_resolve_user_rejects_inactive_user():
    user = _db_user(is_active=False)
    with pytest.raises(AuthError):
        asyncio.run(resolve_user(_FakeSession(user), {"sub": str(user.id), "ver": 1}))


def test_resolve_user_rejects_stale_token_version():
    user = _db_user(token_version=3)
    with pytest.raises(AuthError):
        asyncio.run(resolve_user(_FakeSession(user), {"sub": str(user.id), "ver": 2}))


def test_resolve_user_rejects_bad_subject():
    with pytest.raises(AuthError):
        asyncio.run(resolve_user(_FakeSession(None), {"sub": "not-a-uuid", "ver": 1}))


def test_get_current_user_requires_cookie():
    with pytest.raises(HTTPException) as excinfo:
        asyncio.run(get_current_user(_request()))

    assert excinfo.value.status_code == 401


def test_require_admin_allows_admin():
    admin = _auth_user(role="admin")
    assert asyncio.run(require_admin(admin)) is admin


def test_require_admin_rejects_viewer():
    with pytest.raises(HTTPException) as excinfo:
        asyncio.run(require_admin(_auth_user(role="viewer")))

    assert excinfo.value.status_code == 403
