"""
Log replay tool.

Load a JSONL telemetry export and replay events for offline analysis,
parameter comparison, or issue reproduction.

Usage:
    from rws_tracking.tools.replay import TelemetryReplay

    replay = TelemetryReplay.from_jsonl("session.jsonl")
    replay.print_summary()
    replay.compare_metrics(other_replay)
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from statistics import mean, stdev

from ..telemetry.logger import EventRecord


@dataclass
class TelemetryReplay:
    events: list[EventRecord] = field(default_factory=list)

    # ------------------------------------------------------------------
    # Load
    # ------------------------------------------------------------------

    @classmethod
    def from_jsonl(cls, path: str | Path) -> TelemetryReplay:
        """Load events from a JSONL file exported by InMemoryTelemetryLogger."""
        events: list[EventRecord] = []
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                d = json.loads(line)
                events.append(
                    EventRecord(
                        event_type=d["event_type"],
                        timestamp=d["timestamp"],
                        payload=d["payload"],
                    )
                )
        return cls(events=events)

    @classmethod
    def from_logger(cls, logger: object) -> TelemetryReplay:
        """Create replay directly from an InMemoryTelemetryLogger."""
        return cls(events=list(getattr(logger, "events", [])))

    # ------------------------------------------------------------------
    # Analysis
    # ------------------------------------------------------------------

    def control_events(self) -> list[EventRecord]:
        return [e for e in self.events if e.event_type == "control"]

    def switch_events(self) -> list[EventRecord]:
        return [e for e in self.events if e.event_type == "switch"]

    def metrics(self) -> dict[str, float]:
        controls = self.control_events()
        switches = self.switch_events()
        if not controls:
            return {
                "lock_rate": 0.0,
                "avg_abs_error_deg": 0.0,
                "p95_abs_error_deg": 0.0,
                "switches_per_min": 0.0,
                "error_stdev_deg": 0.0,
            }

        abs_errors = sorted(
            max(
                abs(e.payload.get("yaw_error_deg", 0.0)), abs(e.payload.get("pitch_error_deg", 0.0))
            )
            for e in controls
        )
        lock_count = sum(1 for e in controls if e.payload.get("state") == 2.0)
        span = max(controls[-1].timestamp - controls[0].timestamp, 1e-3)
        p95_idx = int(len(abs_errors) * 0.95)

        return {
            "lock_rate": lock_count / len(controls),
            "avg_abs_error_deg": mean(abs_errors),
            "p95_abs_error_deg": abs_errors[min(p95_idx, len(abs_errors) - 1)],
            "error_stdev_deg": stdev(abs_errors) if len(abs_errors) > 1 else 0.0,
            "switches_per_min": len(switches) * 60.0 / span,
            "total_control_events": float(len(controls)),
            "duration_s": span,
        }

    def print_summary(self) -> None:
        m = self.metrics()
        print("=" * 50)
        print("  Telemetry Replay Summary")
        print("=" * 50)
        for k, v in m.items():
            print(f"  {k:30s}: {v:.4f}")
        print("=" * 50)

    def compare_metrics(self, other: TelemetryReplay) -> None:
        """Print side-by-side comparison of two replay sessions."""
        m1 = self.metrics()
        m2 = other.metrics()
        print(f"{'Metric':30s} {'Session A':>12s} {'Session B':>12s} {'Delta':>10s}")
        print("-" * 66)
        for k in m1:
            a, b = m1.get(k, 0.0), m2.get(k, 0.0)
            delta = b - a
            print(f"  {k:28s} {a:12.4f} {b:12.4f} {delta:+10.4f}")

    # ------------------------------------------------------------------
    # Extract time series for plotting
    # ------------------------------------------------------------------

    def error_time_series(self) -> dict[str, list[float]]:
        """Return dict with 'time', 'yaw_error', 'pitch_error' lists."""
        controls = self.control_events()
        return {
            "time": [e.timestamp for e in controls],
            "yaw_error": [e.payload.get("yaw_error_deg", 0.0) for e in controls],
            "pitch_error": [e.payload.get("pitch_error_deg", 0.0) for e in controls],
            "state": [e.payload.get("state", 0.0) for e in controls],
        }
