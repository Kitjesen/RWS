"""
RWS Tracking Benchmark: 使用 roboflow trackers 库进行跟踪对比测试。
"""

import time
from pathlib import Path

import cv2
import numpy as np
import supervision as sv

# Attempt to import trackers from roboflow
from trackers import DeepSORT
from ultralytics import YOLO


def run_trackers_benchmark(video_path: Path, output_path: Path):
    print(f"\n{'=' * 60}")
    print("  Roboflow Trackers Benchmark")
    print(f"  Video: {video_path.name}")
    print(f"{'=' * 60}\n")

    # Load YOLO model for detection
    model = YOLO("yolo11n.pt")

    # Initialize tracker
    # DeepSORT has built-in ReID
    tracker = DeepSORT()

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        print(f"[ERR] Cannot open {video_path}")
        return

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(output_path), fourcc, fps, (w, h))

    # For annotation
    box_annotator = sv.BoxAnnotator()
    label_annotator = sv.LabelAnnotator()

    # Statistics
    id_history = {}
    id_first_seen = {}
    id_last_seen = {}
    total_ids = set()
    frame_idx = 0
    t_start = time.monotonic()
    inference_times = []

    print("[RUN] Processing frames...")

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        t0 = time.monotonic()

        # 1. Detect
        results = model(frame, verbose=False, classes=[0, 2, 3, 5])  # person, car, motorcycle, bus
        detections = sv.Detections.from_ultralytics(results[0])

        # 2. Track (DeepSORT needs image for ReID features)
        # Check DeepSORT signature. Supervision trackers take detections, but DeepSORT might need the frame.
        try:
            tracked_detections = tracker.update(detections=detections, image=frame)
        except TypeError:
            # Maybe it just takes detections?
            tracked_detections = tracker.update(detections=detections)

        t1 = time.monotonic()
        inference_times.append(t1 - t0)

        # Annotate
        labels = (
            [f"ID:{tracker_id}" for tracker_id in tracked_detections.tracker_id]
            if tracked_detections.tracker_id is not None
            else []
        )

        annotated_frame = box_annotator.annotate(scene=frame.copy(), detections=tracked_detections)
        annotated_frame = label_annotator.annotate(
            scene=annotated_frame, detections=tracked_detections, labels=labels
        )

        # Record stats
        if tracked_detections.tracker_id is not None:
            for tid in tracked_detections.tracker_id:
                total_ids.add(tid)
                if tid not in id_history:
                    id_history[tid] = []
                    id_first_seen[tid] = frame_idx
                id_history[tid].append(frame_idx)
                id_last_seen[tid] = frame_idx

        # HUD
        avg_ms = inference_times[-1] * 1000
        cv2.putText(
            annotated_frame,
            f"Frame {frame_idx}/{total_frames}  {avg_ms:.0f}ms  IDs:{len(total_ids)}",
            (10, 25),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (0, 255, 0),
            1,
        )
        cv2.putText(
            annotated_frame,
            "Roboflow DeepSORT (ReID)",
            (10, 50),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (200, 200, 200),
            1,
        )

        writer.write(annotated_frame)
        frame_idx += 1

        if frame_idx % 50 == 0:
            elapsed = time.monotonic() - t_start
            fps_actual = frame_idx / max(elapsed, 0.001)
            print(
                f"  [{frame_idx}/{total_frames}] {fps_actual:.1f} FPS, {len(total_ids)} unique IDs so far"
            )

    cap.release()
    writer.release()

    # ======= STATISTICS REPORT =======
    elapsed = time.monotonic() - t_start
    avg_inference_ms = np.mean(inference_times) * 1000 if inference_times else 0

    print(f"\n{'=' * 60}")
    print("  TRACKING BENCHMARK REPORT: DeepSORT")
    print(f"{'=' * 60}")
    print(f"  Total frames processed : {frame_idx}")
    print(f"  Average FPS            : {frame_idx / max(elapsed, 0.001):.1f}")
    print(f"  Avg inference time     : {avg_inference_ms:.1f}ms")
    print(f"  Unique track IDs       : {len(total_ids)}")
    print(f"  Output video           : {output_path}")
    print()

    # ID stability analysis
    print("  --- ID Stability ---")
    for tid in sorted(total_ids):
        frames_list = id_history[tid]
        span = id_last_seen[tid] - id_first_seen[tid] + 1
        coverage = len(frames_list) / max(span, 1) * 100
        gaps = []
        for k in range(1, len(frames_list)):
            gap = frames_list[k] - frames_list[k - 1]
            if gap > 1:
                gaps.append(gap)
        gap_str = f"  gaps: {gaps}" if gaps else "  continuous"
        print(
            f"  ID {tid:3d}: {len(frames_list):4d} frames, span={span}, coverage={coverage:.0f}%{gap_str}"
        )


if __name__ == "__main__":
    benchmark_dir = Path(__file__).parent
    video_path = benchmark_dir / "test_people.mp4"
    output_path = benchmark_dir / "output_deepsort.mp4"
    run_trackers_benchmark(video_path, output_path)
