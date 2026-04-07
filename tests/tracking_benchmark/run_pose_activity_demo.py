from __future__ import annotations

import argparse
import sys
import time
from collections import deque
from pathlib import Path

import cv2
import numpy as np
import supervision as sv

BENCHMARK_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BENCHMARK_DIR.parent.parent.parent
sys.path.insert(0, str(BENCHMARK_DIR))
sys.path.insert(0, str(PROJECT_ROOT / 'src'))

from activity_labels import (  # noqa: E402
    ActivityOverlayTracker,
    PoseObservation,
    RenderTrack,
    box_iou,
    match_pose_observations,
    should_reset_trace,
)
from rws_tracking.perception.fusion_mot import FusionMOTConfig  # noqa: E402
from rws_tracking.perception.fusion_seg_tracker import FusionSegTracker  # noqa: E402
from rws_tracking.perception.reid_extractor import ReIDConfig  # noqa: E402


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--video', type=Path, default=BENCHMARK_DIR / 'test_people.mp4')
    parser.add_argument('--output', type=Path, default=BENCHMARK_DIR / 'output_pose_activity_demo.mp4')
    parser.add_argument('--model', type=str, default='yolo11s-pose.pt')
    parser.add_argument('--imgsz', type=int, default=1280)
    parser.add_argument('--confidence-high', type=float, default=0.25)
    parser.add_argument('--confidence-low', type=float, default=0.12)
    parser.add_argument('--w-skeleton', type=float, default=0.06)
    parser.add_argument('--skeleton-gate', type=float, default=1.2)
    parser.add_argument('--kp-visibility-thresh', type=float, default=0.2)
    parser.add_argument('--hold-frames', type=int, default=4)
    parser.add_argument('--bbox-alpha', type=float, default=0.65)
    parser.add_argument('--pose-iou-threshold', type=float, default=0.2)
    parser.add_argument('--show-traces', action='store_true')
    parser.add_argument('--trace-length', type=int, default=8)
    parser.add_argument('--min-trace-age', type=int, default=8)
    parser.add_argument('--trace-jump-factor', type=float, default=1.0)
    parser.add_argument('--min-trace-iou', type=float, default=0.3)
    parser.add_argument('--device', type=str, default='')
    parser.add_argument('--max-frames', type=int, default=None)
    return parser.parse_args()


def _extract_pose_observations(raw_results: list | None) -> list[PoseObservation]:
    observations: list[PoseObservation] = []
    if raw_results is None:
        return observations

    for result in raw_results:
        boxes = getattr(result, 'boxes', None)
        keypoints = getattr(result, 'keypoints', None)
        if boxes is None or keypoints is None or len(boxes) == 0:
            continue
        xyxy = boxes.xyxy.cpu().numpy()
        kpts = keypoints.data.cpu().numpy()
        for idx in range(min(len(xyxy), len(kpts))):
            observations.append(
                PoseObservation(
                    bbox_xyxy=xyxy[idx].astype('float64'),
                    keypoints=kpts[idx].astype('float64'),
                )
            )
    return observations


def _color_for_track(track_id: int, ghost: bool) -> tuple[int, int, int]:
    if ghost:
        return (150, 150, 150)
    return (
        64 + (track_id * 37) % 160,
        80 + (track_id * 67) % 150,
        96 + (track_id * 97) % 140,
    )


def _draw_label(frame, text: str, x: int, y: int, color: tuple[int, int, int]) -> None:
    font = cv2.FONT_HERSHEY_SIMPLEX
    scale = 0.55
    thickness = 1
    (w, h), baseline = cv2.getTextSize(text, font, scale, thickness)
    top = max(0, y - h - baseline - 6)
    cv2.rectangle(frame, (x, top), (x + w + 8, y), color, thickness=-1)
    cv2.putText(frame, text, (x + 4, y - 4), font, scale, (15, 15, 15), thickness, cv2.LINE_AA)


