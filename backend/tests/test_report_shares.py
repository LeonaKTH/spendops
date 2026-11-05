import uuid
from datetime import UTC, date, datetime, timedelta

from app.db.models import ReportShare
from app.services.report_shares import generate_token, hash_token, is_active


def make_share(**overrides) -> ReportShare:
    values = {
        "token_hash": hash_token("token"),
        "dataset_id": uuid.uuid4(),
        "dataset_name": "bills_2026",
        "expires_at": datetime.now(UTC) + timedelta(days=7),
    }
    values.update(overrides)
    return ReportShare(**values)


def test_share_token_is_random_and_hashed():
    first = generate_token()
    second = generate_token()

    assert first != second
    assert len(first) >= 40
    assert hash_token(first) != first
    assert len(hash_token(first)) == 64
    assert hash_token(first) == hash_token(first)


def test_share_is_active_until_expiry_or_revocation():
    assert is_active(make_share()) is True
    assert is_active(make_share(expires_at=datetime.now(UTC) - timedelta(seconds=1))) is False
    assert is_active(make_share(revoked_at=datetime.now(UTC))) is False
    # 数据库在极少数驱动下可能返回 naive datetime，也应按 UTC 处理。
    naive_expired = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=1)
    assert is_active(make_share(expires_at=naive_expired)) is False


def test_share_binds_period():
    share = make_share(period_start=date(2026, 7, 1), period_end=date(2026, 9, 30))
    assert share.period_start == date(2026, 7, 1)
    assert share.period_end == date(2026, 9, 30)


def test_share_binds_provider():
    share = make_share(provider="Anthropic")
    assert share.provider == "Anthropic"
