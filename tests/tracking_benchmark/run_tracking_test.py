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
import supervision as sv

BENCHMARK_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BENCHMARK_DIR.parent.parent.parent
sys.path.insert(0, str(BENCHMARK_DIR))
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from benchmark_metrics import (  # noqa: E402
    average_people_per_frame,
    average_track_length,
    count_long_tracks,
    count_short_tracks,
    compute_fragmentation,
    p95_frame_latency_ms,
    short_track_ratio,
)
from rws_tracking.algebra.kalman2d import KalmanCAConfig  # noqa: E402
from rws_tracking.perception.appearance_gallery import GalleryConfig  # noqa: E402
from rws_tracking.perception.reid_extractor import ReIDConfig  # noqa: E402
from rws_tracking.perception.supervision_adapter import tracks_to_sv_detections  # noqa: E402
from rws_tracking.perception.yolo_seg_tracker import YoloSegTracker  # noqa: E402
from zone_analytics import ZoneAnalytics  # noqa: E402


@dataclass
class BenchmarkStats:
    name: str = ""
    total_frames: int = 0
    wall_time: float = 0.0
    inference_times: list[float] = field(default_factory=list)
    unique_ids: set[int] = field(default_factory=set)
    frame_track_counts: list[int] = field(default_factory=list)
    id_history: dict[int, list[int]] = field(default_factory=dict)
    id_first_seen: dict[int, int] = field(default_factory=dict)
    id_last_seen: dict[int, int] = field(default_factory=dict)
    reid_recoveries: int = 0
    fragmentation: int = 0
    avg_gap: float = 0.0
    score: float = 0.0
    zone_counts: dict = field(default_factory=dict)


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


def _compute_fragmentation(id_history: dict[int, list[int]]) -> tuple[int, float]:
    """Return (total_breaks, avg_gap_of_breaks)."""
    return compute_fragmentation(id_history)


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
    zone_analytics: ZoneAnalytics | None = None,
) -> BenchmarkStats:
    video_info = sv.VideoInfo.from_video_path(str(video_path))
    fps = video_info.fps or 30.0
    print(
        f"\n  [{label}] {video_info.width}x{video_info.height}"
        f" @ {fps:.0f}FPS  ({video_info.total_frames} frames)"
    )

    box_annotator = sv.BoxAnnotator(color_lookup=sv.ColorLookup.TRACK)
    label_annotator = sv.LabelAnnotator(color_lookup=sv.ColorLookup.TRACK)
    trace_annotator = sv.TraceAnnotator(
        color_lookup=sv.ColorLookup.TRACK,
        trace_length=30,
        thickness=2,
    )
    fps_monitor = sv.FPSMonitor()

    stats = BenchmarkStats(name=label)
    t_start = time.monotonic()

    def _run(sink: sv.VideoSink | None) -> None:
        fps_monitor.reset()
        frames = sv.get_video_frames_generator(str(video_path), end=max_frames)
        for frame_idx, frame in enumerate(frames):
            ts = frame_idx / fps
            t0 = time.monotonic()
            tracks = tracker.detect_and_track(frame, ts)
            stats.inference_times.append(time.monotonic() - t0)
            fps_monitor.tick()

            detections = tracks_to_sv_detections(tracks)
            stats.frame_track_counts.append(len(tracks))
            for track in tracks:
                tid = track.track_id
                stats.unique_ids.add(tid)
                if tid not in stats.id_history:
                    stats.id_history[tid] = []
                    stats.id_first_seen[tid] = frame_idx
                stats.id_history[tid].append(frame_idx)
                stats.id_last_seen[tid] = frame_idx

            annotated = frame.copy()
            if len(detections.xyxy) > 0:
                labels = [f"ID:{int(tid)}" for tid in detections.tracker_id]
                annotated = trace_annotator.annotate(scene=annotated, detections=detections)
                annotated = box_annotator.annotate(scene=annotated, detections=detections)
                annotated = label_annotator.annotate(
                    scene=annotated, detections=detections, labels=labels
                )

            if zone_analytics is not None:
                zone_analytics.update(detections)
                annotated = zone_analytics.annotate(annotated, detections)

            reid_info = ""
            if hasattr(tracker, "reid_stats"):
                rs = tracker.reid_stats
                if rs["enabled"]:
                    skip_pct = (rs["skips"] / max(rs["extractions"] + rs["skips"], 1)) * 100
                    reid_info = f"  ReID remaps={rs['remaps']} skip={skip_pct:.0f}%"
                    stats.reid_recoveries = rs["remaps"]

            cv2.putText(
                annotated,
                f"[{label}] F{frame_idx}  {stats.inference_times[-1]*1000:.0f}ms"
                f"  IDs:{len(stats.unique_ids)}{reid_info}",
                (10, 25),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.55,
                (0, 255, 0),
                1,
            )

            if sink is not None:
                sink.write_frame(annotated)

            if frame_idx > 0 and frame_idx % 100 == 0:
                print(
                    f"    [{frame_idx}/{video_info.total_frames}]"
                    f" {fps_monitor.fps:.1f} FPS, {len(stats.unique_ids)} IDs"
                )

            stats.total_frames = frame_idx + 1

    if write_video and output_path is not None:
        with sv.VideoSink(str(output_path), video_info=video_info) as sink:
            _run(sink)
    else:
        _run(None)

    stats.wall_time = time.monotonic() - t_start
    stats.fragmentation, stats.avg_gap = _compute_fragmentation(stats.id_history)
    if zone_analytics is not None:
        stats.zone_counts = {
            "line": zone_analytics.report.line_counts,
            "polygon_occupancy": zone_analytics.report.polygon_occupancy,
            "polygon_dwell": zone_analytics.report.polygon_dwell,
        }
    return stats


