# RWS 项目结构

## 根目录

```
RWS/
├── README.md               # 项目主文档
├── CHANGELOG.md            # 变更日志
├── docs/CONTRIBUTING.md    # 贡献指南
├── docs/CODE_OF_CONDUCT.md # 行为准则
├── docs/SECURITY.md        # 安全政策
├── docs/SUPPORT.md         # 支持渠道
├── config.yaml             # 系统配置
├── requirements.txt        # Python 依赖
├── pyproject.toml          # 项目元数据 + 工具配置
├── .gitignore
├── .gitattributes
└── .editorconfig
```

## 源代码 (`src/rws_tracking/`)

按领域解耦，每层通过 `interfaces.py` 定义 Protocol 约束。

```
src/rws_tracking/
├── __init__.py             # 顶层导出 + lazy import
├── interfaces.py           # 向后兼容：汇总各层 Protocol
│
├── types/                  # 数据类型（按领域拆分）
│   ├── common.py           #   BoundingBox, TrackState
│   ├── perception.py       #   Detection, Track, TargetObservation
│   ├── control.py          #   GimbalFeedback, ControlCommand, TargetError
│   ├── hardware.py         #   BodyState, RangefinderReading
│   ├── ballistic.py        #   ProjectileParams, BallisticSolution, LeadAngle
│   ├── decision.py         #   ThreatAssessment
│   └── safety.py           #   SafetyZone, SafetyStatus
│
├── config/                 # 配置（按领域拆分 + YAML loader）
│   ├── perception.py       #   SelectorConfig, DetectorConfig
│   ├── control.py          #   PIDConfig, GimbalControllerConfig, ...
│   ├── decision.py         #   EngagementConfig, ThreatWeightsConfig
│   ├── hardware.py         #   DriverLimitsConfig, RangefinderConfig
│   ├── safety.py           #   SafetyConfig, SafetyInterlockCfg
│   ├── environment.py      #   CameraConfig, ProjectileConfig, EnvironmentConfig
│   ├── api.py              #   VideoStreamCfg
│   └── loader.py           #   SystemConfig, load_config(), save_config()
│
├── algebra/                # 数学 / 几何
│   ├── coordinate_transform.py   # CameraModel, PixelToGimbalTransform
│   └── kalman2d.py               # 2D Kalman 滤波器
│
├── perception/             # 感知层（接口 → 实现）
│   ├── interfaces.py       #   Detector, Tracker, TargetSelector Protocol
│   ├── yolo_detector.py    #   YoloDetector
│   ├── yolo_seg_tracker.py #   YoloSegTracker (BoT-SORT)
│   ├── tracker.py          #   SimpleIoUTracker
│   ├── selector.py         #   WeightedTargetSelector
│   ├── passthrough_detector.py
│   ├── rotating_selector.py
│   ├── multi_target.py
│   └── multi_target_selector.py
│
├── decision/               # 决策层
│   ├── interfaces.py       #   ThreatAssessorProtocol, EngagementQueueProtocol
│   ├── state_machine.py    #   TrackStateMachine (SEARCH→TRACK→LOCK→LOST)
│   └── engagement.py       #   ThreatAssessor, EngagementQueue
│
├── control/                # 控制层
│   ├── interfaces.py       #   GimbalController, BallisticSolverProtocol,
│   │                       #   LeadCalculatorProtocol, StateMachineProtocol, ...
│   ├── controller.py       #   TwoAxisGimbalController (PID + 状态机注入)
│   ├── adaptive.py         #   自适应 PID 增益调度
│   ├── ballistic.py        #   Simple/Table/Physics 弹道模型
│   ├── lead_angle.py       #   LeadAngleCalculator (射击提前量)
│   └── trajectory.py       #   GimbalTrajectoryPlanner (S-curve / Trapezoidal)
│
├── hardware/               # 硬件抽象层
│   ├── interfaces.py       #   GimbalDriver, GimbalAxisDriver, CompositeGimbalDriver
│   ├── driver.py           #   SimulatedGimbalDriver
│   ├── serial_driver.py    #   SerialGimbalDriver (PELCO-D/P)
│   ├── imu_interface.py    #   BodyMotionProvider Protocol
│   ├── robot_imu.py        #   RobotIMUProvider (Unitree/Spot/Serial)
│   ├── mock_imu.py         #   MockBodyMotionProvider (测试用)
│   └── rangefinder.py      #   RangefinderProvider, SimulatedRangefinder, DistanceFusion
│
├── safety/                 # 安全系统
│   ├── interfaces.py       #   SafetyEvaluatorProtocol
│   ├── manager.py          #   SafetyManager (统一入口)
│   ├── interlock.py        #   SafetyInterlock (联锁条件)
│   └── no_fire_zone.py     #   NoFireZoneManager (禁射区)
│
├── pipeline/               # 编排层（composition root）
│   ├── pipeline.py         #   VisionGimbalPipeline (完整射击链路)
│   ├── protocols.py        #   FrameBufferProtocol, FrameAnnotatorProtocol
│   ├── app.py              #   工厂函数 + demo 入口
│   └── multi_gimbal_pipeline.py  # 多云台协同
│
├── telemetry/              # 遥测日志
│   ├── interfaces.py       #   TelemetryLogger Protocol
│   └── logger.py           #   InMemoryTelemetryLogger
│
├── api/                    # REST / gRPC 服务
│   ├── server.py           #   Flask REST + MJPEG 端点
│   ├── client.py           #   REST 客户端
│   ├── grpc_server.py      #   gRPC 服务端
│   ├── grpc_client.py      #   gRPC 客户端
│   ├── video_stream.py     #   FrameBuffer, FrameAnnotator
│   ├── tracking.proto      #   Protobuf 定义
│   ├── tracking_pb2.py     #   生成代码
│   └── tracking_pb2_grpc.py
│
└── tools/                  # 仿真 / 调优 / 回放
    ├── simulation.py       #   WorldCoordinateScene
    ├── tuning.py           #   PID 网格搜索
    ├── replay.py           #   遥测回放
    ├── dashboard.py        #   实时仪表盘
    ├── config_reload.py    #   运行时配置热加载
    └── sim/                #   MuJoCo SIL 仿真
        ├── mujoco_env.py
        ├── mujoco_driver.py
        ├── mujoco_camera.py
        ├── run_sil.py
        └── assets/         #   MJCF 模型文件
```

