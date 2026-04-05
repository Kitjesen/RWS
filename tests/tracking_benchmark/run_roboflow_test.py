"""RWS tracking benchmark for supervision-compatible trackers."""

from __future__ import annotations

import argparse
import time
from pathlib import Path

import cv2
import numpy as np
import supervision as sv
from ultralytics import YOLO


def _build_tracker(tracker_kind: str, fps: float):
    if tracker_kind == 'deepsort':
        try:
            from trackers import DeepSORT
        except ImportError as exc:
            raise RuntimeError(
                'DeepSORT is unavailable in the current trackers package. '
                'Use --tracker bytetrack or install a DeepSORT-capable tracker package.'
            ) from exc
        return DeepSORT(), 'Roboflow DeepSORT (ReID)'
    if tracker_kind == 'bytetrack':
        frame_rate = max(int(round(fps)), 1)
        return sv.ByteTrack(frame_rate=frame_rate), 'Supervision ByteTrack'
    raise ValueError(f'Unsupported tracker: {tracker_kind}')


def _default_output_path(benchmark_dir: Path, tracker_kind: str) -> Path:
    filename_map = {
        'deepsort': 'output_deepsort.mp4',
        'bytetrack': 'output_bytetrack.mp4',
    }
    return benchmark_dir / filename_map[tracker_kind]


def run_trackers_benchmark(
    video_path: Path,
    output_path: Path,
    tracker_kind: str,
    max_frames: int | None = None,
) -> dict[str, float | int | str]:
    print(f"\n{'=' * 60}")
    print(f'  Supervision Tracker Benchmark: {tracker_kind}')
    print(f'  Video: {video_path.name}')
    print(f"{'=' * 60}\n")

    model = YOLO('yolo11n.pt')

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f'Cannot open {video_path}')

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    target_frames = min(max_frames, total_frames) if max_frames is not None else total_frames

    tracker, tracker_label = _build_tracker(tracker_kind, fps)

    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    writer = cv2.VideoWriter(str(output_path), fourcc, fps, (w, h))

    box_annotator = sv.BoxAnnotator(color_lookup=sv.ColorLookup.TRACK)
    label_annotator = sv.LabelAnnotator(color_lookup=sv.ColorLookup.TRACK)

    id_history: dict[int, list[int]] = {}
    id_first_seen: dict[int, int] = {}
    id_last_seen: dict[int, int] = {}
    total_ids: set[int] = set()
    frame_idx = 0
    t_start = time.monotonic()
    inference_times: list[float] = []

    print('[RUN] Processing frames...')

    while frame_idx < target_frames:
        ret, frame = cap.read()
        if not ret:
            break

        t0 = time.monotonic()
        results = model(frame, verbose=False, classes=[0, 2, 3, 5])
        detections = sv.Detections.from_ultralytics(results[0])

        if tracker_kind == 'deepsort':
            try:
                tracked_detections = tracker.update(detections=detections, image=frame)
            except TypeError:
                tracked_detections = tracker.update(detections=detections)
        else:
            tracked_detections = tracker.update_with_detections(detections)

        t1 = time.monotonic()
        inference_times.append(t1 - t0)

        labels = []
        if tracked_detections.tracker_id is not None:
            labels = [f'ID:{int(tracker_id)}' for tracker_id in tracked_detections.tracker_id]

        annotated_frame = box_annotator.annotate(scene=frame.copy(), detections=tracked_detections)
        annotated_frame = label_annotator.annotate(
            scene=annotated_frame,
            detections=tracked_detections,
            labels=labels,
        )

        if tracked_detections.tracker_id is not None:
            for tid_raw in tracked_detections.tracker_id:
                tid = int(tid_raw)
                total_ids.add(tid)
                if tid not in id_history:
                    id_history[tid] = []
                    id_first_seen[tid] = frame_idx
                id_history[tid].append(frame_idx)
                id_last_seen[tid] = frame_idx

        avg_ms = inference_times[-1] * 1000
        cv2.putText(
            annotated_frame,
            f'Frame {frame_idx}/{target_frames}  {avg_ms:.0f}ms  IDs:{len(total_ids)}',
            (10, 25),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (0, 255, 0),
            1,
        )
        cv2.putText(
            annotated_frame,
            tracker_label,
            (10, 50),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (200, 200, 200),
            1,
        )

        writer.write(annotated_frame)
        frame_idx += 1

        if frame_idx % 50 == 0 or frame_idx == target_frames:
            elapsed = time.monotonic() - t_start
            fps_actual = frame_idx / max(elapsed, 0.001)
            print(
                f'  [{frame_idx}/{target_frames}] {fps_actual:.1f} FPS, '
                f'{len(total_ids)} unique IDs so far'
            )

    cap.release()
    writer.release()

    elapsed = time.monotonic() - t_start
    avg_inference_ms = np.mean(inference_times) * 1000 if inference_times else 0.0
    avg_fps = frame_idx / max(elapsed, 0.001)

    print(f"\n{'=' * 60}")
    print(f'  TRACKING BENCHMARK REPORT: {tracker_label}')
    print(f"{'=' * 60}")
    print(f'  Total frames processed : {frame_idx}')
    print(f'  Average FPS            : {avg_fps:.1f}')
    print(f'  Avg inference time     : {avg_inference_ms:.1f}ms')
    print(f'  Unique track IDs       : {len(total_ids)}')
    print(f'  Output video           : {output_path}')
    print()
    print('  --- ID Stability ---')
    for tid in sorted(total_ids):
        frames_list = id_history[tid]
        span = id_last_seen[tid] - id_first_seen[tid] + 1
        coverage = len(frames_list) / max(span, 1) * 100
        gaps = []
        for k in range(1, len(frames_list)):
            gap = frames_list[k] - frames_list[k - 1]
            if gap > 1:
                gaps.append(gap)
        gap_str = f'  gaps: {gaps}' if gaps else '  continuous'
        print(
            f'  ID {tid:3d}: {len(frames_list):4d} frames, '
            f'span={span}, coverage={coverage:.0f}%{gap_str}'
        )

    return {
        'tracker': tracker_kind,
        'frames': frame_idx,
        'avg_fps': avg_fps,
        'avg_inference_ms': float(avg_inference_ms),
        'unique_ids': len(total_ids),
        'output': str(output_path),
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--tracker',
        choices=['deepsort', 'bytetrack', 'all'],
        default='all',
        help='Tracker lane to run. Default runs both lanes.',
    )
    parser.add_argument(
        '--video',
        type=Path,
        default=None,
        help='Override input video path. Default is test_people.mp4 in the benchmark dir.',
    )
    parser.add_argument(
        '--output',
        type=Path,
        default=None,
        help='Override output path for single-tracker runs.',
    )
    parser.add_argument(
        '--max-frames',
        type=int,
        default=None,
        help='Optional frame cap for smoke runs.',
    )
    return parser.parse_args()


