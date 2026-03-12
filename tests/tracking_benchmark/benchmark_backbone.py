"""Benchmark: MobileNet vs OSNet Re-ID backbone on multiple videos.

Compares three configurations:
  A: Baseline (YOLO-Seg + BoT-SORT, no Re-ID)
  B: Re-ID with MobileNet (ImageNet pretrained, generic classifier)
  C: Re-ID with OSNet x1.0 (MSMT17 pretrained, person Re-ID specialist)
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

GALLERY_CFG = GalleryConfig(
    match_threshold=0.26,
    match_threshold_relaxed=0.20,
    cascade_recent_s=2.0,
    second_best_margin=0.02,
    spatial_gate_px=450.0,
    spatial_gate_grow_rate=220.0,
    appearance_weight=0.50,
    motion_weight=0.35,
    iou_weight=0.15,
    min_fused_score=0.24,
    ema_alpha=0.85,
    max_lost_age=5.0,
    min_track_age_frames=3,
)

COMMON = {
    "model_path": "yolo11n-seg.pt",
    "confidence_threshold": 0.35,
    "tracker": "botsort.yaml",
    "class_whitelist": ["person"],
    "device": "",
    "kalman_config": KalmanCAConfig(),
}


def run_tracker(
    video_path: str,
    label: str,
    max_frames: int,
    enable_reid: bool = False,
    backbone: str = "mobilenet",
):
    cap = cv2.VideoCapture(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    kwargs = dict(**COMMON, enable_reid=enable_reid)
    if enable_reid:
        kwargs["reid_config"] = ReIDConfig(backbone=backbone, device="")
        kwargs["gallery_config"] = GALLERY_CFG

    tracker = YoloSegTracker(**kwargs)

    unique_ids: set[int] = set()
    id_history: dict[int, list[int]] = {}
    latencies: list[float] = []

    n = min(max_frames, total_frames)
    for i in range(n):
        ret, frame = cap.read()
        if not ret:
            break
        t0 = time.perf_counter()
        tracks = tracker.detect_and_track(frame, i / fps)
        dt = (time.perf_counter() - t0) * 1000
        latencies.append(dt)

        for t in tracks:
            unique_ids.add(t.track_id)
            id_history.setdefault(t.track_id, []).append(i)

        if (i + 1) % 100 == 0:
            print(
                f"  [{label}] frame {i + 1}/{n}: {len(unique_ids)} IDs, "
                f"avg={sum(latencies[-100:]) / min(100, len(latencies)):.0f}ms"
            )

    cap.release()

    track_lens = [len(frames) for frames in id_history.values()]
    avg_len = sum(track_lens) / max(len(track_lens), 1)
    frag_breaks = 0
    break_gaps: list[int] = []
    for frames in id_history.values():
        for j in range(1, len(frames)):
            if frames[j] - frames[j - 1] > 1:
                frag_breaks += 1
                break_gaps.append(frames[j] - frames[j - 1])
    avg_gap = sum(break_gaps) / max(len(break_gaps), 1)

    reid_info = ""
    if enable_reid:
        rs = tracker.reid_stats
        skip_pct = rs["skips"] / max(rs["extractions"] + rs["skips"], 1) * 100
        reid_info = (
            f"  remaps={rs['remaps']}  extractions={rs['extractions']}  skip%={skip_pct:.0f}%"
        )

    avg_lat = sum(latencies) / max(len(latencies), 1)
    p95_lat = sorted(latencies)[int(len(latencies) * 0.95)] if latencies else 0

    print(f"\n  [{label}] RESULT:")
    print(f"    Unique IDs:      {len(unique_ids)}")
    print(f"    Avg track len:   {avg_len:.1f} frames")
    print(f"    Frag breaks:     {frag_breaks}")
    print(f"    Avg break gap:   {avg_gap:.1f} frames")
    print(f"    Avg latency:     {avg_lat:.0f} ms")
    print(f"    P95 latency:     {p95_lat:.0f} ms")
    if reid_info:
        print(f"   {reid_info}")

    return {
        "unique_ids": len(unique_ids),
        "avg_track_len": avg_len,
        "frag_breaks": frag_breaks,
        "avg_gap": avg_gap,
        "avg_latency": avg_lat,
        "p95_latency": p95_lat,
    }


def main():
    test_dir = Path(__file__).parent
    videos = []
    for name in ["test_people.mp4", "test_subway.mp4"]:
        p = test_dir / name
        if p.exists():
            cap = cv2.VideoCapture(str(p))
            total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            w, h = int(cap.get(3)), int(cap.get(4))
            cap.release()
            videos.append((str(p), name, total, w, h))

    if not videos:
        print("No test videos found!")
        return

    MAX_FRAMES = 300
    all_results: dict[str, dict[str, dict]] = {}

    for vpath, vname, vtotal, vw, vh in videos:
        print(f"\n{'=' * 60}")
        print(f"VIDEO: {vname}  ({vw}x{vh}, {vtotal} frames, testing {min(MAX_FRAMES, vtotal)})")
        print("=" * 60)

        results: dict[str, dict] = {}

        print("\n--- A: Baseline (no Re-ID) ---")
        results["baseline"] = run_tracker(vpath, "Baseline", MAX_FRAMES)

        print("\n--- B: MobileNet Re-ID (ImageNet) ---")
        results["mobilenet"] = run_tracker(
            vpath, "MobileNet", MAX_FRAMES, enable_reid=True, backbone="mobilenet"
        )

        print("\n--- C: OSNet Re-ID (MSMT17 person Re-ID) ---")
        results["osnet"] = run_tracker(
            vpath, "OSNet", MAX_FRAMES, enable_reid=True, backbone="osnet_x1_0"
        )

        all_results[vname] = results

    print(f"\n\n{'=' * 60}")
    print("SUMMARY")
    print("=" * 60)
    for vname, results in all_results.items():
        base = results["baseline"]["unique_ids"]
        mob = results["mobilenet"]["unique_ids"]
        osn = results["osnet"]["unique_ids"]
        mob_pct = (1 - mob / max(base, 1)) * 100
        osn_pct = (1 - osn / max(base, 1)) * 100

        print(f"\n{vname}:")
        print(f"  {'Metric':<20} {'Baseline':>10} {'MobileNet':>12} {'OSNet':>12}")
        print(f"  {'-' * 20} {'-' * 10} {'-' * 12} {'-' * 12}")
        for key in ["unique_ids", "avg_track_len", "frag_breaks", "avg_gap", "avg_latency"]:
            bv = results["baseline"][key]
            mv = results["mobilenet"][key]
            ov = results["osnet"][key]
            if key == "unique_ids":
                print(f"  {key:<20} {bv:>10} {mv:>8} ({mob_pct:+.0f}%) {ov:>8} ({osn_pct:+.0f}%)")
            elif "latency" in key:
                print(f"  {key:<20} {bv:>8.0f}ms {mv:>10.0f}ms {ov:>10.0f}ms")
            else:
                fmt = ".1f" if isinstance(bv, float) else "d"
                print(f"  {key:<20} {bv:>10{fmt}} {mv:>12{fmt}} {ov:>12{fmt}}")


if __name__ == "__main__":
    main()
