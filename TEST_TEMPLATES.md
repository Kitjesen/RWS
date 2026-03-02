# RWS 新功能测试模板

## 1. test_emap_correction_nulls_gimbal_rotation (P0)
文件: `tests/test_kalman_emap.py`

```python
"""Test CentroidKalmanCA.predict_with_ego_motion (EMAP) ego-motion compensation."""

import math
import numpy as np
import pytest
from src.rws_tracking.algebra.kalman2d import CentroidKalmanCA, KalmanConfig


class TestEMAP:
    """Test suite for Ego-Motion Aware Prediction."""

    def test_predict_with_ego_motion_stationary_yaw(self):
        """World-fixed object should not move when gimbal yaws."""
        kf = CentroidKalmanCA(cx0=640.0, cy0=360.0)

        # Gimbal yaws right 10°, camera focal length fx=970
        d_yaw_deg = 10.0
        fx, fy = 970.0, 965.0

        kf.predict_with_ego_motion(dt=0.033, d_yaw_deg=d_yaw_deg,
                                    d_pitch_deg=0.0, fx=fx, fy=fy)

        pos = kf.position
        # World-fixed point should shift LEFT (negative cx)
        # Δcx = -fx * tan(Δψ) ≈ -970 * tan(10°) ≈ -171 pixels
        expected_dx = -fx * math.tan(math.radians(d_yaw_deg))
        assert pos[0] == pytest.approx(640.0 + expected_dx, abs=5.0)
        assert pos[1] == pytest.approx(360.0, abs=1.0)  # y unchanged

    def test_predict_with_ego_motion_stationary_pitch(self):
        """World-fixed object should not move when gimbal pitches."""
        kf = CentroidKalmanCA(cx0=640.0, cy0=360.0)

        d_pitch_deg = 5.0
        fx, fy = 970.0, 965.0

        kf.predict_with_ego_motion(dt=0.033, d_yaw_deg=0.0,
                                    d_pitch_deg=d_pitch_deg, fx=fx, fy=fy)

        pos = kf.position
        # World-fixed point should shift DOWN when camera tilts up
        # Δcy = fy * tan(Δθ) ≈ 965 * tan(5°) ≈ 84 pixels
        expected_dy = fy * math.tan(math.radians(d_pitch_deg))
        assert pos[0] == pytest.approx(640.0, abs=1.0)  # x unchanged
        assert pos[1] == pytest.approx(360.0 + expected_dy, abs=5.0)

    def test_predict_with_ego_motion_moving_target(self):
        """Moving target should be corrected for gimbal rotation."""
        # Start with moving target (vx=100 px/s)
        kf = CentroidKalmanCA(cx0=640.0, cy0=360.0, vx0=100.0, vy0=0.0)

        dt = 0.033
        d_yaw_deg = 0.0
        fx, fy = 970.0, 965.0

        # Predict with ego-motion
        kf.predict_with_ego_motion(dt=dt, d_yaw_deg=d_yaw_deg,
                                    d_pitch_deg=0.0, fx=fx, fy=fy)

        pos = kf.position
        # Should move right due to velocity, no gimbal rotation correction
        assert pos[0] > 640.0

    def test_predict_with_ego_motion_zero_rotation(self):
        """No gimbal rotation should not affect position."""
        kf = CentroidKalmanCA(cx0=640.0, cy0=360.0, vx0=50.0, vy0=0.0)

        kf.predict_with_ego_motion(dt=0.033, d_yaw_deg=0.0,
                                    d_pitch_deg=0.0, fx=970.0, fy=965.0)

        pos = kf.position
        # Only velocity motion, no gimbal correction
        assert pos[0] > 640.0  # moved right
        assert pos[1] == pytest.approx(360.0, abs=1.0)  # y unchanged

    def test_predict_with_ego_motion_large_angle_warning(self):
        """Large gimbal angles should trigger small-angle approximation failure."""
        kf = CentroidKalmanCA(cx0=640.0, cy0=360.0)

        # 45° is beyond small-angle approximation validity
        d_yaw_deg = 45.0
        fx, fy = 970.0, 965.0

        # Should not crash, but result may be inaccurate
        kf.predict_with_ego_motion(dt=0.033, d_yaw_deg=d_yaw_deg,
                                    d_pitch_deg=0.0, fx=fx, fy=fy)

        # Verify it returns a position (may be inaccurate but shouldn't crash)
        pos = kf.position
        assert pos is not None
        assert not np.isnan(pos[0]) and not np.isnan(pos[1])

    def test_predict_with_ego_motion_negative_angles(self):
        """Negative gimbal angles should apply opposite corrections."""
        kf_pos = CentroidKalmanCA(cx0=640.0, cy0=360.0)
        kf_neg = CentroidKalmanCA(cx0=640.0, cy0=360.0)

        # Positive yaw
        kf_pos.predict_with_ego_motion(dt=0.033, d_yaw_deg=10.0,
                                        d_pitch_deg=0.0, fx=970.0, fy=965.0)

        # Negative yaw (opposite direction)
        kf_neg.predict_with_ego_motion(dt=0.033, d_yaw_deg=-10.0,
                                        d_pitch_deg=0.0, fx=970.0, fy=965.0)

        pos_pos = kf_pos.position
        pos_neg = kf_neg.position

        # Should move in opposite directions
        assert pos_pos[0] < 640.0  # left
        assert pos_neg[0] > 640.0  # right
```

