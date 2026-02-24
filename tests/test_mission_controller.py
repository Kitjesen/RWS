"""Tests for mission controller API (mission_routes Blueprint)."""

from __future__ import annotations

import pytest
from flask import Flask

from src.rws_tracking.api.mission_routes import _reset_state, mission_bp

# ---------------------------------------------------------------------------
# Minimal mock API
# ---------------------------------------------------------------------------


class MockPipeline:
    def __init__(self):
        self._lifecycle_manager = None
        self._shooting_chain = None
        self._audit_logger = None


class MockTrackingAPI:
    def __init__(self, start_ok=True):
        self.pipeline = MockPipeline()
        self._start_ok = start_ok
        self.stop_called = False

    def start_tracking(self, camera_source=0):
        if self._start_ok:
            return {"success": True}
        return {"success": False, "error": "camera fail"}

    def stop_tracking(self):
        self.stop_called = True
        return {"success": True}


@pytest.fixture()
def app():
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(mission_bp)
    with app.app_context():
        _reset_state()
    return app


@pytest.fixture()
def client(app):
    with app.test_client() as c:
        yield c


@pytest.fixture()
def client_with_api(app):
    api = MockTrackingAPI()
    app.extensions["tracking_api"] = api
    with app.test_client() as c:
        yield c, api


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestMissionStatus:
    def test_idle_state(self, client):
        r = client.get("/api/mission/status")
        assert r.status_code == 200
        d = r.get_json()
        assert d["active"] is False
        assert d["elapsed_s"] == 0.0


class TestMissionStart:
    def test_start_no_api(self, client):
        r = client.post("/api/mission/start", json={})
        assert r.status_code == 503

    def test_start_success(self, client_with_api):
        c, api = client_with_api
        r = c.post("/api/mission/start", json={"camera_source": 0, "mission_name": "Test"})
        assert r.status_code == 200
        d = r.get_json()
        assert d["ok"] is True
        assert "session_id" in d

    def test_double_start_rejected(self, client_with_api):
        c, api = client_with_api
        c.post("/api/mission/start", json={})
        r = c.post("/api/mission/start", json={})
        assert r.status_code == 409

    def test_status_active_after_start(self, client_with_api):
        c, api = client_with_api
        c.post("/api/mission/start", json={"mission_name": "Alpha"})
        r = c.get("/api/mission/status")
        d = r.get_json()
        assert d["active"] is True
        assert d["elapsed_s"] >= 0.0

    def test_camera_fail_returns_500(self, app):
        api = MockTrackingAPI(start_ok=False)
        app.extensions["tracking_api"] = api
        with app.test_client() as c:
            r = c.post("/api/mission/start", json={})
            assert r.status_code == 500


class TestMissionEnd:
    def test_end_no_active_mission(self, client):
        r = client.post("/api/mission/end", json={})
        assert r.status_code == 409

    def test_end_after_start(self, client_with_api):
        c, api = client_with_api
        c.post("/api/mission/start", json={"mission_name": "Bravo"})
        r = c.post("/api/mission/end", json={})
        assert r.status_code == 200
        d = r.get_json()
        assert d["ok"] is True
        assert d["elapsed_s"] >= 0.0
        assert api.stop_called

    def test_idle_after_end(self, client_with_api):
        c, api = client_with_api
        c.post("/api/mission/start", json={})
        c.post("/api/mission/end", json={})
        r = c.get("/api/mission/status")
        assert r.get_json()["active"] is False

    def test_can_restart_after_end(self, client_with_api):
        c, api = client_with_api
        c.post("/api/mission/start", json={})
        c.post("/api/mission/end", json={})
        r = c.post("/api/mission/start", json={})
        assert r.status_code == 200