if __name__ == '__main__':
    args = _parse_args()
    benchmark_dir = Path(__file__).parent
    video_path = args.video or (benchmark_dir / 'test_people.mp4')

    tracker_kinds = ['deepsort', 'bytetrack'] if args.tracker == 'all' else [args.tracker]
    if len(tracker_kinds) > 1 and args.output is not None:
        raise SystemExit('--output is only supported for single-tracker runs.')

    summaries = []
    for tracker_kind in tracker_kinds:
        output_path = args.output or _default_output_path(benchmark_dir, tracker_kind)
        try:
            summaries.append(
                run_trackers_benchmark(
                    video_path=video_path,
                    output_path=output_path,
                    tracker_kind=tracker_kind,
                    max_frames=args.max_frames,
                )
            )
        except RuntimeError as exc:
            if args.tracker == 'all':
                print(f'[SKIP] {tracker_kind}: {exc}')
                continue
            raise

    if len(summaries) > 1:
        print(f"\n{'=' * 60}")
        print('  TRACKER SUMMARY')
        print(f"{'=' * 60}")
        for summary in summaries:
            print(
                f"  {summary['tracker']:<10} FPS={summary['avg_fps']:.1f}  "
                f"AvgMS={summary['avg_inference_ms']:.1f}  IDs={summary['unique_ids']}"
            )
