"""run() 흐름: 진행 중 저장, 계정 격리, 중지/시간 제한."""
import asyncio
import os

import pytest

import source_naverpaper as np


def _config(tmp_path, user_ids, **kwargs):
    return np.RunConfig(
        db_path=str(tmp_path / "np.db"),
        cookie_dir=str(tmp_path / "cookies"),
        accounts=[np.AccountConfig(user_id=uid, password="pw") for uid in user_ids],
        **kwargs,
    )


@pytest.fixture(autouse=True)
def _reset_stop():
    np.clear_stop_request()
    yield
    np.clear_stop_request()


@pytest.fixture
def no_collection(monkeypatch):
    async def fake_collect(session_db, emit, *args, **kwargs):
        return {"https://campaign2.naver.com/a"}, set(), {}

    monkeypatch.setattr(np, "save_naver_campaign_urls", fake_collect)


def _ok_result(user_id):
    result = np.AccountResult(user_id=user_id)
    result.target_url_count = 1
    result.visited_url_count = 1
    result.estimated_points = 3
    result.details.append(np.DetailResult(user_id=user_id, url="https://campaign2.naver.com/a", status="visited", point=3))
    return result


def test_finished_account_is_visible_while_run_in_progress(tmp_path, monkeypatch, no_collection):
    """사용자가 실행 중에 결과 메뉴를 열면 → 끝난 계정 결과가 이미 보여야 한다."""
    config = _config(tmp_path, ["user1", "user2"])
    seen_during_run = {}

    async def fake_process_account(account, session_db, *args, **kwargs):
        if account.user_id == "user2":
            seen_during_run["runs"] = np.recent_runs(config.db_path, 10)
            seen_during_run["tabs"] = np.recent_run_account_tabs(config.db_path, 10)
        return _ok_result(account.user_id)

    monkeypatch.setattr(np, "process_account", fake_process_account)
    result = asyncio.run(np.run(config))

    assert result.status == "completed"
    runs = seen_during_run["runs"]
    assert len(runs) == 1 and runs[0]["status"] == "running"
    tab_users = [tab["user_id"] for tab in seen_during_run["tabs"]]
    assert tab_users == ["user1"]


def test_failing_account_does_not_stop_other_accounts(tmp_path, monkeypatch, no_collection):
    """한 계정에서 예외가 나도 → 다음 계정은 계속 처리되어야 한다."""
    config = _config(tmp_path, ["bad", "good"])

    async def fake_process_account(account, session_db, *args, **kwargs):
        if account.user_id == "bad":
            raise RuntimeError("browser crashed")
        return _ok_result(account.user_id)

    monkeypatch.setattr(np, "process_account", fake_process_account)
    result = asyncio.run(np.run(config))

    assert result.status == "completed"
    assert [r.user_id for r in result.account_results] == ["bad", "good"]
    assert result.visited_url_count == 1
    bad = result.account_results[0]
    assert bad.details and bad.details[0].status == "error"
    assert "browser crashed" in bad.details[0].message


def test_stop_request_skips_remaining_accounts(tmp_path, monkeypatch, no_collection):
    """사용자가 중지를 누르면 → 남은 계정은 건너뛰고 결과는 stopped로 저장된다."""
    config = _config(tmp_path, ["user1", "user2"])
    processed = []

    async def fake_process_account(account, session_db, *args, **kwargs):
        processed.append(account.user_id)
        np.request_stop()
        return _ok_result(account.user_id)

    monkeypatch.setattr(np, "process_account", fake_process_account)
    result = asyncio.run(np.run(config))

    assert processed == ["user1"]
    assert result.status == "stopped"
    runs = np.recent_runs(config.db_path, 10)
    assert runs[0]["status"] == "stopped"
    assert runs[0]["finished_at"]


def test_time_limit_stops_run(tmp_path, monkeypatch, no_collection):
    """실행 시간 제한을 넘기면 → 남은 계정을 건너뛰고 timeout으로 끝난다."""
    config = _config(tmp_path, ["user1", "user2"], max_run_seconds=1)
    processed = []
    clock = {"now": 1000.0}
    monkeypatch.setattr(np, "_monotonic", lambda: clock["now"])

    async def fake_process_account(account, session_db, *args, **kwargs):
        processed.append(account.user_id)
        clock["now"] += 5
        return _ok_result(account.user_id)

    monkeypatch.setattr(np, "process_account", fake_process_account)
    result = asyncio.run(np.run(config))

    assert processed == ["user1"]
    assert result.status == "timeout"


def test_stale_running_history_marked_interrupted(tmp_path, monkeypatch, no_collection):
    """재시작 등으로 'running'에 멈춘 이전 기록은 → 다음 실행 때 interrupted로 정리된다."""
    config = _config(tmp_path, ["user1"])
    db = np.Database(config.db_path)
    db.create_all()
    with db.get_session() as s:
        s.add(np.RunHistory(status="running", account_count=1))

    async def fake_process_account(account, session_db, *args, **kwargs):
        return _ok_result(account.user_id)

    monkeypatch.setattr(np, "process_account", fake_process_account)
    asyncio.run(np.run(config))

    statuses = sorted(r["status"] for r in np.recent_runs(config.db_path, 10))
    assert statuses == ["completed", "interrupted"]
