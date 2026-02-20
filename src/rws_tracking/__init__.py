"""
rws_tracking - Vision-Gimbal Tracking System
=============================================

Sub-packages:
    algebra/     - Camera model, distortion, mount extrinsics, coordinate transforms.
    perception/  - Detection (YOLO), tracking, target selection.
    decision/    - Track state machine (Search/Track/Lock/Lost),
                   threat assessment, engagement queue.
    control/     - PID controller, ballistic compensation, lead angle,
                   trajectory planning.
    hardware/    - Gimbal driver abstraction, rangefinder.
    safety/      - No-fire zones, safety interlocks.
    api/         - REST / gRPC server, video streaming.
    telemetry/   - Event logging and metrics.
    pipeline/    - End-to-end orchestration and demo entry points.
    tools/       - Simulation, tuning, replay utilities.
"""

from .algebra import CameraModel, DistortionCoeffs, MountExtrinsics, PixelToGimbalTransform
from .config import SystemConfig, default_controller_config, load_config
from .control import TwoAxisGimbalController
from .types import TrackState
from .hardware import SimulatedGimbalDriver
from .perception import PassthroughDetector, SimpleIoUTracker, WeightedTargetSelector
from .pipeline import VisionGimbalPipeline, run_camera_demo, run_demo
from .telemetry import InMemoryTelemetryLogger


def __getattr__(name: str):
    """Lazy imports for heavy / optional submodules."""
    _lazy = {
        "PhysicsBallisticModel": ".control.ballistic",
        "SimpleBallisticModel": ".control.ballistic",
        "TableBallisticModel": ".control.ballistic",
        "LeadAngleCalculator": ".control.lead_angle",
        "GimbalTrajectoryPlanner": ".control.trajectory",
        "ThreatAssessor": ".decision.engagement",
        "EngagementQueue": ".decision.engagement",
        "SimulatedRangefinder": ".hardware.rangefinder",
        "DistanceFusion": ".hardware.rangefinder",
        "SafetyManager": ".safety.manager",
        "build_pipeline_from_config": ".pipeline.app",
    }
    if name in _lazy:
        import importlib

        mod = importlib.import_module(_lazy[name], __package__)
        return getattr(mod, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
    # Algebra
    "CameraModel",
    "DistortionCoeffs",
    "MountExtrinsics",
    "PixelToGimbalTransform",
    # Config
    "SystemConfig",
    "default_controller_config",
    "load_config",
    # Control
    "TwoAxisGimbalController",
    "PhysicsBallisticModel",
    "SimpleBallisticModel",
    "TableBallisticModel",
    "LeadAngleCalculator",
    "GimbalTrajectoryPlanner",
    # Decision
    "TrackState",
    "ThreatAssessor",
    "EngagementQueue",
    # Hardware
    "SimulatedGimbalDriver",
    "SimulatedRangefinder",
    "DistanceFusion",
    # Safety
    "SafetyManager",
    # Perception
    "PassthroughDetector",
    "SimpleIoUTracker",
    "WeightedTargetSelector",
    # Pipeline
    "VisionGimbalPipeline",
    "build_pipeline_from_config",
    "run_camera_demo",
    "run_demo",
    # Telemetry
    "InMemoryTelemetryLogger",
]
