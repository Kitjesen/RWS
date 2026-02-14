"""
Unit tests for moving-base (robot dog body) compensation.
==========================================================

Validates:
  1. BodyState dataclass & defaults
  2. BodyMotionProvider mock implementations
  3. FullChainTransform coordinate chain
  4. Controller feedforward compensation (body_state=None → zero regression)
  5. Pipeline body_provider plumbing
"""
from __future__ import annotations

import math
import unittest

from src.rws_tracking.types import BodyState, GimbalFeedback, TargetObservation, BoundingBox
from src.rws_tracking.algebra import (
    CameraModel,
    FullChainTransform,
    MountExtrinsics,
    PixelToGimbalTransform,
)
from src.rws_tracking.hardware.mock_imu import (
    ReplayBodyMotion,
    SinusoidalBodyMotion,
    SinusoidalConfig,
    StaticBodyMotion,
)
from src.rws_tracking.config import default_controller_config
from src.rws_tracking.control import TwoAxisGimbalController


def _make_cam() -> CameraModel:
    return CameraModel(width=1280, height=720, fx=970.0, fy=965.0, cx=640.0, cy=360.0)


# ---------------------------------------------------------------------------
# BodyState tests
# ---------------------------------------------------------------------------

class BodyStateTests(unittest.TestCase):
    def test_defaults_are_zero(self) -> None:
        bs = BodyState(timestamp=1.0)
        self.assertEqual(bs.roll_deg, 0.0)
        self.assertEqual(bs.pitch_deg, 0.0)
        self.assertEqual(bs.yaw_deg, 0.0)
        self.assertEqual(bs.roll_rate_dps, 0.0)
        self.assertEqual(bs.pitch_rate_dps, 0.0)
        self.assertEqual(bs.yaw_rate_dps, 0.0)

    def test_timestamp_is_stored(self) -> None:
        bs = BodyState(timestamp=42.5, roll_deg=1.0, yaw_rate_dps=10.0)
        self.assertEqual(bs.timestamp, 42.5)
        self.assertEqual(bs.roll_deg, 1.0)
        self.assertEqual(bs.yaw_rate_dps, 10.0)


# ---------------------------------------------------------------------------
# Mock IMU tests
# ---------------------------------------------------------------------------

class StaticBodyMotionTests(unittest.TestCase):
    def test_always_zero(self) -> None:
        provider = StaticBodyMotion()
        bs = provider.get_body_state(5.0)
        self.assertEqual(bs.roll_deg, 0.0)
        self.assertEqual(bs.yaw_rate_dps, 0.0)
        self.assertEqual(bs.timestamp, 5.0)


class SinusoidalBodyMotionTests(unittest.TestCase):
    def test_zero_at_t0(self) -> None:
        provider = SinusoidalBodyMotion(t0=0.0)
        bs = provider.get_body_state(0.0)
        self.assertAlmostEqual(bs.roll_deg, 0.0, places=6)
        self.assertAlmostEqual(bs.pitch_deg, 0.0, places=6)
        self.assertAlmostEqual(bs.yaw_deg, 0.0, places=6)

    def test_nonzero_at_quarter_period(self) -> None:
        cfg = SinusoidalConfig(roll_amplitude_deg=3.0, roll_freq_hz=1.0)
        provider = SinusoidalBodyMotion(config=cfg, t0=0.0)
        bs = provider.get_body_state(0.25)  # quarter period of 1 Hz → sin(π/2)=1
        self.assertAlmostEqual(bs.roll_deg, 3.0, places=3)

    def test_rate_matches_analytical_derivative(self) -> None:
        cfg = SinusoidalConfig(yaw_amplitude_deg=2.0, yaw_freq_hz=1.0)
        provider = SinusoidalBodyMotion(config=cfg, t0=0.0)
        bs = provider.get_body_state(0.0)
        # At t=0: rate = A * 2π * f * cos(0) = 2 * 2π * 1 = 4π deg/s
        expected = 2.0 * 2.0 * math.pi * 1.0
        self.assertAlmostEqual(bs.yaw_rate_dps, expected, places=3)


class ReplayBodyMotionTests(unittest.TestCase):
    def test_empty_returns_zero(self) -> None:
        provider = ReplayBodyMotion()
        bs = provider.get_body_state(1.0)
        self.assertEqual(bs.roll_deg, 0.0)

    def test_interpolation(self) -> None:
        data = [
            BodyState(timestamp=1.0, roll_deg=0.0),
            BodyState(timestamp=3.0, roll_deg=10.0),
        ]
        provider = ReplayBodyMotion(data=data)
        bs = provider.get_body_state(2.0)  # midpoint
        self.assertAlmostEqual(bs.roll_deg, 5.0, places=3)

    def test_clamp_before_first(self) -> None:
        data = [BodyState(timestamp=5.0, roll_deg=7.0)]
        provider = ReplayBodyMotion(data=data)
        bs = provider.get_body_state(0.0)
        self.assertAlmostEqual(bs.roll_deg, 7.0)

    def test_clamp_after_last(self) -> None:
        data = [
            BodyState(timestamp=1.0, roll_deg=0.0),
            BodyState(timestamp=2.0, roll_deg=10.0),
        ]
        provider = ReplayBodyMotion(data=data)
        bs = provider.get_body_state(99.0)
        self.assertAlmostEqual(bs.roll_deg, 10.0)


