# RWS Vision-Gimbal Tracking — TODO

> 基于全项目代码审查的待办事项，按优先级和模块分类。

---

## P0 — Bug / 功能缺陷（必须修复）

### 控制层 (control)

- [x] **扫描模式实现错误** (`controller.py:247-250`) ✅ 已修复
  - 改为基于时间的正弦波扫描，频率 0.15Hz（约 6.7s 周期）。

- [x] **`assert error is not None` 生产环境不安全** (`controller.py:119`) ✅ 已修复
  - 改为防御性检查 `if error is None: return ControlCommand(...)`。

- [x] **Protocol 接口与实现签名不一致** (`control/interfaces.py` vs `controller.py`) ✅ 已修复
  - Protocol 中已加上 `body_state: Optional[BodyState] = None`。

### 坐标变换 (algebra)

- [x] **`FullChainTransform.target_lock_error` 逻辑冗余** (`coordinate_transform.py:346`) ✅ 已修复
  - 去掉多余的 world 正逆变换，直接从 body_dir 计算 desired gimbal angles。

### 感知层 (perception)

- [x] **`yolo_seg_tracker.py` 裸 `except Exception` 静默吞错** (`yolo_seg_tracker.py:286`) ✅ 已修复
  - 改为捕获具体异常类型（`IndexError`, `AttributeError`, `cv2.error`）。
  - 增加 `logger.warning()` 记录异常信息与 mask 索引，便于线上排查。

### 配置层 (config)

- [x] **`config.yaml` 与 `DetectorConfig` 字段不一致** ✅ 已修复
  - `DetectorConfig` 增加 `tracker: str = "botsort.yaml"` 字段。
  - `_nested_dict_to_config` 增加 `_warn_unknown_keys()` 辅助函数，对未知 YAML 字段发出 `WARNING` 日志。

### 资源管理

- [x] **`run_yolo_cam.py` 主循环资源泄漏** ✅ 已修复
  - 主循环包裹在 `try/finally` 中，确保 `cap.release()` 和 `writer.release()` 一定执行。
  - 配置迁移到 `config.yaml` 统一加载（支持 `--config` 参数指定配置文件）。

---

## P1 — 性能 / 鲁棒性改进（应该修复）

### 控制层

- [x] **体运动补偿被 LPF 平滑** (`controller.py:141-145`) ✅ 已修复
  - 体运动前馈补偿已移到 `_smooth_limit()` 之后，避免被 LPF 衰减。

- [x] **`_last_cmd` 状态切换时不重置** (`controller.py:237-245`) ✅ 已修复
  - 状态切换时（SEARCH→TRACK）重置 `_last_cmd = (0.0, 0.0)`。

- [x] **PID 首次调用微分跳变** (`controller.py:50`) ✅ 已修复
  - 增加 `first_call` 标志，首次调用时将 `prev_error` 初始化为当前 error。

- [x] **state 编码方式脆弱** (`controller.py:147`) ✅ 已修复
  - 使用固定映射 `_STATE_INDEX` 字典。

### 感知层 (perception)

- [x] **YoloSegTracker 立即清除丢失 track 的 Kalman 滤波器** (`yolo_seg_tracker.py:226-228`) ✅ 已修复
  - 增加 0.5s grace period，超时后再清除。

- [x] **YoloSegTracker.first_seen_ts 每帧都设为当前时间** (`yolo_seg_tracker.py:218`) ✅ 已修复
  - 维护 `_first_seen` 字典，只在首次出现时记录。

### 状态机 (decision)

- [x] **`_last_seen_ts` 初始化为 0.0** (`state_machine.py:28`) ✅ 已修复
  - 改为 `Optional[float] = None`，计算时特殊处理。

- [x] **没有 TRACK→SEARCH 的直接路径** (`state_machine.py`) ✅ 已修复
  - 增加跟踪质量评估，误差持续过大超过 `max_track_error_timeout_s` 时回退到 SEARCH。

### 可观测性 (observability)

- [x] **状态切换与目标切换缺少日志** ✅ 已修复
  - `controller.py`：状态切换时打 `INFO` 日志（`controller state: SEARCH -> TRACK`）。
  - `state_machine.py`：引入 `_transition()` 方法，状态变迁时打 `INFO` 日志。
  - `selector.py`：目标切换时打 `DEBUG` 日志（含旧/新 ID、分数、hold 时间）。
  - `driver.py`：命令下发和反馈读取路径均增加 `DEBUG` 日志。

