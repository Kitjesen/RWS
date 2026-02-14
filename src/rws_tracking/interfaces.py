"""
Re-export all layer interfaces for backward compatibility.

Prefer importing from each sub-package directly:
    from rws_tracking.hardware.interfaces import GimbalDriver
    from rws_tracking.control.interfaces import GimbalController
    from rws_tracking.perception.interfaces import Detector, Tracker, TargetSelector
    from rws_tracking.telemetry.interfaces import TelemetryLogger
"""
from .control.interfaces import GimbalController
from .hardware.interfaces import GimbalDriver
from .perception.interfaces import Detector, TargetSelector, Tracker
from .telemetry.interfaces import TelemetryLogger

__all__ = [
    "Detector",
    "GimbalController",
    "GimbalDriver",
    "TargetSelector",
    "TelemetryLogger",
    "Tracker",
]
