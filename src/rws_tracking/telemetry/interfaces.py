"""Telemetry layer interfaces -- implement these to swap logging backends."""
from __future__ import annotations

from typing import Dict, Protocol


class TelemetryLogger(Protocol):
    """
    Logs structured events.

    To implement your own (e.g. write to file, send to network, InfluxDB):
        1. Create a class with a ``log`` method matching this signature.
        2. Inject it into ``VisionGimbalPipeline`` via the ``telemetry`` parameter.
    """
    def log(self, event_type: str, timestamp: float, payload: Dict[str, float]) -> None:
        ...
