# RWS Tracking 快速开始指南

## 目录
1. [基本使用](#基本使用)
2. [API 远程控制](#api-远程控制)
3. [配置说明](#配置说明)
4. [常见问题](#常见问题)

---

## 基本使用

### 1. 安装依赖

```bash
# 核心依赖
pip install ultralytics opencv-python "numpy>=1.24.0,<2.0.0" scipy pyyaml

# 开发依赖（可选）
pip install pytest pytest-cov ruff mypy

# API 依赖（远程控制）
pip install flask flask-cors requests
```

### 2. 运行演示

```bash
# 合成场景演示（无需摄像头）
python scripts/run_demo.py

# 摄像头实时跟踪
python scripts/run_yolo_cam.py
```

### 3. 运行测试

```bash
# Linux/Mac
bash scripts/run_tests.sh

# Windows
scripts\run_tests.bat

# 或使用 pytest
pytest tests/
```

---

## API 远程控制

### 1. 启动 API 服务器

```bash
python scripts/run_api_server.py --host 0.0.0.0 --port 5000
```

### 2. 使用 Python 客户端

```python
from rws_tracking.api import TrackingClient

# 连接到服务器
client = TrackingClient("http://192.168.1.100:5000")

# 启动跟踪
client.start_tracking(camera_source=0)

# 获取状态
status = client.get_status()
print(f"FPS: {status['fps']:.1f}")
print(f"Gimbal: {status['gimbal']}")

# 控制云台
client.set_gimbal_position(yaw_deg=10.0, pitch_deg=5.0)

# 停止跟踪
client.stop_tracking()
```

### 3. 使用 cURL

```bash
# 健康检查
curl http://localhost:5000/api/health

# 启动跟踪
curl -X POST http://localhost:5000/api/start \
  -H "Content-Type: application/json" \
  -d '{"camera_source": 0}'

# 获取状态
curl http://localhost:5000/api/status

# 控制云台
curl -X POST http://localhost:5000/api/gimbal/position \
  -H "Content-Type: application/json" \
  -d '{"yaw_deg": 10.0, "pitch_deg": 5.0}'

# 停止跟踪
curl -X POST http://localhost:5000/api/stop
```

---

## 配置说明

### 配置文件位置
- 主配置：`config.yaml`
- 相机参数：`config.yaml` 中的 `camera` 部分
- 控制器参数：`config.yaml` 中的 `controller` 部分

### 常用配置项

```yaml
# 相机配置
camera:
  width: 1280
  height: 720
  fx: 970.0
  fy: 965.0
  cx: 640.0
  cy: 360.0

# 检测器配置
detector:
  model_path: "yolo11n-seg.pt"
  confidence_threshold: 0.40
  class_whitelist:
    - person

# 控制器配置
controller:
  yaw_pid:
    kp: 5.0
    ki: 0.4
    kd: 0.35
  pitch_pid:
    kp: 5.5
    ki: 0.35
    kd: 0.35
```

---

## 常见问题

### Q: 如何更换摄像头？
A: 修改 `camera_source` 参数：
```python
client.start_tracking(camera_source=1)  # 使用第二个摄像头
client.start_tracking(camera_source="/path/to/video.mp4")  # 使用视频文件
```

### Q: 如何调整跟踪灵敏度？
A: 修改 `config.yaml` 中的 PID 参数：
- 增大 `kp` 提高响应速度
- 增大 `ki` 消除稳态误差
- 增大 `kd` 减少超调

### Q: 如何查看跟踪性能？
A: 使用遥测接口：
```python
telemetry = client.get_telemetry()
print(telemetry['metrics'])
```

### Q: 如何在局域网中使用？
A: 启动服务器时绑定到 `0.0.0.0`：
```bash
python scripts/run_api_server.py --host 0.0.0.0 --port 5000
```
然后从其他设备访问：`http://<服务器IP>:5000`

### Q: 如何添加自定义目标类别？
A: 修改 `config.yaml` 中的 `class_whitelist`：
```yaml
detector:
  class_whitelist:
    - person
    - car
    - dog
```

---

## 更多文档

- [API 完整文档](API_GUIDE.md)
- [架构设计](ARCHITECTURE.md)
- [配置说明](CONFIGURATION.md)
- [测试指南](TESTING_GUIDE.md)
- [API 重构总结](API_REFACTOR_SUMMARY.md)

---

## 项目结构

```
RWS/
├── src/rws_tracking/       # 源代码
│   ├── api/                # REST API 模块
│   ├── perception/         # 检测和跟踪
│   ├── control/            # 控制器
│   ├── hardware/           # 硬件驱动
│   └── pipeline/           # 主流程
├── scripts/                # 运行脚本
│   ├── run_api_server.py   # API 服务器
│   ├── run_demo.py         # 演示程序
│   └── run_yolo_cam.py     # 摄像头跟踪
├── tests/                  # 测试文件
├── models/                 # 模型文件
├── docs/                   # 文档
└── config.yaml             # 配置文件
```

---

## 支持

如有问题，请查看：
1. [文档目录](README.md)
2. [常见问题](FAQ.md)
3. [GitHub Issues](https://github.com/your-repo/issues)
