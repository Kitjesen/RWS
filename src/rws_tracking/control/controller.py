"""
TwoAxisGimbalController
=======================

Responsibility (single):
    Given a TargetObservation (or None), produce a ControlCommand for
    the gimbal driver.

Features:
    - Coordinate conversion delegated to PixelToGimbalTransform.
    - Dual-axis PID with integral anti-windup, derivative LPF, output limiting.
    - Velocity feedforward (ff_kv * target angular rate).
    - Lost-state velocity prediction (constant-velocity model).
    - Latency compensation (extrapolate target position by estimated delay).
    - Scan pattern for SEARCH state.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, replace
from typing import Optional, Tuple

from ..config import GimbalControllerConfig, PIDConfig

logger = logging.getLogger(__name__)
from ..algebra import PixelToGimbalTransform
from ..decision.state_machine import TrackState, TrackStateMachine
from ..types import BodyState, ControlCommand, GimbalFeedback, TargetError, TargetObservation
from .ballistic import (
    BallisticModel,
    SimpleBallisticModel,
    SimpleBallisticConfig,
    TableBallisticModel,
    TableBallisticConfig,
)
from .adaptive import (
    ErrorBasedScheduler,
    ErrorBasedSchedulerConfig,
    DistanceBasedScheduler,
    DistanceBasedSchedulerConfig,
    GainScheduler,
)


# ---------------------------------------------------------------------------
# PID controller (reusable, axis-agnostic)
# ---------------------------------------------------------------------------

@dataclass
class PIDState:
    integral: float = 0.0
    prev_error: float = 0.0
    d_lpf: float = 0.0
    first_call: bool = True


class PID:
    def __init__(self, cfg: PIDConfig) -> None:
        self.cfg = cfg
        self.state = PIDState()

    def step(self, error: float, dt: float, feedforward: float = 0.0) -> float:
        if dt <= 0.0:
            return 0.0
        self.state.integral += error * dt
        self.state.integral = max(-self.cfg.integral_limit, min(self.cfg.integral_limit, self.state.integral))
        if self.state.first_call:
            self.state.prev_error = error
            self.state.first_call = False
        derivative = (error - self.state.prev_error) / dt
        alpha = self.cfg.derivative_lpf_alpha
        self.state.d_lpf = alpha * derivative + (1.0 - alpha) * self.state.d_lpf
        self.state.prev_error = error
        output = (
            self.cfg.kp * error
            + self.cfg.ki * self.state.integral
            + self.cfg.kd * self.state.d_lpf
            + self.cfg.feedforward_kv * feedforward
        )
        return max(-self.cfg.output_limit, min(self.cfg.output_limit, output))

    def reset(self) -> None:
        self.state = PIDState()


# ---------------------------------------------------------------------------
# Two-axis gimbal controller
# ---------------------------------------------------------------------------

_STATE_INDEX: dict[TrackState, float] = {
    TrackState.SEARCH: 0.0,
    TrackState.TRACK: 1.0,
    TrackState.LOCK: 2.0,
    TrackState.LOST: 3.0,
}


class TwoAxisGimbalController:
    def __init__(
        self,
        transform: PixelToGimbalTransform,
        cfg: GimbalControllerConfig,
    ) -> None:
        self._transform = transform
        self._cfg = cfg
        self._yaw_pid = PID(cfg.yaw_pid)
        self._pitch_pid = PID(cfg.pitch_pid)
        self._state_machine = TrackStateMachine(cfg)
        self._last_ts = 0.0
        self._last_cmd = (0.0, 0.0)
        self._scan_start_ts: Optional[float] = None
        self._prev_state: TrackState = TrackState.SEARCH
        self._last_error: Optional[TargetError] = None
        self._last_target: Optional[TargetObservation] = None

        # 弹道补偿模型
        self._ballistic_model: Optional[BallisticModel] = None
        if cfg.ballistic.enabled:
            if cfg.ballistic.model_type == "simple":
                self._ballistic_model = SimpleBallisticModel(
                    SimpleBallisticConfig(
                        target_height_m=cfg.ballistic.target_height_m,
                        quadratic_a=cfg.ballistic.quadratic_a,
                        quadratic_b=cfg.ballistic.quadratic_b,
                        quadratic_c=cfg.ballistic.quadratic_c,
                    )
                )
            elif cfg.ballistic.model_type == "table":
                self._ballistic_model = TableBallisticModel(
                    TableBallisticConfig(
                        target_height_m=cfg.ballistic.target_height_m,
                        distance_table=cfg.ballistic.distance_table,
                        compensation_table=cfg.ballistic.compensation_table,
                    )
                )

        # 自适应PID增益调度
        self._gain_scheduler: Optional[GainScheduler] = None
        if cfg.adaptive_pid.enabled:
            if cfg.adaptive_pid.scheduler_type == "error_based":
                self._gain_scheduler = ErrorBasedScheduler(
                    ErrorBasedSchedulerConfig(
                        low_error_threshold_deg=cfg.adaptive_pid.low_error_threshold_deg,
                        high_error_threshold_deg=cfg.adaptive_pid.high_error_threshold_deg,
                        low_error_multiplier=cfg.adaptive_pid.low_error_multiplier,
                        high_error_multiplier=cfg.adaptive_pid.high_error_multiplier,
                    )
                )
            elif cfg.adaptive_pid.scheduler_type == "distance_based":
                self._gain_scheduler = DistanceBasedScheduler(
                    DistanceBasedSchedulerConfig(
                        near_distance_m=cfg.adaptive_pid.near_distance_m,
                        far_distance_m=cfg.adaptive_pid.far_distance_m,
                        near_multiplier=cfg.adaptive_pid.near_multiplier,
                        far_multiplier=cfg.adaptive_pid.far_multiplier,
                        bbox_area_max=cfg.adaptive_pid.bbox_area_max,
                        ki_distance_scale=cfg.adaptive_pid.ki_distance_scale,
                    )
                )

    @property
    def state(self) -> TrackState:
        return self._state_machine.state

    def compute_command(
        self,
        target: Optional[TargetObservation],
        feedback: GimbalFeedback,
        timestamp: float,
        body_state: Optional[BodyState] = None,
    ) -> ControlCommand:
        """Compute gimbal rate command.

        Parameters
        ----------
        target : TargetObservation or None
        feedback : GimbalFeedback
        timestamp : float
        body_state : BodyState, optional
            If provided, feedforward compensation is applied to counteract
            body (base platform) angular velocity.  When ``None`` the
            controller behaves identically to the legacy (stationary base)
            mode — zero regression.
        """
        dt = max(timestamp - self._last_ts, 1e-3) if self._last_ts > 0.0 else 0.01
        self._last_ts = timestamp

        error, vel_yaw_dps, vel_pitch_dps = self._estimate_error(target, timestamp)
        ballistic_comp = 0.0
        if self._ballistic_model is not None and target is not None:
            ballistic_comp = self._ballistic_model.compute(target.bbox, self._transform.camera.fy)

        state = self._state_machine.update(error, timestamp)

        # Detect state transitions
        if state != self._prev_state:
            logger.info(
                "controller state: %s -> %s", self._prev_state.value, state.value,
            )
            if self._prev_state == TrackState.SEARCH and state == TrackState.TRACK:
                self._last_cmd = (0.0, 0.0)
            if state == TrackState.SEARCH:
                self._scan_start_ts = None
            self._prev_state = state

        cmd_yaw, cmd_pitch = 0.0, 0.0
        kp_mult, ki_mult, kd_mult = 1.0, 1.0, 1.0

        if state in (TrackState.TRACK, TrackState.LOCK):
            if error is None:
                return ControlCommand(timestamp=timestamp, yaw_rate_cmd_dps=0.0, pitch_rate_cmd_dps=0.0)

            # 自适应增益调度
            if self._gain_scheduler is not None:
                err_mag = max(abs(error.yaw_error_deg), abs(error.pitch_error_deg))
                bbox_area = self._last_target.bbox.area if self._last_target else 0.0
                kp_mult, ki_mult, kd_mult = self._gain_scheduler.compute_multipliers(err_mag, bbox_area)

                # 临时调整增益
                temp_yaw_cfg = replace(
                    self._cfg.yaw_pid,
                    kp=self._cfg.yaw_pid.kp * kp_mult,
                    ki=self._cfg.yaw_pid.ki * ki_mult,
                    kd=self._cfg.yaw_pid.kd * kd_mult,
                )
                temp_pitch_cfg = replace(
                    self._cfg.pitch_pid,
                    kp=self._cfg.pitch_pid.kp * kp_mult,
                    ki=self._cfg.pitch_pid.ki * ki_mult,
                    kd=self._cfg.pitch_pid.kd * kd_mult,
                )
                temp_yaw_pid = PID(temp_yaw_cfg)
                temp_pitch_pid = PID(temp_pitch_cfg)
                temp_yaw_pid.state = self._yaw_pid.state
                temp_pitch_pid.state = self._pitch_pid.state

                cmd_yaw = temp_yaw_pid.step(error.yaw_error_deg, dt, feedforward=vel_yaw_dps)
                cmd_pitch = temp_pitch_pid.step(error.pitch_error_deg, dt, feedforward=vel_pitch_dps)

                self._yaw_pid.state = temp_yaw_pid.state
                self._pitch_pid.state = temp_pitch_pid.state
            else:
                # 标准PID
                cmd_yaw = self._yaw_pid.step(error.yaw_error_deg, dt, feedforward=vel_yaw_dps)
                cmd_pitch = self._pitch_pid.step(error.pitch_error_deg, dt, feedforward=vel_pitch_dps)

        elif state == TrackState.LOST:
            predicted = self._predict_lost_error(timestamp)
            if predicted is not None:
                cmd_yaw = self._yaw_pid.step(predicted.yaw_error_deg, dt, feedforward=vel_yaw_dps)
                cmd_pitch = self._pitch_pid.step(predicted.pitch_error_deg, dt, feedforward=vel_pitch_dps)
            else:
                self._yaw_pid.reset()
                self._pitch_pid.reset()
                cmd_yaw, cmd_pitch = self._scan_command(timestamp)

        else:  # SEARCH
            self._yaw_pid.reset()
            self._pitch_pid.reset()
            cmd_yaw, cmd_pitch = self._scan_command(timestamp)

        cmd_yaw, cmd_pitch = self._smooth_limit(cmd_yaw, cmd_pitch)

        # --- Feedforward body-motion compensation AFTER smoothing (bypass LPF) ---
        # Counteract body angular velocity so the weapon stays aimed at the
        # world-fixed target.  Dog turns right -> gimbal compensates left.
        if body_state is not None:
            cmd_yaw -= body_state.yaw_rate_dps
            cmd_pitch -= body_state.pitch_rate_dps
            # Re-apply rate limit (but not LPF)
            max_rate = self._cfg.max_rate_dps
            cmd_yaw = max(-max_rate, min(max_rate, cmd_yaw))
            cmd_pitch = max(-max_rate, min(max_rate, cmd_pitch))

        metadata = {
            "state": _STATE_INDEX[state],
            "yaw_error_deg": error.yaw_error_deg if error else 0.0,
            "pitch_error_deg": error.pitch_error_deg if error else 0.0,
            "target_id": float(error.target_id or -1) if error else -1.0,
            "vel_yaw_dps": vel_yaw_dps,
            "vel_pitch_dps": vel_pitch_dps,
            "ff_yaw_dps": -body_state.yaw_rate_dps if body_state else 0.0,
            "ff_pitch_dps": -body_state.pitch_rate_dps if body_state else 0.0,
            "ballistic_comp_deg": ballistic_comp,
            "adaptive_kp_mult": kp_mult,
            "adaptive_ki_mult": ki_mult,
            "adaptive_kd_mult": kd_mult,
        }
        return ControlCommand(
            timestamp=timestamp,
            yaw_rate_cmd_dps=cmd_yaw,
            pitch_rate_cmd_dps=cmd_pitch,
            metadata=metadata,
        )

    # ------------------------------------------------------------------
    # Error estimation with latency compensation
    # ------------------------------------------------------------------

    def _estimate_error(
        self, target: Optional[TargetObservation], timestamp: float
    ) -> Tuple[Optional[TargetError], float, float]:
        """Returns (error, yaw_velocity_dps, pitch_velocity_dps)."""
        if target is None:
            return None, 0.0, 0.0

        # Latency compensation: extrapolate target center by estimated delay
        # Prefer mask_center (segmentation centroid) over bbox center
        latency = self._cfg.latency_compensation_s
        vx, vy = target.velocity_px_per_s
        cx, cy = target.mask_center if target.mask_center is not None else target.bbox.center
        cx_comp = cx + vx * latency
        cy_comp = cy + vy * latency

        yaw_err, pitch_err = self._transform.pixel_to_angle_error(cx_comp, cy_comp)

        # 弹道补偿
        ballistic_comp = 0.0
        if self._ballistic_model is not None:
            ballistic_comp = self._ballistic_model.compute(target.bbox, self._transform.camera.fy)
            pitch_err += ballistic_comp

        # Estimate angular velocity from pixel velocity
        vel_yaw_dps, vel_pitch_dps = self._pixel_velocity_to_angular(vx, vy)

        error = TargetError(
            timestamp=timestamp,
            yaw_error_deg=yaw_err,
            pitch_error_deg=pitch_err,
            target_id=target.track_id,
        )
        self._last_error = error
        self._last_target = target
        return error, vel_yaw_dps, vel_pitch_dps

    def _pixel_velocity_to_angular(self, vx_px_s: float, vy_px_s: float) -> Tuple[float, float]:
        """Convert pixel velocity to approximate angular velocity (deg/s)."""
        cam = self._transform.camera
        yaw_rate = math.degrees(vx_px_s / cam.fx)
        pitch_rate = -math.degrees(vy_px_s / cam.fy)  # Y-down -> pitch-up
        return yaw_rate, pitch_rate

    # ------------------------------------------------------------------
    # Lost-state velocity prediction
    # ------------------------------------------------------------------

    def _predict_lost_error(self, timestamp: float) -> Optional[TargetError]:
        """Use constant-velocity model to predict target position during LOST."""
        if self._last_error is None or self._last_target is None:
            return None
        dt_lost = timestamp - self._last_error.timestamp
        if dt_lost > self._cfg.predict_timeout_s:
            return None  # too long, give up prediction

        vx, vy = self._last_target.velocity_px_per_s
        cx, cy = (
            self._last_target.mask_center
            if self._last_target.mask_center is not None
            else self._last_target.bbox.center
        )
        pred_cx = cx + vx * dt_lost
        pred_cy = cy + vy * dt_lost

        yaw_err, pitch_err = self._transform.pixel_to_angle_error(pred_cx, pred_cy)
        return TargetError(
            timestamp=timestamp,
            yaw_error_deg=yaw_err,
            pitch_error_deg=pitch_err,
            target_id=self._last_target.track_id,
        )

    # ------------------------------------------------------------------
    # Output smoothing & scan
    # ------------------------------------------------------------------

    def _smooth_limit(self, yaw_cmd: float, pitch_cmd: float) -> Tuple[float, float]:
        alpha = self._cfg.command_lpf_alpha
        y = alpha * yaw_cmd + (1.0 - alpha) * self._last_cmd[0]
        p = alpha * pitch_cmd + (1.0 - alpha) * self._last_cmd[1]
        max_rate = self._cfg.max_rate_dps
        y = max(-max_rate, min(max_rate, y))
        p = max(-max_rate, min(max_rate, p))
        self._last_cmd = (y, p)
        return y, p

    def _scan_command(self, timestamp: float) -> Tuple[float, float]:
        if self._scan_start_ts is None:
            self._scan_start_ts = timestamp
        t = timestamp - self._scan_start_ts
        freq = self._cfg.scan_freq_hz
        yaw_scan, pitch_scan = self._cfg.scan_pattern
        yaw = yaw_scan * self._cfg.scan_yaw_scale * math.sin(2.0 * math.pi * freq * t)
        pitch = (
            pitch_scan * self._cfg.scan_pitch_scale
            * math.sin(2.0 * math.pi * freq * self._cfg.scan_pitch_freq_ratio * t)
        )
        return yaw, pitch
