"""한 번 로그인하면 예약 실행마다 다시 로그인하지 않아야 한다."""
import asyncio
import sys
import time
import types

import pytest

import source_naverpaper as np

FUTURE = time.time() + 86400 * 300
PAST = time.time() - 60


def _storage(**cookies):
    return {"cookies": [{"name": n, "value": "v", "expires": e} for n, e in cookies.items()]}


# ---- 쿠키 판정 -------------------------------------------------------------------

def test_session_only_jst_does_not_invalidate_login():
    """NID_JST 는 원래 세션 쿠키 → 이것 때문에 매번 재로그인하면 안 된다."""
    ok, _ = np.check_storage_data_status(_storage(NID_AUT=FUTURE, NID_SES=FUTURE, NID_JST=-1))
    assert ok is True


def test_session_only_required_cookies_are_accepted():
    """만료일 없는 세션 쿠키도 저장해 두면 계속 쓸 수 있다(실제 유효성은 접속해서 확인)."""
    ok, _ = np.check_storage_data_status(_storage(NID_AUT=-1, NID_SES=-1))
    assert ok is True


def test_expired_or_missing_required_cookie_is_invalid():
    assert np.check_storage_data_status(_storage(NID_AUT=PAST, NID_SES=FUTURE))[0] is False
    assert np.check_storage_data_status(_storage(NID_SES=FUTURE))[0] is False
    assert np.check_storage_data_status({"cookies": []})[0] is False


# ---- 실행 중 로그인 확인 -----------------------------------------------------------

class FakePage:
    def __init__(self, state):
        self.state = state
        self.url = "about:blank"


class FakeContext:
    def __init__(self, state, storage_state):
        self.state = state
        self.storage = storage_state
        state.setdefault("contexts", []).append(storage_state)

    async def new_page(self):
        return FakePage(self.state)

    async def close(self):
        pass

    async def storage_state(self):
        return {"cookies": []}


class FakeBrowser:
    def __init__(self, state):
        self.state = state

    async def new_context(self, **kwargs):
        return FakeContext(self.state, kwargs.get("storage_state"))

    async def close(self):
        pass


@pytest.fixture
def fake_env(monkeypatch, tmp_path):
    state = {"refresh_calls": 0, "balance_calls": 0}

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

    pw_async = types.ModuleType("playwright.async_api")
    pw_async.async_playwright = FakePW
    stealth = types.ModuleType("playwright_stealth")
    stealth.Stealth = FakeStealth
    monkeypatch.setitem(sys.modules, "playwright", types.ModuleType("playwright"))
    monkeypatch.setitem(sys.modules, "playwright.async_api", pw_async)
    monkeypatch.setitem(sys.modules, "playwright_stealth", stealth)

    async def fake_fetch(session_db, nid, candidate_urls=None):
        return {"https://campaign2.naver.com/a"}, 0

    async def fake_ensure(*args, **kwargs):
        return "saved-cookie"

    async def fake_login(page, account, cookie_dir, emit):
        return True, "using saved cookie"

    async def fake_links(page, links, session_db, user_id, emit, excluded=None):
        return [np.DetailResult(user_id=user_id, url="u", status="visited")]

    async def fake_refresh(account, cookie_dir, proxy_url="", emit=None, allow_password_login=True, verify_online=False):
        state["refresh_calls"] += 1
        state["refresh_verify_online"] = verify_online
        return state.get("refresh_ok", True), "relogin"

    monkeypatch.setattr(np, "fetch_naver_campaign_urls", fake_fetch)
    monkeypatch.setattr(np, "ensure_cookie_storage_state", fake_ensure)
    monkeypatch.setattr(np, "naver_login", fake_login)
    monkeypatch.setattr(np, "process_campaign_links", fake_links)
    monkeypatch.setattr(np, "refresh_cookie_from_profile", fake_refresh)
    monkeypatch.setattr(np, "get_storage_state", lambda nid, db, cd: "fresh-cookie")

    class FakeSession:
        def merge(self, obj):
            pass

    return state, FakeSession(), tmp_path


def _balance(state, logged_out_first):
    async def get_balance(page):
        state["balance_calls"] += 1
        if logged_out_first and state["balance_calls"] == 1:
            page.url = "https://nid.naver.com/nidlogin.login?url=https://pay.naver.com"
            return None
        page.url = "https://pay.naver.com/pointshistory/list"
        return 100
    return get_balance


def test_valid_saved_cookie_does_not_relogin(fake_env, monkeypatch):
    state, session, tmp = fake_env
    monkeypatch.setattr(np, "get_naverpay_point_balance", _balance(state, logged_out_first=False))

    result = asyncio.run(np.process_account(np.AccountConfig("u1", "pw"), session, str(tmp), "", lambda m: None))

    assert state["refresh_calls"] == 0
    assert state["contexts"] == ["saved-cookie"]
    assert result.visited_url_count == 1


def test_cookie_rejected_by_naver_relogins_once_and_continues(fake_env, monkeypatch):
    """네이버가 저장 쿠키를 거부(로그인 페이지로 이동)할 때만 → 재로그인 1번 후 계속 진행."""
    state, session, tmp = fake_env
    monkeypatch.setattr(np, "get_naverpay_point_balance", _balance(state, logged_out_first=True))
    logs = []

    result = asyncio.run(np.process_account(np.AccountConfig("u1", "pw"), session, str(tmp), "", logs.append))

    assert state["refresh_calls"] == 1
    assert state["refresh_verify_online"] is True
    assert state["contexts"] == ["saved-cookie", "fresh-cookie"]
    assert result.visited_url_count == 1
    assert any("re-login" in m for m in logs)