- [x] **硬件层完全无日志** (`driver.py`) ✅ 已修复
  - `set_yaw_pitch_rate` 和 `get_feedback` 增加 `DEBUG` 级别日志（命令/反馈/时间戳）。

### 配置硬编码

- [x] **扫描模式参数硬编码** ✅ 已修复
  - `GimbalControllerConfig` 增加 `scan_freq_hz`、`scan_yaw_scale`、`scan_pitch_scale`、`scan_pitch_freq_ratio` 字段。
  - `_scan_command()` 改为读取配置字段，不再硬编码。

- [x] **状态机高误差倍数硬编码** ✅ 已修复
  - `GimbalControllerConfig` 增加 `high_error_multiplier: float = 5.0` 字段。
  - `state_machine.py` 改为使用 `self._cfg.high_error_multiplier` 计算高误差阈值。

- [x] **Selector 年龄归一化常数硬编码** ✅ 已修复
  - `SelectorConfig` 增加 `age_norm_frames: int = 60` 字段。
  - `selector.py` 改为使用 `self._cfg.age_norm_frames` 计算归一化值。

- [x] **自适应 PID 内部常数硬编码** ✅ 已修复
  - `AdaptivePIDConfig` 增加 `bbox_area_max: float = 50000.0` 和 `ki_distance_scale: float = 0.8`。
  - `DistanceBasedSchedulerConfig` 增加对应字段，`DistanceBasedScheduler` 改为读取配置。

- [x] **`pipeline/app.py` 工厂函数大量硬编码** ✅ 已修复
  - 新增 `camera_model_from_config()` 从 `CameraConfig` 构建 `CameraModel`。
  - 新增 `build_pipeline_from_config(cfg: SystemConfig)` 配置驱动的工厂函数（推荐入口）。
  - 原有工厂函数保留不变以保证向后兼容。

### 线程安全

- [x] **关键组件无并发保护** ✅ 已修复（遥测层）
  - `InMemoryTelemetryLogger`：`log()`、`snapshot_metrics()`、`export_jsonl()` 内部加 `threading.Lock`。
  - `FileTelemetryLogger`：`log()`、`snapshot_metrics()`、`close()` 内部加 `threading.Lock`。
  - `FileTelemetryLogger` 增加 `_closed` 标志，`close()` 后再调 `log()` 安全忽略不崩溃。
  - `SimulatedGimbalDriver` / `TwoAxisGimbalController` / `WeightedTargetSelector` 暂未加锁，待多线程化时再加。

---

## P2 — 架构 / 可维护性改进

### 控制层

- [x] **`_pixel_velocity_to_angular` 访问私有成员** (`controller.py:199`) ✅ 已修复
  - `PixelToGimbalTransform` 已暴露 `camera` 属性，controller 改用 `self._transform.camera`。

- [x] **`TargetObservation` 缺少加速度字段** ✅ 已修复
  - `Track` 和 `TargetObservation` 已增加 `acceleration_px_per_s2` 字段，YoloSegTracker 从 CA Kalman 获取加速度。

### 坐标变换

- [x] **`_undistort_and_normalize` 中 cv2 延迟导入** (`coordinate_transform.py:169`) ✅ 已修复
  - cv2 在 `__init__` 中导入并缓存为 `self._cv2`。

### 硬件层 (hardware)

- [ ] **缺少真实串口云台驱动**
  - `serial_driver.py` 已标记为 AD（已删除），目前只有 `SimulatedGimbalDriver`。
  - **修复方案**：实现基于串口协议的 `SerialGimbalDriver`，支持常见云台协议（如 PELCO-D/P、自定义协议）。

- [x] **SimulatedGimbalDriver 缺少动力学模型** ✅ 已修复
  - 增加一阶惯性环节（时间常数 `inertia_time_constant_s`）。
  - 增加静摩擦（`static_friction_dps`）和库仑摩擦（`coulomb_friction_dps`）模型。
  - 仿真更接近真实云台行为（惯性延迟 + 摩擦阻力）。

- [x] **`DriverLimits` 默认值应可配置** ✅ 已修复
  - `config.py` 新增 `DriverLimitsConfig` dataclass，`SystemConfig` 增加 `driver_limits` 字段。
  - `config.yaml` 新增 `driver_limits` 节（限位、速率、惯性、摩擦等参数）。
  - `DriverLimits` 增加 `from_config()` 类方法，`build_pipeline_from_config()` 从配置加载。

