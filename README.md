# RWS — 2-DOF Vision-Gimbal Tracking System

[![CI](https://github.com/Kitjesen/RWS/workflows/CI/badge.svg)](https://github.com/Kitjesen/RWS/actions)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)

轻量级非 ROS2 模块化遥控武器站系统。基于 YOLO11n-Seg + BoT-SORT 实现实时视觉跟踪，支持移动基座（机器狗）IMU 前馈补偿，控制频率 100Hz，跟踪延迟 <50ms。

---

## 目录

- [快速开始](#快速开始)
- [系统架构](#系统架构)
- [功能模块](#功能模块)
- [API 接口](#api-接口)
- [Flutter Dashboard](#flutter-dashboard)
- [配置系统](#配置系统)
- [测试](#测试)
- [项目结构](#项目结构)
- [文档](#文档)
- [许可证](#许可证)

---

## 快速开始

### Docker 部署（推荐）

```bash
git clone https://github.com/Kitjesen/RWS.git
cd RWS
docker compose up
```

| 服务 | 地址 |
|------|------|
| Flutter Dashboard | http://localhost:8080 |
| REST API | http://localhost:5000/api/health |
| gRPC | localhost:50051 |
| Prometheus | http://localhost:9090 |
| Grafana | http://localhost:3000 (admin/admin) |

首次启动需下载约 2GB 镜像并编译 Flutter Web，后续启动 <10s。

USB 摄像头支持 — 在 `docker-compose.yml` 中取消注释：
```yaml
devices:
  - /dev/video0:/dev/video0
```

### 本地安装

```bash
git clone https://github.com/Kitjesen/RWS.git
cd RWS

pip install -r requirements.txt
pip install -e .

# 无摄像头演示
python scripts/demo/run_simple_demo.py

# 摄像头实时演示
python scripts/demo/run_camera_demo.py

# 启动 REST API 服务
python scripts/api/run_rest_server.py
```

### 混合开发模式

```bash
# 后端 Docker（源码热重载）
docker compose -f docker-compose.yml -f docker-compose.dev.yml up backend

# Flutter 前端（独立终端）
cd frontend && flutter run -d chrome
```

---

## 系统架构

系统分为严格解耦的层级，高层依赖抽象（Protocol），不依赖具体实现。所有层级边界使用 Python Protocol 类（结构化类型），添加新检测器、跟踪器或驱动只需实现对应 Protocol。

```
Application / Scripts
        |
Pipeline Orchestration  (pipeline/)
        |
+----------+----------+----------+----------+----------+
|Perception| Decision | Control  | Hardware |  Safety  |
+----------+----------+----------+----------+----------+
        |
Support: Algebra / Telemetry / Config / API / Types
```

### 单帧数据流

```
Frame -> Detector -> Tracker -> Selector -> StateMachine
      -> Rangefinder -> DistanceFusion
      -> PhysicsBallisticModel -> LeadAngleCalculator
      -> SafetyManager -> PIDController -> GimbalDriver -> VideoStreamer
```

---

## 功能模块

### 感知层

感知能力由独立的 [qp-perception](https://pypi.org/project/qp-perception/) 包提供（`pip install qp-perception`），源码仓库：[github.com/Kitjesen/qp-perception](https://github.com/Kitjesen/qp-perception)

- **YOLO11n-Seg 检测** — 实时实例分割，30+ FPS
- **BoT-SORT 多目标跟踪** — 鲁棒的目标关联和轨迹维护
- **FusionMOT** — 融合 IoU + 外观特征的高级跟踪器
- **Re-ID（OSNet）** — 目标重识别，丢失后重新关联
- **加权目标选择器** — 根据距离、大小、置信度自动排列优先级
- **多目标选择器** — 同时跟踪和管理多个威胁目标
- **卡尔曼滤波** — 恒速 / 恒加速两种模型，平滑轨迹预测

### 决策层

- **跟踪状态机** — SEARCH / TRACK / LOCK / LOST 四态自动切换
- **威胁评估器（ThreatAssessor）** — 综合距离、速度、类别对目标评分
- **交战队列（EngagementQueue）** — 按威胁优先级排列，自动选择最高威胁目标
- **目标生命周期管理（TargetLifecycleManager）** — DETECTED / TRACKED / NEUTRALIZED / ARCHIVED，击中的目标不会被重新交战

### 控制层

- **双轴 PID 控制** — Yaw / Pitch 独立 PID 环路，支持自适应增益调整
- **IMU 前馈补偿** — 移动基座（机器狗）运动补偿，消除载体晃动
- **弹道建模（RK4 积分）** — 物理弹丸轨迹仿真，考虑重力、空气阻力、风偏
- **提前角计算（LeadAngleCalculator）** — 运动目标射击角度预判
- **云台轨迹规划** — 平滑转向，防止突变导致的目标丢失

### 安全层

- **射击链（ShootingChain）** — SAFE / ARMED / FIRE_AUTHORIZED / FIRED / COOLDOWN 多级确认流程，是唯一的开火路径
- **安全联锁（SafetyInterlock）** — 7 个条件全部满足才允许射击
- **禁射区（NFZ）** — 多边形 / 圆形区域屏蔽，支持运行时 CRUD
- **IFF 敌我识别** — 防止友军误伤
- **操作员看门狗（OperatorWatchdog）** — 操作员心跳超时 10s 自动切回 SAFE
- **审计日志（AuditLogger）** — SHA-256 链式 JSONL，每次状态转换和开火事件不可篡改记录

### 硬件接口

- **串口云台驱动** — PELCO-D 协议，含反馈解析 + PWM 占空比控制
- **激光测距仪** — 目标距离实时获取
- **距离融合（DistanceFusion）** — 多传感器距离融合
- **仿真模式** — SimulatedGimbalDriver / MockIMU / SimulatedRangefinder，无硬件完整测试

---

## API 接口

同时提供 REST 和 gRPC 两种接口。

### REST API（端口 5000）

| 分类 | 端点 | 说明 |
|------|------|------|
| 开火控制 | `POST /api/fire/arm` | SAFE -> ARMED |
| | `POST /api/fire/request` | 请求开火 |
| | `POST /api/fire/heartbeat` | 操作员心跳 |
| | `POST /api/fire/designate` | 手动指定目标 |
| 任务管理 | `POST /api/mission/start` | 加载剖面，开始任务 |
| | `POST /api/mission/end` | 结束任务，生成报告 |
| 安全区域 | `GET /api/safety/zones` | 列出禁射区 |
| | `POST /api/safety/zones` | 添加禁射区 |
| | `DELETE /api/safety/zones/<id>` | 删除禁射区 |
| 监控 | `GET /api/threats` | 威胁队列（含评分和距离） |
| | `GET /metrics` | Prometheus 格式指标 |
| | `GET /api/selftest` | 7 子系统 go/no-go 自检 |
| | `GET /api/health` | 健康检查 |
| 回放 | `GET /api/replay/sessions` | 遥测会话列表 |
| | `GET /api/replay/sessions/<file>` | 事件回放（按类型/时间过滤） |
| 实时推送 | `GET /api/events` | SSE 事件流 |

SSE 事件类型：`fire_chain_state`, `fire_executed`, `target_designated`, `operator_timeout`, `mission_started`, `mission_ended`, `config_reloaded`, `nfz_added`, `nfz_removed`, `heartbeat`

### gRPC API（端口 50051）

高性能二进制协议，支持实时流式状态更新。

```python
from rws_tracking.api import TrackingGrpcClient

with TrackingGrpcClient("localhost", 50051) as client:
    client.start_tracking()
    for update in client.stream_status(update_rate_hz=10.0):
        print(f"FPS: {update['fps']:.1f}")
```

---

## Flutter Dashboard

实时可视化监控界面，支持响应式三栏 / 两栏 / 移动端布局。

```bash
cd frontend
flutter pub get
flutter run -d chrome
```

功能面板：

- **视频流** — MJPEG 实时画面 + 状态角标
- **误差图表** — Yaw / Pitch 跟踪误差历史曲线
- **云台姿态** — 极坐标可视化当前角度与误差环
- **PID 调参** — 滑块实时调整 Kp / Ki / Kd 并下发
- **系统指标** — 锁定率、平均误差、目标切换频率
- **告警横幅** — SSE 驱动的实时告警覆盖层
- **任务回放** — 事后审查事件时间线

---

## 配置系统

所有运行时参数在 `config.yaml` 中配置，支持热更新（2s 检测间隔，修改后自动生效，无需重启）。

主要配置段：`camera`, `detector`, `selector`, `controller`（含 `yaw_pid` / `pitch_pid`, `ballistic`, `adaptive_pid`）, `driver_limits`, `projectile`, `environment`, `lead_angle`, `trajectory`, `engagement`, `safety`, `rangefinder`, `video_stream`

### 任务剖面

预设的场景参数组合，存放在 `config/profiles/`：

| 剖面 | 用途 |
|------|------|
| `drill.yaml` | 训练演习 |
| `open_field.yaml` | 开阔地形 |
| `surveillance.yaml` | 监视模式 |
| `urban_cqb.yaml` | 城市近战 |
| `exercise.yaml` | 综合演练 |
| `live.yaml` | 实弹模式 |
| `training.yaml` | 训练模式 |

通过 API 加载：`POST /api/mission/start` 传入 `profile` 参数。

---

## 测试

```bash
# 运行全部测试
pytest tests/ -v --tb=short

# 跳过慢测试
pytest tests/ -m "not slow" -v

# 并行执行
pytest tests/ -n auto -v

# 性能基准
pytest tests/benchmarks/ --benchmark-only
```

CI 流水线（GitHub Actions，push/PR 自动触发）：

| Job | 内容 |
|-----|------|
| test | pytest + coverage，Python 3.9 / 3.10 / 3.11 矩阵 |
| lint | ruff check + ruff format + mypy |
| security | safety 依赖漏洞扫描 |
| performance | pytest-benchmark（仅 PR） |

---

## 项目结构

```
RWS/
├── src/rws_tracking/           # 核心源代码
│   ├── algebra/                # 坐标转换、卡尔曼滤波
│   ├── perception/             # 感知层桥接（via qp-perception）
│   ├── decision/               # 状态机、威胁评估、交战队列
│   ├── control/                # PID 控制、弹道建模、提前角
│   ├── hardware/               # 云台驱动（PELCO-D）、IMU、激光测距
│   ├── safety/                 # 禁射区、射击链、联锁、IFF
│   ├── pipeline/               # 主流程管道、组合根
│   ├── telemetry/              # 遥测日志、审计日志、视频环形缓冲
│   ├── health/                 # 子系统心跳监控
│   ├── api/                    # REST / gRPC / SSE / MJPEG
│   ├── config/                 # YAML 加载与热更新
│   └── types/                  # 共享数据类与枚举
│
├── frontend/                   # Flutter Web Dashboard
│   ├── lib/models/             # 数据模型
│   ├── lib/services/           # API 客户端 & Provider
│   ├── lib/screens/            # 页面（响应式布局）
│   └── lib/widgets/            # 组件（误差图表、云台可视化、PID 面板）
│
├── tests/                      # 测试套件
├── docs/                       # 文档（架构、API、指南、FAQ）
├── scripts/                    # 演示脚本、API 启动脚本、工具
├── config/                     # 任务剖面（profiles/）
├── deploy/                     # 部署配置（Prometheus、Grafana、Nginx）
├── docker/                     # Docker 辅助配置
├── hardware/                   # 硬件模型文件
├── models/                     # YOLO 模型权重
├── config.yaml                 # 主配置文件
├── pyproject.toml              # 项目元数据 + 工具配置
├── requirements.txt            # Python 依赖
├── Dockerfile                  # 后端镜像
├── Dockerfile.frontend         # 前端镜像
├── docker-compose.yml          # 生产编排
└── docker-compose.dev.yml      # 开发编排
```

---

## 文档

| 文档 | 说明 |
|------|------|
| [快速开始](docs/getting-started/quick-start.md) | 5 分钟上手 |
| [架构设计](docs/architecture/overview.md) | 系统架构与数据流 |
| [REST API](docs/api/) | 完整 API 参考 |
| [测试指南](docs/guides/testing.md) | 测试策略与运行方法 |
| [贡献指南](docs/CONTRIBUTING.md) | 代码规范与 PR 流程 |
| [安全政策](docs/SECURITY.md) | 漏洞报告流程 |
| [完整文档索引](docs/README.md) | 所有文档入口 |

---

## 性能指标

| 指标 | 数值 |
|------|------|
| 检测帧率 | 30+ FPS (YOLO11n) |
| 跟踪延迟 | <50ms |
| 控制频率 | 100 Hz |
| REST API 延迟 | ~5ms |
| gRPC API 延迟 | ~2ms |

---

## 许可证

[MIT License](LICENSE)

## 联系

- Issues: [GitHub Issues](https://github.com/Kitjesen/RWS/issues)
- Discussions: [GitHub Discussions](https://github.com/Kitjesen/RWS/discussions)
