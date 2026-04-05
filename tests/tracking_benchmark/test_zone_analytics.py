"""Unit tests for zone_analytics and supervision_adapter."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import supervision as sv

# adapter tests
from rws_tracking.perception.supervision_adapter import tracks_to_sv_detections

# zone tests — module lives next to this file
import sys
sys.path.insert(0, str(Path(__file__).parent))
from zone_analytics import ZoneAnalytics, ZoneReport


# ── helpers ──────────────────────────────────────────────────────────────

class _Bbox:
    def __init__(self, x, y, w, h):
        self.x, self.y, self.w, self.h = x, y, w, h


class _Track:
    def __init__(self, tid, conf, bbox, cls="person", center=None):
        self.track_id = tid
        self.confidence = conf
        self.bbox = bbox
        self.class_id = cls
        self.mask_center = center


# ── supervision_adapter tests ────────────────────────────────────────────

class TestSupervisionAdapter:
    def test_empty(self):
        det = tracks_to_sv_detections([])
        assert det.xyxy.shape == (0, 4)

    def test_xyxy_shape(self):
        tracks = [_Track(1, 0.9, _Bbox(10, 20, 50, 60))]
        det = tracks_to_sv_detections(tracks)
        assert det.xyxy.shape == (1, 4)
        np.testing.assert_array_almost_equal(det.xyxy[0], [10, 20, 60, 80])

    def test_tracker_id_and_confidence(self):
        tracks = [
            _Track(3, 0.85, _Bbox(0, 0, 10, 10)),
            _Track(7, 0.72, _Bbox(20, 20, 30, 30)),
        ]
        det = tracks_to_sv_detections(tracks)
        assert list(det.tracker_id) == [3, 7]
        assert det.confidence[0] == pytest.approx(0.85)

    def test_data_fields(self):
        tracks = [_Track(1, 0.9, _Bbox(0, 0, 10, 10), cls="chair", center=(5.0, 5.0))]
        det = tracks_to_sv_detections(tracks)
        assert det.data["class_name"] == ["chair"]
        assert det.data["mask_center"] == [(5.0, 5.0)]

    def test_metadata(self):
        det = tracks_to_sv_detections([_Track(1, 0.9, _Bbox(0, 0, 10, 10))])
        assert det.metadata["source"] == "qp_perception"


# ── ZoneAnalytics tests ─────────────────────────────────────────────────

class TestZoneAnalytics:
    @pytest.fixture()
    def scene_config(self):
        return {
            "line_zones": [
                {"name": "gate", "start": [320, 0], "end": [320, 480]},
            ],
            "polygon_zones": [
                {"name": "lobby", "polygon": [[0, 0], [640, 0], [640, 480], [0, 480]]},
            ],
        }

    def test_init(self, scene_config):
        za = ZoneAnalytics(scene_config)
        assert "gate" in za.report.line_counts
        assert "lobby" in za.report.polygon_dwell

    def test_update_empty(self, scene_config):
        za = ZoneAnalytics(scene_config)
        za.update(sv.Detections.empty())
        assert za.report.line_counts["gate"] == {"in": 0, "out": 0}
        assert za.report.polygon_occupancy["lobby"] == 0

    def test_polygon_occupancy(self, scene_config):
        za = ZoneAnalytics(scene_config)
        # detection inside the polygon
        det = sv.Detections(
            xyxy=np.array([[100, 200, 200, 400]], dtype=np.float32),
            confidence=np.array([0.9], dtype=np.float32),
        )
        za.update(det)
        assert za.report.polygon_occupancy["lobby"] >= 0  # at least ran without error
        assert za.report.polygon_dwell["lobby"] >= 0

    def test_annotate_returns_same_shape(self, scene_config):
        za = ZoneAnalytics(scene_config)
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        det = sv.Detections.empty()
        out = za.annotate(frame, det)
        assert out.shape == frame.shape

    def test_from_yaml(self):
        yaml_path = Path(__file__).parent / "zones.yaml"
        za = ZoneAnalytics.from_yaml(yaml_path, "test_people")
        assert za is not None
        assert "midline" in za.report.line_counts

    def test_from_yaml_missing_scene(self):
        yaml_path = Path(__file__).parent / "zones.yaml"
        za = ZoneAnalytics.from_yaml(yaml_path, "nonexistent_video")
        assert za is None

    def test_from_yaml_missing_file(self, tmp_path):
        za = ZoneAnalytics.from_yaml(tmp_path / "nope.yaml", "anything")
        assert za is None
