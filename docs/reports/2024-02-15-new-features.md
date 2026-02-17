# RWS 新功能快速开始指南

> 本指南介绍如何使用最新添加的功能
> 更新时间：2026-02-15

---

## 一、硬件集成

### 1.1 串口云台驱动

#### 安装依赖

```bash
pip install pyserial
```

#### 基础使用

```python
from src.rws_tracking.hardware.serial_driver import SerialGimbalDriver, GimbalProtocol
import time

# 创建驱动实例
driver = SerialGimbalDriver(
    port="COM3",              # Windows: "COM3", Linux: "/dev/ttyUSB0"
    baudrate=115200,
    protocol=GimbalProtocol.CUSTOM  # 或 PELCO_D, PELCO_P, PWM
)

# 发送控制命令
driver.set_yaw_pitch_rate(
    yaw_rate_dps=10.0,    # 向右转 10°/s
    pitch_rate_dps=5.0,   # 向上转 5°/s
    timestamp=time.time()
)

# 读取反馈
feedback = driver.get_feedback(time.time())
print(f"当前位置: Yaw={feedback.yaw_deg:.2f}°, Pitch={feedback.pitch_deg:.2f}°")

# 关闭连接
driver.close()
```

#### 集成到 Pipeline

```python
from src.rws_tracking.pipeline.pipeline import VisionGimbalPipeline
from src.rws_tracking.hardware.serial_driver import SerialGimbalDriver, GimbalProtocol

# 创建真实云台驱动
driver = SerialGimbalDriver(
    port="COM3",
    baudrate=115200,
    protocol=GimbalProtocol.CUSTOM
)

# 创建 pipeline（其他组件省略）
pipeline = VisionGimbalPipeline(
    detector=detector,
    tracker=tracker,
    selector=selector,
    state_machine=state_machine,
    controller=controller,
    driver=driver,  # 使用真实驱动
    telemetry=telemetry,
)

# 运行
pipeline.run(camera_source=0)
```

#### 支持的协议

**1. 自定义协议（推荐）**

发送格式：
```
[0xFF, 0xAA, yaw_high, yaw_low, pitch_high, pitch_low, checksum]
```

反馈格式：
```
[0xFF, 0xBB, yaw_h, yaw_l, pitch_h, pitch_l, rate_yaw_h, rate_yaw_l, rate_pitch_h, rate_pitch_l, checksum]
```

**2. PELCO-D 协议**

标准 PTZ 协议，适用于工业云台。

**3. PWM 舵机**

需要 Arduino 等微控制器转换，发送 ASCII 命令：
```
Y<angle>,P<angle>\n
```

---

### 1.2 真实 IMU 接口

#### 宇树机器狗集成

```python
from src.rws_tracking.hardware.robot_imu import RobotIMUProvider, UnitreeAdapter

# 假设已有宇树 SDK 实例
from unitree_legged_sdk import Robot

robot = Robot()
adapter = UnitreeAdapter(robot)
imu = RobotIMUProvider(adapter, enable_filtering=True, filter_alpha=0.3)

# 获取姿态
body_state = imu.get_body_state(time.time())
if body_state:
    print(f"Roll: {body_state.roll_deg:.2f}°")
    print(f"Pitch: {body_state.pitch_deg:.2f}°")
    print(f"Yaw: {body_state.yaw_deg:.2f}°")
    print(f"Yaw Rate: {body_state.yaw_rate_dps:.2f}°/s")
```

#### 波士顿动力 Spot 集成

```python
from src.rws_tracking.hardware.robot_imu import RobotIMUProvider, SpotAdapter
import bosdyn.client
from bosdyn.client.robot_state import RobotStateClient

# 连接 Spot
sdk = bosdyn.client.create_standard_sdk('rws-tracking')
robot = sdk.create_robot('192.168.80.3')
robot.authenticate('user', 'password')

state_client = robot.ensure_client(RobotStateClient.default_service_name)
adapter = SpotAdapter(state_client)
imu = RobotIMUProvider(adapter)

# 使用
body_state = imu.get_body_state(time.time())
```

#### 通用串口 IMU

```python
from src.rws_tracking.hardware.robot_imu import RobotIMUProvider, GenericSerialIMU

# 连接串口 IMU（如 MPU6050, BNO055）
adapter = GenericSerialIMU(port="COM4", baudrate=115200)
imu = RobotIMUProvider(adapter)

# 使用
body_state = imu.get_body_state(time.time())
```