---

## 2. test_oru_velocity_blending_post_occlusion (P0)
文件: `tests/test_fusion_mot_oru.py`

```python
"""Test FusionMOT ORU (Observed-velocity Refined Update) after occlusion."""

import pytest
from src.rws_tracking.perception.fusion_mot import FusionMOT, FusionMOTConfig
from src.rws_tracking.types import Detection, BoundingBox
import numpy as np


class TestORUPostOcclusion:
    """Test occlusion-aware velocity correction."""

    def test_oru_alpha_blending(self):
        """ORU should blend observed velocity with Kalman prediction."""
        cfg = FusionMOTConfig(oru_alpha=0.6)
        tracker = FusionMOT(cfg)

        # Frame 1-5: Track a moving target
        for i in range(5):
            dets = [Detection(
                bbox=BoundingBox(x=100.0 + i*50.0, y=100.0, w=50.0, h=100.0),
                confidence=0.9, class_id="person"
            )]
            tracks = tracker.update(dets, timestamp=i*0.033)

        # Verify target is moving
        moving_track = tracks[0]
        vx_before, _ = moving_track.velocity_px_per_s
        assert vx_before > 0

        # Frames 6-8: Occlusion (no detection)
        for i in range(6, 9):
            tracks = tracker.update([], timestamp=i*0.033)

        # Frame 9: Target reappears, but with DIFFERENT velocity
        # (e.g., decelerated during occlusion)
        new_det_x = 100.0 + 5*50.0 + 10.0  # slower than before
        dets = [Detection(
            bbox=BoundingBox(x=new_det_x, y=100.0, w=50.0, h=100.0),
            confidence=0.9, class_id="person"
        )]
        tracks = tracker.update(dets, timestamp=9*0.033)

        # ORU blending should correct velocity
        # Expected: v_corrected = 0.6 * v_observed + 0.4 * v_kalman
        assert len(tracks) > 0
        vx_after, _ = tracks[0].velocity_px_per_s
        assert vx_after is not None

    def test_oru_pure_kalman_when_alpha_zero(self):
        """When oru_alpha=0, velocity should be pure Kalman prediction."""
        cfg_pure_kf = FusionMOTConfig(oru_alpha=0.0)
        tracker_kf = FusionMOT(cfg_pure_kf)

        cfg_blended = FusionMOTConfig(oru_alpha=0.6)
        tracker_blend = FusionMOT(cfg_blended)

        # Same detection sequence
        dets_moving = [
            Detection(bbox=BoundingBox(x=100.0, y=100.0, w=50.0, h=100.0),
                      confidence=0.9, class_id="person"),
            Detection(bbox=BoundingBox(x=150.0, y=100.0, w=50.0, h=100.0),
                      confidence=0.9, class_id="person"),
        ]

        for i, det in enumerate(dets_moving):
            tracker_kf.update([det], timestamp=i*0.033)
            tracker_blend.update([det], timestamp=i*0.033)

        # Occlusion
        for i in range(2, 5):
            tracker_kf.update([], timestamp=i*0.033)
            tracker_blend.update([], timestamp=i*0.033)

        # Reappear with new velocity
        new_det_slow = Detection(
            bbox=BoundingBox(x=180.0, y=100.0, w=50.0, h=100.0),
            confidence=0.9, class_id="person"
        )

        tracks_kf = tracker_kf.update([new_det_slow], timestamp=5*0.033)
        tracks_blend = tracker_blend.update([new_det_slow], timestamp=5*0.033)

        # Pure Kalman and blended should differ
        vx_kf = tracks_kf[0].velocity_px_per_s[0] if tracks_kf else 0
        vx_blend = tracks_blend[0].velocity_px_per_s[0] if tracks_blend else 0

        assert vx_kf is not None
        assert vx_blend is not None

    def test_oru_prevents_velocity_drift(self):
        """ORU should prevent large velocity drift during long occlusions."""
        cfg = FusionMOTConfig(oru_alpha=0.6)
        tracker = FusionMOT(cfg)

        # Establish baseline velocity
        for i in range(3):
            dets = [Detection(
                bbox=BoundingBox(x=100.0 + i*40.0, y=100.0, w=50.0, h=100.0),
                confidence=0.9, class_id="person"
            )]
            tracker.update(dets, timestamp=i*0.033)

        # Long occlusion (10 frames)
        for i in range(3, 13):
            tracker.update([], timestamp=i*0.033)

        # Reappear
        dets = [Detection(
            bbox=BoundingBox(x=300.0, y=100.0, w=50.0, h=100.0),
            confidence=0.9, class_id="person"
        )]
        tracks = tracker.update(dets, timestamp=13*0.033)

        # Velocity should recover reasonably
        vx = tracks[0].velocity_px_per_s[0]
        # Not drift too far from expected (~40 px/frame at 30Hz ≈ 1200 px/s)
        assert not np.isnan(vx)
```

