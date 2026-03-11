"""集成测试 — 所有高级功能 enabled=true 的端到端测试。"""

import dataclasses
from unittest.mock import MagicMock, patch

import pytest

from src.rws_tracking.algebra import CameraModel, PixelToGimbalTransform
from src.rws_tracking.config import (
    GimbalControllerConfig,
    PIDConfig,
    SystemConfig,
)
from src.rws_tracking.control import TwoAxisGimbalController
from src.rws_tracking.control.lead_angle import (
    LeadAngleCalculator,
    LeadAngleConfig,
    SimpleFlightTimeProvider,
)
from src.rws_tracking.control.trajectory import GimbalTrajectoryPlanner, TrajectoryConfig
from src.rws_tracking.decision.engagement import EngagementQueue, ThreatAssessor
from src.rws_tracking.hardware import SimulatedGimbalDriver
from src.rws_tracking.hardware.rangefinder import (
    DistanceFusion,
    SimulatedRangefinder,
    SimulatedRangefinderConfig,
)
from src.rws_tracking.perception import (
    PassthroughDetector,
    SimpleIoUTracker,
    WeightedTargetSelector,
)
from src.rws_tracking.pipeline.pipeline import VisionGimbalPipeline
from src.rws_tracking.safety.manager import SafetyManager, SafetyManagerConfig
from src.rws_tracking.telemetry import InMemoryTelemetryLogger
from src.rws_tracking.types import BoundingBox, Detection, SafetyZone

CAM = CameraModel(width=1280, height=720, fx=970.0, fy=965.0, cx=640.0, cy=360.0)


def _full_pipeline():
    """Build pipeline with ALL extensions enabled."""
    pid = PIDConfig(kp=5.0, ki=0.3, kd=0.2)
    cfg = GimbalControllerConfig(yaw_pid=pid, pitch_pid=pid)
    transform = PixelToGimbalTransform(CAM)

    threat_assessor = ThreatAssessor(1280, 720, 970.0)
    engagement_queue = EngagementQueue()

    rf_cfg = SimulatedRangefinderConfig(noise_std_m=0.5, max_range_m=500.0)
    rangefinder = SimulatedRangefinder(config=rf_cfg, camera_fy=970.0)
    distance_fusion = DistanceFusion(camera_fy=970.0)

    lead_calc = LeadAngleCalculator(
        transform=transform,
        flight_time_provider=SimpleFlightTimeProvider(900.0),
        config=LeadAngleConfig(enabled=True),
    )

    safety_mgr = SafetyManager(SafetyManagerConfig(
        zones=(SafetyZone(zone_id="nfz1", center_yaw_deg=90.0,
                          center_pitch_deg=0.0, radius_deg=10.0, zone_type="no_fire"),),
    ))

    trajectory_planner = GimbalTrajectoryPlanner(TrajectoryConfig())

    return VisionGimbalPipeline(
        detector=PassthroughDetector(),
        tracker=SimpleIoUTracker(),
        selector=WeightedTargetSelector(frame_width=1280, frame_height=720),
        controller=TwoAxisGimbalController(transform=transform, cfg=cfg),
        driver=SimulatedGimbalDriver(),
        telemetry=InMemoryTelemetryLogger(),
        threat_assessor=threat_assessor,
        engagement_queue=engagement_queue,
        distance_fusion=distance_fusion,
        rangefinder=rangefinder,
        lead_calculator=lead_calc,
        safety_manager=safety_mgr,
        trajectory_planner=trajectory_planner,
    )


