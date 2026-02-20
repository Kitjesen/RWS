# RWS 系统架构文档

## 概述

RWS (Robot Weapon Station) 是一个模块化的二自由度云台视觉跟踪系统，采用 Protocol 驱动的依赖注入架构，支持多种传感器和控制策略。

## 系统架构

### 层次结构

```
┌─────────────────────────────────────────────────────────────┐
│                     Application Layer                        │
│  (pipeline/app.py, run_yolo_cam.py, test scripts)           │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│                    Pipeline Orchestration                    │
│  VisionGimbalPipeline, MultiGimbalPipeline                  │
│  - 协调各层组件                                              │
│  - 管理数据流                                                │
│  - 信号处理和优雅退出                                         │
└─────────────────────────────────────────────────────────────┘
     ↓          ↓            ↓           ↓          ↓
┌─────────┐ ┌─────────┐ ┌──────────┐ ┌─────────┐ ┌─────────┐
│Perception│ │Decision │ │ Control  │ │Hardware │ │ Safety  │
│          │ │         │ │          │ │         │ │         │
│- Detector│ │- State  │ │- PID     │ │- Driver │ │- NFZ    │
│- Tracker │ │  Machine│ │- Ballist.│ │- IMU    │ │- Inter- │
│- Selector│ │- Threat │ │- Lead    │ │- Range- │ │  lock   │
│          │ │  Assess │ │  Angle   │ │  finder │ │- Safety │
│          │ │- Engage │ │- Traject.│ │         │ │  Mgr    │
│          │ │  Queue  │ │          │ │         │ │         │
└─────────┘ └─────────┘ └──────────┘ └─────────┘ └─────────┘
     ↓          ↓            ↓           ↓          ↓
┌─────────────────────────────────────────────────────────────┐
│                      Support Layers                          │
│  - Algebra (坐标变换, Kalman 滤波)                           │
│  - Telemetry (日志, 指标)                                    │
│  - Config (配置管理)                                         │
│  - API (REST + gRPC + 视频流)                                │
│  - Tools (仿真, 调优, 可视化)                                │
└─────────────────────────────────────────────────────────────┘
```

## 数据流

### 单云台跟踪流程（完整射击链路）

```
Frame (图像/检测)
    ↓
┌─────────────────┐
│   Detector      │  检测目标 (YOLO / Passthrough)
└─────────────────┘
    ↓ List[Detection]
┌─────────────────┐
│   Tracker       │  多目标跟踪 (BoT-SORT / SimpleIoU)
└─────────────────┘
    ↓ List[Track]
┌─────────────────┐                        ┌──────────────────┐
│   Selector      │  选择最优目标           │  ThreatAssessor  │
└─────────────────┘                        │  (威胁评估排序)  │
    ↓ TargetObservation (可选)              └────────┬─────────┘
                                                     ↓
┌─────────────────┐                        ┌──────────────────┐
│  State Machine  │  状态管理               │ EngagementQueue  │
│  SEARCH/TRACK/  │                        │  (交战队列)      │
│  LOCK/LOST      │                        └──────────────────┘
└─────────────────┘
    ↓ TrackState
┌─────────────────┐     ┌──────────────┐
│  Rangefinder    │────→│ DistanceFusion│──→ distance_m
│  (激光测距)     │     └──────────────┘        │
└─────────────────┘                             ↓
                                     ┌──────────────────┐
                                     │ PhysicsBallistic  │
                                     │ Model             │
                                     │ (飞行时间/下坠/   │
                                     │  风偏)            │
                                     └────────┬─────────┘
                                              ↓ flight_time_s
                                     ┌──────────────────┐
                                     │ LeadAngle        │
                                     │ Calculator       │
                                     │ (射击提前量)     │
                                     └────────┬─────────┘
                                              ↓ lead_yaw/pitch
┌─────────────────┐     ┌──────────────────────────────────┐
│  SafetyManager  │────→│  Controller (PID)                │
│  (NFZ + 联锁)   │     │  误差 = 目标角 + 弹道补偿 + 提前量 │
└─────────────────┘     │  + 体运动补偿 + 自适应增益         │
                        └──────────────────────────────────┘
    ↓ SafetyStatus          ↓ ControlCommand
                       ┌──────────────────┐
                       │ TrajectoryPlanner │ (多目标切换时平滑过渡)
                       └────────┬─────────┘
                                ↓ (yaw_rate, pitch_rate)
                       ┌──────────────────┐
                       │    Driver        │  云台驱动
                       └──────────────────┘
                                ↓ GimbalFeedback
                       ┌──────────────────┐
                       │  VideoStreamer   │  帧标注 + MJPEG/gRPC 推流
                       └──────────────────┘
```