### 遥测层 (telemetry)

- [x] **InMemoryTelemetryLogger 无内存限制** ✅ 已修复
  - 增加 `max_events` 参数（`Optional[int]`），超出后自动丢弃最旧事件（环形缓冲区）。
  - 默认 `None`（无限制），可设置为固定值防止 OOM。

- [x] **缺少文件日志后端** ✅ 已实现
  - 新增 `FileTelemetryLogger`，支持实时写入 JSONL 文件（每个事件立即 flush）。
  - 支持追加模式（`append=True`）续写已有日志。
  - 支持上下文管理器（`with` 语句）自动关闭文件。

### 管线层 (pipeline)

- [ ] **pipeline.controller 类型为 `object`** (`pipeline.py:47`)
  - ~~`controller: object` 丢失了类型信息，IDE 无法提供补全。~~
  - ✅ 已修复：改为 `controller: GimbalController`。

- [x] **缺少优雅退出机制** ✅ 已实现
  - 增加 `install_signal_handlers()` 方法，捕获 SIGINT/SIGTERM 信号。
  - 增加 `should_stop()` 和 `stop()` 方法，支持主循环检查退出标志。
  - 增加 `cleanup()` 方法，确保文件日志等资源正确关闭。
  - `run_camera_demo()` 已集成优雅退出（Ctrl+C 或按 'q'）。

### 类型标注 (typing)

- [x] **`config.py` 中 `type: ignore[assignment]` 应消除** ✅ 已修复
  - `preferred_classes` 改为 `Optional[Dict[str, float]] = None`。
  - `controller` 改为 `Optional[GimbalControllerConfig] = None`。
  - 两处 `# type: ignore` 已移除。

- [x] **部分公开方法缺少类型注解** ✅ 已修复
  - `FileTelemetryLogger.__enter__` 返回 `"FileTelemetryLogger"`，`__exit__` 参数和返回类型补全。
  - `run_yolo_cam.py`：`parse_args()` 返回 `Tuple[...]`，`draw_overlay()` 参数类型补全，`color_for_id()` 返回 `Tuple[int, int, int]`。

### 入口脚本

- [x] **`run_yolo_cam.py` 配置与主系统脱节** ✅ 已修复
  - 检测参数（model_path、confidence、tracker、class_whitelist、img_size、device）全部从 `config.yaml` 加载。
  - 支持 `--config` 参数指定配置文件路径。
  - 仅保留可视化专属参数（MASK_ALPHA、OUTPUT_FPS、PREDICT_*）在脚本顶部。

### 文档

- [x] **缺少架构设计文档** ✅ 已完成
  - ✅ 创建 `docs/ARCHITECTURE.md`：系统架构总览、数据流图、层间依赖关系
  - ✅ Protocol 接口使用示例与扩展指南
  - ✅ 各层组件详细说明

- [x] **缺少配置字段说明文档** ✅ 已完成
  - ✅ 创建 `docs/CONFIGURATION.md`：所有配置字段完整说明
  - ✅ 字段含义、单位、取值范围、调参建议
  - ✅ 性能指标参考和常见问题解答

- [x] **缺少坐标变换数学推导文档** ✅ 已完成
  - ✅ 创建 `docs/COORDINATE_MATH.md`：完整数学推导
  - ✅ 坐标系定义、旋转矩阵约定、变换公式
  - ✅ 数值示例和误差分析

---

## P3 — 测试覆盖补充

- [ ] **缺少感知层单元测试**
  - `WeightedTargetSelector` 只有基本测试，缺少：多目标评分排序、class_bonus 权重、目标消失后重选逻辑。
  - `SimpleIoUTracker` 无独立测试。

- [ ] **缺少控制层单元测试**
  - PID 单独测试（阶跃响应、积分饱和、微分滤波）。
  - 延迟补偿效果验证。
  - 体运动补偿效果验证（独立于 pipeline）。

- [ ] **缺少硬件层测试**
  - `SimulatedGimbalDriver` 的限位、死区、积分精度测试。
  - `MockIMU` 各模式输出验证。

- [ ] **缺少 Kalman 滤波器测试**
  - CV/CA 滤波器的收敛性、预测精度、噪声抑制测试。