def test_relogin_failure_is_reported(fake_env, monkeypatch):
    state, session, tmp = fake_env
    state["refresh_ok"] = False

    async def always_logged_out(page):
        page.url = "https://nid.naver.com/nidlogin.login"
        return None

    monkeypatch.setattr(np, "get_naverpay_point_balance", always_logged_out)

    result = asyncio.run(np.process_account(np.AccountConfig("u1", "pw"), session, str(tmp), "", lambda m: None))

    assert result.visited_url_count == 0
    assert result.details and result.details[0].status == "login_error"


# ---- 만료 전 자동 갱신 --------------------------------------------------------------

DAY = 86400


def test_needs_renewal_by_days_left():
    now = time.time()
    assert np.needs_cookie_renewal(_storage(NID_AUT=now + 3 * DAY, NID_SES=-1), 7, now)[0] is True
    assert np.needs_cookie_renewal(_storage(NID_AUT=now + 30 * DAY, NID_SES=-1), 7, now)[0] is False
    # 로그인 상태 유지 없이 받은 세션 쿠키 → 오래 못 가므로 갱신 대상
    assert np.needs_cookie_renewal(_storage(NID_AUT=-1, NID_SES=-1), 7, now)[0] is True
    # 쿠키가 없으면 갱신이 아니라 일반 로그인 흐름이 처리
    assert np.needs_cookie_renewal({"cookies": []}, 7, now)[0] is False
    # 0일이면 기능 끔
    assert np.needs_cookie_renewal(_storage(NID_AUT=now + DAY, NID_SES=-1), 0, now)[0] is False


def _write_cookie(cookie_dir, user_id, storage):
    import json, os
    os.makedirs(cookie_dir, exist_ok=True)
    with open(np.cookie_path(cookie_dir, user_id), "w", encoding="utf-8") as f:
        json.dump(storage, f)


@pytest.fixture
def renew_env(monkeypatch, tmp_path):
    calls = []

    async def fake_refresh(account, cookie_dir, proxy_url="", log=None):
        calls.append(account.user_id)
        if calls_ok[0]:
            _write_cookie(cookie_dir, account.user_id, _storage(NID_AUT=time.time() + 365 * DAY, NID_SES=-1))
            return {"ret": "success", "msg": "cookie refreshed"}
        return {"ret": "warning", "msg": "captcha required"}

    calls_ok = [True]
    monkeypatch.setattr(np, "refresh_cookie", fake_refresh)
    return calls, calls_ok, str(tmp_path / "cookies")


def test_renew_logs_in_when_expiring_and_saves_new_cookie(renew_env):
    calls, _, cookie_dir = renew_env
    _write_cookie(cookie_dir, "u1", _storage(NID_AUT=time.time() + 2 * DAY, NID_SES=-1))
    logs = []

    renewed = asyncio.run(np.renew_cookie_if_needed(np.AccountConfig("u1", "pw"), cookie_dir, "", logs.append, 7))

    assert renewed is True and calls == ["u1"]
    assert np.needs_cookie_renewal(np.load_cookie_file("u1", cookie_dir), 7)[0] is False


def test_renew_skips_fresh_cookie_and_missing_password(renew_env):
    calls, _, cookie_dir = renew_env
    _write_cookie(cookie_dir, "fresh", _storage(NID_AUT=time.time() + 200 * DAY, NID_SES=-1))
    _write_cookie(cookie_dir, "nopw", _storage(NID_AUT=time.time() + DAY, NID_SES=-1))

    asyncio.run(np.renew_cookie_if_needed(np.AccountConfig("fresh", "pw"), cookie_dir, "", lambda m: None, 7))
    asyncio.run(np.renew_cookie_if_needed(np.AccountConfig("nopw", ""), cookie_dir, "", lambda m: None, 7))

    assert calls == []


def test_failed_renewal_keeps_old_cookie_and_waits_a_day(renew_env):
    """갱신 실패(캡차 등) → 기존 쿠키 유지, 같은 날엔 다시 시도하지 않는다(네이버 보안 차단 방지)."""
    calls, calls_ok, cookie_dir = renew_env
    calls_ok[0] = False
    old = _storage(NID_AUT=time.time() + 2 * DAY, NID_SES=-1)
    _write_cookie(cookie_dir, "u1", old)
    logs = []

    first = asyncio.run(np.renew_cookie_if_needed(np.AccountConfig("u1", "pw"), cookie_dir, "", logs.append, 7))
    second = asyncio.run(np.renew_cookie_if_needed(np.AccountConfig("u1", "pw"), cookie_dir, "", logs.append, 7))

    assert first is False and second is False
    assert calls == ["u1"]
    assert np.load_cookie_file("u1", cookie_dir)["cookies"][0]["expires"] == old["cookies"][0]["expires"]
    assert any("captcha required" in m for m in logs)


def test_process_account_renews_before_visiting(fake_env, monkeypatch):
    state, session, tmp = fake_env
    monkeypatch.setattr(np, "get_naverpay_point_balance", _balance(state, logged_out_first=False))
    seen = []

    async def fake_renew(account, cookie_dir, proxy_url, emit, days):
        seen.append((account.user_id, days))
        return False

    monkeypatch.setattr(np, "renew_cookie_if_needed", fake_renew)

    asyncio.run(np.process_account(np.AccountConfig("u1", "pw"), session, str(tmp), "", lambda m: None, renew_days=5))

    assert seen == [("u1", 5)]
