from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Literal

logger = logging.getLogger(__name__)

SubsystemName = Literal[
    "camera", "gimbal_driver", "imu", "rangefinder", "safety", "api"
]


@dataclass
class SubsystemStatus:
    name: str
    status: str = "unknown"  # "ok" | "degraded" | "failed" | "unknown"
    last_heartbeat_ts: float = 0.0
    error_message: str = ""
    heartbeat_timeout_s: float = 2.0

    @property
    def age_s(self) -> float:
        if self.last_heartbeat_ts > 0:
            return time.monotonic() - self.last_heartbeat_ts
        return float("inf")

    def compute_status(self) -> str:
        if self.last_heartbeat_ts == 0.0:
            return "unknown"
        age = self.age_s
        if age > self.heartbeat_timeout_s * 3:
            return "failed"
        if age > self.heartbeat_timeout_s:
            return "degraded"
        return "ok"


class HealthMonitor:
    """Tracks liveness of hardware and software subsystems.

    Usage:
        monitor = HealthMonitor()
        # In camera read loop:
        monitor.heartbeat("camera", timestamp)
        # In serial driver:
        monitor.heartbeat("gimbal_driver", timestamp)
        # Check health:
        if not monitor.is_healthy():
            handle_degraded(monitor.get_failed())
    """

    _DEFAULT_TIMEOUTS: dict[str, float] = {
        "camera": 1.0,
        "gimbal_driver": 0.5,
        "imu": 1.0,
        "rangefinder": 2.0,
        "safety": 2.0,
        "api": 5.0,
    }

    def __init__(self, timeouts: dict[str, float] | None = None):
        merged = {**self._DEFAULT_TIMEOUTS, **(timeouts or {})}
        self._subsystems: dict[str, SubsystemStatus] = {
            name: SubsystemStatus(name=name, heartbeat_timeout_s=t)
            for name, t in merged.items()
        }

    def heartbeat(
        self, subsystem: str, timestamp: float | None = None,
    ) -> None:
        """Record a successful heartbeat for a subsystem."""
        ts = timestamp if timestamp is not None else time.monotonic()
        if subsystem not in self._subsystems:
            self._subsystems[subsystem] = SubsystemStatus(
                name=subsystem,
                heartbeat_timeout_s=self._DEFAULT_TIMEOUTS.get(
                    subsystem, 2.0
                ),
            )
        s = self._subsystems[subsystem]
        s.last_heartbeat_ts = ts
        s.error_message = ""

    def report_error(
        self, subsystem: str, error: str,
        timestamp: float | None = None,
    ) -> None:
        """Report an error for a subsystem."""
        if subsystem not in self._subsystems:
            self._subsystems[subsystem] = SubsystemStatus(
                name=subsystem,
                heartbeat_timeout_s=self._DEFAULT_TIMEOUTS.get(
                    subsystem, 2.0
                ),
            )
        s = self._subsystems[subsystem]
        s.error_message = error
        logger.warning("subsystem %s error: %s", subsystem, error)

    def get_status(self) -> dict[str, dict]:
        """Return status dict for all subsystems."""
        result = {}
        for name, s in self._subsystems.items():
            computed = s.compute_status()
            result[name] = {
                "status": computed,
                "last_heartbeat_age_s": (
                    round(s.age_s, 2)
                    if s.last_heartbeat_ts > 0
                    else None
                ),
                "error": s.error_message or None,
            }
        return result

    def is_healthy(self) -> bool:
        """True if all subsystems are ok or unknown."""
        return all(
            s.compute_status() in ("ok", "unknown")
            for s in self._subsystems.values()
        )

    def get_failed(self) -> list[str]:
        """Return names of failed or degraded subsystems."""
        return [
            name
            for name, s in self._subsystems.items()
            if s.compute_status() in ("failed", "degraded")
        ]

    def overall_status(self) -> str:
        """Returns 'ok', 'degraded', or 'failed'."""
        statuses = [
            s.compute_status() for s in self._subsystems.values()
        ]
        if "failed" in statuses:
            return "failed"
        if "degraded" in statuses:
            return "degraded"
        return "ok"
