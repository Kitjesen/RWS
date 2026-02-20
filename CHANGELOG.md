# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

---

## [Unreleased]

---

## [1.2.0] — 2026-02-18

### Added — 完整射击链路集成 + 工厂函数 + 端到端测试

#### Pipeline 集成 (`pipeline/pipeline.py`)

- **`VisionGimbalPipeline.step()`** 扩展为 12 步完整射击链路：
  detect/track → 威胁评估 → 目标选择 → 距离融合 → 弹道解算
  → 提前量 → 安全检查 → PID 控制 → 安全限速 → 驱动 → 遥测 → 推帧
- 所有扩展组件通过构造函数可选注入，默认 `None` = 不启用（零回归）
- **`PipelineOutputs`** 扩展：新增 `tracks`、`threat_assessments`、
  `ballistic_solution`、`lead_angle`、`safety_status`、`distance_m` 字段
- 提前量叠加到 PID 输出之后（角速度追加）
- 弹道风偏补偿叠加到 yaw 通道
- 安全系统靠近禁射区时自动降速

#### 工厂函数 (`pipeline/app.py`)

- **`build_pipeline_from_config()`** 全面扩展：
  根据 `SystemConfig` 各 section 的 `enabled` 标志自动创建并注入：
  - ThreatAssessor + EngagementQueue
  - SimulatedRangefinder + DistanceFusion
  - PhysicsBallisticModel (pipeline 级完整弹道解)
  - LeadAngleCalculator + SimpleFlightTimeProvider (fallback)
  - SafetyManager (含 config → 模块类型桥接)
  - GimbalTrajectoryPlanner
  - FrameBuffer + FrameAnnotator

#### Controller 增强 (`control/controller.py`)

- 弹道模型新增 `"physics"` 类型：直接在 controller 内使用 `PhysicsBallisticModel`
- `BallisticConfig` 新增 `muzzle_velocity_mps`、`bc_g7`、`mass_kg`、`caliber_m` 字段

#### 提前量计算增强 (`control/lead_angle.py`)

- 新增 **`SimpleFlightTimeProvider`**：`t = d / v` 简易飞行时间估算，
  作为无物理弹道模型时的 fallback

#### 包导出 (`__init__.py`)

- 顶层 `__init__.py` 使用 `__getattr__` lazy import 模式，
  避免 cv2/ultralytics 在仅需核心类型时被拉入
- `pipeline/__init__.py` 同样改为 lazy import
- 新增导出：`build_pipeline_from_config`、`SystemConfig`、`load_config`、
  各扩展模块核心类

#### 配置系统 (`config.py` + `config.yaml`)

- `BallisticConfig` 新增 Physics 模型参数
- `ProjectileConfig` 新增 `enabled` 字段
- `RangefinderConfig` 新增 `failure_rate`、`target_height_m` 字段
- `save_config()` 使用递归 `_tuples_to_lists()` 替代逐字段转换，
  彻底修复 tuple → YAML roundtrip 问题
- `config.yaml` 补全所有 v1.1 扩展配置节（含注释示例）

#### 集成测试 (`tests/test_shooting_chain.py`) — 新文件

- 18 个测试用例覆盖完整射击链路：
  - 各模块独立单元测试（威胁评估 / 测距 / 弹道 / 提前量 / 安全 / 轨迹）
  - 端到端 pipeline 集成测试（有目标 / 无目标 / 30帧收敛 / 输出类型）
- 直接导入各模块，绕过 cv2/ultralytics 依赖，快速执行（~12s）

---

## [1.1.0] — 2026-02-17

### Added — 射击链路补全 + 安全系统 + 视频流传输

#### 物理弹道模型 (`control/ballistic.py`)

- **`PhysicsBallisticModel`**：RK4 四阶积分求解弹丸三维运动方程
  - G1/G7 标准阻力曲线（马赫数 → 阻力系数查表插值）
  - 重力下坠 + 空气阻力 + 风偏（横风/纵风分解）
  - 温度/气压/湿度/海拔 → 空气密度修正
  - 输出完整 `BallisticSolution`：飞行时间、下坠角、风偏角、着靶速度
- **`estimate_distance_from_bbox()`**：距离估算工具函数提取复用
- **`FullBallisticSolver` Protocol**：完整弹道解算接口

#### 射击提前量 (`control/lead_angle.py`) — 新模块

- **`LeadAngleCalculator`**：融合目标运动预测与弹丸飞行时间
  - 匀加速预测：`pred = pos + v·t_flight + 0.5·a·t_flight²`
  - 迭代收敛（飞行时间 ↔ 预测位置 ↔ 距离互依赖，3 轮收敛）
  - 置信度评估（速度稳定性 × 加速度变化 × 飞行时间 × 检测置信度）
  - 速度指数平滑，防止噪声导致提前量抖动
- **`FlightTimeProvider` Protocol**：飞行时间提供者接口
- **`LeadAngleConfig`**：提前量配置项

#### 云台轨迹规划 (`control/trajectory.py`) — 新模块

