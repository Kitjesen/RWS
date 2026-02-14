# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

---

## [Unreleased]

---

## [1.0.0] — 2026-02-14

### Added — 运动基座补偿 + 全链路代码质量提升

#### 运动基座补偿（机器狗集成）

- **`BodyMotionProvider` Protocol**（`hardware/imu_interface.py`）— 体态数据抽象接口
- **Mock IMU 实现**（`hardware/mock_imu.py`）：`StaticBodyMotion`、`SinusoidalBodyMotion`、`ReplayBodyMotion`
- **`FullChainTransform`**（`algebra/coordinate_transform.py`）— pixel → camera → gimbal → body → world 全链路坐标变换
- **前馈补偿**：`compute_command()` 增加可选 `body_state` 参数，IMU 前馈抵消 ~90% 体动
- **MuJoCo 运动基座 SIL**：`tools/sim/` 新增 moving-base 仿真模型

#### 弹道补偿 & 自适应 PID

- **`SimpleBallisticModel`**：基于 bbox 高度估算距离，二次函数补偿
- **`TableBallisticModel`**：查找表插值，支持实测标定数据
- **`ErrorBasedScheduler`**：根据误差大小分段调整 PID 增益
- **`DistanceBasedScheduler`**：根据目标距离调整 PID 增益

#### 可观测性 & 遥测

- **全链路日志**：controller / state_machine / selector / driver 增加 `logging` 日志
- **`FileTelemetryLogger`**：实时写入 JSONL 文件（每事件 flush）
- **`InMemoryTelemetryLogger` 环形缓冲区**：`max_events` 参数防止 OOM
- **`RealtimeDashboard`**：cv2 四面板实时可视化（误差/命令/状态/指标）

#### 配置体系升级

- **`DetectorConfig` 增加 `tracker` 字段**，与 `config.yaml` 统一
- **`DriverLimitsConfig`**：云台限位/动力学参数可通过 config.yaml 配置
- **扫描参数配置化**：`scan_freq_hz` / `scan_yaw_scale` / `scan_pitch_scale`
- **`high_error_multiplier`**：状态机高误差判断倍数可配置
- **`age_norm_frames`**：Selector 年龄归一化帧数可配置
- **`bbox_area_max` / `ki_distance_scale`**：自适应 PID 常数可配置
- **`build_pipeline_from_config(SystemConfig)`**：配置驱动工厂函数
- **`_warn_unknown_keys()`**：YAML 未知字段警告
- **`type: ignore` 消除**：改用 `Optional` 类型标注

#### 鲁棒性 & 线程安全

- **异常处理**：`yolo_seg_tracker.py` 裸 `except Exception` 改为具体异常 + 日志
- **资源安全**：`run_yolo_cam.py` 主循环 `try/finally` 防止资源泄漏
- **线程安全**：`InMemoryTelemetryLogger` / `FileTelemetryLogger` 加 `threading.Lock`
- **`FileTelemetryLogger` close 后安全忽略写入**

#### 云台仿真增强

- **一阶惯性环节**（`inertia_time_constant_s`）
- **摩擦模型**：静摩擦（`static_friction_dps`）+ 库仑摩擦（`coulomb_friction_dps`）

#### 工具链

- **PID 网格搜索调优**（`tools/tuning.py`）
- **YOLO 微调训练脚本**（`tools/training/train.py`）
- **遥测回放**（`tools/replay.py`）
- **MuJoCo SIL 仿真测试**（`tools/sim/`）

### Changed

- `run_yolo_cam.py` 从 `config.yaml` 统一加载配置（支持 `--config` 参数）
- `pipeline/app.py` 新增 `camera_model_from_config()` 和 `build_pipeline_from_config()`
- `DriverLimits` 增加 `from_config()` 类方法
- `state_machine.py` 提取 `_transition()` 方法，状态变迁时打日志

### Fixed

- `yolo_seg_tracker.py` 裸 `except Exception` 静默吞错 → 具体异常 + `logger.warning`
- `config.yaml` `detector.tracker` 字段加载后被静默丢弃 → `DetectorConfig` 增加字段
- `run_yolo_cam.py` 主循环异常时 VideoCapture/VideoWriter 泄漏 → `try/finally`
- `config.py` `type: ignore[assignment]` × 2 处 → `Optional` 类型标注
- 扫描参数 / 状态机倍数 / Selector 归一化常数 / 自适应 PID 常数硬编码 → 配置化

---

## [0.2.0] — 2026-02-13

### Added — YOLO-Seg + Kalman 轨迹预测

- **YOLO11n-Seg 实例分割**：替代 bbox 检测，mask 轮廓更紧凑
- **BoT-SORT 多目标跟踪**：Kalman 平滑 bbox + ReID，稳定 track ID
- **6-state CA Kalman 滤波器**（`CentroidKalmanCA`）：恒加速模型，支持抛物线轨迹预测
- **cv2.moments 亚像素质心**：提升测量精度
- **视频输入 & 录制**：`run_yolo_cam.py` 支持文件输入、`--save` 录制输出
- **自适应跳帧**：视频播放匹配推理帧率

### Changed

- `YoloSegTracker` 内部集成 Kalman 滤波（替代 EMA + 滑窗速度估计）
- `WeightedTargetSelector` 优先使用 `mask_center`
- `TwoAxisGimbalController` 优先使用 `mask_center` 进行误差估计

---

## [0.1.0] — 2026-02-12

### Added — 初始架构

- **分层架构**：`perception` / `control` / `hardware` / `telemetry` / `pipeline` / `algebra` / `decision`
- **YOLO11n 目标检测**：via `ultralytics`
- **SimpleIoUTracker**：IoU 关联 + 速度估计
- **WeightedTargetSelector**：多目标加权评分 + 防抖
- **TwoAxisGimbalController**：双轴 PID + 积分抗饱和 + 微分 LPF + 速度前馈 + 延迟补偿
- **TrackStateMachine**：SEARCH → TRACK → LOCK → LOST 状态机
- **PixelToGimbalTransform**：像素到云台角误差（含畸变校正、安装外参）
- **SimulatedGimbalDriver**：软限位仿真驱动
- **InMemoryTelemetryLogger**：内存日志 + JSONL 导出
- **MuJoCo SIL 仿真**：闭环控制测试（GroundTruthDetector / YOLO）
- **YAML 配置系统**：`config.yaml` 集中管理参数
- **pytest 测试套件**：19 个单元测试
