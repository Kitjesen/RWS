"""
rws_tracking - Vision-Gimbal Tracking System
=============================================

Sub-packages:
    algebra/     - Camera model, distortion, mount extrinsics, coordinate transforms.
    perception/  - Detection (YOLO), tracking, target selection.
    decision/    - Track state machine (Search/Track/Lock/Lost).
    control/     - PID controller, gimbal command computation.
    hardware/    - Gimbal driver abstraction.
    telemetry/   - Event logging and metrics.
    pipeline/    - End-to-end orchestration and demo entry points.
    tools/       - Simulation, tuning, replay utilities.
"""

from .algebra import CameraModel, DistortionCoeffs, MountExtrinsics, PixelToGimbalTransform
from .config import default_controller_config
from .control import TwoAxisGimbalController
from .decision import TrackState
from .hardware import SimulatedGimbalDriver
from .perception import PassthroughDetector, SimpleIoUTracker, WeightedTargetSelector
from .pipeline import VisionGimbalPipeline, run_camera_demo, run_demo
from .telemetry import InMemoryTelemetryLogger

__all__ = [
    "CameraModel",
    "DistortionCoeffs",
    "InMemoryTelemetryLogger",
    "MountExtrinsics",
    "PassthroughDetector",
    "PixelToGimbalTransform",
    "SimpleIoUTracker",
    "SimulatedGimbalDriver",
    "TrackState",
    "TwoAxisGimbalController",
    "VisionGimbalPipeline",
    "WeightedTargetSelector",
    "default_controller_config",
    "run_camera_demo",
    "run_demo",
]