- **`GimbalTrajectoryPlanner`**：多目标切换时的平滑运动规划
  - 梯形速度曲线（加速-匀速-减速），短距离退化为三角曲线
  - 双轴同步（长轴决定总时间，短轴等比降速匹配）
  - 最小切换间隔防抖、到达阈值判定
  - `TrajectoryPhase` 枚举：IDLE / ACCELERATING / CRUISE / DECELERATING / COMPLETE
- **`plan_trapezoid()` / `sample_trapezoid()`**：可独立使用的轨迹计算工具函数

#### 威胁评估与交战排序 (`decision/engagement.py`) — 新模块

- **`ThreatAssessor`**：5 维度加权威胁打分
  - 距离分量（指数衰减）、接近速度分量（径向投影）、类别威胁等级、朝向余弦相似度、目标大小
  - 可配置权重 `ThreatWeights`
- **`EngagementQueue`**：交战队列管理
  - 三种排序策略：`threat_first` / `nearest_first` / `sector_sweep`
  - `advance()` / `skip()` / `reset()` 控制交战流程
  - 目标连续性保持：当前目标在新评估中仍存在则不跳转

#### 安全系统 (`safety/`) — 新模块

- **`NoFireZoneManager`**（`safety/no_fire_zone.py`）：
  - 圆形禁射区管理（`no_fire` / `caution` 两种类型）
  - 动态增删区域、角距计算、缓冲带渐进降速
- **`SafetyInterlock`**（`safety/interlock.py`）：
  - 7 项联锁条件 AND 逻辑：操作员授权 / 心跳超时 / 通信自检 / 传感器自检 / 目标锁定 / 射程范围 / 禁射区
  - `InterlockResult` 详细阻止原因诊断
- **`SafetyManager`**（`safety/manager.py`）：
  - 统一安全入口，组合 NFZ + Interlock
  - `evaluate()` 输出 `SafetyStatus`（fire_authorized / blocked_reason / emergency_stop）
  - `get_speed_factor()` 提供接近禁射区时的速度限制因子

#### 激光测距 (`hardware/rangefinder.py`) — 新模块

- **`RangefinderProvider` Protocol**：激光测距仪抽象接口
- **`SimulatedRangefinder`**：基于 bbox 估距 + 高斯噪声 + 随机失败 + 信号强度模拟
- **`DistanceFusion`**：激光优先、bbox 兜底的距离信息融合策略

#### 视频流传输 (`api/video_stream.py`) — 新模块

- **`FrameBuffer`**：线程安全环形帧缓冲（push 不阻塞，get 阻塞等待）
- **`FrameAnnotator`**：帧标注叠加（检测框/跟踪 ID/速度向量/准星/状态文字）
- **`MJPEGStreamer`**：MJPEG over HTTP 流生成器（`multipart/x-mixed-replace`）
- **`GrpcFrameEncoder`**：gRPC 帧编码辅助
- **REST 新端点**：
  - `GET /api/video/feed` — MJPEG 视频流（浏览器可直接 `<img src>` 播放）
  - `GET /api/video/snapshot` — 单帧 JPEG 快照
  - `GET /api/video/config` — 当前视频流配置

#### gRPC 协议扩展 (`api/tracking.proto`)

- `StreamFrames` RPC：服务端流式推送标注帧（JPEG + 检测结果元数据）
- `GetSafetyStatus` RPC：查询安全系统状态
- `SetOperatorAuth` RPC：设置操作员授权
- `EmergencyStop` RPC：紧急停止
- `GetThreatAssessment` RPC：获取威胁评估结果
- 新消息类型：`VideoFrame`、`DetectedTarget`、`BoundingBoxMsg`、`ThreatTarget` 等

#### 数据类型扩展 (`types.py`)

- `ProjectileParams`：弹丸物理参数（出膛速度/弹道系数/质量/口径/阻力模型）
- `EnvironmentParams`：射击环境参数（温度/气压/湿度/风速风向/海拔）
- `BallisticSolution`：弹道解算结果（飞行时间/下坠角/风偏角/着靶速度）
- `LeadAngle`：射击提前量结果（yaw/pitch 提前角 + 预测命中点 + 置信度）
- `ThreatAssessment`：威胁评估结果（5 维度分量 + 综合评分 + 排名）
- `SafetyZone` / `SafetyStatus`：安全区域定义 + 系统安全状态
- `RangefinderReading`：激光测距仪读数

#### 全局配置扩展 (`config.py`)

`SystemConfig` 新增 8 个配置节（均支持 YAML 加载）：

| 配置节 | 模块 |
|--------|------|
| `projectile` | 弹丸物理参数 |
| `environment` | 射击环境参数 |
| `lead_angle` | 提前量计算 |
| `trajectory` | 轨迹规划 |
| `engagement` | 威胁评估 |
| `safety` | 安全系统（含联锁 + 禁射区列表）|
| `rangefinder` | 激光测距 |
| `video_stream` | 视频流传输 |

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
