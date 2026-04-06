"""RWS tracking benchmark for supervision-compatible trackers."""

from __future__ import annotations

import argparse
import time
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
import supervision as sv
from ultralytics import YOLO

PROGRESS_INTERVAL = 50


@dataclass(frozen=True)
class BenchmarkPreset:
    model_path: str
    imgsz: int
    confidence: float
    classes: list[int]
    track_activation_threshold: float
    lost_track_buffer: int
    minimum_matching_threshold: float
    minimum_consecutive_frames: int = 1


PRESETS: dict[str, BenchmarkPreset] = {
    'fast': BenchmarkPreset(
        model_path='yolo11n.pt',
        imgsz=640,
        confidence=0.25,
        classes=[0],
        track_activation_threshold=0.25,
        lost_track_buffer=30,
        minimum_matching_threshold=0.8,
        minimum_consecutive_frames=1,
    ),
    'crowd': BenchmarkPreset(
        model_path='yolo11s.pt',
        imgsz=1280,
        confidence=0.15,
        classes=[0],
        track_activation_threshold=0.15,
        lost_track_buffer=60,
        minimum_matching_threshold=0.7,
        minimum_consecutive_frames=1,
    ),
}


def _parse_class_ids(value: str) -> list[int]:
    parts = [part.strip() for part in value.split(',') if part.strip()]
    if not parts:
        raise argparse.ArgumentTypeError('Expected at least one class id.')
    try:
        return [int(part) for part in parts]
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f'Invalid class id list: {value}') from exc


def _resolve_preset(args: argparse.Namespace) -> BenchmarkPreset:
    base = PRESETS[args.preset]
    return BenchmarkPreset(
        model_path=args.model or base.model_path,
        imgsz=args.imgsz if args.imgsz is not None else base.imgsz,
        confidence=args.conf if args.conf is not None else base.confidence,
        classes=args.class_ids if args.class_ids is not None else base.classes,
        track_activation_threshold=(
            args.track_activation_threshold
            if args.track_activation_threshold is not None
            else base.track_activation_threshold
        ),
        lost_track_buffer=(
            args.lost_track_buffer
            if args.lost_track_buffer is not None
            else base.lost_track_buffer
        ),
        minimum_matching_threshold=(
            args.minimum_matching_threshold
            if args.minimum_matching_threshold is not None
            else base.minimum_matching_threshold
        ),
        minimum_consecutive_frames=(
            args.minimum_consecutive_frames
            if args.minimum_consecutive_frames is not None
            else base.minimum_consecutive_frames
        ),
    )


def _build_tracker(tracker_kind: str, fps: float, preset: BenchmarkPreset):
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
        return (
            sv.ByteTrack(
                track_activation_threshold=preset.track_activation_threshold,
                lost_track_buffer=preset.lost_track_buffer,
                minimum_matching_threshold=preset.minimum_matching_threshold,
                minimum_consecutive_frames=preset.minimum_consecutive_frames,
                frame_rate=frame_rate,
            ),
            'Supervision ByteTrack',
        )
    raise ValueError(f'Unsupported tracker: {tracker_kind}')


def _default_output_path(benchmark_dir: Path, tracker_kind: str) -> Path:
    filename_map = {
        'deepsort': 'output_deepsort.mp4',
        'bytetrack': 'output_bytetrack.mp4',
    }
    return benchmark_dir / filename_map[tracker_kind]


def _run_detector(model: YOLO, frame: np.ndarray, preset: BenchmarkPreset) -> sv.Detections:
    results = model(
        frame,
        verbose=False,
        classes=preset.classes,
        conf=preset.confidence,
        imgsz=preset.imgsz,
    )
    return sv.Detections.from_ultralytics(results[0])


def _track_detections(
    tracker_kind: str,
    tracker,
    detections: sv.Detections,
    frame: np.ndarray,
) -> sv.Detections:
    if tracker_kind == 'deepsort':
        try:
            return tracker.update(detections=detections, image=frame)
        except TypeError:
            return tracker.update(detections=detections)
    return tracker.update_with_detections(detections)