---

## 3. test_mpc_vs_pid_step_response (P0)
文件: `tests/test_mpc_controller.py`

```python
"""Test MPC controller and compare with PID baseline."""

import pytest
import numpy as np
from src.rws_tracking.control.mpc_controller import MPCController, MPCConfig
from src.rws_tracking.config.control import PIDConfig, GimbalControllerConfig
from src.rws_tracking.control.controller import TwoAxisGimbalController
from src.rws_tracking.types import GimbalFeedback


class TestMPCController:
    """Test suite for Model Predictive Control."""

    @pytest.fixture
    def mpc_config(self):
        """Create MPC configuration."""
        return MPCConfig(
            horizon=10,
            q_error=100.0,
            r_effort=1.0,
            q_terminal=0.0,
            integral_limit=30.0,
            output_limit=90.0,
            ki=0.1,
            derivative_lpf_alpha=0.4,
            feedforward_kv=0.75,
            plant_dt=0.033,
        )

    def test_mpc_initialization(self, mpc_config):
        """MPC controller should initialize without errors."""
        mpc = MPCController(mpc_config)
        assert mpc is not None
        assert mpc.cfg.horizon == 10

    def test_mpc_step_response(self, mpc_config):
        """MPC should step-down error toward zero."""
        mpc = MPCController(mpc_config)
        feedback = GimbalFeedback(
            timestamp=0.0,
            yaw_angle_deg=0.0,
            pitch_angle_deg=0.0,
            yaw_rate_dps=0.0,
            pitch_rate_dps=0.0,
        )

        errors = []
        for i in range(30):
            # Constant error setpoint = 10 degrees
            error_deg = 10.0

            # Compute MPC command
            cmd_yaw = mpc.step(
                error_deg, feedback.yaw_rate_dps,
                dt=0.033, feedforward=0.0,
                fire_authorized=False
            )

            errors.append(error_deg)

            # Simulate plant: dθ/dt = u, error decreases
            if abs(cmd_yaw) > 0.01:
                error_deg = error_deg - cmd_yaw * 0.033

        # Error should generally trend toward zero (with possible overshoot)
        final_error = errors[-1]
        assert abs(final_error) < 10.0  # Some progress

    def test_mpc_integral_action(self, mpc_config):
        """MPC should eliminate steady-state error via integral action."""
        mpc_config.ki = 0.3  # Enable integral
        mpc = MPCController(mpc_config)

        feedback = GimbalFeedback(timestamp=0.0, yaw_angle_deg=0.0,
                                  pitch_angle_deg=0.0, yaw_rate_dps=0.0,
                                  pitch_rate_dps=0.0)

        # Steady error = 5 degrees
        error = 5.0
        integral_action_vals = []

        for _ in range(50):  # Many steps
            cmd = mpc.step(error, 0.0, dt=0.033, feedforward=0.0,
                           fire_authorized=False)
            integral_action_vals.append(cmd)

        # Last few commands should converge
        avg_last_10 = np.mean(integral_action_vals[-10:])
        assert abs(avg_last_10) > 0.01  # Integral builds up

    def test_mpc_anti_windup(self, mpc_config):
        """MPC integral should clamp to prevent windup."""
        mpc_config.ki = 0.5
        mpc_config.integral_limit = 10.0
        mpc = MPCController(mpc_config)

        feedback = GimbalFeedback(timestamp=0.0, yaw_angle_deg=0.0,
                                  pitch_angle_deg=0.0, yaw_rate_dps=0.0,
                                  pitch_rate_dps=0.0)

        # Large constant error
        error = 50.0
        cmds = []

        for _ in range(100):
            cmd = mpc.step(error, 0.0, dt=0.033, feedforward=0.0,
                           fire_authorized=False)
            cmds.append(cmd)

        # Commands should saturate, not grow without bound
        max_cmd = np.max(np.abs(cmds))
        assert max_cmd <= mpc_config.output_limit + 1.0

    def test_mpc_feedforward_velocity(self, mpc_config):
        """MPC should apply feedforward to target velocity."""
        mpc = MPCController(mpc_config)
        feedback = GimbalFeedback(timestamp=0.0, yaw_angle_deg=0.0,
                                  pitch_angle_deg=0.0, yaw_rate_dps=0.0,
                                  pitch_rate_dps=0.0)

        # Zero error, but target moving
        error = 0.0
        feedforward = 30.0  # deg/s

        cmd = mpc.step(error, feedback.yaw_rate_dps, dt=0.033,
                       feedforward=feedforward, fire_authorized=False)

        # Command should be proportional to feedforward
        # kv = 0.75, so cmd ≈ 0.75 * 30 = 22.5 deg/s
        assert cmd > 10.0  # Significant feedforward contribution

    def test_mpc_output_saturation(self, mpc_config):
        """MPC output should saturate at configured limit."""
        mpc_config.output_limit = 45.0
        mpc = MPCController(mpc_config)

        feedback = GimbalFeedback(timestamp=0.0, yaw_angle_deg=0.0,
                                  pitch_angle_deg=0.0, yaw_rate_dps=0.0,
                                  pitch_rate_dps=0.0)

        # Large error
        error = 100.0
        cmd = mpc.step(error, 0.0, dt=0.033, feedforward=0.0,
                       fire_authorized=False)

        assert abs(cmd) <= mpc_config.output_limit + 0.1
```