def print_comparison(*all_stats: BenchmarkStats, baseline_unique_ids: int | None = None):
    def avg_ms(s: BenchmarkStats) -> float:
        return np.mean(s.inference_times) * 1000 if s.inference_times else 0

    def p95_ms(s: BenchmarkStats) -> float:
        return p95_frame_latency_ms(s.inference_times)

    def count_long(s: BenchmarkStats) -> int:
        return count_long_tracks(s.id_history)

    def count_short(s: BenchmarkStats) -> int:
        return count_short_tracks(s.id_history)

    def avg_len(s: BenchmarkStats) -> float:
        return average_track_length(s.id_history)

    def avg_people(s: BenchmarkStats) -> float:
        return average_people_per_frame(s.frame_track_counts)

    def short_ratio(s: BenchmarkStats) -> float:
        return short_track_ratio(s.id_history)

    col_w = 18
    header_names = [s.name for s in all_stats]

    print(f"\n{'=' * 80}")
    print(f"{'COMPARISON REPORT':^80}")
    print(f"{'=' * 80}")

    header = f"  {'Metric':<30}" + "".join(f" {n:>{col_w}}" for n in header_names)
    print(header)
    print(f"  {'-' * 30}" + (" " + "-" * col_w) * len(all_stats))

    def row(label: str, values: list[str]):
        print(f"  {label:<30}" + "".join(f" {v:>{col_w}}" for v in values))

    row("Frames", [str(s.total_frames) for s in all_stats])
    row("Wall time (s)", [f"{s.wall_time:.1f}" for s in all_stats])
    row("Avg inference (ms)", [f"{avg_ms(s):.1f}" for s in all_stats])
    row("P95 inference (ms)", [f"{p95_ms(s):.1f}" for s in all_stats])
    row("Avg people / frame", [f"{avg_people(s):.2f}" for s in all_stats])
    row("Unique IDs (LOWER=BETTER)", [str(len(s.unique_ids)) for s in all_stats])
    row("Short-track ratio", [f"{short_ratio(s) * 100:.1f}%" for s in all_stats])
    row("Long tracks (>30f)", [str(count_long(s)) for s in all_stats])
    row("Short tracks (<10f)", [str(count_short(s)) for s in all_stats])
    row("Avg track length", [f"{avg_len(s):.1f}" for s in all_stats])
    row("Fragmentation breaks", [str(s.fragmentation) for s in all_stats])
    row("Avg break gap", [f"{s.avg_gap:.1f}" for s in all_stats])
    row(
        "Re-ID recoveries",
        [str(s.reid_recoveries) if s.reid_recoveries else "N/A" for s in all_stats],
    )
    row("Composite score", [f"{s.score:.4f}" for s in all_stats])

    # Zone analytics section (only if at least one run has zone data)
    all_zone_counts = [s.zone_counts for s in all_stats if s.zone_counts]
    if all_zone_counts:
        print()
        print(f"  {'Zone Analytics':^{30 + (col_w + 1) * len(all_stats)}}")
        print(f"  {'-' * 30}" + (" " + "-" * col_w) * len(all_stats))
        ref = all_zone_counts[0]
        for zone_name, counts in ref.get("line", {}).items():
            row(
                f"  {zone_name} IN",
                [str(s.zone_counts.get("line", {}).get(zone_name, {}).get("in", "-"))
                 for s in all_stats],
            )
            row(
                f"  {zone_name} OUT",
                [str(s.zone_counts.get("line", {}).get(zone_name, {}).get("out", "-"))
                 for s in all_stats],
            )
        for zone_name in ref.get("polygon_dwell", {}):
            row(
                f"  {zone_name} dwell(frames)",
                [str(s.zone_counts.get("polygon_dwell", {}).get(zone_name, "-"))
                 for s in all_stats],
            )

    baseline_ids = baseline_unique_ids or (len(all_stats[0].unique_ids) if all_stats else 1)
    print()
    for s in all_stats[1:]:
        red = (1 - len(s.unique_ids) / max(baseline_ids, 1)) * 100
        print(
            f"  {s.name} vs Baseline: ID reduction={red:+.1f}%  "
            f"Avg track len delta={avg_len(s) - avg_len(all_stats[0]):+.1f}f  "
            f"Frag delta={s.fragmentation - all_stats[0].fragmentation:+d}"
        )

    print(f"{'=' * 80}\n")


