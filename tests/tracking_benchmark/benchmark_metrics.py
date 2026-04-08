from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import numpy as np

SHORT_TRACK_THRESHOLD = 10
LONG_TRACK_THRESHOLD = 30


@dataclass(frozen=True)
class TrackMetricsSummary:
    name: str
    total_frames: int
    average_people_per_frame: float
    unique_ids: int
    short_track_count: int
    short_track_ratio: float
    long_track_count: int
    average_track_length: float
    fragmentation_breaks: int
    average_fragment_gap: float
    average_frame_latency_ms: float
    p95_frame_latency_ms: float
    average_fps: float


def compute_fragmentation(id_history: dict[int, list[int]]) -> tuple[int, float]:
    gaps: list[int] = []
    for frames in id_history.values():
        if len(frames) < 2:
            continue
        for idx in range(1, len(frames)):
            gap = frames[idx] - frames[idx - 1]
            if gap > 1:
                gaps.append(gap)
    if not gaps:
        return 0, 0.0
    return len(gaps), float(np.mean(gaps))


def average_people_per_frame(frame_track_counts: Iterable[int]) -> float:
    counts = [int(count) for count in frame_track_counts]
    return float(np.mean(counts)) if counts else 0.0


def count_short_tracks(id_history: dict[int, list[int]], threshold: int = SHORT_TRACK_THRESHOLD) -> int:
    return sum(1 for frames in id_history.values() if len(frames) <= threshold)


def short_track_ratio(id_history: dict[int, list[int]], threshold: int = SHORT_TRACK_THRESHOLD) -> float:
    total = len(id_history)
    if total == 0:
        return 0.0
    return count_short_tracks(id_history, threshold=threshold) / total


def count_long_tracks(id_history: dict[int, list[int]], threshold: int = LONG_TRACK_THRESHOLD) -> int:
    return sum(1 for frames in id_history.values() if len(frames) >= threshold)


def average_track_length(id_history: dict[int, list[int]]) -> float:
    if not id_history:
        return 0.0
    return float(np.mean([len(frames) for frames in id_history.values()]))


def average_frame_latency_ms(inference_times: Iterable[float]) -> float:
    times = [float(value) for value in inference_times]
    return float(np.mean(times) * 1000.0) if times else 0.0


def p95_frame_latency_ms(inference_times: Iterable[float]) -> float:
    times = [float(value) for value in inference_times]
    return float(np.percentile(times, 95) * 1000.0) if times else 0.0


def average_fps(total_frames: int, wall_time_s: float) -> float:
    if total_frames <= 0 or wall_time_s <= 0.0:
        return 0.0
    return float(total_frames / wall_time_s)


def summarize_tracking_run(
    name: str,
    total_frames: int,
    frame_track_counts: Iterable[int],
    inference_times: Iterable[float],
    id_history: dict[int, list[int]],
    wall_time_s: float,
) -> TrackMetricsSummary:
    fragmentation_breaks, average_fragment_gap = compute_fragmentation(id_history)
    return TrackMetricsSummary(
        name=name,
        total_frames=int(total_frames),
        average_people_per_frame=average_people_per_frame(frame_track_counts),
        unique_ids=len(id_history),
        short_track_count=count_short_tracks(id_history),
        short_track_ratio=short_track_ratio(id_history),
        long_track_count=count_long_tracks(id_history),
        average_track_length=average_track_length(id_history),
        fragmentation_breaks=fragmentation_breaks,
        average_fragment_gap=average_fragment_gap,
        average_frame_latency_ms=average_frame_latency_ms(inference_times),
        p95_frame_latency_ms=p95_frame_latency_ms(inference_times),
        average_fps=average_fps(total_frames, wall_time_s),
    )


def markdown_comparison_table(summaries: list[TrackMetricsSummary]) -> str:
    lines = [
        '| Metric | ' + ' | '.join(summary.name for summary in summaries) + ' |',
        '| --- | ' + ' | '.join('---:' for _ in summaries) + ' |',
        '| Avg people / frame | ' + ' | '.join(f'{summary.average_people_per_frame:.2f}' for summary in summaries) + ' |',
        '| Unique IDs | ' + ' | '.join(str(summary.unique_ids) for summary in summaries) + ' |',
        '| Short-track ratio | ' + ' | '.join(f'{summary.short_track_ratio * 100:.1f}%' for summary in summaries) + ' |',
        '| Fragmentation breaks | ' + ' | '.join(str(summary.fragmentation_breaks) for summary in summaries) + ' |',
        '| Avg frame latency | ' + ' | '.join(f'{summary.average_frame_latency_ms:.1f} ms' for summary in summaries) + ' |',
        '| P95 frame latency | ' + ' | '.join(f'{summary.p95_frame_latency_ms:.1f} ms' for summary in summaries) + ' |',
        '| Avg FPS | ' + ' | '.join(f'{summary.average_fps:.2f}' for summary in summaries) + ' |',
        '| Avg track length | ' + ' | '.join(f'{summary.average_track_length:.1f}' for summary in summaries) + ' |',
        '| Long tracks (>=30f) | ' + ' | '.join(str(summary.long_track_count) for summary in summaries) + ' |',
    ]
    return '\n'.join(lines)