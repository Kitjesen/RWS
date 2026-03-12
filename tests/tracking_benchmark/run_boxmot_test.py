import time
from pathlib import Path

import cv2
import numpy as np
import torch
from boxmot import BoTSORT
from ultralytics import YOLO


def run_boxmot_test(video_path: Path, output_path: Path):
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        print(f"[ERR] Cannot open {video_path}")
        return

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    print(f"\n{'=' * 60}")
    print(f"  BoxMOT Video: {video_path.name}")
    print(f"{'=' * 60}\n")

    # Initialize YOLO
    device = "cuda:0" if torch.cuda.is_available() else "cpu"
    model = YOLO("yolo11n.pt")

    # Initialize BoxMOT with OSNet
    tracker = BoTSORT(
        model_weights=Path("osnet_x0_25_msmt17.pt"),
        device=device,
        fp16=False,
    )

    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(output_path), fourcc, fps, (w, h))

    id_history: dict[int, list[int]] = {}
    id_first_seen: dict[int, int] = {}
    id_last_seen: dict[int, int] = {}
    total_ids = set()
    frame_idx = 0
    t_start = time.monotonic()
    inference_times: list[float] = []

    colors = {}

    def get_color(tid: int) -> tuple:
        if tid not in colors:
            rng = np.random.RandomState(tid * 7 + 13)
            colors[tid] = tuple(int(c) for c in rng.randint(80, 255, 3))
        return colors[tid]

    allowed_classes = {0, 2, 5, 7}  # person, car, bus, truck in COCO

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        t0 = time.monotonic()

        # 1. Detect
        results = model(frame, verbose=False)[0]

        # Build dets array: [x1, y1, x2, y2, conf, cls]
        dets = []
        if results.boxes is not None and len(results.boxes) > 0:
            boxes = results.boxes.xyxy.cpu().numpy()
            confs = results.boxes.conf.cpu().numpy()
            clss = results.boxes.cls.cpu().numpy()

            for i in range(len(boxes)):
                if int(clss[i]) in allowed_classes and confs[i] > 0.35:
                    dets.append(
                        [boxes[i][0], boxes[i][1], boxes[i][2], boxes[i][3], confs[i], clss[i]]
                    )

        dets = np.array(dets) if len(dets) > 0 else np.empty((0, 6))

        # 2. Track
        tracks = tracker.update(dets, frame)  # tracks is [x1, y1, x2, y2, id, conf, cls, ind]

        t1 = time.monotonic()
        inference_times.append(t1 - t0)

        annotated = frame.copy()

        for track in tracks:
            x1, y1, x2, y2, tid, conf, cls, ind = track
            tid = int(tid)
            cls = int(cls)
            total_ids.add(tid)

            if tid not in id_history:
                id_history[tid] = []
                id_first_seen[tid] = frame_idx
            id_history[tid].append(frame_idx)
            id_last_seen[tid] = frame_idx

            color = get_color(tid)
            cv2.rectangle(annotated, (int(x1), int(y1)), (int(x2), int(y2)), color, 2)

            cls_name = model.names.get(cls, str(cls))
            label = f"ID:{tid} {cls_name} {conf:.2f}"
            cv2.putText(
                annotated,
                label,
                (int(x1) + 2, int(y1) - 4),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                color,
                2,
            )

        # HUD
        avg_ms = inference_times[-1] * 1000
        cv2.putText(
            annotated,
            f"Frame {frame_idx}/{total_frames}  {avg_ms:.0f}ms  IDs:{len(total_ids)}",
            (10, 25),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (0, 255, 0),
            1,
        )
        cv2.putText(
            annotated,
            "BoxMOT + OSNet ReID",
            (10, 50),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (200, 200, 200),
            1,
        )

        writer.write(annotated)
        frame_idx += 1

        if frame_idx % 50 == 0:
            elapsed = time.monotonic() - t_start
            fps_actual = frame_idx / max(elapsed, 0.001)
            print(
                f"  [{frame_idx}/{total_frames}] {fps_actual:.1f} FPS, {len(total_ids)} unique IDs so far"
            )

    cap.release()
    writer.release()

    elapsed = time.monotonic() - t_start
    print(f"\nBOXMOT BENCHMARK: {frame_idx} frames in {elapsed:.1f}s, {len(total_ids)} IDs total.")
    print(f"Output saved to {output_path}")

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
        if len(frames_list) > 10 or coverage > 50:
            gap_str = f"  gaps: {gaps}" if gaps else "  continuous"
            print(
                f"  ID {tid:3d}: {len(frames_list):4d} frames, span={span}, coverage={coverage:.0f}%{gap_str}"
            )


if __name__ == "__main__":
    benchmark_dir = Path(__file__).parent
    video_path = benchmark_dir / "test_people.mp4"
    output_path = benchmark_dir / "output_boxmot_osnet.mp4"
    run_boxmot_test(video_path, output_path)
