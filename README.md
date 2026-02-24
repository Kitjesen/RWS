# RWS Vision-Gimbal Tracking (2-DOF)

Lightweight non-ROS2 system for visual target pursuit and lock-on
with a yaw/pitch gimbal, powered by **YOLO11n-Seg + BoT-SORT**.

Supports **moving-base operation** (robot dog) with IMU feedforward compensation.

## 🆕 最新更新 (v1.3.0)

- ✅ **Flutter Web Dashboard** - 实时可视化监控界面（误差曲线、云台姿态、PID 调参）
- ✅ **PELCO-D 协议完善** - 串口反馈解析 + PWM 占空比控制
- ✅ **配置热更新修复** - YAML 实时重载全链路打通
- ✅ **安全模块** - 禁射区、射击链、联锁机制
- ✅ **弹道计算** - 提前角 + 弹道轨迹建模
- ✅ **测试全覆盖** - 30+ 测试文件，覆盖全部核心模块
- ✅ **REST & gRPC API** - 双 API 支持 + 视频流端点
- ✅ **真实硬件支持** - 串口云台驱动 + 激光测距仪 + IMU 接口
- ✅ **CI/CD 集成** - Ruff + Mypy + pytest 自动化
- 📖 **文档完善** - 结构化文档系统

[![CI](https://github.com/Kitjesen/RWS/workflows/CI/badge.svg)](https://github.com/Kitjesen/RWS/actions)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Code style: ruff](https://img.shields.io/badge/code%20style-ruff-000000.svg)](https://github.com/astral-sh/ruff)
[![Type checked: mypy](https://img.shields.io/badge/type%20checked-mypy-blue.svg)](http://mypy-lang.org/)

## Quick Start

### Option A: Docker (recommended — no local Python or Flutter install required)

```bash
git clone https://github.com/Kitjesen/RWS.git
cd RWS

# (Optional) Copy and edit environment overrides
cp .env.example .env

docker compose up
```

| Service | URL |
|---|---|
| Flutter dashboard | http://localhost:8080 |
| REST API | http://localhost:5000/api/health |
| gRPC | localhost:50051 |
| Prometheus | http://localhost:9090 |
| Grafana | http://localhost:3000 (admin / admin) |

> First run downloads ~2 GB of images and compiles Flutter web. Subsequent starts take under 10 seconds.

**With a USB camera** — uncomment the `devices` block in `docker-compose.yml`:
```yaml
devices:
  - /dev/video0:/dev/video0
```

### Option B: Local development (backend only in Docker + Flutter locally)

```bash
# Backend in Docker, source-mounted for hot-reload
docker compose -f docker-compose.yml -f docker-compose.dev.yml up backend

# Flutter dashboard in browser (separate terminal)
cd frontend && flutter run -d chrome
```

### Option C: Fully local (no Docker)

```bash
pip install -r requirements.txt
pip install -e .
python scripts/api/run_rest_server.py

# Flutter dashboard (separate terminal)
cd frontend && flutter run -d chrome
```

## 📚 文档

- **[快速开始](docs/getting-started/quick-start.md)** - 5 分钟上手
- **[API 文档](docs/api/)** - REST 和 gRPC API 参考
- **[用户指南](docs/guides/)** - 硬件设置、测试、坐标数学
- **[架构文档](docs/architecture/)** - 系统架构和设计
- **[开发文档](docs/development/)** - 贡献指南、CI/CD
- **[项目结构](docs/PROJECT_STRUCTURE.md)** - 完整的目录结构说明

完整文档索引：[docs/README.md](docs/README.md)

## 🚀 快速开始

### 安装

```bash
# 克隆仓库
git clone https://github.com/Kitjesen/RWS.git
cd RWS

# 安装依赖
pip install -r requirements.txt

# 安装项目（开发模式）
pip install -e .
```

### 运行演示

```bash
# 简单演示（无需摄像头）
python scripts/demo/run_simple_demo.py

# 摄像头演示
python scripts/demo/run_camera_demo.py
```

### API 服务器

```bash
# REST API (端口 5000)
python scripts/api/run_rest_server.py

# gRPC API (端口 50051)
python scripts/api/run_grpc_server.py
```

## 📁 项目结构

```
RWS/
├── src/rws_tracking/           # 核心源代码
│   ├── algebra/                # 坐标转换、卡尔曼滤波
│   ├── perception/             # YOLO 检测、BoT-SORT 跟踪
│   ├── decision/               # 状态机、交战队列
│   ├── control/                # PID 控制、弹道计算、提前角
│   ├── hardware/               # 串口云台 (PELCO-D)、IMU、激光测距
│   ├── safety/                 # 禁射区、射击链、联锁
│   ├── pipeline/               # 主流程管道
│   ├── telemetry/              # 遥测日志
│   ├── api/                    # REST & gRPC API + 视频流
│   ├── config/                 # 配置加载与热更新
│   └── tools/                  # 仿真、训练工具
│
├── frontend/                   # Flutter Web Dashboard
│   ├── lib/models/             # 数据模型
│   ├── lib/services/           # API 客户端 & Provider
│   ├── lib/screens/            # 页面 (响应式布局)
│   └── lib/widgets/            # 组件 (误差图表、云台可视化、PID 面板)
│
├── tests/                      # 30+ 测试文件
├── docs/                       # 结构化文档
├── scripts/                    # 脚本工具
├── models/                     # 模型文件
├── config.yaml                 # 配置文件
└── requirements.txt            # 依赖
```

## 🔌 API 使用

### REST API

```python
from rws_tracking.api import TrackingClient

client = TrackingClient("http://localhost:5000")
client.start_tracking(camera_source=0)
status = client.get_status()
print(f"FPS: {status['fps']:.1f}")
client.stop_tracking()
```

### gRPC API

```python
from rws_tracking.api import TrackingGrpcClient

with TrackingGrpcClient("localhost", 50051) as client:
    client.start_tracking()

    # 实时流式更新
    for update in client.stream_status(update_rate_hz=10.0):
        print(f"FPS: {update['fps']:.1f}")
        if update['frame_count'] > 100:
            break

    client.stop_tracking()
```

查看 [API 文档](docs/api/) 了解更多。

## 🧪 测试

```bash
# 运行所有测试
python scripts/tests/run_tests.sh

# 运行 API 测试
python scripts/tests/test_api.py

# 运行基准测试
pytest tests/benchmarks/ --benchmark-only
```

## 🖥️ Flutter Web Dashboard

实时可视化监控界面，支持响应式三栏 / 两栏 / 移动端布局。

```bash
cd frontend
flutter pub get
flutter run -d chrome
```

功能面板：
- **视频流** - MJPEG 实时画面 + 状态角标
- **误差图表** - Yaw/Pitch 跟踪误差历史曲线 (fl_chart)
- **云台姿态** - 极坐标可视化当前角度与误差环
- **PID 调参** - 滑块实时调整 Kp/Ki/Kd 并下发
- **系统指标** - 锁定率、平均误差、目标切换频率

## 🏗️ 核心特性

### 感知层
- **YOLO11n-Seg** - 快速实例分割
- **BoT-SORT** - 鲁棒多目标跟踪
- **加权选择器** - 智能目标优先级

### 控制层
- **双轴 PID** - 独立 yaw/pitch 控制
- **IMU 前馈** - 移动基座补偿
- **提前角计算** - 运动目标预判
- **弹道建模** - 弹丸轨迹与落点补偿

### 安全层
- **禁射区 (NFZ)** - 多边形 / 圆形区域屏蔽
- **射击链** - 多级确认流程
- **联锁机制** - 硬件 / 软件双重保险

### 硬件支持
- **串口云台** - PELCO-D 协议 (含反馈解析 + PWM)
- **激光测距仪** - 目标距离实时获取
- **真实 IMU** - 姿态反馈
- **仿真模式** - 无硬件测试

### API 接口
- **REST API** - HTTP/JSON (端口 5000)
- **gRPC API** - 高性能二进制协议 (端口 50051)
- **视频流** - MJPEG / Snapshot 端点
- **实时流式** - gRPC 状态流

## 📊 性能

- **检测速度**: 30+ FPS (YOLO11n)
- **跟踪延迟**: <50ms
- **控制频率**: 100 Hz
- **API 延迟**: REST ~5ms, gRPC ~2ms

## 🤝 贡献

欢迎贡献！请查看 [贡献指南](docs/development/contributing.md)。

## 📄 许可证

[MIT License](LICENSE)

## 🔗 相关链接

- [完整文档](docs/README.md)
- [API 参考](docs/api/)
- [架构设计](docs/architecture/overview.md)
- [测试指南](docs/guides/testing.md)
- [CI/CD 状态](docs/development/ci-status.md)

## 📮 联系

- Issues: [GitHub Issues](https://github.com/Kitjesen/RWS/issues)
- Discussions: [GitHub Discussions](https://github.com/Kitjesen/RWS/discussions)
