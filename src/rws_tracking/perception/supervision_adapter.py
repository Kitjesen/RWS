"""Benchmark-only bridge from qp_perception Track objects to supervision."""

from __future__ import annotations

from typing import Sequence

import numpy as np
import supervision as sv


def tracks_to_sv_detections(tracks: Sequence[object]) -> sv.Detections:
    """Convert track-like objects into ``sv.Detections`` for benchmark tooling."""
    count = len(tracks)
    xyxy = np.empty((count, 4), dtype=np.float32)
    confidence = np.empty((count,), dtype=np.float32)
    tracker_id = np.empty((count,), dtype=np.int32)
    class_name: list[str] = []
    mask_center: list[tuple[float, float] | None] = []

    for idx, track in enumerate(tracks):
        bbox = track.bbox
        xyxy[idx] = (
            float(bbox.x),
            float(bbox.y),
            float(bbox.x + bbox.w),
            float(bbox.y + bbox.h),
        )
        confidence[idx] = float(track.confidence)
        tracker_id[idx] = int(track.track_id)
        class_name.append(str(getattr(track, 'class_id', 'unknown')))

        center = getattr(track, 'mask_center', None)
        if center is None:
            mask_center.append(None)
        else:
            mask_center.append((float(center[0]), float(center[1])))

    return sv.Detections(
        xyxy=xyxy,
        confidence=confidence,
        tracker_id=tracker_id,
        data={
            'class_name': class_name,
            'mask_center': mask_center,
        },
        metadata={'source': 'qp_perception'},
    )
