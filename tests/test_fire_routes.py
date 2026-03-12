"""Tests for the fire-control REST API (src/rws_tracking/api/fire_routes.py).

These tests cover the complete fire control surface without needing a real
pipeline, camera, or YOLO model — all heavy dependencies are mocked.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from flask import Flask

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_chain(state: str = "safe", can_fire: bool = False, operator_id: str | None = None):
    """Build a minimal ShootingChain-like mock."""
    from src.rws_tracking.safety.shooting_chain import ShootingChain

    chain = ShootingChain()
    # Advance to the requested state.
    if state in ("armed", "fire_authorized", "fire_requested"):
        chain.arm("test_op")
    if state in ("fire_authorized", "fire_requested"):
        chain.update_authorization(True, timestamp=0.0)
    if state == "fire_requested":
        chain.request_fire("test_op")
    return chain


def _make_app(extensions: dict | None = None):
    from src.rws_tracking.api.fire_routes import fire_bp

    app = Flask(__name__)
    app.config["TESTING"] = True
    if extensions:
        app.extensions.update(extensions)
    app.register_blueprint(fire_bp)
    return app


# ---------------------------------------------------------------------------
# GET /api/fire/status
# ---------------------------------------------------------------------------


class TestGetFireStatus:
    def test_no_chain_returns_not_configured(self):
        app = _make_app()
        with app.test_client() as c:
            resp = c.get("/api/fire/status")
            assert resp.status_code == 200
            data = resp.get_json()
            assert data["state"] == "not_configured"
            assert data["can_fire"] is False

    def test_safe_state(self):
        chain = _make_chain("safe")
        app = _make_app({"shooting_chain": chain})
        with app.test_client() as c:
            resp = c.get("/api/fire/status")
            data = resp.get_json()
            assert data["state"] == "safe"
            assert data["can_fire"] is False

    def test_armed_state(self):
        chain = _make_chain("armed")
        app = _make_app({"shooting_chain": chain})
        with app.test_client() as c:
            resp = c.get("/api/fire/status")
            data = resp.get_json()
            assert data["state"] == "armed"

    def test_fire_authorized_state(self):
        chain = _make_chain("fire_authorized")
        app = _make_app({"shooting_chain": chain})
        with app.test_client() as c:
            resp = c.get("/api/fire/status")
            data = resp.get_json()
            assert data["state"] == "fire_authorized"


# ---------------------------------------------------------------------------
# POST /api/fire/arm
# ---------------------------------------------------------------------------


class TestArmEndpoint:
    def test_arm_from_safe(self):
        chain = _make_chain("safe")
        app = _make_app({"shooting_chain": chain})
        with app.test_client() as c:
            resp = c.post("/api/fire/arm", json={"operator_id": "op1"})
            assert resp.status_code == 200
            data = resp.get_json()
            assert data["state"] == "armed"
            assert data["operator_id"] == "op1"

    def test_arm_missing_operator_id_returns_400(self):
        chain = _make_chain("safe")
        app = _make_app({"shooting_chain": chain})
        with app.test_client() as c:
            resp = c.post("/api/fire/arm", json={})
            assert resp.status_code == 400
            assert "error" in resp.get_json()

    def test_arm_when_already_armed_returns_409(self):
        chain = _make_chain("armed")
        app = _make_app({"shooting_chain": chain})
        with app.test_client() as c:
            resp = c.post("/api/fire/arm", json={"operator_id": "op1"})
            assert resp.status_code == 409

    def test_arm_no_chain_returns_503(self):
        app = _make_app()
        with app.test_client() as c:
            resp = c.post("/api/fire/arm", json={"operator_id": "op1"})
            assert resp.status_code == 503


# ---------------------------------------------------------------------------
# POST /api/fire/safe
# ---------------------------------------------------------------------------


class TestSafeEndpoint:
    def test_safe_from_armed(self):
        chain = _make_chain("armed")
        app = _make_app({"shooting_chain": chain})
        with app.test_client() as c:
            resp = c.post("/api/fire/safe", json={"reason": "operator pressed safe"})
            assert resp.status_code == 200
            data = resp.get_json()
            assert data["state"] == "safe"

    def test_safe_no_body_still_works(self):
        chain = _make_chain("armed")
        app = _make_app({"shooting_chain": chain})
        with app.test_client() as c:
            resp = c.post("/api/fire/safe")
            assert resp.status_code == 200
            assert resp.get_json()["state"] == "safe"

    def test_safe_no_chain_returns_503(self):
        app = _make_app()
        with app.test_client() as c:
            resp = c.post("/api/fire/safe", json={})
            assert resp.status_code == 503

    def test_safe_from_safe_is_idempotent(self):
        chain = _make_chain("safe")
        app = _make_app({"shooting_chain": chain})
        with app.test_client() as c:
            resp = c.post("/api/fire/safe")
            assert resp.status_code == 200
            assert resp.get_json()["state"] == "safe"


# ---------------------------------------------------------------------------
# POST /api/fire/request
# ---------------------------------------------------------------------------


class TestRequestFireEndpoint:
    def test_request_from_fire_authorized(self):
        chain = _make_chain("fire_authorized")
        app = _make_app({"shooting_chain": chain})
        with app.test_client() as c:
            resp = c.post("/api/fire/request", json={"operator_id": "op1"})
            assert resp.status_code == 200
            data = resp.get_json()
            assert data["state"] == "fire_requested"

    def test_request_from_safe_returns_403(self):
        chain = _make_chain("safe")
        app = _make_app({"shooting_chain": chain})
        with app.test_client() as c:
            resp = c.post("/api/fire/request", json={"operator_id": "op1"})
            assert resp.status_code == 403

    def test_request_missing_operator_id_returns_400(self):
        chain = _make_chain("fire_authorized")
        app = _make_app({"shooting_chain": chain})
        with app.test_client() as c:
            resp = c.post("/api/fire/request", json={})
            assert resp.status_code == 400

    def test_request_no_chain_returns_503(self):
        app = _make_app()
        with app.test_client() as c:
            resp = c.post("/api/fire/request", json={"operator_id": "op1"})
            assert resp.status_code == 503


# ---------------------------------------------------------------------------
# POST /api/fire/heartbeat
# ---------------------------------------------------------------------------


class TestHeartbeatEndpoint:
    def test_heartbeat_success(self):
        app = _make_app()  # no watchdog needed for basic response
        with app.test_client() as c:
            resp = c.post("/api/fire/heartbeat", json={"operator_id": "op1"})
            assert resp.status_code == 200
            data = resp.get_json()
            assert data["ok"] is True
            assert data["operator_id"] == "op1"

    def test_heartbeat_missing_operator_id_returns_400(self):
        app = _make_app()
        with app.test_client() as c:
            resp = c.post("/api/fire/heartbeat", json={})
            assert resp.status_code == 400

    def test_heartbeat_notifies_watchdog(self):
        mock_wd = MagicMock()
        app = _make_app({"operator_watchdog": mock_wd})
        with app.test_client() as c:
            resp = c.post("/api/fire/heartbeat", json={"operator_id": "op1"})
            assert resp.status_code == 200
            mock_wd.heartbeat.assert_called_once_with("op1")

    def test_heartbeat_notifies_interlock(self):
        mock_sm = MagicMock()
        mock_sm.interlock = MagicMock()
        app = _make_app({"safety_manager": mock_sm})
        with app.test_client() as c:
            resp = c.post("/api/fire/heartbeat", json={"operator_id": "op2"})
            assert resp.status_code == 200
            mock_sm.interlock.operator_heartbeat.assert_called_once()


# ---------------------------------------------------------------------------
# IFF endpoints
# ---------------------------------------------------------------------------


class TestIffEndpoints:
    def _make_iff_checker(self, friendly_ids: list[int] | None = None):
        from src.rws_tracking.safety.iff import IFFChecker

        iff = IFFChecker()
        for tid in friendly_ids or []:
            iff.add_friendly_track(tid)
        return iff

    def test_mark_friendly_success(self):
        iff = self._make_iff_checker()
        app = _make_app({"iff_checker": iff})
        with app.test_client() as c:
            resp = c.post("/api/fire/iff/mark_friendly", json={"track_id": 7})
            assert resp.status_code == 200
            data = resp.get_json()
            assert data["ok"] is True
            assert data["track_id"] == 7
            assert 7 in iff.friendly_track_ids

    def test_mark_friendly_missing_track_id_returns_400(self):
        iff = self._make_iff_checker()
        app = _make_app({"iff_checker": iff})
        with app.test_client() as c:
            resp = c.post("/api/fire/iff/mark_friendly", json={})
            assert resp.status_code == 400

    def test_mark_friendly_non_integer_track_id_returns_400(self):
        iff = self._make_iff_checker()
        app = _make_app({"iff_checker": iff})
        with app.test_client() as c:
            resp = c.post("/api/fire/iff/mark_friendly", json={"track_id": "abc"})
            assert resp.status_code == 400

    def test_mark_friendly_no_iff_checker_returns_503(self):
        app = _make_app()
        with app.test_client() as c:
            resp = c.post("/api/fire/iff/mark_friendly", json={"track_id": 1})
            assert resp.status_code == 503

    def test_unmark_friendly_success(self):
        iff = self._make_iff_checker([3, 5])
        app = _make_app({"iff_checker": iff})
        with app.test_client() as c:
            resp = c.post("/api/fire/iff/unmark_friendly", json={"track_id": 3})
            assert resp.status_code == 200
            assert 3 not in iff.friendly_track_ids
            assert 5 in iff.friendly_track_ids

    def test_iff_status_lists_friendly_tracks(self):
        iff = self._make_iff_checker([1, 2, 3])
        app = _make_app({"iff_checker": iff})
        with app.test_client() as c:
            resp = c.get("/api/fire/iff/status")
            assert resp.status_code == 200
            data = resp.get_json()
            assert set(data["friendly_track_ids"]) == {1, 2, 3}

    def test_iff_status_no_checker_returns_503(self):
        app = _make_app()
        with app.test_client() as c:
            resp = c.get("/api/fire/iff/status")
            assert resp.status_code == 503


# ---------------------------------------------------------------------------
# Clips endpoints
# ---------------------------------------------------------------------------


class TestClipsEndpoints:
    def test_list_clips_no_dir_returns_empty_list(self):
        app = _make_app()
        with app.test_client() as c:
            resp = c.get("/api/fire/clips")
            assert resp.status_code == 200
            assert resp.get_json() == []

    def test_list_clips_empty_dir(self, tmp_path):
        mock_vrb = SimpleNamespace(output_dir=str(tmp_path))
        app = _make_app({"video_ring_buffer": mock_vrb})
        with app.test_client() as c:
            resp = c.get("/api/fire/clips")
            assert resp.status_code == 200
            assert resp.get_json() == []

    def test_list_clips_with_files(self, tmp_path):
        (tmp_path / "clip_1700000000.mp4").write_bytes(b"fake")
        (tmp_path / "clip_1700001000.mp4").write_bytes(b"fake2")
        mock_vrb = SimpleNamespace(output_dir=str(tmp_path))
        app = _make_app({"video_ring_buffer": mock_vrb})
        with app.test_client() as c:
            resp = c.get("/api/fire/clips")
            data = resp.get_json()
            assert len(data) == 2
            filenames = {e["filename"] for e in data}
            assert "clip_1700000000.mp4" in filenames
            assert "clip_1700001000.mp4" in filenames

    def test_download_clip_success(self, tmp_path):
        clip = tmp_path / "clip_1234567890.mp4"
        clip.write_bytes(b"video data")
        mock_vrb = SimpleNamespace(output_dir=str(tmp_path))
        app = _make_app({"video_ring_buffer": mock_vrb})
        with app.test_client() as c:
            resp = c.get("/api/fire/clips/clip_1234567890.mp4")
            assert resp.status_code == 200

    def test_download_clip_not_found(self, tmp_path):
        mock_vrb = SimpleNamespace(output_dir=str(tmp_path))
        app = _make_app({"video_ring_buffer": mock_vrb})
        with app.test_client() as c:
            resp = c.get("/api/fire/clips/ghost.mp4")
            assert resp.status_code == 404

    def test_download_clip_path_traversal_rejected(self, tmp_path):
        mock_vrb = SimpleNamespace(output_dir=str(tmp_path))
        app = _make_app({"video_ring_buffer": mock_vrb})
        with app.test_client() as c:
            resp = c.get("/api/fire/clips/..%2F..%2Fetc%2Fpasswd")
            # Flask routing will either 404 or reject; either way, not 200
            assert resp.status_code in (400, 404)


# ---------------------------------------------------------------------------
# Designation endpoints
# ---------------------------------------------------------------------------


class TestDesignationEndpoints:
    def _make_pipeline(self, track_id: int | None = None):
        pipeline = MagicMock()
        pipeline.designated_track_id = track_id
        return pipeline

    def _make_api(self, pipeline=None):
        api = MagicMock()
        api.pipeline = pipeline
        return api

    def test_get_designation_no_pipeline(self):
        app = _make_app()
        with app.test_client() as c:
            resp = c.get("/api/fire/designate")
            assert resp.status_code == 200
            data = resp.get_json()
            assert data["track_id"] is None
            assert data["designated"] is False

    def test_get_designation_with_track(self):
        pipeline = self._make_pipeline(track_id=5)
        api = self._make_api(pipeline)
        app = _make_app({"tracking_api": api})
        with app.test_client() as c:
            resp = c.get("/api/fire/designate")
            data = resp.get_json()
            assert data["track_id"] == 5
            assert data["designated"] is True

    def test_get_designation_no_track(self):
        pipeline = self._make_pipeline(track_id=None)
        api = self._make_api(pipeline)
        app = _make_app({"tracking_api": api})
        with app.test_client() as c:
            resp = c.get("/api/fire/designate")
            data = resp.get_json()
            assert data["track_id"] is None
            assert data["designated"] is False

    def test_designate_target_success(self):
        pipeline = self._make_pipeline()
        api = self._make_api(pipeline)
        app = _make_app({"tracking_api": api})
        with app.test_client() as c:
            resp = c.post("/api/fire/designate", json={"track_id": 3, "operator_id": "op1"})
            assert resp.status_code == 200
            data = resp.get_json()
            assert data["ok"] is True
            assert data["track_id"] == 3
            pipeline.designate_target.assert_called_once_with(3, "op1")

    def test_designate_target_missing_track_id_returns_400(self):
        pipeline = self._make_pipeline()
        api = self._make_api(pipeline)
        app = _make_app({"tracking_api": api})
        with app.test_client() as c:
            resp = c.post("/api/fire/designate", json={})
            assert resp.status_code == 400

    def test_designate_target_invalid_track_id_returns_400(self):
        pipeline = self._make_pipeline()
        api = self._make_api(pipeline)
        app = _make_app({"tracking_api": api})
        with app.test_client() as c:
            resp = c.post("/api/fire/designate", json={"track_id": "bad"})
            assert resp.status_code == 400

    def test_designate_no_pipeline_returns_503(self):
        app = _make_app()
        with app.test_client() as c:
            resp = c.post("/api/fire/designate", json={"track_id": 1})
            assert resp.status_code == 503

    def test_clear_designation_success(self):
        pipeline = self._make_pipeline(track_id=7)
        api = self._make_api(pipeline)
        app = _make_app({"tracking_api": api})
        with app.test_client() as c:
            resp = c.delete("/api/fire/designate")
            assert resp.status_code == 200
            data = resp.get_json()
            assert data["ok"] is True
            assert data["cleared_track_id"] == 7
            pipeline.clear_designation.assert_called_once()

    def test_clear_designation_no_pipeline_returns_503(self):
        app = _make_app()
        with app.test_client() as c:
            resp = c.delete("/api/fire/designate")
            assert resp.status_code == 503
