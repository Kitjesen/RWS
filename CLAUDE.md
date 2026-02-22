# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

RWS (Robot Weapon Station) is a modular 2-DOF gimbal visual tracking system. It is **non-ROS2**, uses **Protocol-driven dependency injection**, and targets real-time tracking at 30+ FPS with YOLO11n-Seg + BoT-SORT. It supports moving-base operation (robot dog) with IMU feedforward compensation.

## Commands

### Setup
```bash
pip install -r requirements.txt
pip install -e .          # editable install so tests can import from src/
```

### Running
```bash
python scripts/demo/run_simple_demo.py     # No camera required
python scripts/demo/run_camera_demo.py     # Live camera

python scripts/api/run_rest_server.py      # REST API on port 5000
python scripts/api/run_grpc_server.py      # gRPC API on port 50051
```

### Testing
```bash
# Run all tests
pytest tests/ -v --tb=short

# Run a single test file
pytest tests/test_pipeline.py -v

# Run tests with a specific marker
pytest tests/ -m "not slow" -v

# Run tests in parallel (faster)
pytest tests/ -n auto -v

# Skip coverage (faster local runs)
pytest tests/ -v --no-cov --tb=short
```

> **Note**: Some tests use outdated API names and `continue-on-error` in CI. The test suite is still actively being aligned with the current codebase.

### Linting & Type Checking
```bash
ruff check src/ tests/        # Lint
ruff format src/ tests/       # Format
ruff check --fix src/ tests/  # Auto-fix lint issues

mypy src/rws_tracking --ignore-missing-imports
```

### Flutter Dashboard
```bash
cd frontend
flutter pub get
flutter run -d chrome          # Dev server
flutter build web              # Production build
```

## Architecture

The system is organized into strict, decoupled layers. **High-layer modules depend on abstractions (Protocols), not concrete implementations.** Never bypass this with direct cross-layer state access.

```
Application / Scripts
        ↓
Pipeline Orchestration  (src/rws_tracking/pipeline/)
        ↓
┌──────────┬──────────┬──────────┬──────────┬──────────┐
│Perception│ Decision │ Control  │ Hardware │  Safety  │
└──────────┴──────────┴──────────┴──────────┴──────────┘
        ↓
Support: Algebra · Telemetry · Config · API · Types
```

### Data Flow (single gimbal)
```
Frame → Detector → Tracker → Selector → StateMachine
      → Rangefinder → DistanceFusion
      → PhysicsBallisticModel → LeadAngleCalculator
      → SafetyManager → PIDController → GimbalDriver → VideoStreamer
```

### Key Packages

| Package | Responsibility |
|---|---|
| `perception/` | `YoloDetector`, `YoloSegTracker` (BoT-SORT), `WeightedTargetSelector`, `FusionMOT` |
| `decision/` | `TrackStateMachine` (SEARCH→TRACK→LOCK→LOST), `ThreatAssessor`, `EngagementQueue` |
| `control/` | `TwoAxisGimbalController` (PID + feedforward), `PhysicsBallisticModel` (RK4), `LeadAngleCalculator`, `GimbalTrajectoryPlanner` |
| `hardware/` | `SimulatedGimbalDriver`, `SerialGimbalDriver` (PELCO-D), `MockIMU`, `SimulatedRangefinder`, `DistanceFusion` |
| `safety/` | `NoFireZoneManager` (NFZ), `SafetyInterlock` (7-condition AND), `SafetyManager` |
| `algebra/` | `PixelToGimbalTransform`, `ConstantVelocityKalman2D`, `ConstantAccelerationKalman2D` |
| `telemetry/` | `InMemoryTelemetryLogger`, `FileTelemetryLogger` |
| `config/` | YAML config loading + hot-reload |
| `api/` | REST (port 5000), gRPC (port 50051), MJPEG video stream |
| `types/` | Shared frozen dataclasses and enums — `TrackState`, `BoundingBox`, layer-specific types |
| `pipeline/` | `VisionGimbalPipeline`, `MultiGimbalPipeline`, `build_pipeline_from_config()` |

### Protocol-Based Extension

All layer boundaries use Python `Protocol` classes (structural typing). To add a new detector, tracker, selector, or driver, implement the matching Protocol — no base classes required. See `src/rws_tracking/interfaces.py` for the re-export shim and each sub-package's `interfaces.py` for the Protocol definitions.

### Types

Shared types live in `src/rws_tracking/types/`:
- `common.py` — `TrackState`, `BoundingBox`
- `perception.py`, `control.py`, `decision.py`, `hardware.py`, `safety.py`, `ballistic.py` — layer-specific frozen dataclasses

**Import from the most specific sub-package, not from `types/` directly.**

### Configuration

All runtime parameters are in `config.yaml` (root). Loaded via `load_config()` and supports hot-reload. Key sections: `camera`, `detector`, `selector`, `controller` (with `yaw_pid`/`pitch_pid`, `ballistic`, `adaptive_pid`), `driver_limits`, `projectile`, `environment`, `lead_angle`, `trajectory`, `engagement`, `safety`, `rangefinder`, `video_stream`.

## Engineering Principles (from Cursor rules)

- **Single responsibility per file** — if a file has mixed concerns, split it.
- **Unidirectional dependencies** — high layers depend on abstractions; concrete implementations are replaceable.
- **Interface-first** — modules communicate via stable interfaces/contracts, never by direct internal state access.
- **No cross-layer direct calls** — `control/` must not reach into `hardware/` internals; use the Protocol.
- **Math changes** — always define variable names, units, and boundary conditions. Attach derivation notes when modifying physical models (ballistic, lead angle, coordinate transforms).
- **PR discipline** — describe domain boundary, interface changes, coupling risk, and rollback plan.

## CI Pipeline

GitHub Actions runs on push/PR to `master`/`develop`:
1. **test** — pytest with coverage, Python 3.9/3.10/3.11 matrix
2. **lint** — `ruff check`, `ruff format --check`, `mypy`
3. **security** — `safety check` on dependencies
4. **performance** — `pytest-benchmark` (PR only)

Pre-commit hooks: trailing whitespace, YAML/TOML check, ruff lint+format, mypy (src/ only), pytest (-x fast-fail).

## Notable Files

- `config.yaml` — primary runtime configuration
- `src/rws_tracking/pipeline/app.py` — `build_pipeline_from_config()`, the main composition root
- `src/rws_tracking/pipeline/pipeline.py` — `VisionGimbalPipeline` main loop
- `src/rws_tracking/interfaces.py` — backward-compat re-export of all Protocol types
- `docs/architecture/overview.md` — detailed architecture with data-flow diagrams and control equations
- `docs/tracking/TRACKING_DEVLOG.md` — FusionMOT / pose-guided tracking design decisions
