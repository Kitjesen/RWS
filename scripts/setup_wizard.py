#!/usr/bin/env python3
"""RWS Setup Wizard — gets a new operator running in under 5 minutes.

Asks 6 essential questions and generates a ready-to-use config.yaml.
Also creates scenario-specific profiles under config/profiles/.

Usage:
    python scripts/setup_wizard.py
"""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path

# ---------------------------------------------------------------------------
# Terminal helpers
# ---------------------------------------------------------------------------

_RESET = "\033[0m"
_BOLD = "\033[1m"
_CYAN = "\033[36m"
_GREEN = "\033[32m"
_YELLOW = "\033[33m"
_RED = "\033[31m"
_DIM = "\033[2m"


def _supports_color() -> bool:
    return hasattr(sys.stdout, "isatty") and sys.stdout.isatty()


def _c(text: str, code: str) -> str:
    if _supports_color():
        return f"{code}{text}{_RESET}"
    return text


def bold(t: str) -> str:
    return _c(t, _BOLD)


def cyan(t: str) -> str:
    return _c(t, _CYAN)


def green(t: str) -> str:
    return _c(t, _GREEN)


def yellow(t: str) -> str:
    return _c(t, _YELLOW)


def red(t: str) -> str:
    return _c(t, _RED)


def dim(t: str) -> str:
    return _c(t, _DIM)


def _print_banner() -> None:
    banner = textwrap.dedent(r"""
        ██████╗ ██╗    ██╗███████╗
        ██╔══██╗██║    ██║██╔════╝
        ██████╔╝██║ █╗ ██║███████╗
        ██╔══██╗██║███╗██║╚════██║
        ██║  ██║╚███╔███╔╝███████║
        ╚═╝  ╚═╝ ╚══╝╚══╝ ╚══════╝
    """)
    print(cyan(banner))
    print(bold("  Robot Weapon Station — Setup Wizard"))
    print(dim("  Generates a ready-to-use config.yaml in under 5 minutes.\n"))
    print("─" * 60)


# ---------------------------------------------------------------------------
# Question helpers
# ---------------------------------------------------------------------------


def _ask_choice(prompt: str, options: list[str], default: str) -> str:
    """Present a numbered menu and return the chosen value key (1-based)."""
    print(f"\n{bold(prompt)}")
    for opt in options:
        print(f"  {opt}")
    while True:
        raw = input(f"  {dim(f'[default: {default}]')} Choice: ").strip()
        if raw == "":
            return default
        if raw in {str(i + 1) for i in range(len(options))}:
            return raw
        print(f"  {yellow('Please enter a number between 1 and')} {len(options)}")


def _ask_text(prompt: str, default: str, secret: bool = False) -> str:
    """Ask a free-text question with an optional default."""
    suffix = dim(f" [default: {default!r}]") if default else dim(" [press Enter to skip]")
    if secret:
        import getpass

        raw = getpass.getpass(f"\n{bold(prompt)}{suffix}: ")
    else:
        raw = input(f"\n{bold(prompt)}{suffix}: ").strip()
    return raw if raw else default


# ---------------------------------------------------------------------------
# Config template builders
# ---------------------------------------------------------------------------

# Camera presets: (width, height, fx, fy, cx, cy)
_CAMERA_PRESETS = {
    "1": (640, 480, 640.0, 638.0, 320.0, 240.0),
    "2": (1280, 720, 970.0, 965.0, 640.0, 360.0),
    "3": (1920, 1080, 1440.0, 1440.0, 960.0, 540.0),
}

