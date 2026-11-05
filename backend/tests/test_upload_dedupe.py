import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api.v1 import datasets as datasets_api


class _FakeTransaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


class _FakeSession:
    def begin(self):
        return _FakeTransaction()


class _FakeSessionFactory:
    async def __aenter__(self):
        return _FakeSession()

    async def __aexit__(self, *args):
        return False


def _run(monkeypatch, *, force=False, find_result=None, find_error=None):
    async def fake_read(_file):
        return "bills.xlsx", object(), "hash-123"

    async def fake_find(_session, _hash):
        if find_error is not None:
            raise find_error
        return find_result

    monkeypatch.setattr(datasets_api, "_read_tabular_upload", fake_read)
    monkeypatch.setattr(datasets_api, "SessionLocal", _FakeSessionFactory)
    monkeypatch.setattr(datasets_api, "find_dataset_by_hash", fake_find)

    return asyncio.run(
        datasets_api.upload_dataset(
            request=SimpleNamespace(),
            file=None,
            force=force,
            admin=SimpleNamespace(id="admin-id"),
        )
    )


def test_duplicate_upload_returns_409(monkeypatch):
    existing = SimpleNamespace(name="bills", row_count=60)

    with pytest.raises(HTTPException) as caught:
        _run(monkeypatch, find_result=existing)

    assert caught.value.status_code == 409
    assert "已导入为数据集" in caught.value.detail


def test_force_skips_hash_lookup(monkeypatch):
    async def fail_if_called(_session, _hash):
        raise AssertionError("force 导入不应查询重复")

    async def fake_read(_file):
        return "bills.xlsx", object(), "hash-123"

    async def fake_create(*args, **kwargs):
        raise RuntimeError("stop-after-check")

    monkeypatch.setattr(datasets_api, "_read_tabular_upload", fake_read)
    monkeypatch.setattr(datasets_api, "SessionLocal", _FakeSessionFactory)
    monkeypatch.setattr(datasets_api, "find_dataset_by_hash", fail_if_called)
    monkeypatch.setattr(datasets_api, "create_dataset", fake_create)

    with pytest.raises(HTTPException) as caught:
        asyncio.run(
            datasets_api.upload_dataset(
                request=SimpleNamespace(),
                file=None,
                force=True,
                admin=SimpleNamespace(id="admin-id"),
            )
        )

    # 校验失败仍按 500 包装，但不应是重复文件错误
    assert caught.value.status_code == 500


def test_unexpected_write_error_returns_500(monkeypatch):
    with pytest.raises(HTTPException) as caught:
        _run(monkeypatch, find_error=RuntimeError("database down"))

    assert caught.value.status_code == 500
    assert "写入数据库失败" in caught.value.detail