- [ ] **缺少集成测试场景**
  - 多目标交叉遮挡场景。
  - 目标快速机动（急转弯、加减速）场景。
  - 高延迟 / 低帧率降级场景。

- [ ] **缺少弹道补偿单元测试**
  - `SimpleBallisticModel`：边界输入（bbox 高度为 0、极大值）、二次函数拟合精度。
  - `TableBallisticModel`：插值精度、表长度不一致、外推边界行为。

- [ ] **缺少自适应 PID 单元测试**
  - `ErrorBasedScheduler`：增益连续性（边界处无跳变）、极端误差输入。
  - `DistanceBasedScheduler`：增益随距离的单调性、bbox_area 为 0 的防御。

- [ ] **缺少 `FullChainTransform` 端到端测试**
  - `target_lock_error` 完整链路：含 body_state + mount offset + 畸变的联合验证。
  - 正逆变换一致性：pixel → angle → pixel 往返误差应在亚像素级。

- [ ] **缺少 `FileTelemetryLogger` 边界测试**
  - `close()` 后再调 `log()` 的行为验证（应抛异常或静默忽略，不能崩溃）。
  - `snapshot_metrics` 在零事件时的返回值验证。
  - 追加模式下文件格式连续性验证。

- [ ] **缺少性能基准测试**
  - Pipeline 单帧端到端延迟 benchmark（含感知 + 决策 + 控制）。
  - 坐标变换单次调用耗时 benchmark。
  - 用于回归检测：版本迭代后性能不能下降超过阈值。
  - **工具建议**：`pytest-benchmark` 或手动 `time.perf_counter` 计时。

---

## P4 — 新功能 / 未来规划

### 移动平台集成（机器狗）

- [ ] **真实 IMU 驱动接口**
  - 对接机器狗 SDK 获取实时 body_state（roll/pitch/yaw + 角速度）。
  - 考虑 IMU 数据与视觉帧的时间同步问题。

- [ ] **多传感器融合**
  - IMU + 视觉的互补滤波或 EKF 融合，提高体姿态估计精度。

### 感知增强

- [ ] **目标重识别 (Re-ID)**
  - 当前 BoT-SORT 有基础 Re-ID，但遮挡后长时间丢失再出现时 ID 会变。
  - 考虑增加外观特征缓存，支持跨遮挡重识别。

- [ ] **多类别优先级策略**
  - 当前 `preferred_classes` 是静态权重，考虑支持动态优先级（如威胁评估）。

- [ ] **夜视 / 红外模态支持**
  - YOLO 模型需要针对红外图像微调，检测器需要支持多模态输入。

### 控制增强

- [x] **自适应 PID / 增益调度** ✅ 已实现
  - `ErrorBasedScheduler`：根据误差大小分段调整增益（小误差降低增益精确锁定，大误差提高增益快速追赶）。
  - `DistanceBasedScheduler`：根据目标距离调整增益（远距离提高增益补偿角分辨率下降）。
  - 配置：`AdaptivePIDConfig`，默认关闭（`enabled: False`）。

- [x] **弹道补偿** ✅ 已实现
  - `SimpleBallisticModel`：基于 bbox 高度估算距离，二次函数补偿（`a*d^2 + b*d + c`）。
  - `TableBallisticModel`：查找表插值，支持实测标定数据。
  - 配置：`BallisticConfig`，默认关闭（`enabled: False`）。

- [ ] **多目标同时跟踪与分配**
  - 当前架构为 `TargetSelector` 选出单一目标给单一控制器。
  - 若需要支持多云台 / 多武器站协同，需扩展为多目标分配策略（如匈牙利算法分配目标到多个执行器）。
  - 涉及 `TargetSelector` 接口变更和 `Pipeline` 多实例编排。

### 工具链

- [x] **实时可视化仪表盘** ✅ 已实现
  - `RealtimeDashboard`：基于 cv2 的轻量级四面板可视化（误差曲线、命令曲线、状态机、实时指标）。
  - 支持 10 秒滚动窗口，从 `InMemoryTelemetryLogger` 拉取数据。

- [ ] **自动化回归测试**
  - 录制真实场景视频 + 标注，作为回归测试数据集，CI 中自动运行。