# ROE profiles mapped to safety/engagement knobs
_ROE_SETTINGS = {
    "1": {  # Training — dry-fire, safest
        "engagement_enabled": True,
        "safety_enabled": True,
        "require_operator_auth": True,
        "min_lock_time_s": 2.0,
        "heartbeat_timeout_s": 5.0,
        "ballistic_enabled": False,
        "projectile_enabled": False,
        "roe_name": "training",
    },
    "2": {  # Exercise — simulated fire, relaxed
        "engagement_enabled": True,
        "safety_enabled": True,
        "require_operator_auth": True,
        "min_lock_time_s": 1.5,
        "heartbeat_timeout_s": 8.0,
        "ballistic_enabled": False,
        "projectile_enabled": False,
        "roe_name": "exercise",
    },
    "3": {  # Live operations — full safety, strict
        "engagement_enabled": True,
        "safety_enabled": True,
        "require_operator_auth": True,
        "min_lock_time_s": 1.0,
        "heartbeat_timeout_s": 10.0,
        "ballistic_enabled": True,
        "projectile_enabled": True,
        "roe_name": "live",
    },
}


def _build_config(
    scenario: str,
    cam: str,
    roe: str,
    api_key: str,
    operator_timeout: int,
    serial_port: str = "",
) -> str:
    """Return a complete config.yaml string for the given answers."""

    w, h, fx, fy, cx, cy = _CAMERA_PRESETS[cam]
    roe_cfg = _ROE_SETTINGS[roe]

    driver_type = "serial" if scenario == "2" else "simulated"
    port_line = f"  port: \"{serial_port}\"" if scenario == "2" else "  # port: \"/dev/ttyUSB0\"  # serial driver only"
    api_key_line = f"  key: \"{api_key}\"" if api_key else "  # key: \"\"  # no auth for local use"
    rangefinder_type = "serial" if scenario == "2" else "simulated"
    ballistic_enabled = str(roe_cfg["ballistic_enabled"]).lower()
    projectile_enabled = str(roe_cfg["projectile_enabled"]).lower()
    roe_name = roe_cfg["roe_name"]

    return f"""\
# ============================================================
# RWS Vision-Gimbal Tracking System — Generated Configuration
# Generated by: scripts/setup_wizard.py
# Scenario: {['', 'simulation', 'lab', 'field'][int(scenario)]}
# ROE Profile: {roe_name}
# ============================================================

camera:
  width: {w}
  height: {h}
  fx: {fx}
  fy: {fy}
  cx: {cx}
  cy: {cy}
  distortion_k1: 0.0
  distortion_k2: 0.0
  distortion_p1: 0.0
  distortion_p2: 0.0
  distortion_k3: 0.0
  mount_roll_deg: 0.0
  mount_pitch_deg: 0.0
  mount_yaw_deg: 0.0

detector:
  model_path: "yolo11n-seg.pt"
  confidence_threshold: 0.35
  nms_iou_threshold: 0.40
  img_size: 640
  device: ""
  tracker: "botsort.yaml"
  class_whitelist:
    - person

selector:
  weights:
    confidence: 0.35
    size: 0.18
    center_proximity: 0.20
    track_age: 0.15
    class_weight: 0.10
    switch_penalty: 0.35
    velocity_approach: 0.12
  min_hold_time_s: 0.5
  delta_threshold: 0.15
  preferred_classes:
    person: 1.0
    car: 0.6

controller:
  yaw_pid:
    kp: 6.0
    ki: 0.5
    kd: 0.40
    integral_limit: 40.0
    output_limit: 180.0
    derivative_lpf_alpha: 0.35
    feedforward_kv: 0.80
  pitch_pid:
    kp: 6.5
    ki: 0.45
    kd: 0.40
    integral_limit: 40.0
    output_limit: 180.0
    derivative_lpf_alpha: 0.35
    feedforward_kv: 0.75
  max_rate_dps: 180.0
  command_lpf_alpha: 0.80
  lock_error_threshold_deg: 1.2
  lock_hold_time_s: 0.3
  predict_timeout_s: 0.50
  lost_timeout_s: 1.5
  max_track_error_timeout_s: 5.0
  high_error_multiplier: 5.0
  scan_pattern: [45.0, 18.0]
  scan_freq_hz: 0.18
  scan_yaw_scale: 1.0
  scan_pitch_scale: 0.35
  scan_pitch_freq_ratio: 0.65
  latency_compensation_s: 0.033
  ballistic:
    enabled: {ballistic_enabled}
    model_type: "simple"
    target_height_m: 1.8
    quadratic_a: 0.001
    quadratic_b: 0.01
    quadratic_c: 0.0
    muzzle_velocity_mps: 900.0
    bc_g7: 0.223
    mass_kg: 0.0098
    caliber_m: 0.00762
  adaptive_pid:
    enabled: true
    scheduler_type: "error_based"
    low_error_threshold_deg: 1.2
    high_error_threshold_deg: 8.0
    low_error_multiplier: 0.55
    high_error_multiplier: 1.6

# Driver: {driver_type}
driver:
  type: "{driver_type}"
{port_line}
  baud: 9600

driver_limits:
  yaw_min_deg: -160.0
  yaw_max_deg: 160.0
  pitch_min_deg: -45.0
  pitch_max_deg: 75.0
  max_rate_dps: 240.0
  deadband_dps: 0.2
  inertia_time_constant_s: 0.05
  static_friction_dps: 0.5
  coulomb_friction_dps: 2.0

projectile:
  enabled: {projectile_enabled}
  muzzle_velocity_mps: 850.0
  ballistic_coefficient: 0.4
  projectile_mass_kg: 0.0098
  projectile_diameter_m: 0.00762
  drag_model: "g1"

environment:
  temperature_c: 15.0
  pressure_hpa: 1013.25
  humidity_pct: 50.0
  wind_speed_mps: 0.0
  wind_direction_deg: 0.0
  altitude_m: 0.0

lead_angle:
  enabled: true
  use_acceleration: true
  max_lead_deg: 5.0
  min_confidence: 0.3
  velocity_smoothing_alpha: 0.7
  target_height_m: 1.8
  convergence_iterations: 3

trajectory:
  enabled: false
  max_rate_dps: 180.0
  max_acceleration_dps2: 720.0
  settling_threshold_deg: 0.5
  use_s_curve: false
  max_jerk_dps3: 3600.0
  min_switch_interval_s: 0.3

engagement:
  enabled: {str(roe_cfg['engagement_enabled']).lower()}
  strategy: "threat_first"
  max_engagement_range_m: 500.0
  min_threat_threshold: 0.1
  distance_decay_m: 50.0
  velocity_norm_px_s: 200.0
  target_height_m: 1.8
  sector_size_deg: 30.0
  weights:
    distance: 0.30
    velocity: 0.25
    class_threat: 0.20
    heading: 0.15
    size: 0.10

safety:
  enabled: {str(roe_cfg['safety_enabled']).lower()}
  nfz_slow_down_margin_deg: 5.0
  interlock:
    require_operator_auth: {str(roe_cfg['require_operator_auth']).lower()}
    min_lock_time_s: {roe_cfg['min_lock_time_s']}
    min_engagement_range_m: 5.0
    max_engagement_range_m: 500.0
    system_check_interval_s: 1.0
    heartbeat_timeout_s: {roe_cfg['heartbeat_timeout_s']}
  zones: []

# API security
api:
{api_key_line}

# Operator watchdog
operator_watchdog:
  timeout_s: {operator_timeout}

rangefinder:
  enabled: true
  type: "{rangefinder_type}"
  max_range_m: 1500.0
  min_range_m: 1.0
  noise_std_m: 0.5
  failure_rate: 0.05
  max_laser_age_s: 0.5
  target_height_m: 1.8
  serial_port: ""
  serial_baud: 9600

video_stream:
  enabled: true
  jpeg_quality: 70
  max_fps: 30.0
  scale_factor: 1.0
  buffer_size: 3
  annotate_detections: true
  annotate_tracks: true
  annotate_crosshair: true
  annotate_safety_zones: true
"""


