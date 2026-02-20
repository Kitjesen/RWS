"""
RWS Tracking Benchmark v4: Deep OC-SORT paper-guided improvements.

Three techniques from Deep OC-SORT (CMU, ICASSP 2023):
  - **Dynamic Appearance (DA)**: confidence-modulated EMA rejects dirty features.
  - **Adaptive Weighting (AW)**: discriminativeness-based appearance boost.
  - **Observation-Centric Momentum (OCM)**: raw-observation velocity for lost tracks.

Flow:
  1) Run baseline once.
  2) Run multiple Re-ID configs on a short clip (fast search).
  3) Pick the best config by composite score.
  4) Re-run baseline + best config on full video and export annotated videos.
"""

import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import cv2
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from rws_tracking.algebra.kalman2d import KalmanCAConfig
from rws_tracking.perception.appearance_gallery import GalleryConfig
from rws_tracking.perception.reid_extractor import ReIDConfig
from rws_tracking.perception.yolo_seg_tracker import YoloSegTracker


@dataclass
class BenchmarkStats:
    name: str = ""
    total_frames: int = 0
    wall_time: float = 0.0
    inference_times: list[float] = field(default_factory=list)
    unique_ids: set[int] = field(default_factory=set)
    id_history: dict[int, list[int]] = field(default_factory=dict)
    id_first_seen: dict[int, int] = field(default_factory=dict)
    id_last_seen: dict[int, int] = field(default_factory=dict)
    reid_recoveries: int = 0
    fragmentation: int = 0
    avg_gap: float = 0.0
    score: float = 0.0


def download_test_video(output_path: Path) -> bool:
    if output_path.exists():
        print(f"[OK] Test video exists: {output_path}")
        return True

    url = "https://media.roboflow.com/supervision/video-examples/people-walking.mp4"
    print(f"[DL] Downloading from {url} ...")
    try:
        import urllib.request
        urllib.request.urlretrieve(url, str(output_path))
        if output_path.exists() and output_path.stat().st_size > 100_000:
            print(f"[OK] Downloaded ({output_path.stat().st_size // 1024} KB)")
            return True
    except Exception as e:
        print(f"[ERR] Download failed: {e}")
    return False


def get_color(tid: int, palette: dict[int, tuple]) -> tuple:
    if tid not in palette:
        rng = np.random.RandomState(tid * 7 + 13)
        palette[tid] = tuple(int(c) for c in rng.randint(80, 255, 3))
    return palette[tid]


def _compute_fragmentation(id_history: dict[int, list[int]]) -> tuple[int, float]:
    """Return (total_breaks, avg_gap_of_breaks)."""
    gaps: list[int] = []
    for frames in id_history.values():
        if len(frames) < 2:
            continue
        for i in range(1, len(frames)):
            g = frames[i] - frames[i - 1]
            if g > 1:
                gaps.append(g)
    if not gaps:
        return 0, 0.0
    return len(gaps), float(np.mean(gaps))


def _composite_score(s: BenchmarkStats, baseline_unique_ids: int) -> float:
    """
    Higher is better.
    Emphasize ID stability while still considering speed.
    """
    uid_reduction = (baseline_unique_ids - len(s.unique_ids)) / max(baseline_unique_ids, 1)
    long_track_bonus = np.mean([len(v) for v in s.id_history.values()]) / max(s.total_frames, 1)
    frag_penalty = s.fragmentation / max(s.total_frames, 1)
    latency_penalty = (np.mean(s.inference_times) if s.inference_times else 0.0) * 2.0
    return 2.0 * uid_reduction + 1.0 * long_track_bonus - 1.5 * frag_penalty - latency_penalty