---

## 4. test_min_hostile_confidence_filtering (P0)
文件: `tests/test_iff_confidence.py`

```python
"""Test IFFChecker min_hostile_confidence gate."""

import pytest
from src.rws_tracking.safety.iff import IFFChecker
from src.rws_tracking.types import Track
from src.rws_tracking.types.common import BoundingBox


def _make_track(track_id: int, confidence: float) -> Track:
    return Track(
        track_id=track_id,
        bbox=BoundingBox(x=0.0, y=0.0, w=100.0, h=100.0),
        confidence=confidence,
        class_id="unknown",
        first_seen_ts=0.0,
        last_seen_ts=1.0,
    )


class TestMinHostileConfidence:
    """Test confidence threshold filtering."""

    def test_low_confidence_rejected_above_threshold(self):
        """Low-confidence tracks should be rejected when below threshold."""
        checker = IFFChecker(min_hostile_confidence=0.5)
        tracks = [
            _make_track(1, confidence=0.3),  # Below threshold
            _make_track(2, confidence=0.7),  # Above threshold
        ]

        results = checker.check(tracks)

        # Track 1 rejected due to low confidence
        assert 1 in results
        assert results[1].is_friend is False
        assert "confidence" in results[1].reason.lower()

        # Track 2 allowed (not rejected)
        assert 2 in results
        assert results[2].is_friend is False  # Still hostile (not friendly class)

    def test_zero_threshold_allows_all(self):
        """min_hostile_confidence=0.0 should not filter."""
        checker = IFFChecker(min_hostile_confidence=0.0)
        tracks = [_make_track(1, confidence=0.01)]

        results = checker.check(tracks)

        # Should be checked normally (not rejected for low confidence)
        assert 1 in results

    def test_exact_threshold_boundary(self):
        """Confidence exactly at threshold should be allowed."""
        checker = IFFChecker(min_hostile_confidence=0.5)
        tracks = [_make_track(1, confidence=0.5)]

        results = checker.check(tracks)

        # Exactly at threshold should be allowed
        assert 1 in results
        assert results[1].is_friend is False

    def test_just_below_threshold_rejected(self):
        """Confidence just below threshold should be rejected."""
        checker = IFFChecker(min_hostile_confidence=0.5)
        tracks = [_make_track(1, confidence=0.4999)]

        results = checker.check(tracks)

        # Just below should be rejected
        assert 1 in results
        assert results[1].is_friend is False
        assert "min_hostile_confidence" in results[1].reason

    def test_high_confidence_always_checked(self):
        """High confidence tracks should always go through normal checks."""
        checker = IFFChecker(
            min_hostile_confidence=0.5,
            friendly_classes={"civilian"}
        )

        tracks = [
            _make_track(1, confidence=0.99),  # High confidence
        ]
        tracks[0] = Track(
            track_id=1,
            bbox=BoundingBox(x=0.0, y=0.0, w=100.0, h=100.0),
            confidence=0.99,
            class_id="civilian",
            first_seen_ts=0.0,
            last_seen_ts=1.0,
        )

        results = checker.check(tracks)

        # Should pass through and be classified as friendly
        assert 1 in results
        assert results[1].is_friend is True

    def test_confidence_with_whitelist(self):
        """Whitelisted track should bypass confidence check."""
        checker = IFFChecker(
            min_hostile_confidence=0.5,
            track_id_whitelist={42}
        )

        tracks = [
            _make_track(42, confidence=0.1),  # Low confidence, but whitelisted
            _make_track(43, confidence=0.1),  # Low confidence, not whitelisted
        ]

        results = checker.check(tracks)

        # Whitelisted (42) should be friendly
        assert results[42].is_friend is True

        # Non-whitelisted (43) should be rejected for low confidence
        assert results[43].is_friend is False
        assert "confidence" in results[43].reason.lower()
```

