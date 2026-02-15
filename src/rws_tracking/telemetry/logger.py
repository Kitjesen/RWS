"""Event logger and metrics snapshot."""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from pathlib import Path
from types import TracebackType


@dataclass
class EventRecord:
    event_type: str
    timestamp: float
    payload: dict[str, float]


@dataclass
class InMemoryTelemetryLogger:
    events: list[EventRecord] = field(default_factory=list)
    max_events: int | None = None  # None = unlimited, int = ring buffer
    # Incremental counters for O(1) metrics
    _control_count: int = field(default=0, repr=False)
    _lock_count: int = field(default=0, repr=False)
    _error_sum: float = field(default=0.0, repr=False)
    _switch_count: int = field(default=0, repr=False)
    _first_control_ts: float = field(default=0.0, repr=False)
    _last_control_ts: float = field(default=0.0, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def log(self, event_type: str, timestamp: float, payload: dict[str, float]) -> None:
        with self._lock:
            self.events.append(
                EventRecord(event_type=event_type, timestamp=timestamp, payload=payload)
            )

            # Ring buffer: drop oldest events if exceeding max_events
            if self.max_events is not None and len(self.events) > self.max_events:
                self.events.pop(0)

            if event_type == "control":
                if self._control_count == 0:
                    self._first_control_ts = timestamp
                self._last_control_ts = timestamp
                self._control_count += 1
                if payload.get("state") == 2.0:
                    self._lock_count += 1
                self._error_sum += max(
                    abs(payload.get("yaw_error_deg", 0.0)),
                    abs(payload.get("pitch_error_deg", 0.0)),
                )
            elif event_type == "switch":
                self._switch_count += 1

    def snapshot_metrics(self) -> dict[str, float]:
        with self._lock:
            if self._control_count == 0:
                return {"lock_rate": 0.0, "avg_abs_error_deg": 0.0, "switches_per_min": 0.0}
            span = max(self._last_control_ts - self._first_control_ts, 1e-3)
            return {
                "lock_rate": self._lock_count / self._control_count,
                "avg_abs_error_deg": self._error_sum / self._control_count,
                "switches_per_min": self._switch_count * 60.0 / span,
            }

    def export_jsonl(self) -> str:
        with self._lock:
            return "\n".join(
                json.dumps(
                    {"event_type": e.event_type, "timestamp": e.timestamp, "payload": e.payload},
                    ensure_ascii=True,
                )
                for e in self.events
            )


class FileTelemetryLogger:
    """实时写入 JSONL 文件的遥测日志器

    特点：
    - 每个事件立即写入磁盘（flush），适合长时间运行
    - 不占用内存（不缓存事件列表）
    - 支持追加模式，可以续写已有日志
    - 线程安全（内部加锁）
    """

    def __init__(self, file_path: str | Path, append: bool = False) -> None:
        self.file_path = Path(file_path)
        mode = "a" if append else "w"
        self._file = open(self.file_path, mode, encoding="utf-8")
        self._lock = threading.Lock()
        self._closed = False

        # Metrics counters (same as InMemoryTelemetryLogger)
        self._control_count = 0
        self._lock_count = 0
        self._error_sum = 0.0
        self._switch_count = 0
        self._first_control_ts = 0.0
        self._last_control_ts = 0.0

    def log(self, event_type: str, timestamp: float, payload: dict[str, float]) -> None:
        with self._lock:
            if self._closed:
                return
            record = {"event_type": event_type, "timestamp": timestamp, "payload": payload}
            self._file.write(json.dumps(record, ensure_ascii=True) + "\n")
            self._file.flush()  # 立即写入磁盘

            # Update metrics
            if event_type == "control":
                if self._control_count == 0:
                    self._first_control_ts = timestamp
                self._last_control_ts = timestamp
                self._control_count += 1
                if payload.get("state") == 2.0:
                    self._lock_count += 1
                self._error_sum += max(
                    abs(payload.get("yaw_error_deg", 0.0)),
                    abs(payload.get("pitch_error_deg", 0.0)),
                )
            elif event_type == "switch":
                self._switch_count += 1

    def snapshot_metrics(self) -> dict[str, float]:
        with self._lock:
            if self._control_count == 0:
                return {"lock_rate": 0.0, "avg_abs_error_deg": 0.0, "switches_per_min": 0.0}
            span = max(self._last_control_ts - self._first_control_ts, 1e-3)
            return {
                "lock_rate": self._lock_count / self._control_count,
                "avg_abs_error_deg": self._error_sum / self._control_count,
                "switches_per_min": self._switch_count * 60.0 / span,
            }

    def close(self) -> None:
        """关闭文件句柄"""
        with self._lock:
            if not self._closed and hasattr(self, "_file") and self._file:
                self._file.close()
                self._closed = True

    def __enter__(self) -> FileTelemetryLogger:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> bool:
        self.close()
        return False