### 距离信息流（Rangefinder 在架构中的位置）

```
                   ┌──────────────┐
                   │  Rangefinder │  硬件层: 物理传感器
                   │  (激光测距)  │
                   └──────┬───────┘
                          │
                   ┌──────┴───────┐
                   │ DistanceFusion│  硬件层: 激光优先 + bbox 兜底
                   └──────┬───────┘
                          │ distance_m (统一距离输出)
         ┌────────────────┼──────────────────┬────────────────┐
         ↓                ↓                  ↓                ↓
  ┌──────────────┐ ┌──────────────┐ ┌────────────────┐ ┌───────────┐
  │ Physics      │ │ LeadAngle    │ │ ThreatAssessor │ │ Adaptive  │
  │ Ballistic    │ │ Calculator   │ │ (距离评分)     │ │ PID       │
  │ (飞行时间/   │ │ (需要飞行   │ │                │ │ (距离增益)│
  │  下坠/风偏)  │ │  时间)       │ │                │ │           │
  └──────────────┘ └──────────────┘ └────────────────┘ └───────────┘
```

**关键原则**: 测距仪放在 `hardware/` 层（物理传感器归属），通过
`DistanceFusion` 统一出口提供距离数据，所有需要距离的下游模块
（弹道、提前量、威胁评估、自适应PID）从融合器获取，不再各自估距。

### 多云台协同流程

```
Frame
    ↓
Detector + Tracker (共享)
    ↓ List[Track]
┌─────────────────────────┐
│  MultiTargetSelector    │  选择 Top-N 目标
└─────────────────────────┘
    ↓ List[TargetObservation]
┌─────────────────────────┐
│   TargetAllocator       │  匈牙利算法分配
│  (Hungarian Algorithm)  │
└─────────────────────────┘
    ↓ List[TargetAssignment]
┌─────────────────────────┐
│  Multiple Controllers   │  每个云台独立控制
│  + Drivers              │
└─────────────────────────┘
```

## 核心组件

### 1. Perception Layer (感知层)

#### Detector Protocol
```python
class Detector(Protocol):
    def detect(self, frame: object, timestamp: float) -> List[Detection]:
        ...
```

**实现：**
- `PassthroughDetector`: 直接传递检测结果（用于仿真）
- `YoloDetector`: YOLO11n 目标检测
- `YoloSegTracker`: YOLO11n-Seg + BoT-SORT 组合（推荐）

#### Tracker Protocol
```python
class Tracker(Protocol):
    def update(self, detections: List[Detection], timestamp: float) -> List[Track]:
        ...
```

**实现：**
- `SimpleIoUTracker`: 基于 IoU 的简单跟踪器
- `YoloSegTracker`: 内置 BoT-SORT 跟踪（Kalman + Re-ID）

#### TargetSelector Protocol
```python
class TargetSelector(Protocol):
    def select(self, tracks: List[Track], timestamp: float) -> Optional[TargetObservation]:
        ...
```

**实现：**
- `WeightedTargetSelector`: 加权评分选择器
  - 权重：置信度、尺寸、中心距离、年龄、类别偏好
  - 防抖动：最小保持时间、切换惩罚

**多目标扩展：**
- `WeightedMultiTargetSelector`: 返回 Top-N 目标
- `TargetAllocator`: 匈牙利算法分配目标到多个云台

### 2. Decision Layer (决策层)

#### TrackStateMachine
状态机管理跟踪状态：

```
SEARCH ──────→ TRACK ──────→ LOCK
   ↑              ↓             ↓
   └──────────── LOST ←─────────┘
```

**状态转换条件：**
- `SEARCH → TRACK`: 检测到目标
- `TRACK → LOCK`: 误差 < threshold 且持续 > hold_time
- `LOCK → TRACK`: 误差 > threshold
- `TRACK/LOCK → LOST`: 目标丢失
- `LOST → SEARCH`: 超时或误差过大

