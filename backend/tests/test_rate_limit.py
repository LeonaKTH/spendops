import asyncio

from app.core.config import get_settings
from app.infra import rate_limit


class FakeRedis:
    def __init__(self):
        self.values: dict[str, int] = {}
        self.ttls: dict[str, int] = {}

    async def get(self, key):
        return self.values.get(key)

    async def incr(self, key):
        self.values[key] = self.values.get(key, 0) + 1
        return self.values[key]

    async def expire(self, key, ttl):
        self.ttls[key] = ttl
        return True

    async def ttl(self, key):
        return self.ttls.get(key, -1)

    async def delete(self, key):
        self.values.pop(key, None)
        return 1


class BrokenRedis:
    async def get(self, key):
        raise ConnectionError("redis down")

    async def incr(self, key):
        raise ConnectionError("redis down")

    async def expire(self, key, ttl):
        raise ConnectionError("redis down")

    async def ttl(self, key):
        raise ConnectionError("redis down")

    async def delete(self, key):
        raise ConnectionError("redis down")


def test_lockout_after_max_attempts():
    settings = get_settings()
    redis = FakeRedis()

    for _ in range(settings.login_max_attempts - 1):
        assert asyncio.run(rate_limit.check_login_locked("alice", "1.1.1.1", redis)) == 0
        asyncio.run(rate_limit.record_login_failure("alice", "1.1.1.1", redis))

    assert asyncio.run(rate_limit.check_login_locked("alice", "1.1.1.1", redis)) == 0

    asyncio.run(rate_limit.record_login_failure("alice", "1.1.1.1", redis))

    retry_after = asyncio.run(rate_limit.check_login_locked("alice", "1.1.1.1", redis))
    assert retry_after > 0
    assert retry_after <= settings.login_lockout_seconds


def test_lockout_is_scoped_to_username_and_ip():
    settings = get_settings()
    redis = FakeRedis()

    for _ in range(settings.login_max_attempts):
        asyncio.run(rate_limit.record_login_failure("alice", "1.1.1.1", redis))

    assert asyncio.run(rate_limit.check_login_locked("alice", "1.1.1.1", redis)) > 0
    assert asyncio.run(rate_limit.check_login_locked("bob", "1.1.1.1", redis)) == 0
    assert asyncio.run(rate_limit.check_login_locked("alice", "2.2.2.2", redis)) == 0


def test_ip_threshold_locks_across_usernames():
    settings = get_settings()
    redis = FakeRedis()

    for index in range(settings.login_ip_max_attempts):
        asyncio.run(rate_limit.record_login_failure(f"user{index}", "3.3.3.3", redis))

    assert asyncio.run(rate_limit.check_login_locked("fresh", "3.3.3.3", redis)) > 0
    assert asyncio.run(rate_limit.check_login_locked("fresh", "4.4.4.4", redis)) == 0


def test_failure_counter_sets_ttl_on_first_increment():
    redis = FakeRedis()
    settings = get_settings()

    asyncio.run(rate_limit.record_login_failure("alice", "1.1.1.1", redis))

    assert redis.ttls["procurebi:auth:fail:alice:1.1.1.1"] == settings.login_lockout_seconds
    assert redis.ttls["procurebi:auth:fail:ip:1.1.1.1"] == settings.login_lockout_seconds


def test_successful_login_clears_pair_counter():
    settings = get_settings()
    redis = FakeRedis()

    for _ in range(settings.login_max_attempts):
        asyncio.run(rate_limit.record_login_failure("alice", "1.1.1.1", redis))
    assert asyncio.run(rate_limit.check_login_locked("alice", "1.1.1.1", redis)) > 0

    asyncio.run(rate_limit.clear_login_failures("alice", "1.1.1.1", redis))

    assert asyncio.run(rate_limit.check_login_locked("alice", "1.1.1.1", redis)) == 0


def test_redis_failure_fails_open():
    redis = BrokenRedis()

    assert asyncio.run(rate_limit.check_login_locked("alice", "1.1.1.1", redis)) == 0
    assert asyncio.run(rate_limit.record_login_failure("alice", "1.1.1.1", redis)) == (0, 0)
    asyncio.run(rate_limit.clear_login_failures("alice", "1.1.1.1", redis))


def test_share_limit_counts_ip_and_token():
    settings = get_settings()
    redis = FakeRedis()
    token = "shared-token-abc"

    for _ in range(settings.share_rate_max_requests):
        assert asyncio.run(
            rate_limit.hit_share_limit(token=token, ip="5.5.5.5", redis=redis)
        ) == 0

    retry_after = asyncio.run(
        rate_limit.hit_share_limit(token=token, ip="5.5.5.5", redis=redis)
    )
    assert retry_after > 0
    assert retry_after <= settings.share_rate_window_seconds

    # 同一 token 换 IP 仍受限，避免链接被分布式抓取。
    assert asyncio.run(
        rate_limit.hit_share_limit(token=token, ip="6.6.6.6", redis=redis)
    ) > 0
    # 其他链接在新 IP 上仍可访问。
    assert asyncio.run(
        rate_limit.hit_share_limit(token="another-token", ip="7.7.7.7", redis=redis)
    ) == 0


def test_share_limit_fails_open_when_redis_down():
    assert asyncio.run(
        rate_limit.hit_share_limit(token="t", ip="1.1.1.1", redis=BrokenRedis())
    ) == 0
