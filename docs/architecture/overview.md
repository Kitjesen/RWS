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
         ↓              ↓              ↓              ↓
┌──────────────┐ ┌──────────────┐ ┌──────────────┐ ┌──────────────┐
│  Perception  │ │   Decision   │ │   Control    │ │   Hardware   │
│              │ │              │ │              │ │              │
│ - Detector   │ │ - State      │ │ - PID        │ │ - Driver     │
│ - Tracker    │ │   Machine    │ │ - Transform  │ │ - IMU        │
│ - Selector   │ │              │ │ - Ballistic  │ │              │
└──────────────┘ └──────────────┘ └──────────────┘ └──────────────┘
         ↓              ↓              ↓              ↓
┌─────────────────────────────────────────────────────────────┐
│                      Support Layers                          │
│  - Algebra (坐标变换, Kalman 滤波)                           │
│  - Telemetry (日志, 指标)                                    │
│  - Config (配置管理)                                         │
│  - Tools (仿真, 调优, 可视化)                                │
└─────────────────────────────────────────────────────────────┘
```

## 数据流

### 单云台跟踪流程

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
┌─────────────────┐
│   Selector      │  选择最优目标
└─────────────────┘
    ↓ TargetObservation (可选)
┌─────────────────┐
│  State Machine  │  状态管理 (SEARCH/TRACK/LOCK/LOST)
└─────────────────┘
    ↓ TrackState
┌─────────────────┐
│  Controller     │  PID 控制 + 坐标变换
└─────────────────┘
    ↓ ControlCommand (yaw_rate, pitch_rate)
┌─────────────────┐
│    Driver       │  云台驱动
└─────────────────┘
    ↓ GimbalFeedback (yaw_deg, pitch_deg)
```

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
5. **弹道补偿**: 补偿弹道下坠（可选）
6. **自适应 PID**: 根据误差/距离动态调整增益（可选）

**控制方程：**
```
u(t) = Kp·e(t) + Ki·∫e(τ)dτ + Kd·de/dt + Kv·v_target - ω_body
```

其中：
- `e(t)`: 角度误差
- `v_target`: 目标角速度（前馈）
- `ω_body`: 机器人本体角速度（补偿）

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