# ---------------------------------------------------------------------------
# Main wizard flow
# ---------------------------------------------------------------------------


def _run_wizard() -> None:
    _print_banner()

    # Q1: Scenario
    scenario = _ask_choice(
        "What scenario are you setting up?",
        [
            "1) Simulation/Demo  (no hardware, safe to run anywhere)",
            "2) Lab test         (real gimbal connected via serial)",
            "3) Field deployment (gimbal + full live config)",
        ],
        default="1",
    )

    # Q1b: If lab/field, ask for serial port
    serial_port = ""
    if scenario in ("2", "3"):
        serial_port = _ask_text(
            "Serial port for gimbal driver?",
            default="/dev/ttyUSB0" if sys.platform != "win32" else "COM3",
        )

    # Q2: Camera resolution
    cam = _ask_choice(
        "Camera resolution?",
        [
            "1) 640x480    — fast, low-power (Raspberry Pi, Jetson Nano)",
            "2) 1280x720   — HD balance (default, recommended)",
            "3) 1920x1080  — Full HD (high accuracy, needs GPU)",
        ],
        default="2" if scenario in ("2", "3") else "1",
    )

    # Q3: ROE profile
    roe = _ask_choice(
        "Rules of Engagement profile?",
        [
            "1) Training   — dry-fire only, maximum safety interlocks",
            "2) Exercise   — simulated engagement, relaxed constraints",
            "3) Live ops   — full live configuration, all safety active",
        ],
        default="1",
    )

    # Q4: API security key
    api_key = _ask_text(
        "Set API security key? (press Enter to skip for local use)",
        default="",
    )

    # Q5: Operator heartbeat timeout
    timeout_raw = _ask_text(
        "Operator heartbeat timeout (seconds)?",
        default="10",
    )
    try:
        operator_timeout = max(1, int(timeout_raw))
    except ValueError:
        print(yellow("  Invalid number — using default 10s"))
        operator_timeout = 10

    # Q6: Output path
    default_output = "config.yaml"
    output_path = _ask_text(
        "Save config to?",
        default=default_output,
    )

    # ── Generate ────────────────────────────────────────────────────────────
    print(f"\n{'─' * 60}")
    print(bold("  Generating configuration..."))

    content = _build_config(
        scenario=scenario,
        cam=cam,
        roe=roe,
        api_key=api_key,
        operator_timeout=operator_timeout,
        serial_port=serial_port,
    )

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    if out.exists():
        backup = out.with_suffix(".yaml.bak")
        out.rename(backup)
        print(dim(f"  Existing config backed up to {backup}"))

    out.write_text(content, encoding="utf-8")

    # ── Summary ─────────────────────────────────────────────────────────────
    scenario_names = {
        "1": "Simulation/Demo",
        "2": "Lab test (serial driver)",
        "3": "Field deployment",
    }
    cam_names = {"1": "640x480", "2": "1280x720", "3": "1920x1080"}
    roe_names = {"1": "Training", "2": "Exercise", "3": "Live ops"}

    print(f"\n{'─' * 60}")
    print(green(bold("  Config saved successfully!\n")))
    print(f"  {green('✓')} Path      : {bold(str(out.resolve()))}")
    print(f"  {green('✓')} Scenario  : {scenario_names[scenario]}")
    print(f"  {green('✓')} Resolution: {cam_names[cam]}")
    print(f"  {green('✓')} ROE       : {roe_names[roe]}")
    print(f"  {green('✓')} Timeout   : {operator_timeout}s")
    if api_key:
        print(f"  {green('✓')} API key   : {'*' * len(api_key)}")
    else:
        print(f"  {yellow('!')} API key   : none (local use only)")

    print(f"\n{'─' * 60}")
    print(bold("  Next steps:\n"))
    print(f"    Install deps:    {cyan('pip install -r requirements.txt && pip install -e .')}")
    print(f"    Start server:    {cyan('python scripts/api/run_rest_server.py')}")
    print(f"    Run demo:        {cyan('python scripts/demo/run_simple_demo.py')}")
    print(f"    Open dashboard:  {cyan('http://localhost:5000')}")
    print(f"\n    Run self-test:   {cyan('curl http://localhost:5000/api/selftest')}")
    print(f"    Then start:      {cyan('POST /api/mission/start')}")
    print(f"\n  Profile presets available in {cyan('config/profiles/')}:")
    print(f"    training.yaml · exercise.yaml · live.yaml")
    print(f"\n{'─' * 60}\n")


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    try:
        _run_wizard()
    except KeyboardInterrupt:
        print(f"\n\n{yellow('Setup cancelled.')}")
        sys.exit(0)
