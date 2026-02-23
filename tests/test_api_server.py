"""API Server 单元测试 — mock Flask。"""

from unittest.mock import MagicMock, patch

import pytest


class TestTrackingAPI:
    @pytest.fixture
    def api(self):
        from src.rws_tracking.api.server import TrackingAPI
        api = TrackingAPI.__new__(TrackingAPI)
        api.config = MagicMock()
        api.pipeline = MagicMock()
        api.pipeline.controller = MagicMock()
        api.pipeline.selector = MagicMock()
        api.pipeline._safety_manager = None
        api.camera = None
        api.running = False
        api.frame_count = 0
        api.error_count = 0
        api.thread = None
        api.last_error = None
        api.last_frame_time = 0.0
        return api

    def test_get_status(self, api):
        status = api.get_status()
        assert "running" in status

    def test_start_tracking_no_camera(self, api):
        result = api.start_tracking()
        assert not result["success"]

    def test_stop_tracking(self, api):
        api.running = True
        result = api.stop_tracking()
        assert result["success"]
        assert not api.running

    def test_update_config_empty(self, api):
        result = api.update_config({})
        assert result["success"]

    def test_update_config_pid(self, api):
        # Setup mock PID
        class _F:
            def __init__(self, name): self.name = name

        mock_pid = MagicMock()
        mock_cfg = MagicMock()
        mock_cfg.kp = 5.0
        mock_cfg.ki = 0.3
        mock_cfg.kd = 0.2
        mock_cfg.__dataclass_fields__ = {
            "kp": _F("kp"),
            "ki": _F("ki"),
            "kd": _F("kd"),
        }
        mock_pid.cfg = mock_cfg
        api.pipeline.controller._yaw_pid = mock_pid
        api.pipeline.controller._pitch_pid = mock_pid

        result = api.update_config({
            "pid": {"yaw": {"kp": 8.0}}
        })
        assert result["success"]
        assert "pid.yaw" in result.get("hot_applied", [])

    def test_update_config_stored(self, api):
        api.config.some_key = "old"
        result = api.update_config({"some_key": "new"})
        assert result["success"]


class TestFlaskApp:
    @pytest.fixture
    def client(self):
        from src.rws_tracking.api.server import TrackingAPI, run_api_server
        api = TrackingAPI.__new__(TrackingAPI)
        api.config = MagicMock()
        api.pipeline = MagicMock()
        api.pipeline.controller = MagicMock()
        api.pipeline.selector = MagicMock()
        api.pipeline = None
        api.camera = None
        api.running = False
        api.frame_count = 0
        api.error_count = 0
        api.thread = None
        api.last_error = None
        api.last_frame_time = 0.0

        from flask import Flask
        app = Flask(__name__)

        @app.route("/api/status")
        def status():
            from flask import jsonify
            return jsonify(api.get_status())

        @app.route("/api/tracking/start", methods=["POST"])
        def start():
            from flask import jsonify
            return jsonify(api.start_tracking())

        @app.route("/api/tracking/stop", methods=["POST"])
        def stop():
            from flask import jsonify
            return jsonify(api.stop_tracking())

        app.config["TESTING"] = True
        return app.test_client()

    def test_status_endpoint(self, client):
        resp = client.get("/api/status")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "running" in data

    def test_start_endpoint(self, client):
        resp = client.post("/api/tracking/start")
        assert resp.status_code == 200

    def test_stop_endpoint(self, client):
        resp = client.post("/api/tracking/stop")
        assert resp.status_code == 200
