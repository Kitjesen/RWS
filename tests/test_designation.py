"""Tests for operator target designation — pipeline override and API endpoints."""

from __future__ import annotations

from unittest.mock import MagicMock

# ---------------------------------------------------------------------------
# Pipeline designation tests
# ---------------------------------------------------------------------------


class TestPipelineDesignation:
    """Test VisionGimbalPipeline designation methods."""

    def _make_pipeline(self):
        """Build a minimal pipeline for testing (no camera/YOLO)."""
        from src.rws_tracking.algebra import CameraModel, PixelToGimbalTransform
        from src.rws_tracking.config import GimbalControllerConfig, PIDConfig, SelectorConfig
        from src.rws_tracking.control import TwoAxisGimbalController
        from src.rws_tracking.hardware import SimulatedGimbalDriver
        from src.rws_tracking.perception import PassthroughDetector, SimpleIoUTracker
        from src.rws_tracking.perception.selector import WeightedTargetSelector
        from src.rws_tracking.pipeline.pipeline import VisionGimbalPipeline
        from src.rws_tracking.telemetry import InMemoryTelemetryLogger

        cam = CameraModel(width=1280, height=720, fx=970.0, fy=965.0, cx=640.0, cy=360.0)
        pid = PIDConfig(kp=5.0, ki=0.3, kd=0.2)
        cfg = GimbalControllerConfig(yaw_pid=pid, pitch_pid=pid)
        return VisionGimbalPipeline(
            detector=PassthroughDetector(),
            tracker=SimpleIoUTracker(),
            selector=WeightedTargetSelector(
                frame_width=cam.width,
                frame_height=cam.height,
                config=SelectorConfig(),
            ),
            controller=TwoAxisGimbalController(transform=PixelToGimbalTransform(cam), cfg=cfg),
            driver=SimulatedGimbalDriver(),
            telemetry=InMemoryTelemetryLogger(),
        )

    def test_designated_track_id_starts_none(self):
        p = self._make_pipeline()
        assert p.designated_track_id is None

    def test_designate_sets_track_id(self):
        p = self._make_pipeline()
        p.designate_target(7, "op1")
        assert p.designated_track_id == 7
        assert p._designated_by == "op1"

    def test_clear_designation_removes_id(self):
        p = self._make_pipeline()
        p.designate_target(7)
        p.clear_designation()
        assert p.designated_track_id is None

    def test_clear_designation_when_none_is_noop(self):
        p = self._make_pipeline()
        p.clear_designation()  # should not raise
        assert p.designated_track_id is None

    def test_designate_overrides_previous(self):
        p = self._make_pipeline()
        p.designate_target(3)
        p.designate_target(9, "op2")
        assert p.designated_track_id == 9
        assert p._designated_by == "op2"


# ---------------------------------------------------------------------------
# API endpoint tests
# ---------------------------------------------------------------------------


def _make_app_with_mock_pipeline(pipeline=None):
    """Create a Flask test app with fire_bp and a mock pipeline."""
    from flask import Flask

    from src.rws_tracking.api.fire_routes import fire_bp

    app = Flask(__name__)
    app.config["TESTING"] = True

    mock_api = MagicMock()
    mock_api.pipeline = pipeline
    app.extensions["tracking_api"] = mock_api

    app.register_blueprint(fire_bp)
    return app


class TestDesignationAPI:
    def _pipeline_mock(self, designated=None):
        m = MagicMock()
        m.designated_track_id = designated
        return m

    def test_post_designate_sets_track(self):
        pl = self._pipeline_mock()
        app = _make_app_with_mock_pipeline(pl)
        with app.test_client() as c:
            resp = c.post(
                "/api/fire/designate",
                json={"track_id": 5, "operator_id": "op1"},
            )
            assert resp.status_code == 200
            data = resp.get_json()
            assert data["ok"] is True
            assert data["track_id"] == 5
            pl.designate_target.assert_called_once_with(5, "op1")

    def test_post_designate_missing_track_id_returns_400(self):
        pl = self._pipeline_mock()
        app = _make_app_with_mock_pipeline(pl)
        with app.test_client() as c:
            resp = c.post("/api/fire/designate", json={})
            assert resp.status_code == 400

    def test_post_designate_no_pipeline_returns_503(self):
        app = _make_app_with_mock_pipeline(None)
        with app.test_client() as c:
            resp = c.post("/api/fire/designate", json={"track_id": 1})
            assert resp.status_code == 503

    def test_delete_designation_clears(self):
        pl = self._pipeline_mock(designated=7)
        app = _make_app_with_mock_pipeline(pl)
        with app.test_client() as c:
            resp = c.delete("/api/fire/designate")
            assert resp.status_code == 200
            data = resp.get_json()
            assert data["ok"] is True
            assert data["cleared_track_id"] == 7
            pl.clear_designation.assert_called_once()

    def test_get_designation_returns_current(self):
        pl = self._pipeline_mock(designated=4)
        app = _make_app_with_mock_pipeline(pl)
        with app.test_client() as c:
            resp = c.get("/api/fire/designate")
            assert resp.status_code == 200
            data = resp.get_json()
            assert data["track_id"] == 4
            assert data["designated"] is True

    def test_get_designation_none(self):
        pl = self._pipeline_mock(designated=None)
        app = _make_app_with_mock_pipeline(pl)
        with app.test_client() as c:
            resp = c.get("/api/fire/designate")
            data = resp.get_json()
            assert data["track_id"] is None
            assert data["designated"] is False

    def test_get_designation_no_pipeline(self):
        app = _make_app_with_mock_pipeline(None)
        with app.test_client() as c:
            resp = c.get("/api/fire/designate")
            assert resp.status_code == 200
            data = resp.get_json()
            assert data["designated"] is False