if __name__ == "__main__":
    benchmark_dir = Path(__file__).parent
    video_path = benchmark_dir / "test_people.mp4"

    if not download_test_video(video_path):
        sys.exit(1)

    _zones_yaml = benchmark_dir / "zones.yaml"
    _video_stem = video_path.stem

    common_kwargs = {
        "model_path": "yolo11n-seg.pt",
        "confidence_threshold": 0.35,
        "tracker": "botsort.yaml",
        "class_whitelist": ["person"],
        "device": "",
        "kalman_config": KalmanCAConfig(),
    }

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
            {
                "match_threshold": 0.30,
                "match_threshold_relaxed": 0.24,
                "cascade_recent_s": 1.5,
                "second_best_margin": 0.03,
                "spatial_gate_px": 380.0,
                "spatial_gate_grow_rate": 180.0,
                "appearance_weight": 0.55,
                "motion_weight": 0.30,
                "iou_weight": 0.15,
                "min_fused_score": 0.30,
                "da_alpha_fixed": 0.95,
                "da_confidence_sigma": 0.40,
                "aw_epsilon": 0.5,
                "aw_base_weight": 0.55,
                "ocm_window": 5,
            },
        ),
        (
            "paper-strong-da",
            {
                "match_threshold": 0.30,
                "match_threshold_relaxed": 0.24,
                "cascade_recent_s": 1.5,
                "second_best_margin": 0.03,
                "spatial_gate_px": 380.0,
                "spatial_gate_grow_rate": 180.0,
                "appearance_weight": 0.55,
                "motion_weight": 0.30,
                "iou_weight": 0.15,
                "min_fused_score": 0.30,
                "da_alpha_fixed": 0.92,
                "da_confidence_sigma": 0.45,
                "aw_epsilon": 0.5,
                "aw_base_weight": 0.55,
                "ocm_window": 5,
            },
        ),
        (
            "paper-strong-aw",
            {
                "match_threshold": 0.28,
                "match_threshold_relaxed": 0.22,
                "cascade_recent_s": 1.8,
                "second_best_margin": 0.03,
                "spatial_gate_px": 400.0,
                "spatial_gate_grow_rate": 200.0,
                "appearance_weight": 0.55,
                "motion_weight": 0.30,
                "iou_weight": 0.15,
                "min_fused_score": 0.28,
                "da_alpha_fixed": 0.95,
                "da_confidence_sigma": 0.40,
                "aw_epsilon": 1.0,
                "aw_base_weight": 0.75,
                "ocm_window": 5,
            },
        ),
        (
            "paper-recall",
            {
                "match_threshold": 0.26,
                "match_threshold_relaxed": 0.20,
                "cascade_recent_s": 2.0,
                "second_best_margin": 0.02,
                "spatial_gate_px": 450.0,
                "spatial_gate_grow_rate": 220.0,
                "appearance_weight": 0.50,
                "motion_weight": 0.35,
                "iou_weight": 0.15,
                "min_fused_score": 0.24,
                "da_alpha_fixed": 0.95,
                "da_confidence_sigma": 0.40,
                "aw_epsilon": 0.5,
                "aw_base_weight": 0.55,
                "ocm_window": 7,
            },
        ),
        (
            "paper-precision",
            {
                "match_threshold": 0.34,
                "match_threshold_relaxed": 0.28,
                "cascade_recent_s": 1.2,
                "second_best_margin": 0.04,
                "spatial_gate_px": 320.0,
                "spatial_gate_grow_rate": 140.0,
                "appearance_weight": 0.62,
                "motion_weight": 0.25,
                "iou_weight": 0.13,
                "min_fused_score": 0.34,
                "da_alpha_fixed": 0.95,
                "da_confidence_sigma": 0.40,
                "aw_epsilon": 0.5,
                "aw_base_weight": 0.55,
                "ocm_window": 5,
            },
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
        zone_analytics=ZoneAnalytics.from_yaml(_zones_yaml, _video_stem),
    )
    stats_a.score = _composite_score(stats_a, baseline_unique_ids=len(stats_a.unique_ids))
    del tracker_a

    best_gallery_cfg = GalleryConfig(
        ema_alpha=0.85,
        max_lost_age=5.0,
        min_track_age_frames=3,
        **best_cfg,
    )

    tracker_b = YoloSegTracker(
        **common_kwargs,
        enable_reid=True,
        reid_config=ReIDConfig(device=""),
        gallery_config=best_gallery_cfg,
    )
    stats_b = run_single_test(
        video_path,
        output_path=benchmark_dir / "output_B_reid_best.mp4",
        tracker=tracker_b,
        label=f"B:{best_name}",
        max_frames=None,
        write_video=True,
        zone_analytics=ZoneAnalytics.from_yaml(_zones_yaml, _video_stem),
    )
    stats_b.score = _composite_score(stats_b, baseline_unique_ids=len(stats_a.unique_ids))
    del tracker_b

    # C: Re-ID + CMC (camera motion compensation)
    tracker_c = YoloSegTracker(
        **common_kwargs,
        enable_reid=True,
        enable_cmc=True,
        reid_config=ReIDConfig(device=""),
        gallery_config=GalleryConfig(
            ema_alpha=0.85,
            max_lost_age=5.0,
            min_track_age_frames=3,
            **best_cfg,
        ),
    )
    stats_c = run_single_test(
        video_path,
        output_path=benchmark_dir / "output_C_reid_cmc.mp4",
        tracker=tracker_c,
        label="C:ReID+CMC",
        max_frames=None,
        write_video=True,
        zone_analytics=ZoneAnalytics.from_yaml(_zones_yaml, _video_stem),
    )
    stats_c.score = _composite_score(stats_c, baseline_unique_ids=len(stats_a.unique_ids))

    print_comparison(stats_a, stats_b, stats_c, baseline_unique_ids=len(stats_a.unique_ids))

