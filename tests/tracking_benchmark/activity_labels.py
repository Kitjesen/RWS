from __future__ import annotations

from collections import Counter, deque
from dataclasses import dataclass, field
from typing import Any, Iterable

import numpy as np

_KP_SHOULDER_L = 5
_KP_SHOULDER_R = 6
_KP_WRIST_L = 9
_KP_WRIST_R = 10
_KP_HIP_L = 11
_KP_HIP_R = 12
_KP_KNEE_L = 13
_KP_KNEE_R = 14
_KP_ANKLE_L = 15
_KP_ANKLE_R = 16

_LYING_ASPECT_RATIO = 1.75
_HAND_UP_MARGIN = 0.04
_CROUCH_SEGMENT_RATIO = 0.12
_CROUCH_TORSO_RATIO = 0.18
_WALK_SPEED_RATIO = 0.35
_MOVE_SPEED_RATIO = 0.12
_DEFAULT_TRACE_JUMP_FACTOR = 1.35


@dataclass(frozen=True)
class PoseObservation:
    bbox_xyxy: np.ndarray
    keypoints: np.ndarray


@dataclass(frozen=True)
class RenderTrack:
    track_id: int
    bbox_xyxy: np.ndarray
    action_label: str
    ghost: bool = False
    misses: int = 0
    age_frames: int = 1


@dataclass
class _TrackState:
    smoothed_box: np.ndarray
    action_history: deque[str] = field(default_factory=lambda: deque(maxlen=8))
    stable_action: str = 'stand'
    last_seen_frame: int = 0
    age_frames: int = 1


def track_box_to_xyxy(track: Any) -> np.ndarray:
    bbox = track.bbox
    return np.array(
        [bbox.x, bbox.y, bbox.x + bbox.w, bbox.y + bbox.h],
        dtype=np.float64,
    )


def box_iou(box_a: np.ndarray, box_b: np.ndarray) -> float:
    x1 = max(float(box_a[0]), float(box_b[0]))
    y1 = max(float(box_a[1]), float(box_b[1]))
    x2 = min(float(box_a[2]), float(box_b[2]))
    y2 = min(float(box_a[3]), float(box_b[3]))

    inter_w = max(0.0, x2 - x1)
    inter_h = max(0.0, y2 - y1)
    inter_area = inter_w * inter_h
    if inter_area <= 0.0:
        return 0.0

    area_a = max(0.0, float(box_a[2] - box_a[0])) * max(0.0, float(box_a[3] - box_a[1]))
    area_b = max(0.0, float(box_b[2] - box_b[0])) * max(0.0, float(box_b[3] - box_b[1]))
    union = area_a + area_b - inter_area
    return inter_area / union if union > 0.0 else 0.0


def match_pose_observations(
    tracks: Iterable[Any],
    pose_observations: list[PoseObservation],
    iou_threshold: float = 0.2,
) -> dict[int, np.ndarray | None]:
    unmatched = set(range(len(pose_observations)))
    matches: dict[int, np.ndarray | None] = {}

    for track in tracks:
        track_box = track_box_to_xyxy(track)
        best_idx = None
        best_iou = iou_threshold
        for idx in unmatched:
            iou = box_iou(track_box, pose_observations[idx].bbox_xyxy)
            if iou > best_iou:
                best_iou = iou
                best_idx = idx

        if best_idx is None:
            matches[track.track_id] = None
            continue

        matches[track.track_id] = pose_observations[best_idx].keypoints
        unmatched.remove(best_idx)

    return matches


def _valid_keypoint(keypoints: np.ndarray | None, idx: int, visibility_thresh: float) -> bool:
    if keypoints is None or idx >= len(keypoints):
        return False
    if keypoints.shape[-1] < 3:
        return float(keypoints[idx, 0]) > 1.0 and float(keypoints[idx, 1]) > 1.0
    return (
        float(keypoints[idx, 2]) >= visibility_thresh
        and float(keypoints[idx, 0]) > 1.0
        and float(keypoints[idx, 1]) > 1.0
    )


def _midpoint(
    keypoints: np.ndarray | None,
    idx_a: int,
    idx_b: int,
    visibility_thresh: float,
) -> np.ndarray | None:
    if not _valid_keypoint(keypoints, idx_a, visibility_thresh):
        return None
    if not _valid_keypoint(keypoints, idx_b, visibility_thresh):
        return None
    return (keypoints[idx_a, :2] + keypoints[idx_b, :2]) * 0.5