- [ ] **全量数据录制与回放**
  - 当前 `TelemetryReplay` 只能回放遥测数据，无法录制原始视频帧 + 传感器数据。
  - 需要 rosbag 式的全量数据录制能力，支持端到端离线回放验证。
  - **方案**：录制时同步保存视频帧（压缩 H.264）+ IMU 数据 + 时间戳索引文件，回放时按时间戳同步喂入 pipeline。

### 运维与部署

- [ ] **CI/CD 集成**
  - 缺少 GitHub Actions / GitLab CI 配置文件。
  - 应覆盖：单元测试、`mypy` 类型检查、`ruff` / `flake8` 代码风格、依赖安全扫描。
  - SIL 测试（MuJoCo）可作为可选 stage（需要 GPU 或特定环境）。

- [ ] **配置热更新**
  - 当前配置在启动时一次性加载，运行中无法修改 PID 参数或切换模式。
  - **方案 A**：YAML 文件监听（`watchdog`），检测到变更后重新加载并通知各组件。
  - **方案 B**：暴露轻量 HTTP/gRPC API，支持运行时参数调整（适合远程调试）。

- [ ] **网络化遥测后端**
  - 当前 telemetry 只有 `InMemoryTelemetryLogger` 和 `FileTelemetryLogger`，缺少网络传输能力。
  - 无法实现远程实时监控、多机汇聚、告警推送等场景。
  - **方案**：新增 `MqttTelemetryLogger` 或 `GrpcStreamLogger`，实现 `TelemetryLogger` Protocol。

- [ ] **帧率自适应降级**
  - 当 YOLO 推理延迟过高导致帧率下降时，缺少自动降级策略。
  - **方案**：监测实际帧率，低于阈值时自动切换策略（降低输入分辨率 / 跳帧处理 / 切换轻量模型 / 降低 `confidence` 阈值以减少 NMS 耗时）。

---

## 已完成

- [x] 架构重构：坐标变换移入 `algebra/`，状态机移入 `decision/`
- [x] Protocol 驱动的依赖注入
- [x] YOLO-Seg + BoT-SORT 集成 (`YoloSegTracker`)
- [x] CA Kalman 滤波器（6 状态恒加速模型）
- [x] 体运动前馈补偿框架
- [x] 延迟补偿 + 丢失预测
- [x] PID 积分抗饱和 + 微分低通滤波 + 速度前馈
- [x] 遥测日志 + JSONL 导出 + 回放工具
- [x] PID 网格搜索调优工具
- [x] MuJoCo SIL 仿真测试
- [x] 弹道补偿（SimpleBallisticModel + TableBallisticModel）
- [x] 自适应 PID 增益调度（ErrorBasedScheduler + DistanceBasedScheduler）
- [x] 实时可视化仪表盘（RealtimeDashboard）
- [x] InMemoryTelemetryLogger 环形缓冲区（max_events 参数）
- [x] FileTelemetryLogger（实时写入 JSONL）
- [x] SimulatedGimbalDriver 动力学模型（一阶惯性 + 摩擦）
- [x] Pipeline 优雅退出机制（signal handlers + cleanup）
- [x] `yolo_seg_tracker.py` 裸 `except Exception` → 具体异常 + logger.warning
- [x] `DetectorConfig` 增加 `tracker` 字段，YAML 未知字段警告
- [x] `run_yolo_cam.py` 资源泄漏修复（try/finally）+ 配置统一加载
- [x] 全链路可观测性：controller / state_machine / selector / driver 增加日志
- [x] 扫描模式参数配置化（scan_freq_hz / scan_yaw_scale / scan_pitch_scale）
- [x] 状态机高误差倍数配置化（high_error_multiplier）
- [x] Selector 年龄归一化配置化（age_norm_frames）
- [x] 自适应 PID 常数配置化（bbox_area_max / ki_distance_scale）
- [x] `build_pipeline_from_config(SystemConfig)` 配置驱动工厂函数
- [x] Telemetry 线程安全（InMemoryTelemetryLogger + FileTelemetryLogger 加锁）
- [x] FileTelemetryLogger close 后安全忽略写入
- [x] DriverLimitsConfig + config.yaml driver_limits 节 + DriverLimits.from_config()
- [x] config.py type: ignore 消除（Optional 类型标注）
- [x] 公开方法类型注解补全（FileTelemetryLogger / run_yolo_cam.py）
- [x] `camera_model_from_config()` 从 CameraConfig 构建 CameraModel
