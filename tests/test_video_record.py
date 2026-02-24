"""视频录制 API 单元测试。

Tests the video_record_routes Blueprint endpoints and the record_frame() helper.
Uses a temporary directory for clip storage to avoid polluting the real logs/.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from flask import Flask

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_client(tmp_clips_dir: Path):
    """Return a Flask test client with the record blueprint wired in.

    Patches the module-level ``_clips_dir`` so clips land in a tmpdir.
    """
    import src.rws_tracking.api.video_record_routes as vrr

    # Reset all module-level state before each test.
    with vrr._lock:
        vrr._recording = False
        vrr._writer = None
        vrr._clip_filename = None
        vrr._started_at = None
        vrr._clips_dir = tmp_clips_dir

    from src.rws_tracking.api.video_record_routes import record_bp

    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(record_bp)
    return app.test_client()


# ---------------------------------------------------------------------------
# Test class
# ---------------------------------------------------------------------------


class TestVideoRecord:
    @pytest.fixture(autouse=True)
    def _reset_state(self, tmp_path):
        """Reset module state and point clips_dir to a tmpdir before every test."""
        import src.rws_tracking.api.video_record_routes as vrr

        clips_dir = tmp_path / "clips"
        with vrr._lock:
            vrr._recording = False
            vrr._writer = None
            vrr._clip_filename = None
            vrr._started_at = None
            vrr._clips_dir = clips_dir

        self.clips_dir = clips_dir
        self.vrr = vrr
        yield

        # Cleanup: release any open writer.
        with vrr._lock:
            if vrr._writer is not None:
                try:
                    vrr._writer.release()
                except Exception:
                    pass
            vrr._recording = False
            vrr._writer = None
            vrr._clip_filename = None
            vrr._started_at = None

    @pytest.fixture
    def client(self, tmp_path):
        return _make_client(self.clips_dir)

    # ------------------------------------------------------------------
    # 1. test_record_status_idle
    # ------------------------------------------------------------------

    def test_record_status_idle(self, client):
        """Initial status should show recording=False."""
        resp = client.get("/api/video/record/status")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["recording"] is False
        assert data["filename"] is None
        assert data["elapsed_s"] == 0.0

    # ------------------------------------------------------------------
    # 2. test_start_recording_creates_file
    # ------------------------------------------------------------------

    def test_start_recording_creates_file(self, client):
        """After start, status shows recording=True and a filename is returned."""
        mock_writer = MagicMock()
        mock_writer.isOpened.return_value = True

        with patch("cv2.VideoWriter", return_value=mock_writer), \
             patch("cv2.VideoWriter_fourcc", return_value=0x7634706D):
            resp = client.post("/api/video/record/start")

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["ok"] is True
        assert data["filename"].startswith("clip_")
        assert data["filename"].endswith(".mp4")

        # Status endpoint should now report recording=True
        status_resp = client.get("/api/video/record/status")
        status = status_resp.get_json()
        assert status["recording"] is True
        assert status["filename"] is not None

    # ------------------------------------------------------------------
    # 3. test_stop_recording_returns_filename
    # ------------------------------------------------------------------

    def test_stop_recording_returns_filename(self, client):
        """After stop, the response contains the filename and elapsed_s."""
        mock_writer = MagicMock()
        mock_writer.isOpened.return_value = True

        with patch("cv2.VideoWriter", return_value=mock_writer), \
             patch("cv2.VideoWriter_fourcc", return_value=0x7634706D):
            start_resp = client.post("/api/video/record/start")

        assert start_resp.get_json()["ok"] is True

        stop_resp = client.post("/api/video/record/stop")
        assert stop_resp.status_code == 200
        stop_data = stop_resp.get_json()
        assert stop_data["ok"] is True
        assert stop_data["filename"] is not None
        assert stop_data["filename"].endswith(".mp4")
        assert isinstance(stop_data["elapsed_s"], float)

    # ------------------------------------------------------------------
    # 4. test_list_clips_empty
    # ------------------------------------------------------------------

    def test_list_clips_empty(self, client):
        """GET /api/video/clips with no files returns empty list."""
        resp = client.get("/api/video/clips")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["clips"] == []

    # ------------------------------------------------------------------
    # 5. test_list_clips_after_record
    # ------------------------------------------------------------------

    def test_list_clips_after_record(self, client):
        """After creating a clip file, it appears in the list."""
        # Create a real mp4 file in the clips dir.
        self.clips_dir.mkdir(parents=True, exist_ok=True)
        clip_file = self.clips_dir / "clip_20240101_120000.mp4"
        clip_file.write_bytes(b"\x00" * 1024)  # 1 KB dummy file

        resp = client.get("/api/video/clips")
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data["clips"]) == 1
        assert data["clips"][0]["filename"] == "clip_20240101_120000.mp4"
        assert data["clips"][0]["size_mb"] >= 0.0
        assert "created_at" in data["clips"][0]

    # ------------------------------------------------------------------
    # 6. test_delete_clip
    # ------------------------------------------------------------------

    def test_delete_clip(self, client):
        """DELETE /api/video/clips/<filename> removes the file."""
        self.clips_dir.mkdir(parents=True, exist_ok=True)
        clip_file = self.clips_dir / "clip_test.mp4"
        clip_file.write_bytes(b"\x00" * 512)

        resp = client.delete("/api/video/clips/clip_test.mp4")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["ok"] is True
        assert not clip_file.exists()

        # Confirm it's gone from the list.
        list_resp = client.get("/api/video/clips")
        assert list_resp.get_json()["clips"] == []

    # ------------------------------------------------------------------
    # 7. test_record_frame_noop_when_not_recording
    # ------------------------------------------------------------------

    def test_record_frame_noop_when_not_recording(self):
        """record_frame() is a no-op when recording is False."""
        vrr = self.vrr
        frame = np.zeros((480, 640, 3), dtype=np.uint8)

        mock_writer = MagicMock()
        # Even if a writer were set, it should not be called.
        with vrr._lock:
            vrr._recording = False
            vrr._writer = mock_writer

        vrr.record_frame(frame)
        mock_writer.write.assert_not_called()

    # ------------------------------------------------------------------
    # 8. test_duplicate_start_is_idempotent
    # ------------------------------------------------------------------

    def test_duplicate_start_is_idempotent(self, client):
        """Calling start twice does not crash — second call returns already_recording=True."""
        mock_writer = MagicMock()
        mock_writer.isOpened.return_value = True

        with patch("cv2.VideoWriter", return_value=mock_writer), \
             patch("cv2.VideoWriter_fourcc", return_value=0x7634706D):
            resp1 = client.post("/api/video/record/start")
            resp2 = client.post("/api/video/record/start")

        assert resp1.status_code == 200
        assert resp1.get_json()["ok"] is True

        assert resp2.status_code == 200
        data2 = resp2.get_json()
        assert data2["ok"] is True
        assert data2.get("already_recording") is True

        # Clean up
        with patch("cv2.VideoWriter", return_value=mock_writer):
            client.post("/api/video/record/stop")


class TestDeleteClipNotFound:
    """Edge-case tests for delete and download endpoints."""

    @pytest.fixture(autouse=True)
    def _reset(self, tmp_path):
        import src.rws_tracking.api.video_record_routes as vrr
        clips_dir = tmp_path / "clips"
        with vrr._lock:
            vrr._recording = False
            vrr._writer = None
            vrr._clip_filename = None
            vrr._started_at = None
            vrr._clips_dir = clips_dir
        self.vrr = vrr

    @pytest.fixture
    def client(self, tmp_path):
        from src.rws_tracking.api.video_record_routes import record_bp
        app = Flask(__name__)
        app.config["TESTING"] = True
        app.register_blueprint(record_bp)
        return app.test_client()

    def test_delete_nonexistent_returns_404(self, client):
        """Deleting a clip that doesn't exist returns 404."""
        resp = client.delete("/api/video/clips/nonexistent.mp4")
        assert resp.status_code == 404

    def test_stop_when_not_recording_returns_400(self, client):
        """Stopping when not recording returns 400."""
        resp = client.post("/api/video/record/stop")
        assert resp.status_code == 400
        data = resp.get_json()
        assert data["ok"] is False
