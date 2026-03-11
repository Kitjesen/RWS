"""Benchmark: YOLO model size comparison (Nano vs Small).

Compares detection quality and tracking stability:
  - yolo11n-pose.pt (Nano, ~2.6M params)
  - yolo11s-pose.pt (Small, ~9.4M params, ~4x larger)

Goal: Measure if larger model reduces miss-detections and improves ID stability.
"""
import sys

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent.parent / "src"))

import time
from pathlib import Path

import cv2

from rws_tracking.perception.fusion_mot import FusionMOTConfig
from rws_tracking.perception.fusion_seg_tracker import FusionSegTracker
from rws_tracking.perception.reid_extractor import ReIDConfig


def run_test(tracker_obj, video_path: str, label: str, max_frames: int):
    cap = cv2.VideoCapture(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    unique_ids: set[int] = set()
    id_history: dict[int, list[int]] = {}
    latencies: list[float] = []
    det_counts: list[int] = []
    n = min(max_frames, total)

    for i in range(n):
        ret, frame = cap.read()
        if not ret:
            break
        t0 = time.perf_counter()
        tracks = tracker_obj.detect_and_track(frame, i / fps)
        dt_ms = (time.perf_counter() - t0) * 1000
        latencies.append(dt_ms)
        det_counts.append(len(tracks))

        for t in tracks:
            unique_ids.add(t.track_id)
            id_history.setdefault(t.track_id, []).append(i)

        if (i + 1) % 100 == 0:
            print(f"  [{label}] frame {i+1}/{n}: {len(unique_ids)} IDs, "
                  f"avg_det={sum(det_counts[-100:])/100:.1f}, "
                  f"avg_lat={sum(latencies[-100:])/100:.0f}ms")

    cap.release()

    track_lens = [len(f) for f in id_history.values()]
    avg_len = sum(track_lens) / max(len(track_lens), 1)
    frag = sum(1 for frames in id_history.values()
               for j in range(1, len(frames)) if frames[j] - frames[j-1] > 1)
    avg_lat = sum(latencies) / max(len(latencies), 1)
    p95_lat = sorted(latencies)[int(len(latencies) * 0.95)] if latencies else 0
    avg_det = sum(det_counts) / max(len(det_counts), 1)

    return {
        "label": label,
        "unique_ids": len(unique_ids),
        "avg_track_len": avg_len,
        "frag": frag,
        "avg_det": avg_det,
        "avg_lat": avg_lat,
        "p95_lat": p95_lat,
    }


def print_results(video_name: str, results: list[dict]):
    col = 18
    sep = "=" * (24 + col * len(results))
    print(f"\n{sep}")
    print(f"  {video_name}")
    print(sep)
    print(f"  {'Metric':<22}", end="")
    for r in results:
        print(f" {r['label']:>{col}}", end="")
    print()
    print(f"  {'-'*22}", end="")
    for _ in results:
        print(f" {'-'*col}", end="")
    print()

    base = results[0]
    for key, label, fmt, _higher_better in [
        ("unique_ids",    "Unique IDs (lower=better)",  "d",   False),
        ("avg_track_len", "Avg track len (higher=better)", ".1f", True),
        ("frag",          "Frag breaks (lower=better)", "d",   False),
        ("avg_det",       "Avg detections/frame",       ".2f", True),
        ("avg_lat",       "Avg latency (ms)",           ".0f", False),
        ("p95_lat",       "P95 latency (ms)",           ".0f", False),
    ]:
        print(f"  {label:<22}", end="")
        for r in results:
            val = r[key]
            if r is base:
                cell = f"{val:{fmt}}"
                print(f" {cell:>{col}}", end="")
            else:
                bval = base[key]
                if bval != 0:
                    pct = (val - bval) / abs(bval) * 100
                else:
                    pct = 0.0
                sign = "+" if pct > 0 else ""
                cell = f"{val:{fmt}}({sign}{pct:.0f}%)"
                print(f" {cell:>{col}}", end="")
        print()


def main():
    test_dir = Path(__file__).parent
    videos = []
    for name in ["test_people.mp4", "test_subway.mp4"]:
        p = test_dir / name
        if p.exists():
            videos.append((str(p), name))

    if not videos:
        print("No test videos found!")
        return

    MAX = 300
    MOT_CFG = FusionMOTConfig(
        w_skeleton=0.06,
        use_hip_center=True,
        skeleton_gate=1.2,
        kp_visibility_thresh=0.2,
    )
    REID_CFG = ReIDConfig(backbone="osnet_x1_0", device="")

    models = [
        ("yolo11n-pose.pt", "Nano"),
        ("yolo11s-pose.pt", "Small"),
    ]

    for vpath, vname in videos:
        cap = cv2.VideoCapture(vpath)
        w, h = int(cap.get(3)), int(cap.get(4))
        total = int(cap.get(7))
        cap.release()
        print(f"\n{'#'*70}")
        print(f"  VIDEO: {vname} ({w}x{h}, {total}f, testing {min(MAX, total)})")
        print(f"{'#'*70}")

        results = []
        for model_path, label in models:
            print(f"\n--- {label}: {model_path} ---")
            try:
                tracker = FusionSegTracker(
                    model_path=model_path,
                    confidence_threshold=0.35,
                    low_confidence_threshold=0.15,
                    class_whitelist=["person"],
                    device="",
                    img_size=640,
                    reid_config=REID_CFG,
                    mot_config=MOT_CFG,
                )
                results.append(run_test(tracker, vpath, label, MAX))
                del tracker
            except Exception as exc:
                print(f"  [{label}] FAILED: {exc}")

        if results:
            print_results(vname, results)

    print("\nDone.")


if __name__ == "__main__":
    main()