#### ThreatAssessor (威胁评估)
多维度威胁评分模型：
```
threat_score = w_dist · f_dist(d) + w_vel · f_vel(v) + w_class · f_class(c)
             + w_head · f_head(θ) + w_size · f_size(A)
```

**评估维度：**
- 距离分量：指数衰减 `exp(-d / decay)`
- 接近速度：目标朝我方运动的速度径向分量
- 类别威胁：可配置等级（如 vehicle > person）
- 朝向分量：运动方向与我方的余弦相似度
- 目标大小：bbox 面积归一化

#### EngagementQueue (交战队列)
管理交战序列：
- **三种排序策略**：`threat_first`（威胁优先）/ `nearest_first`（最近优先）/ `sector_sweep`（扇区扫清）
- 目标连续性保持：当前目标在新评估中仍存在则不跳转
- `advance()` / `skip()` / `reset()` 控制交战流程

### 3. Control Layer (控制层)

#### TwoAxisGimbalController

**核心功能：**
1. **坐标变换**: 像素 → 相机系 → 云台系
2. **PID 控制**: 双轴独立 PID
   - 积分抗饱和
   - 微分低通滤波
   - 速度前馈
3. **延迟补偿**: 根据目标速度外推位置
4. **体运动补偿**: 前馈补偿机器人本体角速度
5. **弹道补偿**: 补偿弹道下坠（可选，含物理弹道模型）
6. **自适应 PID**: 根据误差/距离动态调整增益（可选）

**控制方程：**
```
u(t) = Kp·e(t) + Ki·∫e(τ)dτ + Kd·de/dt + Kv·v_target - ω_body
```

其中：
- `e(t)`: 角度误差（含弹道补偿 + 射击提前量）
- `v_target`: 目标角速度（前馈）
- `ω_body`: 机器人本体角速度（补偿）

#### PhysicsBallisticModel (物理弹道)

RK4 积分求解弹丸三维运动方程：
```
ma = F_gravity + F_drag(Cd, ρ, v) + F_wind
```
- G1/G7 标准阻力曲线
- 环境修正（温度/气压/湿度 → 空气密度 ρ）
- 输出：飞行时间 + 下坠补偿角 + 风偏补偿角

#### LeadAngleCalculator (射击提前量)

预测弹丸飞行期间目标的位移：
```
predicted_pos = current_pos + v · t_flight + 0.5 · a · t_flight²
lead_angle = angle(predicted_pos) - angle(current_pos)
```
- 迭代收敛：飞行时间 ↔ 距离 ↔ 预测位置互依赖
- 置信度 = 速度稳定性 × 加速度平稳度 × 飞行时间合理性

#### GimbalTrajectoryPlanner (轨迹规划)

多目标切换时的平滑运动规划：
```
速率 ^
     |  /‾‾‾‾\          ← 梯形曲线 (长距离)
     | /      \
     |/        \
     +----------→ 时间

     |  /\              ← 三角曲线 (短距离)
     | /  \
     |/    \
     +------→ 时间
```
- 双轴同步、防抖切换

### 4. Hardware Layer (硬件层)

#### GimbalDriver Protocol
```python
class GimbalDriver(Protocol):
    def set_yaw_pitch_rate(self, yaw_rate_dps: float, pitch_rate_dps: float, timestamp: float) -> None:
        ...
    def get_feedback(self, timestamp: float) -> GimbalFeedback:
        ...
```

**实现：**
- `SimulatedGimbalDriver`: 仿真驱动（含动力学模型）
  - 一阶惯性
  - 静摩擦 + 库仑摩擦
  - 限位保护
- `SerialGimbalDriver`: 串口驱动（待实现）

#### BodyMotionProvider Protocol
```python
class BodyMotionProvider(Protocol):
    def get_body_state(self, timestamp: float) -> Optional[BodyState]:
        ...
```

**实现：**
- `MockIMU`: 仿真 IMU（正弦波、随机游走、静止）

#### RangefinderProvider Protocol (激光测距)
```python
class RangefinderProvider(Protocol):
    def measure(self, timestamp: float) -> RangefinderReading: ...
    def get_last_reading(self) -> RangefinderReading: ...
```