## 测试 (`tests/`)

```
tests/
├── test_shooting_chain.py      # 完整射击链路集成测试
├── test_tracking_flow.py       # 跟踪流程集成测试
├── test_body_compensation.py   # 载体运动补偿
├── test_controller.py          # PID 控制器
├── test_kalman.py              # Kalman 滤波器
├── test_selector.py            # 目标选择器
├── test_safety.py              # 安全系统
├── test_telemetry.py           # 遥测日志
├── test_rangefinder.py         # 测距 + 距离融合
├── test_coordinate_transform.py
└── test_sil.py                 # SIL 仿真
```

## 文档 (`docs/`)

```
docs/
├── README.md                   # 文档索引
├── TODO.md                     # 待办事项
├── PROJECT_STRUCTURE.md        # 本文件
├── FAQ.md
├── getting-started/            # 新手入门
├── guides/                     # 使用指南
├── api/                        # API 文档
├── architecture/               # 架构文档
├── development/                # 开发指南
└── reports/ARCHIVE.md          # 历史报告归档
```

## 脚本 (`scripts/`)

```
scripts/
├── api/                    # API 启动 & 示例
├── demo/                   # 演示脚本
├── tests/                  # 测试运行器
└── tools/                  # Proto 生成等
```

## 依赖层级图

```
types/  config/           ← 纯数据，无业务逻辑
  ↑       ↑
algebra/  perception/interfaces  decision/interfaces  safety/interfaces
  ↑       ↑                     ↑                    ↑
control/interfaces ──────────────────────────────────────────────
  ↑                                                             ↑
pipeline/ ←──── hardware/interfaces  telemetry/interfaces  api (lazy)
```

单向依赖，无循环。pipeline 是唯一的 composition root。