def trace_center_from_box(box_xyxy: np.ndarray) -> tuple[int, int]:
    x1, y1, x2, y2 = np.asarray(box_xyxy, dtype=np.float64).round().astype(int)
    return ((x1 + x2) // 2, (y1 + y2) // 2)


def should_reset_trace(
    previous_center: tuple[int, int],
    new_center: tuple[int, int],
    box_xyxy: np.ndarray,
    jump_factor: float = _DEFAULT_TRACE_JUMP_FACTOR,
) -> bool:
    box = np.asarray(box_xyxy, dtype=np.float64)
    width = max(float(box[2] - box[0]), 1.0)
    height = max(float(box[3] - box[1]), 1.0)
    max_jump = max(width, height) * max(float(jump_factor), 0.5)
    distance = float(np.hypot(new_center[0] - previous_center[0], new_center[1] - previous_center[1]))
    return distance > max_jump


def infer_action_label(
    track: Any,
    keypoints: np.ndarray | None,
    visibility_thresh: float = 0.2,
) -> str:
    if keypoints is not None and not isinstance(keypoints, np.ndarray):
        keypoints = np.asarray(keypoints, dtype=np.float64)
    bbox = track.bbox
    bbox_h = max(float(bbox.h), 1.0)
    bbox_w = max(float(bbox.w), 1.0)
    vx, vy = getattr(track, 'velocity_px_per_s', (0.0, 0.0))
    speed_ratio = float(np.hypot(vx, vy)) / bbox_h

    if bbox_w > bbox_h * _LYING_ASPECT_RATIO and speed_ratio < _MOVE_SPEED_RATIO:
        return 'lying'

    if keypoints is not None:
        left_hand_up = (
            _valid_keypoint(keypoints, _KP_WRIST_L, visibility_thresh)
            and _valid_keypoint(keypoints, _KP_SHOULDER_L, visibility_thresh)
            and float(keypoints[_KP_WRIST_L, 1])
            < float(keypoints[_KP_SHOULDER_L, 1]) - bbox_h * _HAND_UP_MARGIN
        )
        right_hand_up = (
            _valid_keypoint(keypoints, _KP_WRIST_R, visibility_thresh)
            and _valid_keypoint(keypoints, _KP_SHOULDER_R, visibility_thresh)
            and float(keypoints[_KP_WRIST_R, 1])
            < float(keypoints[_KP_SHOULDER_R, 1]) - bbox_h * _HAND_UP_MARGIN
        )
        if left_hand_up or right_hand_up:
            return 'hand-up'

        shoulder_mid = _midpoint(keypoints, _KP_SHOULDER_L, _KP_SHOULDER_R, visibility_thresh)
        hip_mid = _midpoint(keypoints, _KP_HIP_L, _KP_HIP_R, visibility_thresh)
        knee_mid = _midpoint(keypoints, _KP_KNEE_L, _KP_KNEE_R, visibility_thresh)
        ankle_mid = _midpoint(keypoints, _KP_ANKLE_L, _KP_ANKLE_R, visibility_thresh)
        if shoulder_mid is not None and hip_mid is not None and knee_mid is not None and ankle_mid is not None:
            torso_ratio = max(0.0, float(hip_mid[1] - shoulder_mid[1])) / bbox_h
            upper_leg_ratio = max(0.0, float(knee_mid[1] - hip_mid[1])) / bbox_h
            lower_leg_ratio = max(0.0, float(ankle_mid[1] - knee_mid[1])) / bbox_h
            if (
                torso_ratio < _CROUCH_TORSO_RATIO
                and upper_leg_ratio < _CROUCH_SEGMENT_RATIO
                and lower_leg_ratio < _CROUCH_SEGMENT_RATIO
            ):
                return 'crouch'

    if speed_ratio >= _WALK_SPEED_RATIO:
        return 'walk'
    if speed_ratio >= _MOVE_SPEED_RATIO:
        return 'move'
    return 'stand'


class ActivityOverlayTracker:
    def __init__(
        self,
        hold_frames: int = 4,
        bbox_alpha: float = 0.65,
        action_history: int = 8,
        visibility_thresh: float = 0.2,
    ) -> None:
        self._hold_frames = max(int(hold_frames), 0)
        self._bbox_alpha = float(np.clip(bbox_alpha, 0.0, 1.0))
        self._action_history = max(int(action_history), 1)
        self._visibility_thresh = visibility_thresh
        self._states: dict[int, _TrackState] = {}

    def update(
        self,
        tracks: Iterable[Any],
        pose_matches: dict[int, np.ndarray | None],
        frame_index: int,
    ) -> list[RenderTrack]:
        render_items: list[RenderTrack] = []
        active_ids: set[int] = set()

        for track in tracks:
            track_id = int(track.track_id)
            active_ids.add(track_id)
            current_box = track_box_to_xyxy(track)
            state = self._states.get(track_id)
            if state is None:
                state = _TrackState(
                    smoothed_box=current_box.copy(),
                    action_history=deque(maxlen=self._action_history),
                    last_seen_frame=frame_index,
                )
                self._states[track_id] = state
            else:
                state.smoothed_box = (
                    self._bbox_alpha * current_box + (1.0 - self._bbox_alpha) * state.smoothed_box
                )
                state.last_seen_frame = frame_index

            state.age_frames = int(max(getattr(track, 'age_frames', 1), 1))
            raw_action = infer_action_label(
                track,
                pose_matches.get(track_id),
                visibility_thresh=self._visibility_thresh,
            )
            state.action_history.append(raw_action)
            state.stable_action = self._select_action(state.action_history, state.stable_action)
            render_items.append(
                RenderTrack(
                    track_id=track_id,
                    bbox_xyxy=state.smoothed_box.copy(),
                    action_label=state.stable_action,
                    ghost=False,
                    misses=int(getattr(track, 'misses', 0)),
                    age_frames=state.age_frames,
                )
            )

        stale_ids: list[int] = []
        for track_id, state in self._states.items():
            if track_id in active_ids:
                continue
            missed = frame_index - state.last_seen_frame
            if missed <= self._hold_frames:
                render_items.append(
                    RenderTrack(
                        track_id=track_id,
                        bbox_xyxy=state.smoothed_box.copy(),
                        action_label=state.stable_action,
                        ghost=True,
                        misses=missed,
                        age_frames=state.age_frames,
                    )
                )
            else:
                stale_ids.append(track_id)

        for track_id in stale_ids:
            del self._states[track_id]

        render_items.sort(key=lambda item: (item.ghost, item.track_id))
        return render_items

    @staticmethod
    def _select_action(history: deque[str], fallback: str) -> str:
        if not history:
            return fallback
        counts = Counter(history)
        return max(counts.items(), key=lambda kv: (kv[1], kv[0] == fallback))[0]