import asyncio
import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api.v1 import datasets as datasets_api
from app.services.query import QueryResult


def _run(monkeypatch, *, found=True, offset=0):
    async def fake_load(_session, _ids, active_only=False):
        if not found:
            return []
        return [SimpleNamespace(row_count=120, columns=[])]

    async def fake_fetch(_dataset, _limit, _offset):
        return QueryResult(columns=["账期"], rows=[["2025-01-01"]])

    monkeypatch.setattr(datasets_api, "load_datasets", fake_load)
    monkeypatch.setattr(datasets_api, "fetch_dataset_rows", fake_fetch)

    return asyncio.run(
        datasets_api.dataset_rows(
            str(uuid.uuid4()),
            limit=20,
            offset=offset,
            db=SimpleNamespace(),
            _current=SimpleNamespace(),
        )
    )


def test_dataset_rows_returns_page(monkeypatch):
    page = _run(monkeypatch, offset=40)

    assert page.total == 120
    assert page.offset == 40
    assert page.limit == 20
    assert page.columns == ["账期"]
    assert page.rows == [["2025-01-01"]]


def test_dataset_rows_missing_returns_404(monkeypatch):
    with pytest.raises(HTTPException) as caught:
        _run(monkeypatch, found=False)

    assert caught.value.status_code == 404


def test_dataset_rows_rejects_invalid_id():
    with pytest.raises(HTTPException) as caught:
        asyncio.run(
            datasets_api.dataset_rows(
                "not-a-uuid",
                limit=20,
                offset=0,
                db=SimpleNamespace(),
                _current=SimpleNamespace(),
            )
        )

    assert caught.value.status_code == 400