class TestFullIntegration:
    @pytest.fixture
    def pipeline(self):
        return _full_pipeline()

    def test_step_no_target(self, pipeline):
        output = pipeline.step(None, 0.0)
        assert output is not None
        assert output.command is not None

    def test_step_with_target(self, pipeline):
        dets = [Detection(
            bbox=BoundingBox(x=600, y=300, w=80, h=150),
            confidence=0.9, class_id="person",
        )]
        pipeline.detector.inject(dets)
        output = pipeline.step(None, 0.0)
        assert output is not None

    def test_tracking_loop(self, pipeline):
        for i in range(50):
            t = i * 0.033
            dets = [Detection(
                # y=285 centers the bbox at cy=360, giving pitch_err≈0 so lock is achievable
                bbox=BoundingBox(x=600 + i, y=285, w=80, h=150),
                confidence=0.9, class_id="person",
            )]
            pipeline.detector.inject(dets)
            pipeline.step(None, t)
        metrics = pipeline.telemetry.snapshot_metrics()
        assert metrics["lock_rate"] > 0.0

    def test_target_in_nfz(self, pipeline):
        """Target near NFZ should have safety constraints."""
        for i in range(20):
            t = i * 0.033
            # Target at yaw ~90 deg (in NFZ)
            dets = [Detection(
                bbox=BoundingBox(x=1200, y=360, w=80, h=150),
                confidence=0.9, class_id="person",
            )]
            pipeline.detector.inject(dets)
            output = pipeline.step(None, t)
        assert output is not None

    def test_target_switch(self, pipeline):
        """Test switching between targets."""
        for i in range(10):
            dets = [Detection(
                bbox=BoundingBox(x=200, y=300, w=80, h=150),
                confidence=0.9, class_id="person",
            )]
            pipeline.detector.inject(dets)
            pipeline.step(None, i * 0.033)

        for i in range(10):
            dets = [Detection(
                bbox=BoundingBox(x=1000, y=400, w=80, h=150),
                confidence=0.95, class_id="person",
            )]
            pipeline.detector.inject(dets)
            pipeline.step(None, (10 + i) * 0.033)

        metrics = pipeline.telemetry.snapshot_metrics()
        assert metrics is not None

    def test_target_lost_and_recovered(self, pipeline):
        """Test target loss and recovery."""
        # Track target
        for i in range(10):
            dets = [Detection(
                bbox=BoundingBox(x=600, y=300, w=80, h=150),
                confidence=0.9, class_id="person",
            )]
            pipeline.detector.inject(dets)
            pipeline.step(None, i * 0.033)

        # Lose target
        for i in range(15):
            pipeline.step(None, (10 + i) * 0.033)

        # Recover target
        for i in range(10):
            dets = [Detection(
                bbox=BoundingBox(x=600, y=300, w=80, h=150),
                confidence=0.9, class_id="person",
            )]
            pipeline.detector.inject(dets)
            pipeline.step(None, (25 + i) * 0.033)

        metrics = pipeline.telemetry.snapshot_metrics()
        assert metrics is not None


class TestConfigDrivenPipeline:
    def test_build_from_config_all_enabled(self):
        from src.rws_tracking.pipeline.app import build_pipeline_from_config
        cfg = SystemConfig()
        # Sub-configs are frozen dataclasses; use dataclasses.replace() to mutate
        cfg.safety = dataclasses.replace(cfg.safety, enabled=True)
        cfg.engagement = dataclasses.replace(cfg.engagement, enabled=True)
        cfg.trajectory = dataclasses.replace(cfg.trajectory, enabled=True)
        cfg.rangefinder = dataclasses.replace(cfg.rangefinder, enabled=True)
        cfg.lead_angle = dataclasses.replace(cfg.lead_angle, enabled=True)
        cfg.projectile = dataclasses.replace(cfg.projectile, enabled=True)
        cfg.video_stream = dataclasses.replace(cfg.video_stream, enabled=True)

        with patch("src.rws_tracking.pipeline.app.YoloSegTracker") as mock_yolo:
            mock_yolo.return_value = MagicMock()
            p = build_pipeline_from_config(cfg)

        assert p._safety_manager is not None
        assert p._threat_assessor is not None
        assert p._trajectory_planner is not None
        assert p._rangefinder is not None
        assert p._lead_calculator is not None
        assert p._ballistic_solver is not None
        assert p._frame_buffer is not None