# ---------------------------------------------------------------------------
# FullChainTransform tests
# ---------------------------------------------------------------------------

class FullChainTransformTests(unittest.TestCase):
    def test_no_body_matches_pixel_to_gimbal(self) -> None:
        """With body=None, target_lock_error should equal PixelToGimbalTransform."""
        cam = _make_cam()
        fct = FullChainTransform(cam)
        simple = PixelToGimbalTransform(cam)
        fb = GimbalFeedback(timestamp=0.0, yaw_deg=0.0, pitch_deg=0.0,
                            yaw_rate_dps=0.0, pitch_rate_dps=0.0)

        u, v = 700.0, 300.0
        yaw_full, pitch_full = fct.target_lock_error(u, v, fb, body=None)
        yaw_simple, pitch_simple = simple.pixel_to_angle_error(u, v)
        self.assertAlmostEqual(yaw_full, yaw_simple, places=6)
        self.assertAlmostEqual(pitch_full, pitch_simple, places=6)

    def test_zero_body_matches_simple(self) -> None:
        """With body at zero orientation, FullChainTransform should also produce
        the same result as target_lock_error(body=None)."""
        cam = _make_cam()
        fct = FullChainTransform(cam)
        fb = GimbalFeedback(timestamp=0.0, yaw_deg=0.0, pitch_deg=0.0,
                            yaw_rate_dps=0.0, pitch_rate_dps=0.0)
        body_zero = BodyState(timestamp=0.0)

        u, v = 700.0, 300.0
        yaw_none, pitch_none = fct.target_lock_error(u, v, fb, body=None)
        yaw_zero, pitch_zero = fct.target_lock_error(u, v, fb, body=body_zero)
        self.assertAlmostEqual(yaw_none, yaw_zero, places=4)
        self.assertAlmostEqual(pitch_none, pitch_zero, places=4)

    def test_pixel_to_world_returns_finite(self) -> None:
        cam = _make_cam()
        fct = FullChainTransform(cam)
        fb = GimbalFeedback(timestamp=0.0, yaw_deg=5.0, pitch_deg=-3.0,
                            yaw_rate_dps=0.0, pitch_rate_dps=0.0)
        body = BodyState(timestamp=0.0, roll_deg=2.0, pitch_deg=-1.0, yaw_deg=10.0)
        yaw, pitch = fct.pixel_to_world_direction(640.0, 360.0, fb, body)
        self.assertTrue(math.isfinite(yaw))
        self.assertTrue(math.isfinite(pitch))


# ---------------------------------------------------------------------------
# Controller feedforward tests
# ---------------------------------------------------------------------------

