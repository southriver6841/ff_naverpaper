"""process_account: 도중 예외가 나도 브라우저가 닫혀야 한다(좀비 Chromium 방지)."""
import asyncio
import sys
import types

import pytest

import source_naverpaper as np


class FakeContext:
    def __init__(self, state):
        self.state = state

    async def new_page(self):
        return object()

    async def close(self):
        self.state["context_closed"] = True

    async def storage_state(self):
        return {"cookies": []}


class FakeBrowser:
    def __init__(self, state):
        self.state = state

    async def new_context(self, **kwargs):
        return FakeContext(self.state)

    async def close(self):
        self.state["browser_closed"] = True


@pytest.fixture
def fake_playwright(monkeypatch):
    state = {}

    class FakePW:
        def __init__(self):
            self.chromium = types.SimpleNamespace(launch=self._launch)

        async def _launch(self, **kwargs):
            return FakeBrowser(state)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

    class FakeStealth:
        async def apply_stealth_async(self, page):
            return None

    pw_pkg = types.ModuleType("playwright")
    pw_async = types.ModuleType("playwright.async_api")
    pw_async.async_playwright = FakePW
    stealth = types.ModuleType("playwright_stealth")
    stealth.Stealth = FakeStealth
    monkeypatch.setitem(sys.modules, "playwright", pw_pkg)
    monkeypatch.setitem(sys.modules, "playwright.async_api", pw_async)
    monkeypatch.setitem(sys.modules, "playwright_stealth", stealth)
    return state


def test_browser_closed_when_processing_raises(tmp_path, monkeypatch, fake_playwright):
    async def fake_fetch(session_db, nid, candidate_urls=None):
        return {"https://campaign2.naver.com/a"}, 0

    async def fake_storage(*args, **kwargs):
        return {"cookies": []}

    async def boom(*args, **kwargs):
        raise RuntimeError("page crashed")

    monkeypatch.setattr(np, "fetch_naver_campaign_urls", fake_fetch)
    monkeypatch.setattr(np, "ensure_cookie_storage_state", fake_storage)
    monkeypatch.setattr(np, "naver_login", boom)

    account = np.AccountConfig(user_id="user1", password="pw")
    with pytest.raises(RuntimeError):
        asyncio.run(np.process_account(account, None, str(tmp_path), "", lambda m: None))

    assert fake_playwright.get("context_closed") is True
    assert fake_playwright.get("browser_closed") is True
