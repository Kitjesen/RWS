# RWS Vision-Gimbal Tracking (2-DOF)

Lightweight non-ROS2 system for visual target pursuit and lock-on
with a yaw/pitch gimbal, powered by **YOLO11n-Seg + BoT-SORT**.

Supports **moving-base operation** (robot dog) with IMU feedforward compensation.

## 🆕 最新更新 (v1.2.0)

- ✅ **REST & gRPC API** - 双 API 支持，远程控制和实时流式传输
- ✅ **项目结构重构** - 清晰的文档分类和脚本组织
- ✅ **真实硬件支持** - 串口云台驱动 + 真实 IMU 接口
- ✅ **配置热更新** - 运行时调整参数，无需重启
- ✅ **CI/CD 集成** - 自动化测试和代码质量检查（全部通过 ✓）
- ✅ **测试增强** - 150+ 测试用例，覆盖率 28%+
- ✅ **代码质量** - Ruff 检查通过，Mypy 类型检查通过
- 📖 **文档完善** - 结构化文档系统

[![CI](https://github.com/Kitjesen/RWS/workflows/CI/badge.svg)](https://github.com/Kitjesen/RWS/actions)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Code style: ruff](https://img.shields.io/badge/code%20style-ruff-000000.svg)](https://github.com/astral-sh/ruff)
[![Type checked: mypy](https://img.shields.io/badge/type%20checked-mypy-blue.svg)](http://mypy-lang.org/)

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
│   ├── decision/               # 状态机
│   ├── control/                # PID 控制器
│   ├── hardware/               # 云台驱动、IMU 接口
│   ├── pipeline/               # 主流程管道
│   ├── telemetry/              # 遥测日志
│   ├── api/                    # REST & gRPC API
│   └── tools/                  # 仿真、训练工具
│
├── scripts/                    # 脚本工具
│   ├── api/                    # API 服务器和客户端示例
│   ├── demo/                   # 演示脚本
│   ├── tools/                  # 开发工具
│   └── tests/                  # 测试脚本
│
├── docs/                       # 文档
│   ├── getting-started/        # 新手入门
│   ├── guides/                 # 使用指南
│   ├── api/                    # API 文档
│   ├── architecture/           # 架构文档
│   ├── development/            # 开发文档
│   └── reports/                # 项目报告
│
├── tests/                      # 测试用例
├── models/                     # 模型文件
├── dataset/                    # 数据集
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

## 🏗️ 核心特性

### 感知层
- **YOLO11n-Seg** - 快速实例分割
- **BoT-SORT** - 鲁棒多目标跟踪
- **加权选择器** - 智能目标优先级

### 控制层
- **双轴 PID** - 独立 yaw/pitch 控制
- **IMU 前馈** - 移动基座补偿
- **延迟补偿** - 预测未来位置

### 硬件支持
- **串口云台** - 标准 UART 协议
- **真实 IMU** - 姿态反馈
- **仿真模式** - 无硬件测试

### API 接口
- **REST API** - HTTP/JSON (端口 5000)
- **gRPC API** - 高性能二进制协议 (端口 50051)
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
