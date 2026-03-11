"""Benchmark: FusionMOT variants vs BoT-SORT baselines.

Four-way comparison:
  A: Baseline   — YOLO-seg + BoT-SORT, no Re-ID
  B: BoT+OSNet  — YOLO-seg + BoT-SORT + OSNet Re-ID (post-hoc)
  C: FusionMOT  — YOLO-seg + FusionMOT (Kalman CA, fused cost matrix, OSNet)
  D: Pose+Skel  — YOLO-pose + FusionMOT + skeleton cue (hip center, 8-D descriptor)

Lower unique IDs / higher avg_track_len / lower frag = better tracking stability.
"""
import sys

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent.parent / "src"))

import time
from pathlib import Path

import cv2

from rws_tracking.perception.appearance_gallery import GalleryConfig
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
    col = 17
    sep = "=" * (22 + col * len(results))
    print(f"\n{sep}")
    print(f"  {video_name}")
    print(sep)
    print(f"  {'Metric':<20}", end="")
    for r in results:
        print(f" {r['label']:>{col}}", end="")
    print()
    print(f"  {'-'*20}", end="")
    for _ in results:
        print(f" {'-'*col}", end="")
    print()

    base = results[0]
    for key, label, fmt, _higher_better in [
        ("unique_ids",    "Unique IDs",      "d",   False),
        ("avg_track_len", "Avg track len",   ".1f", True),
        ("frag",          "Frag breaks",     "d",   False),
        ("avg_gap",       "Avg break gap",   ".1f", False),
        ("avg_lat",       "Avg latency(ms)", ".0f", False),
        ("p95_lat",       "P95 latency(ms)", ".0f", False),
    ]:
        print(f"  {label:<20}", end="")
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
    GalleryConfig(
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

        # Cached baseline numbers from previous full run (saves ~4 min per video)
        CACHED = {
            "test_people.mp4": [
                {"label": "Baseline",  "unique_ids": 69,  "avg_track_len": 87.6,
                 "frag": 213, "avg_gap": 5.4,  "avg_lat": 172, "p95_lat": 216,
                 "remaps": 0, "skip_pct": 0},
                {"label": "BoT+OSNet", "unique_ids": 28,  "avg_track_len": 215.9,
                 "frag": 117, "avg_gap": 8.7,  "avg_lat": 250, "p95_lat": 401,
                 "remaps": 0, "skip_pct": 0},
                {"label": "FusionMOT", "unique_ids": 34,  "avg_track_len": 260.2,
                 "frag": 241, "avg_gap": 2.6,  "avg_lat": 183, "p95_lat": 286,
                 "remaps": 0, "skip_pct": 0},
            ],
            "test_subway.mp4": [
                {"label": "Baseline",  "unique_ids": 18,  "avg_track_len": 124.7,
                 "frag": 39,  "avg_gap": 7.0,  "avg_lat": 186, "p95_lat": 215,
                 "remaps": 0, "skip_pct": 0},
                {"label": "BoT+OSNet", "unique_ids": 9,   "avg_track_len": 249.4,
                 "frag": 31,  "avg_gap": 10.1, "avg_lat": 189, "p95_lat": 243,
                 "remaps": 0, "skip_pct": 0},
                {"label": "FusionMOT", "unique_ids": 15,  "avg_track_len": 209.5,
                 "frag": 36,  "avg_gap": 12.9, "avg_lat": 141, "p95_lat": 195,
                 "remaps": 0, "skip_pct": 0},
            ],
        }
        results = list(CACHED.get(vname, []))

        # C: FusionMOT (self-built, Kalman CA internal)
        print("\n--- C: FusionMOT (self-built tracker + Kalman CA) ---")
        t_c = FusionSegTracker(
            model_path="yolo11n-seg.pt",
            confidence_threshold=0.35,
            low_confidence_threshold=0.15,
            class_whitelist=["person"],
            device="",
            img_size=640,
            reid_config=ReIDConfig(backbone="osnet_x1_0", device=""),
            mot_config=FusionMOTConfig(),
        )
        results.append(run_test(t_c, vpath, "FusionMOT", MAX))
        del t_c

        # D: FusionMOT + Pose model + skeleton cue
        # Uses yolo11n-pose.pt (same Nano speed) which outputs COCO-17 keypoints.
        # Hip center replaces bbox centroid as Kalman anchor; 8-D bone-proportion
        # descriptor is added as a 5th cost-matrix cue (w=0.10).
        # Requires yolo11n-pose.pt — skipped if not available.
        pose_model = "yolo11n-pose.pt"
        try:
            import ultralytics  # noqa: F401
            print(f"\n--- D: FusionMOT + Pose skeleton (model={pose_model}) ---")
            t_d = FusionSegTracker(
                model_path=pose_model,
                confidence_threshold=0.35,
                low_confidence_threshold=0.15,
                class_whitelist=["person"],
                device="",
                img_size=640,
                reid_config=ReIDConfig(backbone="osnet_x1_0", device=""),
                mot_config=FusionMOTConfig(
                    w_skeleton=0.06,      # soft cue, not hard gate
                    use_hip_center=True,
                    skeleton_gate=1.2,    # wider: allows view-angle variation
                    kp_visibility_thresh=0.2,  # lower: catches small targets in high-res video
                ),
            )
            results.append(run_test(t_d, vpath, "Pose+Skel", MAX))
            del t_d
        except Exception as exc:
            print(f"  [D] skipped: {exc}")

        print_results(vname, results)

    print("\nDone.")


if __name__ == "__main__":
    main()
