"""mod_main 연결 확인: FlaskFarm 대신 최소 가짜 모듈로 import 한다."""
import importlib
import os
import sys
import types

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture
def mod_main(monkeypatch):
    settings = {}

    class FakeModelSetting:
        @staticmethod
        def get(key):
            return settings.get(key)

        @staticmethod
        def set(key, value):
            settings[key] = value

    class FakeBase:
        def __init__(self, P, name=None, first_menu=None, scheduler_desc=None):
            self.P = P
            self.name = name

    logger = types.SimpleNamespace(info=lambda *a, **k: None, warning=lambda *a, **k: None, error=lambda *a, **k: None)
    fake_P = types.SimpleNamespace(ModelSetting=FakeModelSetting, logger=logger, package_name="ff_naverpaper")

    setup_mod = types.ModuleType("ff_naverpaper.setup")
    setup_mod.P = fake_P
    setup_mod.F = types.SimpleNamespace()
    setup_mod.PluginModuleBase = FakeBase
    setup_mod.default_route_socketio_module = lambda *a, **k: None
    setup_mod.__all__ = ["P", "F", "PluginModuleBase", "default_route_socketio_module"]

    flask_mod = types.ModuleType("flask")
    flask_mod.jsonify = lambda x: x
    flask_mod.render_template = lambda *a, **k: ""

    pkg = types.ModuleType("ff_naverpaper")
    pkg.__path__ = [ROOT]
    monkeypatch.setitem(sys.modules, "ff_naverpaper", pkg)
    monkeypatch.setitem(sys.modules, "ff_naverpaper.setup", setup_mod)
    monkeypatch.setitem(sys.modules, "flask", flask_mod)
    sys.modules.pop("ff_naverpaper.mod_main", None)
    sys.modules.pop("ff_naverpaper.source_naverpaper", None)
    module = importlib.import_module("ff_naverpaper.mod_main")
    yield module, settings
    sys.modules.pop("ff_naverpaper.mod_main", None)
    sys.modules.pop("ff_naverpaper.source_naverpaper", None)


def test_stop_command_sets_stop_flag_while_running(mod_main):
    module, _ = mod_main
    m = module.ModuleMain.__new__(module.ModuleMain)
    m.collection_running = True
    np = module._load_source_module()
    np.clear_stop_request()

    ret = m.process_command("run_stop", None, None, None, None)

    assert ret["ret"] == "success"
    assert np.is_stop_requested() is True
    np.clear_stop_request()


def test_stop_command_warns_when_idle(mod_main):
    module, _ = mod_main
    m = module.ModuleMain.__new__(module.ModuleMain)
    m.collection_running = False
    np = module._load_source_module()
    np.clear_stop_request()

    ret = m.process_command("run_stop", None, None, None, None)

    assert ret["ret"] == "warning"
    assert np.is_stop_requested() is False


def test_time_limit_setting_passed_to_run(mod_main, monkeypatch, tmp_path):
    module, settings = mod_main
    settings["max_run_minutes"] = "15"
    m = module.ModuleMain.__new__(module.ModuleMain)
    np = module._load_source_module()
    captured = {}

    monkeypatch.setattr(m, "_accounts", lambda *a, **k: [np.AccountConfig(user_id="u", password="p")], raising=False)
    monkeypatch.setattr(m, "_db_path", lambda: str(tmp_path / "x.db"), raising=False)
    monkeypatch.setattr(m, "_cookie_dir", lambda: str(tmp_path), raising=False)
    monkeypatch.setattr(m, "_ensure_dirs", lambda: None, raising=False)
    monkeypatch.setattr(np, "run_sync", lambda config, log=None: captured.setdefault("config", config))

    m._run_now()

    assert captured["config"].max_run_seconds == 15 * 60


def test_cookie_renew_setting_passed_to_run(mod_main, monkeypatch, tmp_path):
    module, settings = mod_main
    settings["cookie_renew_days"] = "10"
    m = module.ModuleMain.__new__(module.ModuleMain)
    np = module._load_source_module()
    captured = {}
    monkeypatch.setattr(m, "_accounts", lambda *a, **k: [np.AccountConfig(user_id="u", password="p")], raising=False)
    monkeypatch.setattr(m, "_db_path", lambda: str(tmp_path / "x.db"), raising=False)
    monkeypatch.setattr(m, "_cookie_dir", lambda: str(tmp_path), raising=False)
    monkeypatch.setattr(m, "_ensure_dirs", lambda: None, raising=False)
    monkeypatch.setattr(np, "run_sync", lambda config, log=None: captured.setdefault("config", config))

    m._run_now()

    assert captured["config"].cookie_renew_days == 10
