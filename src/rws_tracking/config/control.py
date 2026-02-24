"""控制层配置：PID、MPC、弹道、自适应、提前量、轨迹规划。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PIDConfig:
    kp: float = 5.0
    ki: float = 0.3
    kd: float = 0.2
    integral_limit: float = 30.0
    output_limit: float = 90.0
    derivative_lpf_alpha: float = 0.3
    feedforward_kv: float = 0.0


@dataclass(frozen=True)
class BallisticConfig:
    enabled: bool = False
    model_type: str = "simple"
    target_height_m: float = 1.8
    quadratic_a: float = 0.001
    quadratic_b: float = 0.01
    quadratic_c: float = 0.0
    distance_table: tuple[float, ...] = (5.0, 10.0, 15.0, 20.0, 25.0, 30.0)
    compensation_table: tuple[float, ...] = (0.1, 0.4, 0.9, 1.6, 2.5, 3.6)
    muzzle_velocity_mps: float = 900.0
    bc_g7: float = 0.223
    mass_kg: float = 0.0098
    caliber_m: float = 0.00762


@dataclass(frozen=True)
class AdaptivePIDConfig:
    enabled: bool = False
    scheduler_type: str = "error_based"
    low_error_threshold_deg: float = 2.0
    high_error_threshold_deg: float = 10.0
    low_error_multiplier: float = 0.8
    high_error_multiplier: float = 1.5
    near_distance_m: float = 5.0
    far_distance_m: float = 30.0
    near_multiplier: float = 1.0
    far_multiplier: float = 1.3
    bbox_area_max: float = 50000.0
    ki_distance_scale: float = 0.8


@dataclass(frozen=True)
class MPCConfig:
    """Tuning parameters for the MPC axis controller (mirrors mpc_controller.MPCConfig)."""

    horizon: int = 10
    q_error: float = 100.0
    r_effort: float = 1.0
    q_terminal: float = 0.0        # 0 = use q_error
    integral_limit: float = 30.0
    output_limit: float = 90.0
    ki: float = 0.3
    derivative_lpf_alpha: float = 0.3
    feedforward_kv: float = 0.0
    plant_dt: float = 0.033        # Should match pipeline loop interval


@dataclass(frozen=True)
class GimbalControllerConfig:
    yaw_pid: PIDConfig
    pitch_pid: PIDConfig
    max_rate_dps: float = 180.0
    command_lpf_alpha: float = 0.4
    lock_error_threshold_deg: float = 0.8
    lock_hold_time_s: float = 0.4
    predict_timeout_s: float = 0.25
    lost_timeout_s: float = 1.5
    max_track_error_timeout_s: float = 5.0
    high_error_multiplier: float = 5.0
    scan_pattern: tuple[float, float] = (40.0, 20.0)
    scan_freq_hz: float = 0.15
    scan_yaw_scale: float = 1.0
    scan_pitch_scale: float = 0.3
    scan_pitch_freq_ratio: float = 0.7
    latency_compensation_s: float = 0.0
    ballistic: BallisticConfig = BallisticConfig()
    adaptive_pid: AdaptivePIDConfig = AdaptivePIDConfig()
    # Disturbance Observer (DOB) for inner-loop vibration rejection.
    # Estimates low-frequency disturbances (e.g. robot-dog gait at 2–4 Hz)
    # by comparing the previous rate command with the measured actual rate.
    # The LPF-smoothed estimate is subtracted from the PID output to
    # pre-compensate for persistent disturbances.
    # dob_alpha : IIR update weight per sample (0=no update, 1=no smoothing).
    #   At 30 Hz, alpha=0.5 → ~3.3 Hz bandwidth (passes gait, rejects fast noise).
    # dob_gain  : Output scale (< 1.0 for conservative rejection).
    dob_enabled: bool = False
    dob_alpha: float = 0.5
    dob_gain: float = 1.0
    # Controller mode — 'pid' (default) or 'mpc'
    controller_mode: str = 'pid'
    # MPC parameters used when controller_mode == 'mpc'
    mpc: MPCConfig = MPCConfig()


@dataclass(frozen=True)
class LeadAngleConfig:
    enabled: bool = False
    use_acceleration: bool = True
    max_lead_deg: float = 5.0
    min_confidence: float = 0.3
    velocity_smoothing_alpha: float = 0.7
    target_height_m: float = 1.8
    convergence_iterations: int = 3


@dataclass(frozen=True)
class TrajectoryPlannerConfig:
    enabled: bool = False
    max_rate_dps: float = 180.0
    max_acceleration_dps2: float = 720.0
    settling_threshold_deg: float = 0.5
    use_s_curve: bool = False
    max_jerk_dps3: float = 3600.0
    min_switch_interval_s: float = 0.3
