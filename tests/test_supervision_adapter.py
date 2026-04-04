from __future__ import annotations

from dataclasses import dataclass

import pytest

from rws_tracking.perception.supervision_adapter import tracks_to_sv_detections


@dataclass
class FakeBoundingBox:
    x: float
    y: float
    w: float
    h: float


@dataclass
class FakeTrack:
    track_id: int
    bbox: FakeBoundingBox
    confidence: float
    class_id: str
    mask_center: tuple[float, float] | None = None


def test_tracks_to_sv_detections_preserves_geometry_and_ids():
    detections = tracks_to_sv_detections(
        [
            FakeTrack(
                track_id=7,
                bbox=FakeBoundingBox(x=10.0, y=20.0, w=30.0, h=40.0),
                confidence=0.85,
                class_id='person',
                mask_center=(25.0, 45.0),
            ),
            FakeTrack(
                track_id=11,
                bbox=FakeBoundingBox(x=1.0, y=2.0, w=3.0, h=4.0),
                confidence=0.55,
                class_id='vehicle',
            ),
        ]
    )

    assert detections.xyxy.tolist() == [
        [10.0, 20.0, 40.0, 60.0],
        [1.0, 2.0, 4.0, 6.0],
    ]
    assert detections.confidence.tolist() == pytest.approx([0.85, 0.55])
    assert detections.tracker_id.tolist() == [7, 11]
    assert detections.data['class_name'] == ['person', 'vehicle']
    assert detections.data['mask_center'] == [(25.0, 45.0), None]


def test_tracks_to_sv_detections_handles_empty_input():
    detections = tracks_to_sv_detections([])

    assert detections.xyxy.shape == (0, 4)
    assert detections.confidence.shape == (0,)
    assert detections.tracker_id.shape == (0,)
    assert detections.data['class_name'] == []
    assert detections.data['mask_center'] == []