def run_single_test(
    video_path: Path,
    output_path: Path | None,
    tracker: YoloSegTracker,
    label: str,
    max_frames: int | None = None,
    write_video: bool = True,
) -> BenchmarkStats:
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        return BenchmarkStats(name=label)

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    print(f"\n  [{label}] {w}x{h} @ {fps:.0f}FPS  ({total_frames} frames)")

    writer = None
    if write_video and output_path is not None:
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        writer = cv2.VideoWriter(str(output_path), fourcc, fps, (w, h))

    stats = BenchmarkStats(name=label)
    colors: dict[int, tuple] = {}
    frame_idx = 0
    t_start = time.monotonic()

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        ts = frame_idx / fps
        t0 = time.monotonic()
        tracks = tracker.detect_and_track(frame, ts)
        t1 = time.monotonic()
        stats.inference_times.append(t1 - t0)

        annotated = frame.copy()
        for track in tracks:
            tid = track.track_id
            stats.unique_ids.add(tid)
            if tid not in stats.id_history:
                stats.id_history[tid] = []
                stats.id_first_seen[tid] = frame_idx
            stats.id_history[tid].append(frame_idx)
            stats.id_last_seen[tid] = frame_idx

            b = track.bbox
            x1, y1 = int(b.x), int(b.y)
            x2, y2 = int(b.x + b.w), int(b.y + b.h)
            color = get_color(tid, colors)
            cv2.rectangle(annotated, (x1, y1), (x2, y2), color, 2)

            lbl = f"ID:{tid}"
            (tw, th_t), _ = cv2.getTextSize(lbl, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
            cv2.rectangle(annotated, (x1, y1 - th_t - 6), (x1 + tw + 4, y1), color, -1)
            cv2.putText(annotated, lbl, (x1 + 2, y1 - 4),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)

        reid_info = ""
        if hasattr(tracker, "reid_stats"):
            rs = tracker.reid_stats
            if rs["enabled"]:
                skip_pct = (rs["skips"] / max(rs["extractions"] + rs["skips"], 1)) * 100
                reid_info = f"  ReID remaps={rs['remaps']} skip={skip_pct:.0f}%"
                stats.reid_recoveries = rs["remaps"]

        avg_ms = stats.inference_times[-1] * 1000
        cv2.putText(annotated,
                     f"[{label}] F{frame_idx}  {avg_ms:.0f}ms  IDs:{len(stats.unique_ids)}{reid_info}",
                     (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 0), 1)

        if writer is not None:
            writer.write(annotated)
        frame_idx += 1
        if max_frames is not None and frame_idx >= max_frames:
            break

        if frame_idx % 100 == 0:
            elapsed = time.monotonic() - t_start
            fps_actual = frame_idx / max(elapsed, 0.001)
            print(f"    [{frame_idx}/{total_frames}] {fps_actual:.1f} FPS, {len(stats.unique_ids)} IDs")

    cap.release()
    if writer is not None:
        writer.release()
    stats.total_frames = frame_idx
    stats.wall_time = time.monotonic() - t_start
    stats.fragmentation, stats.avg_gap = _compute_fragmentation(stats.id_history)
    return stats


def print_comparison(*all_stats: BenchmarkStats, baseline_unique_ids: int | None = None):
    def avg_ms(s: BenchmarkStats) -> float:
        return np.mean(s.inference_times) * 1000 if s.inference_times else 0

    def p95_ms(s: BenchmarkStats) -> float:
        return np.percentile(s.inference_times, 95) * 1000 if s.inference_times else 0

    def count_long(s: BenchmarkStats) -> int:
        return sum(1 for f in s.id_history.values() if len(f) >= 30)

    def count_short(s: BenchmarkStats) -> int:
        return sum(1 for f in s.id_history.values() if len(f) <= 10)

    def avg_len(s: BenchmarkStats) -> float:
        return np.mean([len(f) for f in s.id_history.values()]) if s.id_history else 0

    col_w = 18
    header_names = [s.name for s in all_stats]

    print(f"\n{'='*80}")
    print(f"{'COMPARISON REPORT':^80}")
    print(f"{'='*80}")

    header = f"  {'Metric':<30}" + "".join(f" {n:>{col_w}}" for n in header_names)
    print(header)
    print(f"  {'-'*30}" + (" " + "-"*col_w) * len(all_stats))

    def row(label: str, values: list[str]):
        print(f"  {label:<30}" + "".join(f" {v:>{col_w}}" for v in values))

    row("Frames", [str(s.total_frames) for s in all_stats])
    row("Wall time (s)", [f"{s.wall_time:.1f}" for s in all_stats])
    row("Avg inference (ms)", [f"{avg_ms(s):.1f}" for s in all_stats])
    row("P95 inference (ms)", [f"{p95_ms(s):.1f}" for s in all_stats])
    row("Unique IDs (LOWER=BETTER)", [str(len(s.unique_ids)) for s in all_stats])
    row("Long tracks (>30f)", [str(count_long(s)) for s in all_stats])
    row("Short tracks (<10f)", [str(count_short(s)) for s in all_stats])
    row("Avg track length", [f"{avg_len(s):.1f}" for s in all_stats])
    row("Fragmentation breaks", [str(s.fragmentation) for s in all_stats])
    row("Avg break gap", [f"{s.avg_gap:.1f}" for s in all_stats])
    row("Re-ID recoveries", [str(s.reid_recoveries) if s.reid_recoveries else "N/A" for s in all_stats])
    row("Composite score", [f"{s.score:.4f}" for s in all_stats])

    baseline_ids = baseline_unique_ids or (len(all_stats[0].unique_ids) if all_stats else 1)
    print()
    for s in all_stats[1:]:
        red = (1 - len(s.unique_ids) / max(baseline_ids, 1)) * 100
        print(
            f"  {s.name} vs Baseline: ID reduction={red:+.1f}%  "
            f"Avg track len delta={avg_len(s) - avg_len(all_stats[0]):+.1f}f  "
            f"Frag delta={s.fragmentation - all_stats[0].fragmentation:+d}"
        )

    print(f"{'='*80}\n")


if __name__ == "__main__":
    benchmark_dir = Path(__file__).parent
    video_path = benchmark_dir / "test_people.mp4"

    if not download_test_video(video_path):
        sys.exit(1)

    common_kwargs = dict(
        model_path="yolo11n-seg.pt",
        confidence_threshold=0.35,
        tracker="botsort.yaml",
        class_whitelist=["person"],
        device="",
        kalman_config=KalmanCAConfig(),
    )

    search_frames = 220  # fast tuning window

    print("\n" + "=" * 80)
    print("  BASELINE (search window)")
    print("=" * 80)
    tracker_base_search = YoloSegTracker(**common_kwargs, enable_reid=False)
    base_search = run_single_test(
        video_path,
        output_path=None,
        tracker=tracker_base_search,
        label="Baseline-search",
        max_frames=search_frames,
        write_video=False,
    )
    del tracker_base_search

    # Each config now includes Deep OC-SORT parameters: DA, AW, OCM
    candidate_cfgs: list[tuple[str, dict[str, Any]]] = [
        (
            "paper-balanced",
            dict(
                match_threshold=0.30,
                match_threshold_relaxed=0.24,
                cascade_recent_s=1.5,
                second_best_margin=0.03,
                spatial_gate_px=380.0,
                spatial_gate_grow_rate=180.0,
                appearance_weight=0.55,
                motion_weight=0.30,
                iou_weight=0.15,
                min_fused_score=0.30,
                da_alpha_fixed=0.95,
                da_confidence_sigma=0.40,
                aw_epsilon=0.5,
                aw_base_weight=0.55,
                ocm_window=5,
            ),
        ),
        (
            "paper-strong-da",
            dict(
                match_threshold=0.30,
                match_threshold_relaxed=0.24,
                cascade_recent_s=1.5,
                second_best_margin=0.03,
                spatial_gate_px=380.0,
                spatial_gate_grow_rate=180.0,
                appearance_weight=0.55,
                motion_weight=0.30,
                iou_weight=0.15,
                min_fused_score=0.30,
                da_alpha_fixed=0.92,
                da_confidence_sigma=0.45,
                aw_epsilon=0.5,
                aw_base_weight=0.55,
                ocm_window=5,
            ),
        ),
        (
            "paper-strong-aw",
            dict(
                match_threshold=0.28,
                match_threshold_relaxed=0.22,
                cascade_recent_s=1.8,
                second_best_margin=0.03,
                spatial_gate_px=400.0,
                spatial_gate_grow_rate=200.0,
                appearance_weight=0.55,
                motion_weight=0.30,
                iou_weight=0.15,
                min_fused_score=0.28,
                da_alpha_fixed=0.95,
                da_confidence_sigma=0.40,
                aw_epsilon=1.0,
                aw_base_weight=0.75,
                ocm_window=5,
            ),
        ),
        (
            "paper-recall",
            dict(
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
                da_alpha_fixed=0.95,
                da_confidence_sigma=0.40,
                aw_epsilon=0.5,
                aw_base_weight=0.55,
                ocm_window=7,
            ),
        ),
        (
            "paper-precision",
            dict(
                match_threshold=0.34,
                match_threshold_relaxed=0.28,
                cascade_recent_s=1.2,
                second_best_margin=0.04,
                spatial_gate_px=320.0,
                spatial_gate_grow_rate=140.0,
                appearance_weight=0.62,
                motion_weight=0.25,
                iou_weight=0.13,
                min_fused_score=0.34,
                da_alpha_fixed=0.95,
                da_confidence_sigma=0.40,
                aw_epsilon=0.5,
                aw_base_weight=0.55,
                ocm_window=5,
            ),
        ),
    ]

    search_results: list[tuple[str, BenchmarkStats, dict[str, Any]]] = []
    print("\n" + "=" * 80)
    print("  GRID SEARCH (search window)")
    print("=" * 80)
    for name, cfg in candidate_cfgs:
        tracker = YoloSegTracker(
            **common_kwargs,
            enable_reid=True,
            reid_config=ReIDConfig(device=""),
            gallery_config=GalleryConfig(
                ema_alpha=0.85,
                max_lost_age=5.0,
                min_track_age_frames=3,
                **cfg,
            ),
        )
        s = run_single_test(
            video_path,
            output_path=None,
            tracker=tracker,
            label=name,
            max_frames=search_frames,
            write_video=False,
        )
        s.score = _composite_score(s, baseline_unique_ids=len(base_search.unique_ids))
        search_results.append((name, s, cfg))
        print(
            f"  {name}: IDs={len(s.unique_ids)} remaps={s.reid_recoveries} "
            f"frag={s.fragmentation} score={s.score:.4f}"
        )

    search_results.sort(key=lambda x: x[1].score, reverse=True)
    best_name, best_stats, best_cfg = search_results[0]
    print("\nBest search config:", best_name, best_cfg)

    print("\n" + "=" * 80)
    print("  FINAL FULL-RUN COMPARISON (baseline vs best config)")
    print("=" * 80)

    tracker_a = YoloSegTracker(**common_kwargs, enable_reid=False)
    stats_a = run_single_test(
        video_path,
        output_path=benchmark_dir / "output_A_baseline.mp4",
        tracker=tracker_a,
        label="A:Baseline",
        max_frames=None,
        write_video=True,
    )
    stats_a.score = _composite_score(stats_a, baseline_unique_ids=len(stats_a.unique_ids))
    del tracker_a

    tracker_b = YoloSegTracker(
        **common_kwargs,
        enable_reid=True,
        reid_config=ReIDConfig(device=""),
        gallery_config=GalleryConfig(
            ema_alpha=0.85,
            max_lost_age=5.0,
            min_track_age_frames=3,
            **best_cfg,
        ),
    )
    stats_b = run_single_test(
        video_path,
        output_path=benchmark_dir / "output_B_reid_best.mp4",
        tracker=tracker_b,
        label=f"B:{best_name}",
        max_frames=None,
        write_video=True,
    )
    stats_b.score = _composite_score(stats_b, baseline_unique_ids=len(stats_a.unique_ids))

    print_comparison(stats_a, stats_b, baseline_unique_ids=len(stats_a.unique_ids))
