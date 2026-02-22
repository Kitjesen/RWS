"""PID baseline grid-search tuner."""

from __future__ import annotations

from dataclasses import replace
from itertools import product

from ..algebra import CameraModel, PixelToGimbalTransform
from ..config import GimbalControllerConfig, SelectorConfig
from ..control import TwoAxisGimbalController
from ..hardware import SimulatedGimbalDriver
from ..perception import PassthroughDetector, SimpleIoUTracker, WeightedTargetSelector
from ..pipeline.pipeline import VisionGimbalPipeline
from ..telemetry import InMemoryTelemetryLogger
from .simulation import SimTarget, SyntheticScene


def grid_search_pid(
    base_cfg: GimbalControllerConfig,
    camera: CameraModel,
    duration_s: float = 8.0,
    dt_s: float = 0.03,
) -> tuple[GimbalControllerConfig, float]:
    gains = [0.8, 1.0, 1.2]
    best_cfg = base_cfg
    best_score = float("inf")

    for kpk, kik, kdk in product(gains, gains, gains):
        cfg = replace(
            base_cfg,
            yaw_pid=replace(
                base_cfg.yaw_pid,
                kp=base_cfg.yaw_pid.kp * kpk,
                ki=base_cfg.yaw_pid.ki * kik,
                kd=base_cfg.yaw_pid.kd * kdk,
            ),
            pitch_pid=replace(
                base_cfg.pitch_pid,
                kp=base_cfg.pitch_pid.kp * kpk,
                ki=base_cfg.pitch_pid.ki * kik,
                kd=base_cfg.pitch_pid.kd * kdk,
            ),
        )
        score = _run_single_target_score(cfg, camera, duration_s, dt_s)
        if score < best_score:
            best_score = score
            best_cfg = cfg

    return best_cfg, best_score


def _run_single_target_score(
    cfg: GimbalControllerConfig, camera: CameraModel, duration_s: float, dt_s: float
) -> float:
    transform = PixelToGimbalTransform(camera)
    pipeline = VisionGimbalPipeline(
        detector=PassthroughDetector(),
        tracker=SimpleIoUTracker(),
        selector=WeightedTargetSelector(
            camera.width,
            camera.height,
            config=SelectorConfig(preferred_classes={"person": 1.0}),
        ),
        controller=TwoAxisGimbalController(transform=transform, cfg=cfg),
        driver=SimulatedGimbalDriver(),
        telemetry=InMemoryTelemetryLogger(),
    )

    scene = SyntheticScene(camera.width, camera.height, seed=7)
    scene.add_target(
        SimTarget(
            cx=100.0, cy=130.0, w=80.0, h=120.0, vx=45.0, vy=18.0, confidence=0.9, class_id="person"
        )
    )

    ts = 0.0
    while ts < duration_s:
        frame = scene.step(dt_s)
        pipeline.step(frame, ts)
        ts += dt_s
    return pipeline.telemetry.snapshot_metrics()["avg_abs_error_deg"]