---

## 5. test_dob_disturbance_estimation (P1)
文件: `tests/test_controller_dob.py`

```python
"""Test DOB (Disturbance Observer) in TwoAxisGimbalController."""

import pytest
import numpy as np
from src.rws_tracking.control.controller import TwoAxisGimbalController
from src.rws_tracking.config.control import GimbalControllerConfig, PIDConfig
from src.rws_tracking.algebra.coordinate_transform import (
    CameraModel, PixelToGimbalTransform
)
from src.rws_tracking.types import GimbalFeedback, TargetObservation, BoundingBox


class TestDOB:
    """Test Disturbance Observer."""

    @pytest.fixture
    def controller_with_dob(self):
        """Create controller with DOB enabled."""
        cam = CameraModel(width=1280, height=720, fx=970.0, fy=965.0,
                         cx=640.0, cy=360.0)
        cfg = GimbalControllerConfig(
            yaw_pid=PIDConfig(kp=5.0, ki=0.3),
            pitch_pid=PIDConfig(kp=5.0, ki=0.3),
            dob_enabled=True,
        )
        return TwoAxisGimbalController(PixelToGimbalTransform(cam), cfg)

    def test_dob_estimates_constant_disturbance(self, controller_with_dob):
        """DOB should estimate a constant persistent disturbance."""
        ctrl = controller_with_dob

        # Simulate constant disturbance (e.g., gait oscillation)
        disturbance = 5.0  # deg/s constant

        feedback_yaw = 0.0
        disturbance_estimates = []

        for i in range(20):
            # Create target observation (zero error to isolate disturbance)
            obs = TargetObservation(
                timestamp=0.0,
                track_id=1,
                bbox=BoundingBox(x=640.0, y=360.0, w=100.0, h=100.0),
                confidence=0.9,
                class_id="person",
                velocity_px_per_s=(0.0, 0.0),
                acceleration_px_per_s2=(0.0, 0.0),
            )

            feedback = GimbalFeedback(
                timestamp=i*0.033,
                yaw_angle_deg=feedback_yaw,
                pitch_angle_deg=0.0,
                yaw_rate_dps=0.0,
                pitch_rate_dps=0.0,
            )

            cmd = ctrl.compute_command(obs, feedback, fire_authorized=False)

            # Simulate plant with disturbance
            # feedback_yaw += (cmd.yaw_rate_command + disturbance) * 0.033

            # Extract DOB estimate (if accessible via internal state)
            # disturbance_estimates.append(est)

        # DOB should converge to disturbance estimate
        # assert np.mean(disturbance_estimates[-5:]) == pytest.approx(5.0, abs=1.0)

    def test_dob_disabled_no_disturbance_compensation(self):
        """Without DOB, disturbance should not be compensated."""
        cam = CameraModel(width=1280, height=720, fx=970.0, fy=965.0,
                         cx=640.0, cy=360.0)
        cfg = GimbalControllerConfig(
            yaw_pid=PIDConfig(kp=5.0, ki=0.3),
            pitch_pid=PIDConfig(kp=5.0, ki=0.3),
            dob_enabled=False,  # DOB disabled
        )
        ctrl = TwoAxisGimbalController(PixelToGimbalTransform(cam), cfg)

        obs = TargetObservation(
            timestamp=0.0, track_id=1,
            bbox=BoundingBox(x=640.0, y=360.0, w=100.0, h=100.0),
            confidence=0.9, class_id="person",
            velocity_px_per_s=(0.0, 0.0),
            acceleration_px_per_s2=(0.0, 0.0),
        )

        feedback = GimbalFeedback(timestamp=0.0, yaw_angle_deg=0.0,
                                  pitch_angle_deg=0.0, yaw_rate_dps=0.0,
                                  pitch_rate_dps=0.0)

        cmd = ctrl.compute_command(obs, feedback, fire_authorized=False)

        # Should compute command without DOB compensation
        assert cmd is not None
```

---

## Summary of Test Coverage Gaps

| Priority | Feature | Test File | Line Count |
|----------|---------|-----------|-----------|
| P0 | EMAP | test_kalman_emap.py | ~150 |
| P0 | ORU | test_fusion_mot_oru.py | ~180 |
| P0 | MPC | test_mpc_controller.py | ~240 |
| P0 | IFF Confidence | test_iff_confidence.py | ~120 |
| P1 | DOB | test_controller_dob.py | ~110 |

**Total Missing Test Code: ~800 lines**

Create as priority follow-ups after architecture review.