def _annotate_frame(
    frame: np.ndarray,
    tracked_detections: sv.Detections,
    tracker_label: str,
    frame_idx: int,
    total_frames: int,
    detector_ms: float,
    tracker_ms: float,
    total_ids: int,
    box_annotator: sv.BoxAnnotator,
    label_annotator: sv.LabelAnnotator,
) -> np.ndarray:
    labels = []
    if tracked_detections.tracker_id is not None:
        labels = [f'ID:{int(tracker_id)}' for tracker_id in tracked_detections.tracker_id]

    annotated_frame = box_annotator.annotate(scene=frame.copy(), detections=tracked_detections)
    annotated_frame = label_annotator.annotate(
        scene=annotated_frame,
        detections=tracked_detections,
        labels=labels,
    )
    cv2.putText(
        annotated_frame,
        f'Frame {frame_idx}/{total_frames}  Det:{detector_ms:.0f}ms  Trk:{tracker_ms:.0f}ms  IDs:{total_ids}',
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
    return annotated_frame


def _prepare_writer(
    output_path: Path,
    fps: float,
    width: int,
    height: int,
    enabled: bool,
) -> cv2.VideoWriter | None:
    if not enabled:
        return None

    output_path.parent.mkdir(parents=True, exist_ok=True)
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    writer = cv2.VideoWriter(str(output_path), fourcc, fps, (width, height))
    if not writer.isOpened():
        raise RuntimeError(f'Cannot open writer for {output_path}')
    return writer


def _run_warmup(
    cap: cv2.VideoCapture,
    warmup_frames: int,
    model: YOLO,
    tracker_kind: str,
    tracker,
    preset: BenchmarkPreset,
) -> int:
    if warmup_frames <= 0:
        return 0

    print(f'[WARMUP] Running {warmup_frames} warmup frames...')
    warmed = 0
    while warmed < warmup_frames:
        ret, frame = cap.read()
        if not ret:
            break
        detections = _run_detector(model, frame, preset)
        _track_detections(tracker_kind, tracker, detections, frame)
        warmed += 1
    return warmed


def run_trackers_benchmark(
    video_path: Path,
    output_path: Path,
    tracker_kind: str,
    preset: BenchmarkPreset,
    preset_name: str,
    max_frames: int | None = None,
    warmup_frames: int = 5,
    no_render: bool = False,
    no_save: bool = False,
) -> dict[str, float | int | str]:
    print(f"\n{'=' * 60}")
    print(f'  Supervision Tracker Benchmark: {tracker_kind}')
    print(f'  Video: {video_path.name}')
    print(f'  Preset: {preset_name}')
    print(f'  Model: {preset.model_path}  imgsz={preset.imgsz}  conf={preset.confidence:.2f}  classes={preset.classes}')
    if tracker_kind == 'bytetrack':
        print(
            '  ByteTrack: '
            f'act={preset.track_activation_threshold:.2f} '
            f'lost={preset.lost_track_buffer} '
            f'match={preset.minimum_matching_threshold:.2f} '
            f'min_cons={preset.minimum_consecutive_frames}'
        )
    print(f"{'=' * 60}\n")

    model = YOLO(preset.model_path)

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f'Cannot open {video_path}')

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    warmup_target = min(max(warmup_frames, 0), total_frames)
    available_after_warmup = max(total_frames - warmup_target, 0)
    target_frames = (
        min(max_frames, available_after_warmup)
        if max_frames is not None
        else available_after_warmup
    )
    if target_frames <= 0:
        cap.release()
        raise RuntimeError('No frames left to benchmark after warmup. Reduce --warmup-frames or increase --max-frames.')

    tracker, tracker_label = _build_tracker(tracker_kind, fps, preset)
    warmup_done = _run_warmup(cap, warmup_target, model, tracker_kind, tracker, preset)
    writer = _prepare_writer(output_path, fps, width, height, enabled=not no_save)

    box_annotator = sv.BoxAnnotator(color_lookup=sv.ColorLookup.TRACK)
    label_annotator = sv.LabelAnnotator(color_lookup=sv.ColorLookup.TRACK)

    id_history: dict[int, list[int]] = {}
    id_first_seen: dict[int, int] = {}
    id_last_seen: dict[int, int] = {}
    total_ids: set[int] = set()
    frame_idx = 0
    t_start = time.perf_counter()
    detector_times: list[float] = []
    tracker_times: list[float] = []
    render_times: list[float] = []
    total_times: list[float] = []

    print('[RUN] Processing measured frames...')

    while frame_idx < target_frames:
        ret, frame = cap.read()
        if not ret:
            break

        t_frame_start = time.perf_counter()

        t0 = time.perf_counter()
        detections = _run_detector(model, frame, preset)
        t1 = time.perf_counter()
        tracked_detections = _track_detections(tracker_kind, tracker, detections, frame)
        t2 = time.perf_counter()

        detector_ms = (t1 - t0) * 1000
        tracker_ms = (t2 - t1) * 1000

        if tracked_detections.tracker_id is not None:
            for tid_raw in tracked_detections.tracker_id:
                tid = int(tid_raw)
                total_ids.add(tid)
                if tid not in id_history:
                    id_history[tid] = []
                    id_first_seen[tid] = frame_idx
                id_history[tid].append(frame_idx)
                id_last_seen[tid] = frame_idx

        output_frame = frame
        if not no_render:
            output_frame = _annotate_frame(
                frame=frame,
                tracked_detections=tracked_detections,
                tracker_label=tracker_label,
                frame_idx=frame_idx,
                total_frames=target_frames,
                detector_ms=detector_ms,
                tracker_ms=tracker_ms,
                total_ids=len(total_ids),
                box_annotator=box_annotator,
                label_annotator=label_annotator,
            )

        if writer is not None:
            writer.write(output_frame)

        t_frame_end = time.perf_counter()

        detector_times.append(detector_ms)
        tracker_times.append(tracker_ms)
        render_times.append((t_frame_end - t2) * 1000)
        total_times.append((t_frame_end - t_frame_start) * 1000)

        frame_idx += 1

        if frame_idx % PROGRESS_INTERVAL == 0 or frame_idx == target_frames:
            elapsed = time.perf_counter() - t_start
            fps_actual = frame_idx / max(elapsed, 0.001)
            print(
                f'  [{frame_idx}/{target_frames}] {fps_actual:.1f} FPS, '
                f'{len(total_ids)} unique IDs so far'
            )

    cap.release()
    if writer is not None:
        writer.release()

    elapsed = time.perf_counter() - t_start
    avg_detector_ms = float(np.mean(detector_times)) if detector_times else 0.0
    avg_tracker_ms = float(np.mean(tracker_times)) if tracker_times else 0.0
    avg_render_ms = float(np.mean(render_times)) if render_times else 0.0
    avg_total_ms = float(np.mean(total_times)) if total_times else 0.0
    avg_fps = frame_idx / max(elapsed, 0.001)
    output_display = str(output_path) if writer is not None else 'disabled (--no-save)'

    print(f"\n{'=' * 60}")
    print(f'  TRACKING BENCHMARK REPORT: {tracker_label}')
    print(f"{'=' * 60}")
    print(f'  Warmup frames skipped : {warmup_done}')
    print(f'  Measured frames       : {frame_idx}')
    print(f'  Average FPS           : {avg_fps:.1f}')
    print(f'  Avg detector time     : {avg_detector_ms:.1f}ms')
    print(f'  Avg tracker time      : {avg_tracker_ms:.1f}ms')
    print(f'  Avg render/write time : {avg_render_ms:.1f}ms')
    print(f'  Avg end-to-end time   : {avg_total_ms:.1f}ms')
    print(f'  Unique track IDs      : {len(total_ids)}')
    print(f'  Output video          : {output_display}')
    print()
    print('  --- ID Stability ---')
    for tid in sorted(total_ids):
        frames_list = id_history[tid]
        span = id_last_seen[tid] - id_first_seen[tid] + 1
        coverage = len(frames_list) / max(span, 1) * 100
        gaps = []
        for idx in range(1, len(frames_list)):
            gap = frames_list[idx] - frames_list[idx - 1]
            if gap > 1:
                gaps.append(gap)
        gap_str = f'  gaps: {gaps}' if gaps else '  continuous'
        print(
            f'  ID {tid:3d}: {len(frames_list):4d} frames, '
            f'span={span}, coverage={coverage:.0f}%{gap_str}'
        )

    return {
        'tracker': tracker_kind,
        'preset': preset_name,
        'warmup_frames': warmup_done,
        'frames': frame_idx,
        'avg_fps': avg_fps,
        'avg_detector_ms': avg_detector_ms,
        'avg_tracker_ms': avg_tracker_ms,
        'avg_render_ms': avg_render_ms,
        'avg_total_ms': avg_total_ms,
        'unique_ids': len(total_ids),
        'output': output_display,
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
        '--preset',
        choices=sorted(PRESETS.keys()),
        default='crowd',
        help='Benchmark preset. crowd favors recall and stability for dense people scenes.',
    )
    parser.add_argument(
        '--model',
        type=str,
        default=None,
        help='Override model path, for example yolo11n.pt or yolo11m.pt.',
    )
    parser.add_argument(
        '--imgsz',
        type=int,
        default=None,
        help='Override detector image size.',
    )
    parser.add_argument(
        '--conf',
        type=float,
        default=None,
        help='Override detector confidence threshold.',
    )
    parser.add_argument(
        '--class-ids',
        type=_parse_class_ids,
        default=None,
        help='Comma-separated class ids. Default preset uses person-only (0).',
    )
    parser.add_argument(
        '--track-activation-threshold',
        type=float,
        default=None,
        help='Override ByteTrack activation threshold.',
    )
    parser.add_argument(
        '--lost-track-buffer',
        type=int,
        default=None,
        help='Override ByteTrack lost track buffer.',
    )
    parser.add_argument(
        '--minimum-matching-threshold',
        type=float,
        default=None,
        help='Override ByteTrack matching threshold.',
    )
    parser.add_argument(
        '--minimum-consecutive-frames',
        type=int,
        default=None,
        help='Override ByteTrack minimum consecutive frames.',
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
        help='Optional cap for measured frames. Warmup frames are excluded from this count.',
    )
    parser.add_argument(
        '--warmup-frames',
        type=int,
        default=5,
        help='Number of frames to warm up before timing starts.',
    )
    parser.add_argument(
        '--no-render',
        action='store_true',
        help='Skip drawing boxes and labels to isolate detector and tracker performance.',
    )
    parser.add_argument(
        '--no-save',
        action='store_true',
        help='Skip writing the output video to isolate runtime from encoding overhead.',
    )
    return parser.parse_args()


if __name__ == '__main__':
    args = _parse_args()
    benchmark_dir = Path(__file__).parent
    video_path = args.video or (benchmark_dir / 'test_people.mp4')
    preset = _resolve_preset(args)

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
                    preset=preset,
                    preset_name=args.preset,
                    max_frames=args.max_frames,
                    warmup_frames=args.warmup_frames,
                    no_render=args.no_render,
                    no_save=args.no_save,
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
                f"  {summary['tracker']:<10} preset={summary['preset']:<5} FPS={summary['avg_fps']:.1f}  "
                f"Det={summary['avg_detector_ms']:.1f}ms  "
                f"Trk={summary['avg_tracker_ms']:.1f}ms  "
                f"Rnd={summary['avg_render_ms']:.1f}ms  "
                f"Total={summary['avg_total_ms']:.1f}ms  IDs={summary['unique_ids']}"
            )
