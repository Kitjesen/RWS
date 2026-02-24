# RWS Vision-Gimbal Tracking — TODO

> 基于全项目代码审查的待办事项，按优先级和模块分类。
> 已完成条目汇总见文末 [已完成清单](#已完成清单)。

---

## 已完成 (本会话)

以下功能在本会话中确认实现并已合并，按模块汇总。

| 功能 | 说明 |
|------|-----|
| **API wiring** | pipeline 扩展组件（shooting_chain、audit_logger、health_monitor、safety_manager、iff_checker）通过 `_wire_pipeline_extensions()` 注入 `app.extensions`；`/api/tracking/start` 和 `/api/tracking/stop` 作为 Flutter 兼容 URL 别名已注册 |
| **NFZ zone persistence** | `safety_routes.py` 实现禁射区持久化：区域通过 POST /api/safety/zones 写入磁盘，服务重启后由 `load_persisted_zones()` 在 pipeline 启动时自动恢复 |
| **SSE event wiring** | `pipeline.py` 直接调用 `event_bus.emit()` 发送 `threat_detected`（高威胁新目标入队）、`target_neutralized`（lifecycle 标记中和）、`health_degraded`（子系统降级）、`safety_triggered`（联锁阻断射击）四类事件；其余事件由对应路由和 watchdog 发送 |
| **Prometheus gimbal metrics** | `metrics_routes.py` 在 Prometheus 文本格式中暴露云台位置（yaw_deg、pitch_deg）及跟踪误差（yaw_error_deg、pitch_error_deg）指标，供 GET /metrics 拉取 |
| **Flutter polling backoff** | Flutter 仪表盘侧已实现指数退避轮询：连续错误后拉取间隔自动延长，避免后端过载 |
| **Bearer token auth + rate limiting** | `server.py` 实现 `RWS_API_KEY` 环境变量驱动的 Bearer token 认证中间件（`hmac.compare_digest` 常数时间比较）；火控端点令牌桶限速 30 req/min/IP；`/api/health`、`/api/events`、`/metrics`、`/api/video/*` 豁免认证 |
| **GimbalTrajectoryPlanner wiring** | `pipeline.step()` 第 8b 步：检测到 `track_id` 变更时调用 `set_target()` 触发梯形轨迹规划；轨迹激活期间以 `get_rate_command()` 完全覆盖 PID 输出；`metadata["trajectory_active"]` 标记激活帧 |
| **MultiGimbalPipeline HTTP stub** | `multi_routes.py` 提供 `/api/multi/*` HTTP 存根端点；`docs/architecture/overview.md` 多云台协同流程图已更新 |
| **Flutter PreflightWidget** | Flutter 前飞检查清单组件 `PreflightWidget` 已实现，调用 GET /api/selftest 展示 7 子系统 go/no-go 状态 |
| **Flutter SSE handlers** | Flutter AlertBannerOverlay 已订阅并处理 `fire_executed`（射击执行）、`target_designated`（目标指定）、`config_reloaded`（配置热重载）事件 |
| **gRPC parity** | gRPC 服务器从 14 个 RPC 扩展至 29 个，新增火控（arm/safe/request/heartbeat/designate）、任务管理（start/end）、NFZ CRUD（add/remove/list）等接口，与 REST API 对等 |
| **config.yaml defaults** | `config.yaml` 中 `safety.enabled` 和 `engagement.enabled` 默认值改为 `true`，新部署无需手动开启 |

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
  - `PhysicsBallisticModel`：与解析解对比、风偏精度、RK4 收敛性。

- [ ] **射击提前量单元测试**
  - `LeadAngleCalculator`：静止目标提前量为 0、匀速目标置信度、加速度影响。
  - 迭代收敛验证。

- [ ] **轨迹规划单元测试**
  - 梯形/三角曲线参数正确性、双轴同步、时间采样一致性。

- [ ] **威胁评估单元测试**
  - `ThreatAssessor`：多目标排序稳定性、各分量权重线性组合验证。
  - `EngagementQueue`：advance/skip/reset 逻辑。

- [ ] **安全系统单元测试**
  - `NoFireZoneManager`：区域内外判定、缓冲带降速因子。
  - `SafetyInterlock`：各联锁条件 AND 逻辑、心跳超时。
  - `SafetyManager`：NFZ + interlock 联合检查。

- [ ] **视频流单元测试**
  - `FrameBuffer`：线程安全、满缓冲丢弃策略。
  - `MJPEGStreamer`：帧率限制、编码正确性。

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
  - 弹道解算 (PhysicsBallisticModel) 单次调用耗时。
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

- [ ] **3D 位置估计**
  - 当前仅 2D 图像空间，考虑双目/LiDAR 融合实现 3D 目标定位。

### 控制增强

- [ ] **物理弹道模型实弹标定**
  - `PhysicsBallisticModel` 已实现 RK4 积分求解，需实弹测试标定阻力系数。
  - 与查表模型对比验证精度。

- [ ] **弹道-提前量集成优化**
  - 当前弹道补偿和提前量分别计算，考虑联合优化（弹道+运动预测+风偏一体化）。

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

- [ ] **帧率自适应降级**
  - 监测实际帧率，低于阈值时自动降级（降低分辨率 / 跳帧 / 切换轻量模型）。

### 安全增强

- [ ] **敌我识别 (IFF) 集成**
  - 结合目标 Re-ID + 类别分类 + 外部 IFF 信号，防止误击友方。

- [ ] **多操作员协同**
  - 支持多操作员分别控制不同云台，权限隔离。

- [ ] **审计日志**
  - 所有射击授权/拒绝事件、操作员操作、安全事件记录到不可篡改日志。

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

### P4 — 新功能（已实现）

| 功能 | 说明 |
|------|-----|
| 自适应 PID | ErrorBasedScheduler + DistanceBasedScheduler |
| 弹道补偿 | SimpleBallisticModel + TableBallisticModel |
| **物理弹道模型** | PhysicsBallisticModel — RK4 积分、G1/G7 阻力曲线、风偏、环境参数 |
| **射击提前量** | LeadAngleCalculator — 目标运动预测 + 弹丸飞行时间融合、置信度评估 |
| **云台轨迹规划** | GimbalTrajectoryPlanner — 梯形速度曲线、双轴同步、防抖切换 |
| **威胁评估** | ThreatAssessor — 多维度威胁打分（距离/速度/类别/朝向/大小） |
| **交战排序** | EngagementQueue — 按威胁/距离/扇区三种策略排序，队列管理 |
| **安全系统** | SafetyManager = NoFireZoneManager + SafetyInterlock（禁射区/联锁/紧急停止） |
| **激光测距** | RangefinderProvider + SimulatedRangefinder + DistanceFusion 距离融合 |
| **视频流传输** | MJPEG over HTTP + gRPC 帧流 + FrameBuffer + FrameAnnotator |
| 实时仪表盘 | RealtimeDashboard（cv2 四面板可视化） |
| 配置工厂 | `build_pipeline_from_config(SystemConfig)` |
| `camera_model_from_config()` | 从 CameraConfig 构建 CameraModel |
| **全局配置扩展** | SystemConfig 新增 8 个配置节（弹丸/环境/提前量/轨迹/交战/安全/测距/视频流） |
| **射击链路集成** | pipeline.step() 扩展为 12 步完整数据流（感知→评估→选择→距离→弹道→提前量→安全→PID→限速→驱动→遥测→推帧） |
| **工厂函数增强** | build_pipeline_from_config() 自动创建注入全部扩展组件，config 驱动开关 |
| **Lazy Import** | 顶层/pipeline `__init__` 改为 `__getattr__` 惰性导入，避免 cv2/ultralytics 被意外拉入 |
| **save_config 修复** | tuple→list 递归转换，修复 YAML roundtrip 失败 |
| **集成测试** | test_shooting_chain.py — 18 用例覆盖全链路端到端 |
| ✅ **API wiring** | pipeline 扩展组件注入 app.extensions；/api/tracking/* URL 别名 |
| ✅ **NFZ zone persistence** | 禁射区磁盘持久化 + 启动时自动恢复 |
| ✅ **SSE event wiring** | threat_detected / target_neutralized / health_degraded / safety_triggered 事件接入 pipeline |
| ✅ **Prometheus gimbal metrics** | 云台位置与跟踪误差指标暴露至 /metrics |
| ✅ **Flutter polling backoff** | 指数退避轮询，连续错误自动降频 |
| ✅ **Bearer token auth + rate limiting** | RWS_API_KEY Bearer 认证 + 火控端点 30 req/min 限速 |
| ✅ **GimbalTrajectoryPlanner wiring** | pipeline.step() 第 8b 步目标切换检测 + 梯形轨迹覆盖 PID |
| ✅ **MultiGimbalPipeline HTTP stub** | /api/multi/* 端点 + 架构文档更新 |
| ✅ **Flutter PreflightWidget** | 前飞检查清单组件，调用 /api/selftest |
| ✅ **Flutter SSE handlers** | fire_executed / target_designated / config_reloaded 事件处理 |
| ✅ **gRPC parity (14→29 RPCs)** | 火控、任务、NFZ 接口补全，REST/gRPC 对等 |
| ✅ **config.yaml defaults** | safety/engagement 默认 enabled: true |
