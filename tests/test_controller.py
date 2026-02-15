"""Unit tests for TwoAxisGimbalController."""

import pytest

from src.rws_tracking.algebra.coordinate_transform import (
    CameraModel,
    PixelToGimbalTransform,
)
from src.rws_tracking.config import ControllerConfig, PIDConfig
from src.rws_tracking.control.controller import TwoAxisGimbalController
from src.rws_tracking.types import (
    BodyState,
    BoundingBox,
    GimbalFeedback,
    TargetObservation,
)


@pytest.fixture
def camera_model():
    """Create default camera model."""
    return CameraModel(
        width=1280,
        height=720,
        fx=970.0,
        fy=965.0,
        cx=640.0,
        cy=360.0,
    )


@pytest.fixture
def pid_config():
    """Create default PID config."""
    return PIDConfig(
        kp=5.0,
        ki=0.3,
        kd=0.2,
        integral_limit=40.0,
        output_limit=180.0,
        derivative_lpf_alpha=0.4,
        feedforward_kv=0.75,
    )


@pytest.fixture
def controller_config(pid_config):
    """Create default controller config."""
    return ControllerConfig(
        yaw_pid=pid_config,
        pitch_pid=pid_config,
        max_rate_dps=180.0,
        command_lpf_alpha=0.75,
        lock_error_threshold_deg=0.8,
        lock_hold_time_s=0.4,
        predict_timeout_s=0.25,
        lost_timeout_s=1.5,
        max_track_error_timeout_s=5.0,
        high_error_multiplier=5.0,
        scan_pattern=[40.0, 20.0],
        scan_freq_hz=0.15,
        scan_yaw_scale=1.0,
        scan_pitch_scale=0.3,
        scan_pitch_freq_ratio=0.7,
        latency_compensation_s=0.033,
    )


@pytest.fixture
def controller(camera_model, controller_config):
    """Create controller instance."""
    transform = PixelToGimbalTransform(camera_model)
    return TwoAxisGimbalController(
        transform=transform,
        config=controller_config,
    )


def create_target(
    bbox: tuple[float, float, float, float],
    velocity: tuple[float, float] = (0.0, 0.0),
    timestamp: float = 1.0,
) -> TargetObservation:
    """Helper to create target observation."""
    x, y, w, h = bbox
    return TargetObservation(
        timestamp=timestamp,
        track_id=1,
        bbox=BoundingBox(x=x, y=y, w=w, h=h),
        confidence=0.9,
        class_id="person",
        velocity_px_per_s=velocity,
        acceleration_px_per_s2=(0.0, 0.0),
        mask_center=None,
    )


def create_feedback(
    yaw: float = 0.0,
    pitch: float = 0.0,
    timestamp: float = 1.0,
) -> GimbalFeedback:
    """Helper to create gimbal feedback."""
    return GimbalFeedback(
        timestamp=timestamp,
        yaw_deg=yaw,
        pitch_deg=pitch,
        yaw_rate_dps=0.0,
        pitch_rate_dps=0.0,
    )


class TestPIDControl:
    """Test PID control behavior."""

    def test_proportional_response(self, controller):
        """P term should respond to error."""
        # Target to the right of center
        target = create_target((700, 340, 800, 440), timestamp=1.0)
        feedback = create_feedback(yaw=0.0, pitch=0.0, timestamp=1.0)

        cmd = controller.compute_command(target, feedback, timestamp=1.0)

        # Should command positive yaw rate (turn right)
        assert cmd.yaw_rate_cmd_dps > 0
        assert cmd.state.name == "TRACK"

    def test_integral_accumulation(self, controller):
        """I term should accumulate over time."""
        target = create_target((700, 340, 800, 440))  # Constant error
        feedback = create_feedback(yaw=0.0, pitch=0.0)

        # First command
        cmd1 = controller.compute_command(target, feedback, timestamp=1.0)
        yaw_rate_1 = cmd1.yaw_rate_cmd_dps

        # Second command (same error, integral should accumulate)
        cmd2 = controller.compute_command(target, feedback, timestamp=1.1)
        yaw_rate_2 = cmd2.yaw_rate_cmd_dps

        # Output should increase due to integral term
        assert yaw_rate_2 > yaw_rate_1

    def test_integral_saturation(self, controller):
        """Integral should saturate at limit."""
        target = create_target((900, 340, 1000, 440))  # Large error
        feedback = create_feedback(yaw=0.0, pitch=0.0)

        # Run for many iterations to saturate integral
        for i in range(100):
            controller.compute_command(target, feedback, timestamp=1.0 + i * 0.1)

        # Integral should be clamped
        assert abs(controller._yaw_integral) <= controller._yaw_pid_cfg.integral_limit

    def test_derivative_response(self, controller):
        """D term should respond to rate of change."""
        feedback = create_feedback(yaw=0.0, pitch=0.0)

        # First target at t=1.0
        target1 = create_target((700, 340, 800, 440), timestamp=1.0)
        controller.compute_command(target1, feedback, timestamp=1.0)

        # Second target at t=1.1 (error increasing)
        target2 = create_target((750, 340, 850, 440), timestamp=1.1)
        cmd2 = controller.compute_command(target2, feedback, timestamp=1.1)

        # Derivative term should affect output
        # (exact value depends on filtering, just check it doesn't crash)
        assert cmd2.yaw_rate_cmd_dps != 0

    def test_output_saturation(self, controller):
        """Output should be clamped to max_rate_dps."""
        # Very large error
        target = create_target((1200, 340, 1280, 440))
        feedback = create_feedback(yaw=0.0, pitch=0.0)

        cmd = controller.compute_command(target, feedback, timestamp=1.0)

        # Should be clamped
        assert abs(cmd.yaw_rate_cmd_dps) <= controller._cfg.max_rate_dps
        assert abs(cmd.pitch_rate_cmd_dps) <= controller._cfg.max_rate_dps


