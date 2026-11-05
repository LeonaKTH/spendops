import asyncio
import uuid
from datetime import UTC, date, datetime
from types import SimpleNamespace

import pytest

from app.core.security import AuthUser
from app.services.datasets import DatasetMeta
from app.services.report_views import (
    ReportViewPermissionError,
    create_view,
    delete_view,
)


class _FakeSession:
    def __init__(self, view=None):
        self.added = []
        self.view = view
        self.deleted = False

    def add(self, item):
        self.added.append(item)

    async def flush(self):
        return None

    async def get(self, _model, _key):
        return self.view

    async def delete(self, item):
        self.deleted = True
        self.view = None


def _actor(role="viewer", username="alice") -> AuthUser:
    return AuthUser(
        id=uuid.uuid4(),
        username=username,
        display_name=username,
        role=role,
        is_active=True,
        token_version=1,
        must_change_password=False,
        last_login_at=None,
        created_at=datetime.now(UTC),
    )


def _dataset() -> DatasetMeta:
    return DatasetMeta(
        id=str(uuid.uuid4()),
        name="bills_2026",
        physical_table="t_bills_2026",
        source_file="bills_2026.xlsx",
        sheet_name="Sheet1",
        row_count=100,
        created_at=datetime.now(UTC),
        status="active",
    )


def test_create_view_stores_scope_and_owner():
    actor = _actor()
    session = _FakeSession()

    view = asyncio.run(
        create_view(
            session,
            actor=actor,
            title="  9 月 Anthropic 成本  ",
            dataset=_dataset(),
            start_date=date(2026, 9, 1),
            end_date=date(2026, 9, 30),
            provider="Anthropic",
        )
    )

    assert view.title == "9 月 Anthropic 成本"
    assert view.provider == "Anthropic"
    assert view.owner_id == actor.id
    assert view.created_by_username == "alice"
    assert view.period_start == date(2026, 9, 1)
    assert view.period_end == date(2026, 9, 30)
    assert session.added == [view]


def test_create_view_normalizes_blank_provider():
    view = asyncio.run(
        create_view(
            _FakeSession(),
            actor=_actor(),
            title="全部账期",
            dataset=_dataset(),
            provider="   ",
        )
    )
    assert view.provider is None


def test_viewer_cannot_delete_other_users_view():
    other = _actor(username="bob")
    view = SimpleNamespace(owner_id=other.id)
    with pytest.raises(ReportViewPermissionError):
        asyncio.run(delete_view(_FakeSession(view), str(uuid.uuid4()), actor=_actor()))


def test_viewer_can_delete_own_view():
    actor = _actor()
    view = SimpleNamespace(owner_id=actor.id)
    session = _FakeSession(view)

    deleted = asyncio.run(delete_view(session, str(uuid.uuid4()), actor=actor))

    assert deleted is view
    assert session.deleted is True


def test_admin_can_delete_other_users_view():
    view = SimpleNamespace(owner_id=uuid.uuid4())
    session = _FakeSession(view)

    deleted = asyncio.run(delete_view(session, str(uuid.uuid4()), actor=_actor(role="admin")))

    assert deleted is view
    assert session.deleted is True


def test_delete_view_handles_missing_and_invalid_ids():
    assert asyncio.run(delete_view(_FakeSession(), str(uuid.uuid4()), actor=_actor())) is None

    with pytest.raises(ValueError):
        asyncio.run(delete_view(_FakeSession(), "not-a-uuid", actor=_actor()))
