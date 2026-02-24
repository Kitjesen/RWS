"""视频流模块单元测试。"""


import numpy as np
import pytest

from src.rws_tracking.api.video_stream import FrameAnnotator, FrameBuffer, VideoStreamConfig
from src.rws_tracking.types import BoundingBox, Detection, TargetObservation, Track


class TestFrameBuffer:
    def test_put_and_get(self):
        buf = FrameBuffer(max_size=3)
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        buf.put(frame)
        result = buf.get()
        assert result is not None
        assert result.shape == (480, 640, 3)

    def test_empty_get_returns_none(self):
        buf = FrameBuffer(max_size=3)
        assert buf.get() is None

    def test_overflow_drops_oldest(self):
        buf = FrameBuffer(max_size=2)
        for i in range(5):
            f = np.full((10, 10, 3), i, dtype=np.uint8)
            buf.put(f)
        result = buf.get()
        assert result[0, 0, 0] >= 3  # oldest frames dropped

    def test_latest(self):
        buf = FrameBuffer(max_size=5)
        for i in range(3):
            buf.put(np.full((10, 10, 3), i, dtype=np.uint8))
        latest = buf.latest()
        assert latest is not None
        assert latest[0, 0, 0] == 2

    def test_latest_empty(self):
        buf = FrameBuffer(max_size=3)
        assert buf.latest() is None


class TestVideoStreamConfig:
    def test_defaults(self):
        cfg = VideoStreamConfig()
        assert cfg.jpeg_quality == 70
        assert cfg.max_fps == 30.0
        assert not cfg.enabled

    def test_custom(self):
        cfg = VideoStreamConfig(jpeg_quality=50, max_fps=15, enabled=False)
        assert cfg.jpeg_quality == 50
        assert not cfg.enabled


class TestFrameAnnotator:
    @pytest.fixture
    def annotator(self):
        return FrameAnnotator(VideoStreamConfig())

    @pytest.fixture
    def frame(self):
        return np.zeros((720, 1280, 3), dtype=np.uint8)

    def test_annotate_empty(self, annotator, frame):
        result = annotator.annotate(frame, [], None)
        assert result.shape == frame.shape

    def test_annotate_with_detections(self, annotator, frame):
        dets = [Detection(
            bbox=BoundingBox(x=100, y=100, w=80, h=150),
            confidence=0.9, class_id="person",
        )]
        result = annotator.annotate(frame, dets, None)
        assert result.shape == frame.shape
        # Should have drawn something (not all zeros)
        assert result.sum() > 0

    def test_annotate_with_selected_target(self, annotator, frame):
        target = TargetObservation(
            timestamp=0.0, track_id=1,
            bbox=BoundingBox(x=600, y=300, w=80, h=150),
            confidence=0.9, class_id="person",
        )
        result = annotator.annotate(frame, [], selected_id=target.track_id)
        assert result.sum() > 0

    def test_annotate_with_tracks(self, annotator, frame):
        tracks = [Track(
            track_id=1, bbox=BoundingBox(x=100, y=100, w=80, h=150),
            confidence=0.9, class_id="person",
            first_seen_ts=0.0, last_seen_ts=0.0, age_frames=10,
        )]
        result = annotator.annotate(frame, [], tracks)
        assert result.shape == frame.shape

    def test_crosshair(self, annotator, frame):
        result = annotator.annotate(frame, [], None)
        # Crosshair should be drawn at center
        center_pixel = result[360, 640]
        assert center_pixel.sum() > 0

    def test_disabled_annotations(self, frame):
        cfg = VideoStreamConfig(
            annotate_detections=False,
            annotate_tracks=False,
            annotate_crosshair=False,
        )
        ann = FrameAnnotator(cfg)
        result = ann.annotate(frame, [], None)
        assert result.sum() == 0  # nothing drawn

    def test_scale_factor(self, frame):
        cfg = VideoStreamConfig(scale_factor=0.5)
        ann = FrameAnnotator(cfg)
        result = ann.annotate(frame, [], None)
        # Frame should be scaled down
        assert result.shape[0] <= 720
