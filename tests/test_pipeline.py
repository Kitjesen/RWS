"""Pipeline 完整单元测试。"""


import pytest

from src.rws_tracking.algebra import CameraModel, PixelToGimbalTransform
from src.rws_tracking.config import GimbalControllerConfig, PIDConfig
from src.rws_tracking.control import TwoAxisGimbalController
from src.rws_tracking.hardware import SimulatedGimbalDriver
from src.rws_tracking.perception import (
    PassthroughDetector,
    SimpleIoUTracker,
    WeightedTargetSelector,
)
from src.rws_tracking.pipeline.pipeline import PipelineOutputs, VisionGimbalPipeline
from src.rws_tracking.telemetry import InMemoryTelemetryLogger
from src.rws_tracking.types import BoundingBox, Detection

CAM = CameraModel(width=1280, height=720, fx=970.0, fy=965.0, cx=640.0, cy=360.0)


@pytest.fixture
def pipeline():
    pid = PIDConfig(kp=5.0, ki=0.3, kd=0.2)
    cfg = GimbalControllerConfig(yaw_pid=pid, pitch_pid=pid)
    transform = PixelToGimbalTransform(CAM)
    return VisionGimbalPipeline(
        detector=PassthroughDetector(),
        tracker=SimpleIoUTracker(),
        selector=WeightedTargetSelector(frame_width=1280, frame_height=720),
        controller=TwoAxisGimbalController(transform=transform, cfg=cfg),
        driver=SimulatedGimbalDriver(),
        telemetry=InMemoryTelemetryLogger(),
    )


def _inject(pipeline, dets):
    pipeline.detector.inject(dets)


class TestPipelineBasic:
    def test_step_no_detections(self, pipeline):
        output = pipeline.step(None, 0.0)
        assert isinstance(output, PipelineOutputs)
        assert output.command is not None

    def test_step_with_detection(self, pipeline):
        dets = [Detection(
            bbox=BoundingBox(x=600, y=300, w=80, h=150),
            confidence=0.9, class_id="person",
        )]
        _inject(pipeline, dets)
        output = pipeline.step(None, 0.0)
        assert output.selected_target is not None or output.command is not None

    def test_multiple_steps(self, pipeline):
        for i in range(10):
            dets = [Detection(
                bbox=BoundingBox(x=600 + i, y=300, w=80, h=150),
                confidence=0.9, class_id="person",
            )]
            _inject(pipeline, dets)
            output = pipeline.step(None, i * 0.033)
        assert output is not None

    def test_telemetry_logged(self, pipeline):
        dets = [Detection(
            bbox=BoundingBox(x=600, y=300, w=80, h=150),
            confidence=0.9, class_id="person",
        )]
        _inject(pipeline, dets)
        pipeline.step(None, 0.0)
        assert len(pipeline.telemetry.events) > 0


class TestPipelineSignals:
    def test_should_stop_default(self, pipeline):
        assert not pipeline.should_stop()

    def test_stop(self, pipeline):
        pipeline.stop()
        assert pipeline.should_stop()


class TestPipelineOutputs:
    def test_fields(self):
        from src.rws_tracking.types import ControlCommand
        out = PipelineOutputs(
            command=ControlCommand(yaw_rate_cmd_dps=0.0, pitch_rate_cmd_dps=0.0),
            selected_target=None,
            detections=[],
            tracks=[],
        )
        assert out.command is not None
        assert out.selected_target is None


class TestPipelineWithExtensions:
    def test_with_safety_manager(self):
        pid = PIDConfig(kp=5.0, ki=0.3, kd=0.2)
        cfg = GimbalControllerConfig(yaw_pid=pid, pitch_pid=pid)
        transform = PixelToGimbalTransform(CAM)

        from src.rws_tracking.safety.manager import SafetyManager, SafetyManagerConfig
        sm = SafetyManager(SafetyManagerConfig())

        p = VisionGimbalPipeline(
            detector=PassthroughDetector(),
            tracker=SimpleIoUTracker(),
            selector=WeightedTargetSelector(frame_width=1280, frame_height=720),
            controller=TwoAxisGimbalController(transform=transform, cfg=cfg),
            driver=SimulatedGimbalDriver(),
            telemetry=InMemoryTelemetryLogger(),
            safety_manager=sm,
        )
        output = p.step(None, 0.0)
        assert output is not None

    def test_with_trajectory_planner(self):
        pid = PIDConfig(kp=5.0, ki=0.3, kd=0.2)
        cfg = GimbalControllerConfig(yaw_pid=pid, pitch_pid=pid)
        transform = PixelToGimbalTransform(CAM)

        from src.rws_tracking.control.trajectory import GimbalTrajectoryPlanner
        tp = GimbalTrajectoryPlanner()

        p = VisionGimbalPipeline(
            detector=PassthroughDetector(),
            tracker=SimpleIoUTracker(),
            selector=WeightedTargetSelector(frame_width=1280, frame_height=720),
            controller=TwoAxisGimbalController(transform=transform, cfg=cfg),
            driver=SimulatedGimbalDriver(),
            telemetry=InMemoryTelemetryLogger(),
            trajectory_planner=tp,
        )
        dets = [Detection(
            bbox=BoundingBox(x=600, y=300, w=80, h=150),
            confidence=0.9, class_id="person",
        )]
        p.detector.inject(dets)
        output = p.step(None, 0.0)
        assert output is not None