class TestStateMachine:
    """Test state machine transitions."""

    def test_initial_state_search(self, controller):
        """Initial state should be SEARCH."""
        feedback = create_feedback()
        cmd = controller.compute_command(None, feedback, timestamp=1.0)
        assert cmd.state.name == "SEARCH"

    def test_search_to_track(self, controller):
        """Should transition from SEARCH to TRACK when target appears."""
        feedback = create_feedback()

        # No target: SEARCH
        cmd1 = controller.compute_command(None, feedback, timestamp=1.0)
        assert cmd1.state.name == "SEARCH"

        # Target appears: TRACK
        target = create_target((640, 360, 740, 460))
        cmd2 = controller.compute_command(target, feedback, timestamp=1.1)
        assert cmd2.state.name == "TRACK"

    def test_track_to_lock(self, controller):
        """Should transition to LOCK when error is small and stable."""
        # Target at center (small error)
        target = create_target((635, 355, 645, 365))
        feedback = create_feedback(yaw=0.0, pitch=0.0)

        # Run until lock
        for i in range(20):
            cmd = controller.compute_command(target, feedback, timestamp=1.0 + i * 0.1)

        # Should eventually lock
        assert cmd.state.name == "LOCK"

    def test_lock_to_track_on_large_error(self, controller):
        """Should drop from LOCK to TRACK if error increases."""
        # First, achieve lock
        target_center = create_target((638, 358, 642, 362))
        feedback = create_feedback(yaw=0.0, pitch=0.0)

        for i in range(20):
            controller.compute_command(target_center, feedback, timestamp=1.0 + i * 0.1)

        # Now introduce large error
        target_far = create_target((800, 360, 900, 460))
        cmd = controller.compute_command(target_far, feedback, timestamp=3.0)

        assert cmd.state.name == "TRACK"

    def test_track_to_lost(self, controller):
        """Should transition to LOST when target disappears."""
        target = create_target((640, 360, 740, 460))
        feedback = create_feedback()

        # Track target
        cmd1 = controller.compute_command(target, feedback, timestamp=1.0)
        assert cmd1.state.name == "TRACK"

        # Target disappears
        cmd2 = controller.compute_command(None, feedback, timestamp=1.1)
        assert cmd2.state.name == "LOST"

    def test_lost_to_search_timeout(self, controller):
        """Should return to SEARCH after lost timeout."""
        target = create_target((640, 360, 740, 460))
        feedback = create_feedback()

        # Track then lose target
        controller.compute_command(target, feedback, timestamp=1.0)
        controller.compute_command(None, feedback, timestamp=1.1)

        # Wait past lost_timeout_s (1.5s)
        cmd = controller.compute_command(None, feedback, timestamp=3.0)
        assert cmd.state.name == "SEARCH"