def _trace_anchor_from_box(box_xyxy: np.ndarray) -> tuple[int, int]:
    x1, _, x2, y2 = np.asarray(box_xyxy, dtype=np.float64).round().astype(int)
    return ((x1 + x2) // 2, y2)


def _clear_trace_state(
    track_id: int,
    trace_history: dict[int, deque[tuple[int, int]]],
    trace_boxes: dict[int, np.ndarray],
    trace_frames: dict[int, int],
) -> None:
    history = trace_history.get(track_id)
    if history is not None:
        history.clear()
    trace_boxes.pop(track_id, None)
    trace_frames.pop(track_id, None)


def _update_trace_history(
    item: RenderTrack,
    frame_index: int,
    trace_history: dict[int, deque[tuple[int, int]]],
    trace_boxes: dict[int, np.ndarray],
    trace_frames: dict[int, int],
    trace_length: int,
    min_trace_age: int,
    trace_jump_factor: float,
    min_trace_iou: float,
) -> deque[tuple[int, int]] | None:
    history = trace_history.setdefault(item.track_id, deque(maxlen=trace_length))
    current_box = np.asarray(item.bbox_xyxy, dtype=np.float64)

    if item.ghost or item.age_frames < min_trace_age or item.misses > 0:
        _clear_trace_state(item.track_id, trace_history, trace_boxes, trace_frames)
        history = trace_history.setdefault(item.track_id, deque(maxlen=trace_length))
        return history

    anchor = _trace_anchor_from_box(current_box)
    previous_box = trace_boxes.get(item.track_id)
    previous_frame = trace_frames.get(item.track_id)
    if previous_box is not None:
        had_gap = previous_frame is not None and (frame_index - previous_frame) > 1
        low_iou = box_iou(previous_box, current_box) < min_trace_iou
        anchor_x = int(round((previous_box[0] + previous_box[2]) * 0.5))
        anchor_y = int(round(previous_box[3]))
        jumped = should_reset_trace((anchor_x, anchor_y), anchor, current_box, jump_factor=trace_jump_factor)
        if had_gap or low_iou or jumped:
            history.clear()

    history.append(anchor)
    trace_boxes[item.track_id] = current_box.copy()
    trace_frames[item.track_id] = frame_index
    return history


def _annotate_frame(
    frame,
    frame_index: int,
    render_items: list[RenderTrack],
    trace_history: dict[int, deque[tuple[int, int]]],
    trace_boxes: dict[int, np.ndarray],
    trace_frames: dict[int, int],
    show_traces: bool,
    trace_length: int,
    min_trace_age: int,
    trace_jump_factor: float,
    min_trace_iou: float,
    headline: str,
):
    annotated = frame.copy()
    visible_ids = {item.track_id for item in render_items}
    for stale_track_id in list(trace_history):
        if stale_track_id not in visible_ids:
            _clear_trace_state(stale_track_id, trace_history, trace_boxes, trace_frames)
            trace_history.pop(stale_track_id, None)

    for item in render_items:
        x1, y1, x2, y2 = item.bbox_xyxy.round().astype(int)
        x1 = max(0, x1)
        y1 = max(0, y1)
        x2 = max(x1 + 1, x2)
        y2 = max(y1 + 1, y2)
        color = _color_for_track(item.track_id, item.ghost)
        thickness = 1 if item.ghost else 2
        cv2.rectangle(annotated, (x1, y1), (x2, y2), color, thickness, cv2.LINE_AA)

        if show_traces:
            history = _update_trace_history(
                item,
                frame_index,
                trace_history,
                trace_boxes,
                trace_frames,
                trace_length=trace_length,
                min_trace_age=min_trace_age,
                trace_jump_factor=trace_jump_factor,
                min_trace_iou=min_trace_iou,
            )
            if history is not None and len(history) >= 2:
                points = list(history)
                for start, end in zip(points, points[1:]):
                    cv2.line(annotated, start, end, color, 2, cv2.LINE_AA)
        else:
            _clear_trace_state(item.track_id, trace_history, trace_boxes, trace_frames)

        label = f'ID:{item.track_id} {item.action_label}'
        if item.ghost:
            label += ' hold'
        _draw_label(annotated, label, x1, max(22, y1), color)

    cv2.putText(
        annotated,
        headline,
        (10, 24),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.6,
        (0, 255, 0),
        1,
        cv2.LINE_AA,
    )
    return annotated


def main() -> int:
    args = _parse_args()
    video_path = args.video
    output_path = args.output

    if not video_path.exists():
        raise SystemExit(f'Video not found: {video_path}')

    video_info = sv.VideoInfo.from_video_path(str(video_path))
    fps = video_info.fps or 25.0
    output_path.parent.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(
        str(output_path),
        cv2.VideoWriter_fourcc(*'mp4v'),
        fps,
        (video_info.width, video_info.height),
    )
    if not writer.isOpened():
        raise SystemExit(f'Cannot open writer for {output_path}')

    tracker = FusionSegTracker(
        model_path=args.model,
        confidence_threshold=args.confidence_high,
        low_confidence_threshold=args.confidence_low,
        class_whitelist=['person'],
        device=args.device,
        img_size=args.imgsz,
        reid_config=ReIDConfig(device=args.device),
        mot_config=FusionMOTConfig(
            high_conf=args.confidence_high,
            low_conf=args.confidence_low,
            w_skeleton=args.w_skeleton,
            use_hip_center=True,
            skeleton_gate=args.skeleton_gate,
            kp_visibility_thresh=args.kp_visibility_thresh,
            max_lost_frames=60,
            max_lost_seconds=8.0,
            confirm_frames=2,
        ),
    )
    overlay = ActivityOverlayTracker(
        hold_frames=args.hold_frames,
        bbox_alpha=args.bbox_alpha,
        visibility_thresh=args.kp_visibility_thresh,
    )

    trace_history: dict[int, deque[tuple[int, int]]] = {}
    trace_boxes: dict[int, np.ndarray] = {}
    trace_frames: dict[int, int] = {}
    inference_times: list[float] = []
    total_tracks_seen: set[int] = set()
    t_start = time.perf_counter()

    frames = sv.get_video_frames_generator(str(video_path), end=args.max_frames)
    for frame_idx, frame in enumerate(frames):
        timestamp = frame_idx / fps
        t0 = time.perf_counter()
        tracks = tracker.detect_and_track(frame, timestamp)
        pose_matches = match_pose_observations(
            tracks,
            _extract_pose_observations(tracker.last_raw_results),
            iou_threshold=args.pose_iou_threshold,
        )
        render_items = overlay.update(tracks, pose_matches, frame_idx)
        dt = time.perf_counter() - t0
        inference_times.append(dt)

        total_tracks_seen.update(item.track_id for item in render_items if not item.ghost)
        headline = (
            f'FusionPose  F{frame_idx}  {dt * 1000:.0f}ms  '
            f'visible:{sum(1 for item in render_items if not item.ghost)}  '
            f'ghost:{sum(1 for item in render_items if item.ghost)}  '
            f'ids:{len(total_tracks_seen)}  '
            f'traces:{"on" if args.show_traces else "off"}'
        )
        annotated = _annotate_frame(
            frame,
            frame_idx,
            render_items,
            trace_history,
            trace_boxes,
            trace_frames,
            show_traces=args.show_traces,
            trace_length=args.trace_length,
            min_trace_age=args.min_trace_age,
            trace_jump_factor=args.trace_jump_factor,
            min_trace_iou=args.min_trace_iou,
            headline=headline,
        )
        writer.write(annotated)

        if frame_idx > 0 and frame_idx % 50 == 0:
            elapsed = time.perf_counter() - t_start
            fps_actual = (frame_idx + 1) / max(elapsed, 1e-3)
            print(
                f'[{frame_idx + 1}/{video_info.total_frames}] '
                f'{fps_actual:.1f} FPS  visible={sum(1 for item in render_items if not item.ghost)} '
                f'ghost={sum(1 for item in render_items if item.ghost)} ids={len(total_tracks_seen)} '
                f'traces={"on" if args.show_traces else "off"}'
            )

    writer.release()
    elapsed = time.perf_counter() - t_start
    avg_ms = (sum(inference_times) / len(inference_times) * 1000.0) if inference_times else 0.0
    avg_fps = len(inference_times) / max(elapsed, 1e-3)

    print('\n' + '=' * 60)
    print('  FUSION POSE ACTIVITY DEMO')
    print('=' * 60)
    print(f'  Video           : {video_path.name}')
    print(f'  Output          : {output_path}')
    print(f'  Model           : {args.model}')
    print(f'  Traces          : {"on" if args.show_traces else "off"}')
    print(f'  Frames          : {len(inference_times)}')
    print(f'  Average FPS     : {avg_fps:.1f}')
    print(f'  Avg frame time  : {avg_ms:.1f}ms')
    print(f'  Unique IDs seen : {len(total_tracks_seen)}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())