**实现：**
- `SimulatedRangefinder`: 基于 bbox 估距 + 高斯噪声 + 随机失败
- `DistanceFusion`: 激光优先、bbox 兜底的距离融合策略

**数据流向：** Rangefinder → DistanceFusion → 弹道模型 / 提前量 / 威胁评估

### 5.5. Safety Layer (安全层)

独立安全模块，不依赖 pipeline 主循环。

#### NoFireZoneManager
- 圆形禁射区管理（`no_fire` / `caution`）
- 缓冲带渐进降速（靠近边界线性减速至 0）

#### SafetyInterlock
7 项联锁 AND 逻辑：操作员授权 / 心跳超时 / 通信自检 / 传感器自检 / 目标锁定时间 / 射程范围 / 禁射区

#### SafetyManager
组合 NFZ + Interlock 的统一入口：
```python
status = safety_mgr.evaluate(yaw, pitch, locked, lock_time, distance)
if status.fire_authorized:
    # 允许射击
```

### 5. Algebra Layer (数学层)

#### PixelToGimbalTransform
坐标变换链：
```
Pixel (u, v)
    ↓ 去畸变 (可选)
Normalized Camera Coords (xn, yn)
    ↓ 相机内参逆变换
Camera Ray Direction (X, Y, Z)
    ↓ 相机-云台旋转矩阵
Gimbal Frame Direction
    ↓ atan2
Angular Error (yaw_deg, pitch_deg)
```

#### Kalman Filters
- `ConstantVelocityKalman2D`: CV 模型（4 状态）
- `ConstantAccelerationKalman2D`: CA 模型（6 状态）

### 6. Telemetry Layer (遥测层)

#### TelemetryLogger Protocol
```python
class TelemetryLogger(Protocol):
    def log(self, event_type: str, timestamp: float, payload: Dict[str, float]) -> None:
        ...
    def snapshot_metrics(self) -> Dict[str, float]:
        ...
```

**实现：**
- `InMemoryTelemetryLogger`: 内存日志（支持环形缓冲区）
- `FileTelemetryLogger`: 实时写入 JSONL 文件

**关键指标：**
- `lock_rate`: 锁定率（LOCK 状态占比）
- `avg_abs_error_deg`: 平均绝对误差
- `switches_per_min`: 目标切换频率

## 配置系统

### 配置层次

```yaml
camera:           # 相机内参
  width, height, fx, fy, cx, cy
  distortion_k1, k2, p1, p2, k3
  mount_roll_deg, mount_pitch_deg, mount_yaw_deg

detector:         # 检测器参数
  model_path, confidence_threshold
  class_whitelist, device, img_size

selector:         # 选择器权重
  weights:
    confidence, size, center_proximity, track_age, class_weight
  min_hold_time_s, delta_threshold
  preferred_classes

controller:       # 控制器参数
  yaw_pid: {kp, ki, kd, ...}
  pitch_pid: {kp, ki, kd, ...}
  lock_error_threshold_deg
  lock_hold_time_s
  ballistic: {enabled, model_type, ...}
  adaptive_pid: {enabled, scheduler_type, ...}

driver_limits:    # 云台限位
  yaw_min_deg, yaw_max_deg
  pitch_min_deg, pitch_max_deg
  max_rate_dps
  inertia_time_constant_s
  static_friction_dps, coulomb_friction_dps

# ---- v1.1.0 新增 ----

projectile:       # 弹丸物理参数
  muzzle_velocity_mps, ballistic_coefficient
  projectile_mass_kg, projectile_diameter_m
  drag_model: "g1"  # g1 | g7

environment:      # 射击环境
  temperature_c, pressure_hpa, humidity_pct
  wind_speed_mps, wind_direction_deg, altitude_m

lead_angle:       # 射击提前量
  enabled, use_acceleration, max_lead_deg
  min_confidence, velocity_smoothing_alpha

trajectory:       # 云台轨迹规划
  enabled, max_rate_dps, max_acceleration_dps2
  settling_threshold_deg, min_switch_interval_s

engagement:       # 威胁评估与交战排序
  enabled, strategy: "threat_first"
  weights: {distance, velocity, class_threat, heading, size}
  max_engagement_range_m, min_threat_threshold

safety:           # 安全系统
  enabled
  interlock: {require_operator_auth, min_lock_time_s, ...}
  nfz_slow_down_margin_deg
  zones: [{zone_id, center_yaw_deg, radius_deg, zone_type}, ...]

rangefinder:      # 激光测距
  enabled, type: "simulated"
  max_range_m, noise_std_m, max_laser_age_s

video_stream:     # 视频流传输
  enabled, jpeg_quality, max_fps, scale_factor
  annotate_detections, annotate_tracks, annotate_crosshair
```

