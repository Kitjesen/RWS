# RWS Vision-Gimbal Tracking — TODO

> 基于全项目代码审查的待办事项，按优先级和模块分类。
> 已完成条目汇总见文末 [已完成清单](#已完成清单)。

---

## P2 — 架构 / 可维护性改进

### 硬件层 (hardware)

- [ ] **缺少真实串口云台驱动**
  - 目前只有 `SimulatedGimbalDriver`。
  - **方案**：实现基于串口协议的 `SerialGimbalDriver`，支持常见云台协议（PELCO-D/P、自定义协议）。

### 管线层 (pipeline)

- [ ] **pipeline.controller 类型为 `object`** (`pipeline.py:47`)
  - `controller: object` 丢失了类型信息，IDE 无法提供补全。
  - 应改为 `controller: GimbalController`。

---

## P3 — 测试覆盖补充

- [ ] **感知层单元测试**
  - `WeightedTargetSelector` 缺少：多目标评分排序、class_bonus 权重、目标消失后重选。
  - `SimpleIoUTracker` 无独立测试。

- [ ] **控制层单元测试**
  - PID 阶跃响应、积分饱和、微分滤波。
  - 延迟补偿 & 体运动补偿效果验证。

- [ ] **硬件层测试**
  - `SimulatedGimbalDriver` 限位、死区、积分精度。
  - `MockIMU` 各模式输出验证。

- [ ] **Kalman 滤波器测试**
  - CV/CA 滤波器收敛性、预测精度、噪声抑制。

- [ ] **集成测试场景**
  - 多目标交叉遮挡。
  - 目标快速机动（急转弯、加减速）。
  - 高延迟 / 低帧率降级。

- [ ] **弹道补偿单元测试**
  - `SimpleBallisticModel`：边界输入（bbox 高度为 0、极大值）、二次函数拟合精度。
  - `TableBallisticModel`：插值精度、表长度不一致、外推边界。

- [ ] **自适应 PID 单元测试**
  - `ErrorBasedScheduler`：增益连续性（边界无跳变）、极端误差输入。
  - `DistanceBasedScheduler`：增益随距离单调性、bbox_area 为 0 的防御。

- [ ] **`FullChainTransform` 端到端测试**
  - `target_lock_error` 含 body_state + mount offset + 畸变联合验证。
  - 正逆变换一致性：pixel → angle → pixel 往返误差应在亚像素级。

- [ ] **`FileTelemetryLogger` 边界测试**
  - `close()` 后再调 `log()` 行为验证。
  - `snapshot_metrics` 零事件返回值验证。
  - 追加模式下文件格式连续性验证。

- [ ] **性能基准测试**
  - Pipeline 单帧端到端延迟 benchmark（含感知 + 决策 + 控制）。
  - 坐标变换单次调用耗时 benchmark。
  - 用于回归检测：版本迭代后性能不能下降超过阈值。
  - 工具建议：`pytest-benchmark` 或手动 `time.perf_counter` 计时。

---

## P4 — 新功能 / 未来规划

### 移动平台集成（机器狗）

- [ ] **真实 IMU 驱动接口**
  - 对接机器狗 SDK 获取实时 body_state（roll/pitch/yaw + 角速度）。
  - 考虑 IMU 数据与视觉帧的时间同步。

- [ ] **多传感器融合**
  - IMU + 视觉互补滤波或 EKF 融合，提高体姿态估计精度。

### 感知增强

- [ ] **目标重识别 (Re-ID)**
  - 遮挡后长时间丢失再出现时 ID 会变。
  - 考虑增加外观特征缓存，支持跨遮挡重识别。

- [ ] **多类别优先级策略**
  - 当前 `preferred_classes` 是静态权重，考虑动态优先级（如威胁评估）。

- [ ] **夜视 / 红外模态支持**
  - YOLO 模型需针对红外图像微调，检测器支持多模态输入。

### 控制增强

- [ ] **多目标同时跟踪与分配**
  - 当前为单目标 → 单控制器。
  - 多云台 / 多武器站协同需扩展为多目标分配策略（匈牙利算法）。
  - 涉及 `TargetSelector` 接口变更和 `Pipeline` 多实例编排。

### 工具链

- [ ] **自动化回归测试**
  - 录制真实场景视频 + 标注，作为回归数据集，CI 中自动运行。

- [ ] **全量数据录制与回放**
  - 当前 `TelemetryReplay` 仅回放遥测数据，无法录制原始视频帧 + 传感器数据。
  - 方案：录制同步保存视频帧（H.264）+ IMU + 时间戳索引，回放时按时间戳喂入 pipeline。

### 运维与部署

- [ ] **CI/CD 集成**
  - 覆盖：单元测试、`mypy` 类型检查、`ruff` / `flake8` 代码风格、依赖安全扫描。
  - SIL 测试（MuJoCo）可作为可选 stage。

- [ ] **配置热更新**
  - 方案 A：YAML 文件监听（`watchdog`），检测到变更后重新加载。
  - 方案 B：轻量 HTTP/gRPC API，支持运行时参数调整。

- [ ] **网络化遥测后端**
  - 新增 `MqttTelemetryLogger` 或 `GrpcStreamLogger`，实现远程实时监控。

- [ ] **帧率自适应降级**
  - 监测实际帧率，低于阈值时自动降级（降低分辨率 / 跳帧 / 切换轻量模型）。

---

## 已完成清单

> 以下条目已合并完成，按模块汇总。

### P0 — Bug / 功能缺陷（全部已修复）

| 模块 | 修复内容 |
|------|---------|
| control | 扫描模式改为时间正弦波；`assert error` 改为防御性检查；Protocol 签名对齐 |
| algebra | `FullChainTransform.target_lock_error` 去掉冗余正逆变换 |
| perception | 裸 `except Exception` 改为具体异常 + `logger.warning` |
| config | `DetectorConfig` 增加 `tracker` 字段；YAML 未知字段警告 |
| 资源管理 | `run_yolo_cam.py` 资源泄漏修复（try/finally）+ 配置统一加载 |

### P1 — 性能 / 鲁棒性改进（全部已修复）

| 模块 | 修复内容 |
|------|---------|
| control | 体运动补偿移到 LPF 之后；状态切换重置 `_last_cmd`；PID 首次微分跳变修复；state 编码用字典 |
| perception | Kalman 滤波器增加 0.5s grace period；`first_seen_ts` 只记录首次 |
| decision | `_last_seen_ts` 改为 Optional；增加 TRACK→SEARCH 路径 |
| observability | controller/state_machine/selector/driver 全链路日志 |
| config | 扫描参数、高误差倍数、年龄归一化、自适应 PID 常数全部配置化 |
| 线程安全 | InMemoryTelemetryLogger + FileTelemetryLogger 加锁 |

### P2 — 架构 / 可维护性改进（大部分已完成）

| 模块 | 完成内容 |
|------|---------|
| control | `_pixel_velocity_to_angular` 改用公开属性；`TargetObservation` 增加加速度字段 |
| algebra | cv2 延迟导入改为 `__init__` 缓存 |
| hardware | SimulatedGimbalDriver 增加动力学模型；DriverLimits 配置化 |
| telemetry | InMemoryTelemetryLogger 环形缓冲区；FileTelemetryLogger 实现 |
| pipeline | 优雅退出机制（signal handlers + cleanup） |
| typing | `type: ignore` 消除；公开方法类型注解补全 |
| 入口脚本 | `run_yolo_cam.py` 配置与主系统统一 |
| 文档 | ARCHITECTURE.md、CONFIGURATION.md、COORDINATE_MATH.md |

### P4 — 新功能（已实现部分）

| 功能 | 说明 |
|------|-----|
| 自适应 PID | ErrorBasedScheduler + DistanceBasedScheduler |
| 弹道补偿 | SimpleBallisticModel + TableBallisticModel |
| 实时仪表盘 | RealtimeDashboard（cv2 四面板可视化） |
| 配置工厂 | `build_pipeline_from_config(SystemConfig)` |
| `camera_model_from_config()` | 从 CameraConfig 构建 CameraModel |