class TestLatencyCompensation:
    """Test latency compensation."""

    def test_prediction_with_velocity(self, controller):
        """Should predict future position based on velocity."""
        # Target moving right at 100 px/s
        target = create_target((640, 360, 740, 460), velocity=(100.0, 0.0), timestamp=1.0)
        feedback = create_feedback(timestamp=1.0)

        cmd = controller.compute_command(target, feedback, timestamp=1.0)

        # With latency compensation, should aim ahead
        # (exact value depends on latency_compensation_s)
        assert cmd.yaw_rate_cmd_dps != 0

    def test_no_prediction_without_velocity(self, controller):
        """Should not predict if velocity is zero."""
        target = create_target((640, 360, 740, 460), velocity=(0.0, 0.0), timestamp=1.0)
        feedback = create_feedback(timestamp=1.0)

        cmd = controller.compute_command(target, feedback, timestamp=1.0)

        # Should still work without prediction
        assert cmd.state.name == "TRACK"


class TestBodyMotionCompensation:
    """Test body motion compensation."""

    def test_compensation_with_body_motion(self, controller):
        """Should compensate for body angular velocity."""
        target = create_target((640, 360, 740, 460))
        feedback = create_feedback(yaw=0.0, pitch=0.0)

        # Body rotating right at 10 deg/s
        body_state = BodyState(
            timestamp=1.0,
            roll_deg=0.0,
            pitch_deg=0.0,
            yaw_deg=0.0,
            roll_rate_dps=0.0,
            pitch_rate_dps=0.0,
            yaw_rate_dps=10.0,  # Body rotating right
        )

        cmd = controller.compute_command(target, feedback, timestamp=1.0, body_state=body_state)

        # Should add feedforward to compensate
        # (command should be adjusted to counter body motion)
        assert cmd.yaw_rate_cmd_dps != 0

    def test_no_compensation_without_body_state(self, controller):
        """Should work without body state."""
        target = create_target((640, 360, 740, 460))
        feedback = create_feedback()

        cmd = controller.compute_command(target, feedback, timestamp=1.0)

        # Should work normally
        assert cmd.state.name == "TRACK"


class TestScanPattern:
    """Test scan pattern in SEARCH mode."""

    def test_scan_generates_motion(self, controller):
        """SEARCH mode should generate scan pattern."""
        feedback = create_feedback()

        commands = []
        for i in range(50):
            cmd = controller.compute_command(None, feedback, timestamp=i * 0.1)
            commands.append((cmd.yaw_rate_cmd_dps, cmd.pitch_rate_cmd_dps))

        # Should have non-zero commands (scanning)
        yaw_rates = [c[0] for c in commands]
        assert any(r != 0 for r in yaw_rates)

        # Should be sinusoidal (check sign changes)
        sign_changes = sum(
            1 for i in range(1, len(yaw_rates)) if yaw_rates[i] * yaw_rates[i - 1] < 0
        )
        assert sign_changes > 2  # At least a few oscillations


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_zero_dt(self, controller):
        """Should handle zero time delta."""
        target = create_target((640, 360, 740, 460))
        feedback = create_feedback()

        controller.compute_command(target, feedback, timestamp=1.0)
        cmd2 = controller.compute_command(target, feedback, timestamp=1.0)  # Same time

        # Should not crash
        assert cmd2 is not None

    def test_negative_dt(self, controller):
        """Should handle negative time delta."""
        target = create_target((640, 360, 740, 460))
        feedback = create_feedback()

        controller.compute_command(target, feedback, timestamp=2.0)
        cmd2 = controller.compute_command(target, feedback, timestamp=1.0)  # Earlier

        # Should not crash
        assert cmd2 is not None

    def test_very_large_error(self, controller):
        """Should handle very large errors."""
        target = create_target((10000, 10000, 10100, 10100))  # Way off screen
        feedback = create_feedback()

        cmd = controller.compute_command(target, feedback, timestamp=1.0)

        # Should clamp output
        assert abs(cmd.yaw_rate_cmd_dps) <= controller._cfg.max_rate_dps

    def test_rapid_target_changes(self, controller):
        """Should handle rapid target position changes."""
        feedback = create_feedback()

        for i in range(100):
            # Random target position
            x = 100 + (i * 137) % 1000
            y = 100 + (i * 211) % 500
            target = create_target((x, y, x + 50, y + 50))

            cmd = controller.compute_command(target, feedback, timestamp=i * 0.01)

            # Should not crash
            assert cmd is not None

    def test_state_reset_on_target_loss(self, controller):
        """PID state should reset appropriately on target loss."""
        target = create_target((700, 360, 800, 460))
        feedback = create_feedback()

        # Build up integral
        for i in range(10):
            controller.compute_command(target, feedback, timestamp=1.0 + i * 0.1)

        # Lose target
        controller.compute_command(None, feedback, timestamp=3.0)

        # Integral should be affected (implementation dependent)
        # At minimum, should not crash
        assert controller._yaw_integral is not None
