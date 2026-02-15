# RWS Vision-Gimbal Tracking (2-DOF)

Lightweight non-ROS2 system for visual target pursuit and lock-on
with a yaw/pitch gimbal, powered by **YOLO11n-Seg + BoT-SORT**.

Supports **moving-base operation** (robot dog) with IMU feedforward compensation.

## 🆕 最新更新 (v1.1.0)

- ✅ **真实硬件支持** - 串口云台驱动 + 真实 IMU 接口
- ✅ **配置热更新** - 运行时调整参数，无需重启
- ✅ **CI/CD 集成** - 自动化测试和代码质量检查（全部通过 ✓）
- ✅ **测试增强** - 150+ 测试用例，覆盖率 28%+
- ✅ **代码质量** - Ruff 检查通过，Mypy 类型检查通过
- 📖 **文档完善** - 10+ 篇技术文档

👉 查看 [docs/CI_FINAL_STATUS.md](docs/CI_FINAL_STATUS.md) 了解 CI/CD 详情

[![CI](https://github.com/Kitjesen/RWS/workflows/CI/badge.svg)](https://github.com/Kitjesen/RWS/actions)

## Project Structure

```
RWS/
├── src/rws_tracking/           # 核心源代码
│   ├── types.py                # 全局数据结构定义
│   ├── interfaces.py           # 协议接口（统一导出）
│   ├── config.py               # 配置数据类 + YAML 加载/保存
│   │
│   ├── algebra/                # 数学/几何模块
│   │   ├── coordinate_transform.py  # 坐标转换链：pixel → camera → gimbal → body → world
│   │   └── kalman2d.py              # 2D 卡尔曼滤波器（CV/CA 模型）
│   │
│   ├── perception/             # 感知层
│   │   ├── interfaces.py       # Detector/Tracker/TargetSelector 协议
│   │   ├── yolo_detector.py    # YOLO11n 推理
│   │   ├── yolo_seg_tracker.py # YOLO-Seg + BoT-SORT 组合跟踪器
│   │   ├── passthrough_detector.py  # 仿真检测器适配器
│   │   ├── tracker.py          # SimpleIoUTracker
│   │   ├── selector.py         # 多目标加权评分 + 防抖动
│   │   ├── multi_target_selector.py  # 多目标选择器
│   │   └── rotating_selector.py      # 轮转选择器
│   │
│   ├── decision/               # 决策层
│   │   └── state_machine.py    # 状态机：SEARCH → TRACK → LOCK → LOST
│   │
│   ├── control/                # 控制层
│   │   ├── interfaces.py       # GimbalController 协议
│   │   ├── controller.py       # 双轴 PID + 前馈 + 延迟补偿
│   │   ├── adaptive.py         # 自适应 PID 增益调度
│   │   └── ballistic.py        # 弹道补偿模型
│   │
│   ├── hardware/               # 硬件执行层
│   │   ├── interfaces.py       # GimbalDriver 协议
│   │   ├── driver.py           # 仿真云台驱动（含动力学模型）
│   │   ├── serial_driver.py    # ✨ 串口云台驱动（真实硬件）
│   │   ├── imu_interface.py    # BodyMotionProvider 协议
│   │   ├── mock_imu.py         # 静态/正弦/回放 IMU 模拟器
│   │   └── robot_imu.py        # ✨ 真实 IMU 接口
│   │
│   ├── telemetry/              # 遥测层
│   │   ├── interfaces.py       # TelemetryLogger 协议
│   │   └── logger.py           # 内存 + 文件日志器（线程安全）
│   │
│   ├── pipeline/               # 编排层
│   │   ├── pipeline.py         # VisionGimbalPipeline（端到端循环）
│   │   ├── multi_gimbal_pipeline.py  # 多云台管道
│   │   └── app.py              # 构建辅助函数和演示入口
│   │
│   └── tools/                  # 工具集
│       ├── simulation.py       # 合成场景生成器
│       ├── tuning.py           # PID 网格搜索调优器
│       ├── replay.py           # 遥测回放
│       ├── dashboard.py        # 实时 cv2 仪表板
│       ├── config_reload.py    # ✨ 配置热重载
│       ├── sim/                # MuJoCo SIL 仿真
│       │   ├── mujoco_env.py
│       │   ├── mujoco_camera.py
│       │   ├── mujoco_driver.py
│       │   ├── ground_truth_detector.py
│       │   └── run_sil.py
│       └── training/           # YOLO 微调脚本
│           └── train.py
│
├── tests/                      # 测试套件
│   ├── benchmarks/             # 性能基准测试
│   │   └── test_performance.py
│   ├── test_tracking_flow.py   # 坐标、选择器、状态机、管道测试
│   ├── test_body_compensation.py  # 机体运动补偿测试
│   ├── test_coordinate_transform.py  # 坐标转换测试
│   ├── test_controller.py      # ✨ 控制器单元测试（30+ 用例）
│   ├── test_selector.py        # ✨ 选择器单元测试（20+ 用例）
│   ├── test_kalman.py          # 卡尔曼滤波器测试
│   ├── test_p2_improvements.py # 遥测、动力学、优雅关闭测试
│   └── test_sil.py             # MuJoCo SIL 集成测试
│
├── docs/                       # 文档
│   ├── ARCHITECTURE.md         # 系统架构、数据流、层依赖
│   ├── CONFIGURATION.md        # 配置字段说明和调优指南
│   ├── COORDINATE_MATH.md      # 坐标转换链数学推导
│   ├── HARDWARE_GUIDE.md       # 硬件选型、接线、集成步骤
│   ├── WHY_CROSSHAIR_FIXED.md  # FAQ：为什么十字准星固定
│   ├── TODO.md                 # 路线图和待改进项
│   ├── CI_FIX_SUMMARY.md       # ✨ CI/CD 修复过程报告
│   └── CI_FINAL_STATUS.md      # ✨ CI/CD 最终状态报告
│
├── .github/workflows/          # CI/CD 配置
│   └── ci.yml                  # GitHub Actions 工作流
│
├── config.yaml                 # 系统配置文件
├── pyproject.toml              # 项目元数据和工具配置
├── requirements.txt            # Python 依赖
├── run_demo.py                 # 快速合成演示入口
├── run_yolo_cam.py             # 实时相机/视频 + YOLO-Seg 可视化
└── README.md                   # 本文件
```

## Quick Start

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 合成演示（无需相机）
python run_demo.py

# 3. 实时相机 + YOLO-Seg + BoT-SORT
python run_yolo_cam.py

# 4. 视频文件 + 录制
python run_yolo_cam.py test_videos/xxx.mp4 --save

# 5. 自定义配置
python run_yolo_cam.py --config my_config.yaml

# 6. 运行测试
pytest tests/ -v

# 7. 运行特定测试
pytest tests/test_controller.py -v          # 控制器测试
pytest tests/test_coordinate_transform.py -v # 坐标转换测试
pytest tests/test_kalman.py -v              # 卡尔曼滤波器测试

# 8. 运行性能基准测试
pytest tests/benchmarks/ -v --benchmark-only

# 9. 生成测试覆盖率报告
pytest tests/ --cov=src/rws_tracking --cov-report=html
# 查看报告：open htmlcov/index.html
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
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | 系统架构、数据流、层依赖关系 |
| [docs/CONFIGURATION.md](docs/CONFIGURATION.md) | 配置字段说明、范围、调优指南 |
| [docs/COORDINATE_MATH.md](docs/COORDINATE_MATH.md) | 坐标转换链完整数学推导 |
| [docs/HARDWARE_GUIDE.md](docs/HARDWARE_GUIDE.md) | 硬件选型、接线、集成步骤 |
| [docs/WHY_CROSSHAIR_FIXED.md](docs/WHY_CROSSHAIR_FIXED.md) | FAQ：为什么十字准星保持居中 |
| [docs/TODO.md](docs/TODO.md) | 路线图和待改进项 |
| [docs/CI_FIX_SUMMARY.md](docs/CI_FIX_SUMMARY.md) | ✨ CI/CD 修复过程详细报告 |
| [docs/CI_FINAL_STATUS.md](docs/CI_FINAL_STATUS.md) | ✨ CI/CD 最终状态和解决方案 |

## 测试说明

### 测试文件位置

所有测试文件位于 `tests/` 目录：

```
tests/
├── benchmarks/                 # 性能基准测试
│   └── test_performance.py     # 坐标转换、卡尔曼滤波器性能测试
├── test_body_compensation.py   # 机体运动补偿测试
├── test_controller.py          # 控制器单元测试（30+ 用例）
├── test_coordinate_transform.py # 坐标转换测试
├── test_kalman.py              # 卡尔曼滤波器测试（92% 覆盖率）
├── test_p2_improvements.py     # 遥测、动力学、优雅关闭测试
├── test_selector.py            # 选择器单元测试（20+ 用例）
├── test_sil.py                 # MuJoCo SIL 集成测试
└── test_tracking_flow.py       # 端到端跟踪流程测试
```

### 运行测试

```bash
# 运行所有测试
pytest tests/ -v

# 运行特定模块测试
pytest tests/test_controller.py -v

# 运行带覆盖率报告
pytest tests/ --cov=src/rws_tracking --cov-report=html

# 运行性能基准测试
pytest tests/benchmarks/ -v --benchmark-only

# 并行运行测试（更快）
pytest tests/ -v -n auto
```

### CI/CD 状态

项目配置了完整的 CI/CD 流程，每次推送自动运行：

- ✅ **代码质量检查**：Ruff linter + formatter
- ✅ **类型检查**：Mypy 静态类型分析
- ✅ **安全扫描**：Safety 依赖漏洞检查
- ✅ **多版本测试**：Python 3.9, 3.10, 3.11

查看最新 CI 状态：https://github.com/Kitjesen/RWS/actions

## License

Proprietary. All rights reserved.
