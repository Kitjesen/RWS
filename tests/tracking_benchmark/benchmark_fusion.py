"""Benchmark: FusionMOT (self-built) vs BoT-SORT vs BoT-SORT+ReID.

Three-way comparison:
  A: Baseline (YOLO + BoT-SORT, no Re-ID)
  B: BoT-SORT + Re-ID (OSNet, post-hoc recovery)
  C: FusionMOT (YOLO raw detect + FusionMOT + OSNet, self-built tracker)
"""
import sys
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent.parent / "src"))

import time
from pathlib import Path

import cv2

from rws_tracking.algebra.kalman2d import KalmanCAConfig
from rws_tracking.perception.appearance_gallery import GalleryConfig
from rws_tracking.perception.reid_extractor import ReIDConfig
from rws_tracking.perception.yolo_seg_tracker import YoloSegTracker
from rws_tracking.perception.fusion_seg_tracker import FusionSegTracker
from rws_tracking.perception.fusion_mot import FusionMOTConfig


def run_test(tracker_obj, video_path: str, label: str, max_frames: int):
    cap = cv2.VideoCapture(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    unique_ids: set[int] = set()
    id_history: dict[int, list[int]] = {}
    latencies: list[float] = []
    n = min(max_frames, total)

    for i in range(n):
        ret, frame = cap.read()
        if not ret:
            break
        t0 = time.perf_counter()
        tracks = tracker_obj.detect_and_track(frame, i / fps)
        dt_ms = (time.perf_counter() - t0) * 1000
        latencies.append(dt_ms)

        for t in tracks:
            unique_ids.add(t.track_id)
            id_history.setdefault(t.track_id, []).append(i)

        if (i + 1) % 100 == 0:
            print(f"  [{label}] frame {i+1}/{n}: {len(unique_ids)} IDs, "
                  f"avg={sum(latencies[-100:]) / min(100, len(latencies)):.0f}ms")

    cap.release()

    track_lens = [len(f) for f in id_history.values()]
    avg_len = sum(track_lens) / max(len(track_lens), 1)
    frag = sum(1 for frames in id_history.values()
               for j in range(1, len(frames)) if frames[j] - frames[j-1] > 1)
    gaps = [frames[j] - frames[j-1] for frames in id_history.values()
            for j in range(1, len(frames)) if frames[j] - frames[j-1] > 1]
    avg_gap = sum(gaps) / max(len(gaps), 1)
    avg_lat = sum(latencies) / max(len(latencies), 1)
    p95_lat = sorted(latencies)[int(len(latencies) * 0.95)] if latencies else 0

    rs = tracker_obj.reid_stats if hasattr(tracker_obj, 'reid_stats') else {}
    skip_pct = 0
    if rs.get("extractions", 0) + rs.get("skips", 0) > 0:
        skip_pct = rs["skips"] / (rs["extractions"] + rs["skips"]) * 100

    return {
        "label": label,
        "unique_ids": len(unique_ids),
        "avg_track_len": avg_len,
        "frag": frag,
        "avg_gap": avg_gap,
        "avg_lat": avg_lat,
        "p95_lat": p95_lat,
        "remaps": rs.get("remaps", 0),
        "skip_pct": skip_pct,
    }


def print_results(video_name: str, results: list[dict]):
    print(f"\n{'='*65}")
    print(f"  {video_name}")
    print(f"{'='*65}")
    print(f"  {'Metric':<18}", end="")
    for r in results:
        print(f" {r['label']:>16}", end="")
    print()
    print(f"  {'-'*18}", end="")
    for _ in results:
        print(f" {'-'*16}", end="")
    print()

    base_ids = results[0]["unique_ids"]
    for key, label, fmt in [
        ("unique_ids", "Unique IDs", "d"),
        ("avg_track_len", "Avg track len", ".1f"),
        ("frag", "Frag breaks", "d"),
        ("avg_gap", "Avg break gap", ".1f"),
        ("avg_lat", "Avg latency(ms)", ".0f"),
        ("p95_lat", "P95 latency(ms)", ".0f"),
    ]:
        print(f"  {label:<18}", end="")
        for r in results:
            val = r[key]
            if key == "unique_ids" and r != results[0]:
                pct = (1 - val / max(base_ids, 1)) * 100
                print(f" {val:>10{fmt}}({pct:+.0f}%)", end="")
            elif "lat" in key:
                print(f" {val:>14{fmt}}ms", end="")
            else:
                print(f" {val:>16{fmt}}", end="")
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
    GALLERY_CFG = GalleryConfig(
        match_threshold=0.26, match_threshold_relaxed=0.20,
        cascade_recent_s=2.0, second_best_margin=0.02,
        spatial_gate_px=450.0, spatial_gate_grow_rate=220.0,
        appearance_weight=0.50, motion_weight=0.35,
        iou_weight=0.15, min_fused_score=0.24,
        ema_alpha=0.85, max_lost_age=5.0, min_track_age_frames=3,
    )

    for vpath, vname in videos:
        cap = cv2.VideoCapture(vpath)
        w, h = int(cap.get(3)), int(cap.get(4))
        total = int(cap.get(7))
        cap.release()
        print(f"\n{'#'*65}")
        print(f"  VIDEO: {vname} ({w}x{h}, {total}f, testing {min(MAX, total)})")
        print(f"{'#'*65}")

        results = []

        # A: Baseline
        print("\n--- A: Baseline (YOLO + BoT-SORT) ---")
        t_a = YoloSegTracker(
            model_path="yolo11n-seg.pt", confidence_threshold=0.35,
            tracker="botsort.yaml", class_whitelist=["person"],
            device="", kalman_config=KalmanCAConfig(), enable_reid=False,
        )
        results.append(run_test(t_a, vpath, "Baseline", MAX))
        del t_a

        # B: BoT-SORT + ReID (OSNet)
        print("\n--- B: BoT-SORT + OSNet Re-ID ---")
        t_b = YoloSegTracker(
            model_path="yolo11n-seg.pt", confidence_threshold=0.35,
            tracker="botsort.yaml", class_whitelist=["person"],
            device="", kalman_config=KalmanCAConfig(), enable_reid=True,
            reid_config=ReIDConfig(backbone="osnet_x1_0", device=""),
            gallery_config=GALLERY_CFG,
        )
        results.append(run_test(t_b, vpath, "BoT+OSNet", MAX))
        del t_b

        # C: FusionMOT (self-built)
        print("\n--- C: FusionMOT (self-built tracker) ---")
        t_c = FusionSegTracker(
            model_path="yolo11n-seg.pt",
            confidence_threshold=0.35,
            low_confidence_threshold=0.15,
            class_whitelist=["person"],
            device="",
            img_size=640,
            reid_config=ReIDConfig(backbone="osnet_x1_0", device=""),
            mot_config=FusionMOTConfig(),
            kalman_config=KalmanCAConfig(),
        )
        results.append(run_test(t_c, vpath, "FusionMOT", MAX))
        del t_c

        print_results(vname, results)

    print("\nDone.")


if __name__ == "__main__":
    main()
