from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

BENCHMARK_DIR = Path(__file__).resolve().parent
if str(BENCHMARK_DIR) not in sys.path:
    sys.path.insert(0, str(BENCHMARK_DIR))

from activity_labels import ActivityOverlayTracker, infer_action_label  # noqa: E402


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
    velocity_px_per_s: tuple[float, float] = (0.0, 0.0)
    misses: int = 0


def _empty_pose() -> list[list[float]]:
    return [[0.0, 0.0, 0.0] for _ in range(17)]


def test_infer_action_label_detects_hand_up():
    pose = _empty_pose()
    pose[5] = [40.0, 60.0, 0.9]
    pose[6] = [60.0, 60.0, 0.9]
    pose[10] = [62.0, 40.0, 0.9]

    track = FakeTrack(track_id=1, bbox=FakeBoundingBox(x=20.0, y=20.0, w=60.0, h=120.0))

    assert infer_action_label(track, pose) == 'hand-up'


def test_infer_action_label_detects_walk_from_velocity():
    track = FakeTrack(
        track_id=2,
        bbox=FakeBoundingBox(x=10.0, y=10.0, w=40.0, h=100.0),
        velocity_px_per_s=(45.0, 0.0),
    )

    assert infer_action_label(track, None) == 'walk'


def test_activity_overlay_tracker_holds_recent_track_briefly():
    overlay = ActivityOverlayTracker(hold_frames=2, bbox_alpha=1.0)
    track = FakeTrack(track_id=3, bbox=FakeBoundingBox(x=0.0, y=0.0, w=40.0, h=100.0))

    first = overlay.update([track], {3: None}, frame_index=0)
    second = overlay.update([], {}, frame_index=1)

    assert len(first) == 1
    assert first[0].ghost is False
    assert len(second) == 1
    assert second[0].ghost is True
    assert second[0].track_id == 3