### 配置加载

```python
from src.rws_tracking.config import load_config

cfg = load_config("config.yaml")
pipeline = build_pipeline_from_config(cfg)
```

## 扩展点

### 1. 添加新的检测器

```python
class MyDetector:
    def detect(self, frame: object, timestamp: float) -> List[Detection]:
        # 实现检测逻辑
        return detections

# 使用
pipeline = VisionGimbalPipeline(
    detector=MyDetector(),
    ...
)
```

### 2. 添加新的跟踪器

```python
class MyTracker:
    def update(self, detections: List[Detection], timestamp: float) -> List[Track]:
        # 实现跟踪逻辑
        return tracks
```

### 3. 添加新的选择策略

```python
class MySelector:
    def select(self, tracks: List[Track], timestamp: float) -> Optional[TargetObservation]:
        # 实现选择逻辑
        return best_target
```

### 4. 添加新的硬件驱动

```python
class MyGimbalDriver:
    def set_yaw_pitch_rate(self, yaw_rate_dps: float, pitch_rate_dps: float, timestamp: float) -> None:
        # 发送命令到硬件
        pass

    def get_feedback(self, timestamp: float) -> GimbalFeedback:
        # 读取硬件反馈
        return GimbalFeedback(...)
```

## 性能考虑

### 实时性
- **目标帧率**: 30 Hz (33ms/frame)
- **YOLO 推理**: ~20-30ms (GPU)
- **控制计算**: <1ms
- **总延迟**: ~35-40ms

### 内存管理
- `InMemoryTelemetryLogger`: 使用 `max_events` 限制内存
- `YoloSegTracker`: 自动清理过期 Kalman 滤波器

### 线程安全
- `InMemoryTelemetryLogger`: 内置 `threading.Lock`
- `FileTelemetryLogger`: 内置 `threading.Lock`
- 其他组件：单线程使用（pipeline 主循环）

## 测试策略

### 单元测试
- 坐标变换精度
- PID 响应特性
- 状态机转换逻辑
- Kalman 滤波器收敛性

### 集成测试
- 端到端 pipeline 流程
- 体运动补偿效果
- 多目标场景

### 仿真测试
- `WorldCoordinateScene`: 真实物理仿真
- `SimulatedGimbalDriver`: 动力学仿真
- MuJoCo SIL: 机器人全身仿真

## 部署建议

### 开发环境
```bash
# 安装依赖
pip install -r requirements.txt

# 运行测试
python test_simple.py
python test_realistic_sim.py
python test_multi_gimbal.py
```

### 生产环境
```bash
# 使用配置文件
python run_yolo_cam.py --config config.yaml

# 或使用 API
from src.rws_tracking.config import load_config
from src.rws_tracking.pipeline.app import build_pipeline_from_config

cfg = load_config("config.yaml")
pipeline = build_pipeline_from_config(cfg)
```

## 故障排查

### Lock Rate 低
1. 检查 PID 参数（增大 Kp）
2. 放宽 `lock_error_threshold_deg`
3. 启用自适应 PID
4. 检查目标移动速度

### 目标频繁切换
1. 增大 `min_hold_time_s`
2. 增大 `switch_penalty`
3. 调整类别权重

### 云台震荡
1. 减小 Kp
2. 增大 `command_lpf_alpha`
3. 增大 `derivative_lpf_alpha`

## 相关文档

- [CONFIGURATION.md](CONFIGURATION.md) — 配置字段详解
- [COORDINATE_MATH.md](COORDINATE_MATH.md) — 坐标变换数学推导
- [HARDWARE_GUIDE.md](HARDWARE_GUIDE.md) — 硬件集成指南
- [WHY_CROSSHAIR_FIXED.md](WHY_CROSSHAIR_FIXED.md) — 准心不动的原理与验证
- [TODO.md](TODO.md) — 改进计划与待办事项
