import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.core import security
from app.core.config import Settings
from app.services import users as user_service
from app.services.users import (
    change_password,
    ensure_can_change_admin,
    normalize_username,
    reset_password,
    update_user,
    validate_role,
    validate_username,
)


class _FakeSession:
    async def flush(self):
        return None


def _db_user(**overrides) -> SimpleNamespace:
    values = {
        "id": 1,
        "username": "alice",
        "display_name": "Alice",
        "password_hash": "",
        "role": "viewer",
        "is_active": True,
        "token_version": 1,
        "must_change_password": False,
        "last_login_at": None,
        "created_at": datetime.now(UTC),
    }
    values.update(overrides)
    return SimpleNamespace(**values)


@pytest.fixture
def fast_bcrypt(monkeypatch):
    monkeypatch.setattr(security, "get_settings", lambda: Settings(bcrypt_rounds=4))


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("  Alice ", "alice"), ("BOB", "bob"), ("", ""), (None, "")],
)
def test_normalize_username(raw, expected):
    assert normalize_username(raw) == expected


@pytest.mark.parametrize("username", ["ab", "a" * 33, "bad name", "中文名", "a@b"])
def test_validate_username_rejects_invalid(username):
    with pytest.raises(ValueError):
        validate_username(username)


@pytest.mark.parametrize("username", ["abc", "a" * 32, "john.doe-1_x"])
def test_validate_username_accepts_valid(username):
    assert validate_username(username) == username


def test_validate_role():
    assert validate_role("admin") == "admin"
    assert validate_role("viewer") == "viewer"
    with pytest.raises(ValueError):
        validate_role("owner")


@pytest.mark.parametrize("action", ["delete", "disable", "demote"])
def test_cannot_change_self(action):
    with pytest.raises(ValueError):
        ensure_can_change_admin(
            is_self=True,
            action=action,
            target_is_active_admin=True,
            active_admin_count=5,
        )


@pytest.mark.parametrize("action", ["delete", "disable", "demote"])
def test_cannot_remove_last_active_admin(action):
    with pytest.raises(ValueError):
        ensure_can_change_admin(
            is_self=False,
            action=action,
            target_is_active_admin=True,
            active_admin_count=1,
        )


@pytest.mark.parametrize("action", ["delete", "disable", "demote"])
def test_can_change_admin_when_others_remain(action):
    ensure_can_change_admin(
        is_self=False,
        action=action,
        target_is_active_admin=True,
        active_admin_count=2,
    )


def test_demoting_viewer_is_not_blocked_by_admin_count():
    ensure_can_change_admin(
        is_self=False,
        action="demote",
        target_is_active_admin=False,
        active_admin_count=1,
    )


def test_deactivate_user_bumps_token_version():
    user = _db_user(token_version=2)

    asyncio.run(update_user(_FakeSession(), user, is_active=False))

    assert user.is_active is False
    assert user.token_version == 3


def test_update_role_does_not_touch_token_version():
    user = _db_user(token_version=2)

    asyncio.run(update_user(_FakeSession(), user, role="admin", display_name="  Bob  "))

    assert user.role == "admin"
    assert user.display_name == "Bob"
    assert user.token_version == 2


def test_reset_password_bumps_version_and_forces_change(fast_bcrypt):
    user = _db_user(token_version=2, must_change_password=False)

    asyncio.run(reset_password(_FakeSession(), user, "new-password"))

    assert user.token_version == 3
    assert user.must_change_password is True
    assert security.verify_password("new-password", user.password_hash)


def test_change_password_rejects_wrong_current(fast_bcrypt):
    user = _db_user(password_hash=security.hash_password("old-password", rounds=4))

    with pytest.raises(ValueError, match="当前密码不正确"):
        asyncio.run(
            change_password(
                _FakeSession(),
                user,
                current_password="wrong-password",
                new_password="new-password",
            )
        )


def test_change_password_rejects_same_password(fast_bcrypt):
    user = _db_user(password_hash=security.hash_password("same-password", rounds=4))

    with pytest.raises(ValueError, match="不能与当前密码相同"):
        asyncio.run(
            change_password(
                _FakeSession(),
                user,
                current_password="same-password",
                new_password="same-password",
            )
        )


def test_change_password_success(fast_bcrypt):
    user = _db_user(
        token_version=4,
        must_change_password=True,
        password_hash=security.hash_password("old-password", rounds=4),
    )

    asyncio.run(
        change_password(
            _FakeSession(),
            user,
            current_password="old-password",
            new_password="new-password",
        )
    )

    assert user.token_version == 5
    assert user.must_change_password is False
    assert security.verify_password("new-password", user.password_hash)


def test_module_still_exposes_user_helpers():
    # 防止导入路径变更后测试静默失效。
    assert user_service.create_user is not None