**串口数据格式：**
```
R:<roll>,P:<pitch>,Y:<yaw>,GX:<gx>,GY:<gy>,GZ:<gz>\n
```

示例：
```
R:1.23,P:-0.45,Y:90.12,GX:0.5,GY:-0.2,GZ:1.8\n
```

#### 集成到 Pipeline

```python
pipeline = VisionGimbalPipeline(
    # ... 其他组件 ...
    body_motion_provider=imu,  # 添加 IMU
)
```

---

## 二、配置热更新

### 2.1 文件监听模式

```python
from src.rws_tracking.tools.config_reload import ConfigReloader
from src.rws_tracking.config import load_config

# 定义配置更新回调
def on_config_change(new_config):
    print("配置已更新！")
    # 更新 PID 参数
    pipeline.controller._yaw_pid_cfg = new_config.controller.yaw_pid
    pipeline.controller._pitch_pid_cfg = new_config.controller.pitch_pid
    print(f"新 PID: Kp={new_config.controller.yaw_pid.kp}")

# 启动配置监听
reloader = ConfigReloader(
    config_path="config.yaml",
    callback=on_config_change,
    check_interval=1.0  # 每秒检查一次
)
reloader.start()

# 运行 pipeline
pipeline.run(camera_source=0)

# 停止监听
reloader.stop()
```

**使用方法：**
1. 启动程序
2. 编辑 `config.yaml`，修改参数
3. 保存文件
4. 程序自动重载配置，无需重启

---

### 2.2 HTTP API 模式

```python
from src.rws_tracking.tools.config_reload import ConfigServer

# 启动配置服务器
server = ConfigServer(pipeline, port=8080)
server.start()

# 运行 pipeline
pipeline.run(camera_source=0)
```

**API 端点：**

#### 1. 健康检查
```bash
curl http://localhost:8080/health
```

响应：
```json
{"status": "ok", "pipeline": "running"}
```

#### 2. 更新 PID 参数
```bash
curl -X POST http://localhost:8080/config/pid \
  -H "Content-Type: application/json" \
  -d '{
    "axis": "yaw",
    "kp": 6.0,
    "ki": 0.5,
    "kd": 0.4
  }'
```

响应：
```json
{
  "status": "ok",
  "axis": "yaw",
  "kp": 6.0,
  "ki": 0.5,
  "kd": 0.4
}
```

#### 3. 更新选择器权重
```bash
curl -X POST http://localhost:8080/config/selector \
  -H "Content-Type: application/json" \
  -d '{
    "confidence": 0.4,
    "size": 0.25,
    "center_proximity": 0.2
  }'
```

#### 4. 获取实时指标
```bash
curl http://localhost:8080/metrics
```

响应：
```json
{
  "lock_rate": 0.95,
  "avg_abs_error_deg": 0.18,
  "switches_per_min": 3.2
}
```

---

## 三、测试新功能

### 3.1 运行单元测试

```bash
# 安装测试依赖
pip install pytest pytest-cov

# 运行所有测试
pytest tests/ -v

# 运行特定测试
pytest tests/test_selector.py -v
pytest tests/test_controller.py -v

# 查看覆盖率
pytest tests/ --cov=src/rws_tracking --cov-report=html
```

### 3.2 运行 CI 检查

```bash
# 安装工具
pip install ruff mypy

# 代码风格检查
ruff check src/ tests/

# 自动格式化
ruff format src/ tests/

# 类型检查
mypy src/rws_tracking --ignore-missing-imports
```

---

## 四、完整示例

### 4.1 真实硬件集成示例

```python
"""完整的真实硬件集成示例"""
import time
from src.rws_tracking.config import load_config
from src.rws_tracking.pipeline.app import build_pipeline_from_config
from src.rws_tracking.hardware.serial_driver import SerialGimbalDriver, GimbalProtocol
from src.rws_tracking.hardware.robot_imu import RobotIMUProvider, GenericSerialIMU
from src.rws_tracking.tools.config_reload import ConfigReloader

# 1. 加载配置
config = load_config("config.yaml")

# 2. 创建真实硬件驱动
gimbal_driver = SerialGimbalDriver(
    port="COM3",
    baudrate=115200,
    protocol=GimbalProtocol.CUSTOM
)

imu_adapter = GenericSerialIMU(port="COM4", baudrate=115200)
imu = RobotIMUProvider(imu_adapter, enable_filtering=True)

# 3. 构建 pipeline（替换仿真驱动）
pipeline = build_pipeline_from_config(config)
pipeline.driver = gimbal_driver
pipeline.body_motion_provider = imu

# 4. 启动配置热更新
def on_config_update(new_config):
    print("配置已更新")
    pipeline.controller._yaw_pid_cfg = new_config.controller.yaw_pid
    pipeline.controller._pitch_pid_cfg = new_config.controller.pitch_pid

reloader = ConfigReloader("config.yaml", on_config_update)
reloader.start()

# 5. 运行 pipeline
try:
    pipeline.run(camera_source=0)
except KeyboardInterrupt:
    print("停止中...")
finally:
    reloader.stop()
    gimbal_driver.close()
    imu_adapter.close()
```

