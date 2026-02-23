"""API Server 单元测试 — mock Flask。"""

from unittest.mock import MagicMock, patch
from types import SimpleNamespace

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


class TestGetConfig:
    """Test GET /api/config endpoint via a minimal Flask app."""

    def _make_pid_cfg(self, kp, ki, kd):
        return SimpleNamespace(kp=kp, ki=ki, kd=kd)

    def _make_app_with_config(self, config_path="config.yaml", ctrl_cfg=None):
        from flask import Flask, jsonify
        from src.rws_tracking.api.server import TrackingAPI

        api = TrackingAPI.__new__(TrackingAPI)
        api.config_path = config_path
        api.config = MagicMock()
        api.pipeline = None

        app = Flask(__name__)
        app.config["TESTING"] = True

        @app.route("/api/config", methods=["GET"])
        def get_config():
            from src.rws_tracking.config.loader import load_config
            try:
                cfg = load_config(api.config_path)
                ctrl = cfg.controller
                if ctrl is None:
                    return jsonify({"error": "No controller config"}), 503
                return jsonify({
                    "pid": {
                        "yaw":   {"kp": ctrl.yaw_pid.kp,   "ki": ctrl.yaw_pid.ki,   "kd": ctrl.yaw_pid.kd},
                        "pitch": {"kp": ctrl.pitch_pid.kp, "ki": ctrl.pitch_pid.ki, "kd": ctrl.pitch_pid.kd},
                    }
                })
            except Exception as exc:
                return jsonify({"error": str(exc)}), 503

        return app, api

    def test_get_config_returns_pid(self):
        """GET /api/config returns yaw + pitch PID values from config."""
        mock_ctrl = SimpleNamespace(
            yaw_pid=self._make_pid_cfg(5.0, 0.1, 0.3),
            pitch_pid=self._make_pid_cfg(4.0, 0.05, 0.25),
        )
        mock_cfg = SimpleNamespace(controller=mock_ctrl)

        app, _ = self._make_app_with_config()
        with patch("src.rws_tracking.config.loader.load_config", return_value=mock_cfg):
            with app.test_client() as c:
                resp = c.get("/api/config")
                assert resp.status_code == 200
                data = resp.get_json()
                assert "pid" in data
                assert data["pid"]["yaw"]["kp"] == pytest.approx(5.0)
                assert data["pid"]["pitch"]["kd"] == pytest.approx(0.25)

    def test_get_config_no_controller_returns_503(self):
        """GET /api/config returns 503 when controller config is absent."""
        mock_cfg = SimpleNamespace(controller=None)

        app, _ = self._make_app_with_config()
        with patch("src.rws_tracking.config.loader.load_config", return_value=mock_cfg):
            with app.test_client() as c:
                resp = c.get("/api/config")
                assert resp.status_code == 503
                data = resp.get_json()
                assert "error" in data

    def test_get_config_load_failure_returns_503(self):
        """GET /api/config returns 503 when load_config raises."""
        app, _ = self._make_app_with_config()
        with patch(
            "src.rws_tracking.config.loader.load_config",
            side_effect=FileNotFoundError("not found"),
        ):
            with app.test_client() as c:
                resp = c.get("/api/config")
                assert resp.status_code == 503

    def test_get_config_structure(self):
        """GET /api/config response has expected nested structure."""
        mock_ctrl = SimpleNamespace(
            yaw_pid=self._make_pid_cfg(1.0, 2.0, 3.0),
            pitch_pid=self._make_pid_cfg(4.0, 5.0, 6.0),
        )
        mock_cfg = SimpleNamespace(controller=mock_ctrl)

        app, _ = self._make_app_with_config()
        with patch("src.rws_tracking.config.loader.load_config", return_value=mock_cfg):
            with app.test_client() as c:
                resp = c.get("/api/config")
                data = resp.get_json()
                for axis in ("yaw", "pitch"):
                    assert axis in data["pid"]
                    for param in ("kp", "ki", "kd"):
                        assert param in data["pid"][axis]


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
