"""네이버페이 수집 계정 폴백."""
import asyncio

import source_naverpaper as np


def _accounts(*ids):
    return [np.AccountConfig(user_id=i, password="pw") for i in ids]


def test_falls_back_to_next_account_when_first_cookie_missing():
    """1번 계정 쿠키가 없으면 → 2번 계정으로 수집해야 한다."""
    tried = []

    async def collect(account):
        tried.append(account.user_id)
        return account.user_id == "user2"

    used = asyncio.run(np.collect_with_account_fallback(_accounts("user1", "user2", "user3"), collect, lambda m: None))

    assert tried == ["user1", "user2"]
    assert used.user_id == "user2"


def test_falls_back_when_first_account_raises():
    """1번 계정에서 예외가 나도 → 다음 계정으로 넘어간다."""

    async def collect(account):
        if account.user_id == "user1":
            raise RuntimeError("timeout")
        return True

    logs = []
    used = asyncio.run(np.collect_with_account_fallback(_accounts("user1", "user2"), collect, logs.append))

    assert used.user_id == "user2"
    assert any("timeout" in m for m in logs)


def test_returns_none_when_all_accounts_fail():
    """모든 계정이 실패하면 → None (성공으로 위장하지 않는다)."""

    async def collect(account):
        return False

    assert asyncio.run(np.collect_with_account_fallback(_accounts("a", "b"), collect, lambda m: None)) is None
