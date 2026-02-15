# RWS Vision-Gimbal Tracking (2-DOF)

Lightweight non-ROS2 system for visual target pursuit and lock-on
with a yaw/pitch gimbal, powered by **YOLO11n-Seg + BoT-SORT**.

Supports **moving-base operation** (robot dog) with IMU feedforward compensation.

## 🆕 最新更新 (v1.1.0)

- ✅ **真实硬件支持** - 串口云台驱动 + 真实 IMU 接口
- ✅ **配置热更新** - 运行时调整参数，无需重启
- ✅ **CI/CD 集成** - 自动化测试和代码质量检查
- ✅ **测试增强** - 50+ 新增测试用例
- 📖 **文档完善** - 3 篇新增技术文档

👉 查看 [PROJECT_COMPLETION_SUMMARY.md](PROJECT_COMPLETION_SUMMARY.md) 了解详情

## Project Structure

```
src/rws_tracking/
    types.py                        # Global shared data structures
    interfaces.py                   # Protocol interfaces (unified export)
    config.py                       # Configuration dataclasses + YAML load/save

    algebra/                        # Math / geometry
        coordinate_transform.py     #   pixel → camera → gimbal → body → world
        kalman2d.py                 #   2D Kalman filter (CV / CA models)

    perception/                     # Perception layer
        interfaces.py               #   Detector / Tracker / TargetSelector protocols
        yolo_detector.py            #   YOLO11n inference
        yolo_seg_tracker.py         #   YOLO-Seg + BoT-SORT combined tracker
        passthrough_detector.py     #   Simulation detector adapter
        tracker.py                  #   SimpleIoUTracker
        selector.py                 #   Multi-target weighted scoring + anti-switch

    decision/                       # Decision layer
        state_machine.py            #   SEARCH → TRACK → LOCK → LOST

    control/                        # Control layer
        interfaces.py               #   GimbalController protocol
        controller.py               #   Dual-axis PID + feedforward + latency comp
        adaptive.py                 #   Adaptive PID gain scheduling
        ballistic.py                #   Ballistic compensation models

    hardware/                       # Execution layer
        interfaces.py               #   GimbalDriver protocol
        driver.py                   #   SimulatedGimbalDriver (with dynamics model)
        serial_driver.py            #   🆕 SerialGimbalDriver (real hardware)
        imu_interface.py            #   BodyMotionProvider protocol
        mock_imu.py                 #   Static / Sinusoidal / Replay mock IMUs
        robot_imu.py                #   🆕 RobotIMUProvider (real IMU)

    telemetry/                      # Telemetry layer
        interfaces.py               #   TelemetryLogger protocol
        logger.py                   #   InMemory + File loggers (thread-safe)

    pipeline/                       # Orchestration layer
        pipeline.py                 #   VisionGimbalPipeline (end-to-end loop)
        app.py                      #   Build helpers and demo entry points

    tools/                          # Utilities
        simulation.py               #   Synthetic scene generator
        tuning.py                   #   PID grid-search tuner
        replay.py                   #   Telemetry replay
        dashboard.py                #   Realtime cv2 dashboard
        config_reload.py            #   🆕 Configuration hot-reload
        sim/                        #   MuJoCo SIL simulation
        training/                   #   YOLO fine-tuning scripts

config.yaml                        # System configuration (camera, detector, PID, etc.)
run_demo.py                        # Quick synthetic demo entry point
run_yolo_cam.py                    # Live camera / video + YOLO-Seg visualization

tests/
    test_tracking_flow.py           # Coordinate, selector, state machine, pipeline tests
    test_body_compensation.py       # Body motion compensation tests
    test_p2_improvements.py         # Telemetry, dynamics, graceful shutdown tests
    test_sil.py                     # MuJoCo SIL integration tests
    test_selector.py                # 🆕 WeightedTargetSelector unit tests (20+ cases)
    test_controller.py              # 🆕 TwoAxisGimbalController unit tests (30+ cases)
```

## Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Synthetic demo (no camera needed)
python run_demo.py

# 3. Live camera + YOLO-Seg + BoT-SORT
python run_yolo_cam.py

# 4. Video file + recording
python run_yolo_cam.py test_videos/xxx.mp4 --save

# 5. Custom config
python run_yolo_cam.py --config my_config.yaml

# 6. Tests
python -m pytest tests/ -v
```

## Coordinate Transform Chain

```
World (inertial frame)
  ↑ R_body2world — from dog IMU (roll, pitch, yaw)
Body (dog body frame)
  ↑ R_gimbal2body — from gimbal encoder feedback
Gimbal (gimbal frame)
  ↑ R_cam2gimbal — MountExtrinsics (static installation)
Camera (camera frame)
  ↑ K⁻¹, undistort — camera intrinsics inverse
Pixel (u, v)
```

Conventions:
- Camera: X-right, Y-down, Z-forward (OpenCV).
- Yaw positive = target right of boresight.
- Pitch positive = target above boresight.

## Configuration

All parameters are managed in `config.yaml`:
- **camera**: intrinsics, distortion, mount offsets
- **detector**: YOLO model, confidence, tracker, class whitelist
- **selector**: scoring weights, hold time, preferred classes
- **controller**: PID gains, scan pattern, latency compensation, ballistic, adaptive PID
- **driver_limits**: gimbal limits, friction, inertia

Use `build_pipeline_from_config(load_config("config.yaml"))` for config-driven pipeline creation.

## Documentation

| Document | Description |
|----------|-------------|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | System architecture, data flow, layer dependencies |
| [docs/CONFIGURATION.md](docs/CONFIGURATION.md) | All config fields: meaning, range, tuning guide |
| [docs/COORDINATE_MATH.md](docs/COORDINATE_MATH.md) | Full math derivation of the coordinate transform chain |
| [docs/HARDWARE_GUIDE.md](docs/HARDWARE_GUIDE.md) | Hardware selection, wiring, integration steps |
| [docs/WHY_CROSSHAIR_FIXED.md](docs/WHY_CROSSHAIR_FIXED.md) | FAQ: why the crosshair stays centered |
| [docs/TODO.md](docs/TODO.md) | Roadmap and pending improvements |
| [docs/ENHANCEMENT_PLAN.md](docs/ENHANCEMENT_PLAN.md) | 🆕 Detailed enhancement plan with priorities |
| [docs/TEAM_ANALYSIS_REPORT.md](docs/TEAM_ANALYSIS_REPORT.md) | 🆕 Comprehensive team analysis report |
| [docs/QUICK_START_NEW_FEATURES.md](docs/QUICK_START_NEW_FEATURES.md) | 🆕 Quick start guide for new features |
| [PROJECT_COMPLETION_SUMMARY.md](PROJECT_COMPLETION_SUMMARY.md) | 🆕 Project completion summary |

## License

Proprietary. All rights reserved.