### 4.2 远程监控示例

```python
"""带远程监控的完整示例"""
from src.rws_tracking.config import load_config
from src.rws_tracking.pipeline.app import build_pipeline_from_config
from src.rws_tracking.tools.config_reload import ConfigServer

# 加载配置
config = load_config("config.yaml")
pipeline = build_pipeline_from_config(config)

# 启动 HTTP 配置服务器
server = ConfigServer(pipeline, port=8080)
server.start()

print("配置服务器已启动: http://localhost:8080")
print("可用端点:")
print("  GET  /health")
print("  POST /config/pid")
print("  POST /config/selector")
print("  GET  /metrics")

# 运行 pipeline
pipeline.run(camera_source=0)
```

---

## 五、故障排查

### 5.1 串口连接问题

**问题：** `Failed to open serial port`

**解决：**
1. 检查端口名称是否正确
   ```bash
   # Windows
   mode

   # Linux
   ls /dev/ttyUSB*
   ```

2. 检查权限（Linux）
   ```bash
   sudo chmod 666 /dev/ttyUSB0
   # 或添加用户到 dialout 组
   sudo usermod -a -G dialout $USER
   ```

3. 检查设备是否被占用
   ```bash
   # Linux
   lsof /dev/ttyUSB0
   ```

### 5.2 IMU 数据异常

**问题：** IMU 数据跳变或不稳定

**解决：**
1. 启用滤波
   ```python
   imu = RobotIMUProvider(adapter, enable_filtering=True, filter_alpha=0.3)
   ```

2. 检查串口数据格式
   ```python
   # 打印原始数据
   import serial
   ser = serial.Serial("COM4", 115200)
   print(ser.readline().decode('ascii'))
   ```

3. 调整滤波参数
   - `filter_alpha` 越小，滤波越强（0.1-0.5）

### 5.3 配置热更新不生效

**问题：** 修改配置文件后没有重载

**解决：**
1. 检查文件是否真的保存了
2. 检查 `check_interval` 是否太长
3. 查看日志输出
   ```python
   import logging
   logging.basicConfig(level=logging.INFO)
   ```

### 5.4 HTTP API 无法访问

**问题：** `Connection refused`

**解决：**
1. 检查 Flask 是否安装
   ```bash
   pip install flask
   ```

2. 检查端口是否被占用
   ```bash
   # Windows
   netstat -ano | findstr :8080

   # Linux
   lsof -i :8080
   ```

3. 检查防火墙设置

---

## 六、性能优化建议

### 6.1 串口通信优化

```python
# 使用更高的波特率
driver = SerialGimbalDriver(
    port="COM3",
    baudrate=921600,  # 更快
    protocol=GimbalProtocol.CUSTOM
)
```

### 6.2 IMU 滤波优化

```python
# 根据应用场景调整滤波
# 快速响应（机动性强）
imu = RobotIMUProvider(adapter, filter_alpha=0.5)

# 平滑稳定（精度优先）
imu = RobotIMUProvider(adapter, filter_alpha=0.2)
```

### 6.3 配置热更新优化

```python
# 降低检查频率（减少 CPU 占用）
reloader = ConfigReloader(
    config_path="config.yaml",
    callback=on_config_change,
    check_interval=2.0  # 2 秒检查一次
)
```

---

## 七、下一步

1. **阅读完整文档**
   - [ENHANCEMENT_PLAN.md](ENHANCEMENT_PLAN.md) - 改进计划
   - [TEAM_ANALYSIS_REPORT.md](TEAM_ANALYSIS_REPORT.md) - 分析报告

2. **运行测试**
   ```bash
   pytest tests/ -v --cov=src
   ```

3. **集成真实硬件**
   - 准备云台和 IMU
   - 运行硬件测试脚本
   - 调整参数

4. **部署 CI/CD**
   - 推送到 GitHub
   - 启用 GitHub Actions
   - 查看测试结果

---

**文档版本：** v1.0
**最后更新：** 2026-02-15