class ControllerFeedforwardTests(unittest.TestCase):
    def _make_controller(self) -> TwoAxisGimbalController:
        cam = _make_cam()
        transform = PixelToGimbalTransform(cam)
        cfg = default_controller_config()
        return TwoAxisGimbalController(transform=transform, cfg=cfg)

    def _make_target(self, cx: float = 640.0, cy: float = 360.0) -> TargetObservation:
        return TargetObservation(
            timestamp=1.0,
            track_id=1,
            bbox=BoundingBox(cx - 40, cy - 30, 80, 60),
            confidence=0.9,
            class_id="person",
        )

    def test_none_body_state_is_zero_regression(self) -> None:
        """compute_command(body_state=None) must produce the same output
        as before the feedforward feature was added."""
        ctrl = self._make_controller()
        fb = GimbalFeedback(0.0, 0.0, 0.0, 0.0, 0.0)
        target = self._make_target(700.0, 320.0)

        cmd1 = ctrl.compute_command(target, fb, 1.0, body_state=None)

        # Rebuild controller and run again to compare
        ctrl2 = self._make_controller()
        cmd2 = ctrl2.compute_command(target, fb, 1.0)

        self.assertAlmostEqual(cmd1.yaw_rate_cmd_dps, cmd2.yaw_rate_cmd_dps, places=6)
        self.assertAlmostEqual(cmd1.pitch_rate_cmd_dps, cmd2.pitch_rate_cmd_dps, places=6)

    def test_zero_body_state_equals_none(self) -> None:
        """body_state with all zeros must behave identically to None."""
        ctrl_none = self._make_controller()
        ctrl_zero = self._make_controller()
        fb = GimbalFeedback(0.0, 0.0, 0.0, 0.0, 0.0)
        target = self._make_target(700.0, 320.0)

        cmd_none = ctrl_none.compute_command(target, fb, 1.0, body_state=None)
        cmd_zero = ctrl_zero.compute_command(target, fb, 1.0, body_state=BodyState(timestamp=1.0))

        self.assertAlmostEqual(cmd_none.yaw_rate_cmd_dps, cmd_zero.yaw_rate_cmd_dps, places=4)
        self.assertAlmostEqual(cmd_none.pitch_rate_cmd_dps, cmd_zero.pitch_rate_cmd_dps, places=4)

    def test_feedforward_compensates_yaw_rate(self) -> None:
        """When body yaw_rate > 0 (dog turning right), feedforward should produce
        a negative yaw correction (gimbal turns left to compensate)."""
        ctrl_no_body = self._make_controller()
        ctrl_body = self._make_controller()
        fb = GimbalFeedback(0.0, 0.0, 0.0, 0.0, 0.0)
        # Target at center → PID error ≈ 0
        target = self._make_target(640.0, 360.0)

        cmd_no = ctrl_no_body.compute_command(target, fb, 1.0, body_state=None)
        body = BodyState(timestamp=1.0, yaw_rate_dps=30.0)
        cmd_with = ctrl_body.compute_command(target, fb, 1.0, body_state=body)

        # The feedforward subtracts 30 dps from yaw command
        delta_yaw = cmd_with.yaw_rate_cmd_dps - cmd_no.yaw_rate_cmd_dps
        # Should be significantly negative (compensating the positive body yaw rate)
        # Note: output may be clipped by smooth_limit, so check direction
        self.assertLess(delta_yaw, -5.0)

    def test_feedforward_metadata_logged(self) -> None:
        ctrl = self._make_controller()
        fb = GimbalFeedback(0.0, 0.0, 0.0, 0.0, 0.0)
        target = self._make_target()
        body = BodyState(timestamp=1.0, yaw_rate_dps=15.0, pitch_rate_dps=-10.0)

        cmd = ctrl.compute_command(target, fb, 1.0, body_state=body)
        self.assertIn("ff_yaw_dps", cmd.metadata)
        self.assertIn("ff_pitch_dps", cmd.metadata)
        self.assertAlmostEqual(cmd.metadata["ff_yaw_dps"], -15.0)
        self.assertAlmostEqual(cmd.metadata["ff_pitch_dps"], 10.0)


# ---------------------------------------------------------------------------
# Pipeline body_provider plumbing test
# ---------------------------------------------------------------------------

class PipelineBodyProviderTests(unittest.TestCase):
    def test_pipeline_accepts_body_provider(self) -> None:
        """Pipeline construction with body_provider=StaticBodyMotion should work."""
        from src.rws_tracking.perception import PassthroughDetector, SimpleIoUTracker, WeightedTargetSelector
        from src.rws_tracking.hardware import SimulatedGimbalDriver
        from src.rws_tracking.pipeline import VisionGimbalPipeline
        from src.rws_tracking.telemetry import InMemoryTelemetryLogger
        from src.rws_tracking.config import SelectorConfig

        cam = _make_cam()
        transform = PixelToGimbalTransform(cam)
        cfg = default_controller_config()

        pipeline = VisionGimbalPipeline(
            detector=PassthroughDetector(),
            tracker=SimpleIoUTracker(),
            selector=WeightedTargetSelector(cam.width, cam.height, config=SelectorConfig()),
            controller=TwoAxisGimbalController(transform=transform, cfg=cfg),
            driver=SimulatedGimbalDriver(),
            telemetry=InMemoryTelemetryLogger(),
            body_provider=StaticBodyMotion(),
        )
        output = pipeline.step([], 0.1)
        self.assertIsNone(output.selected_target)

    def test_pipeline_without_body_provider_works(self) -> None:
        """Pipeline with body_provider=None must not regress."""
        from src.rws_tracking.perception import PassthroughDetector, SimpleIoUTracker, WeightedTargetSelector
        from src.rws_tracking.hardware import SimulatedGimbalDriver
        from src.rws_tracking.pipeline import VisionGimbalPipeline
        from src.rws_tracking.telemetry import InMemoryTelemetryLogger
        from src.rws_tracking.config import SelectorConfig

        cam = _make_cam()
        transform = PixelToGimbalTransform(cam)
        cfg = default_controller_config()

        pipeline = VisionGimbalPipeline(
            detector=PassthroughDetector(),
            tracker=SimpleIoUTracker(),
            selector=WeightedTargetSelector(cam.width, cam.height, config=SelectorConfig()),
            controller=TwoAxisGimbalController(transform=transform, cfg=cfg),
            driver=SimulatedGimbalDriver(),
            telemetry=InMemoryTelemetryLogger(),
            body_provider=None,
        )
        frame = [{"bbox": (600, 340, 80, 60), "confidence": 0.9, "class_id": "person"}]
        output = pipeline.step(frame, 0.1)
        self.assertIsNotNone(output.selected_target)


if __name__ == "__main__":
    unittest.main()
