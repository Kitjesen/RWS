# RWS 项目完善计划

> 基于团队协作分析的项目增强建议
> 生成时间：2026-02-15

---

## 执行摘要

RWS 是一个架构优秀、文档完善的视觉跟踪系统。当前版本已实现核心功能，但在硬件集成、测试覆盖、工具链等方面仍有提升空间。

**项目成熟度评估：**
- ✅ 核心功能：完整（检测、跟踪、控制、状态机）
- ✅ 架构设计：优秀（Protocol 驱动、分层清晰）
- ✅ 文档质量：优秀（5篇详细文档）
- ⚠️ 硬件集成：仅仿真（缺少真实驱动）
- ⚠️ 测试覆盖：基础（4个测试文件）
- ⚠️ 工具链：基础（无 CI/CD）

---

## 一、优先级分级

### P0 - 关键缺失（立即实施）

#### 1.1 真实串口云台驱动
**现状：** 只有 `SimulatedGimbalDriver`，无法连接真实硬件。

**方案：**
```python
# src/rws_tracking/hardware/serial_driver.py
class SerialGimbalDriver:
    """串口云台驱动，支持多种协议"""

    def __init__(self, port: str, baudrate: int, protocol: str):
        """
        Parameters
        ----------
        port : str
            串口设备路径（如 "COM3" 或 "/dev/ttyUSB0"）
        baudrate : int
            波特率（如 115200）
        protocol : str
            协议类型："pwm", "pelco-d", "custom"
        """
        pass
```

**实现步骤：**
1. 添加 `pyserial` 依赖到 requirements.txt
2. 实现基础串口通信（发送/接收）
3. 支持常见协议：
   - PWM 舵机控制
   - PELCO-D/P 协议
   - 自定义二进制协议
4. 添加配置项到 config.yaml
5. 编写硬件测试脚本

**预计工作量：** 2-3 天

---

#### 1.2 真实 IMU 接口
**现状：** 只有 `MockIMU`，无法接入机器狗 IMU。

**方案：**
```python
# src/rws_tracking/hardware/robot_imu.py
class RobotIMUProvider:
    """机器狗 IMU 数据提供者"""

    def __init__(self, robot_sdk):
        """
        Parameters
        ----------
        robot_sdk : object
            机器狗 SDK 实例（如宇树 Go1/Go2 SDK）
        """
        pass

    def get_body_state(self, timestamp: float) -> Optional[BodyState]:
        """从机器狗 SDK 获取实时姿态"""
        pass
```

**实现步骤：**
1. 定义通用 IMU 接口（已有 `BodyMotionProvider`）
2. 实现宇树机器狗适配器
3. 实现波士顿动力 Spot 适配器（可选）
4. 添加时间同步机制（IMU 与视觉帧对齐）
5. 编写集成测试

**预计工作量：** 3-4 天

---

### P1 - 重要增强（近期实施）

#### 1.3 CI/CD 集成
**现状：** 无自动化测试和代码检查。

**方案：** 添加 GitHub Actions 工作流

```yaml
# .github/workflows/ci.yml
name: CI

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-python@v4
        with:
          python-version: '3.10'
      - name: Install dependencies
        run: |
          pip install -r requirements.txt
          pip install pytest pytest-cov mypy ruff
      - name: Run tests
        run: pytest tests/ -v --cov=src
      - name: Type check
        run: mypy src/
      - name: Lint
        run: ruff check src/
```

**包含内容：**
- 单元测试自动运行
- 类型检查（mypy）
- 代码风格检查（ruff）
- 测试覆盖率报告
- 依赖安全扫描（safety）

**预计工作量：** 1 天

---

#### 1.4 测试覆盖补充
**现状：** 只有 4 个测试文件，覆盖率不足。

**缺失测试（按优先级）：**

1. **感知层单元测试**
   - `WeightedTargetSelector` 多目标评分
   - `SimpleIoUTracker` 跟踪逻辑
   - `YoloSegTracker` 集成测试

2. **控制层单元测试**
   - PID 阶跃响应
   - 积分饱和测试
   - 微分滤波测试
   - 延迟补偿验证

3. **Kalman 滤波器测试**
   - CV/CA 模型收敛性
   - 预测精度
   - 噪声抑制

4. **边界条件测试**
   - 空输入处理
   - 极端参数
   - 资源清理

**预计工作量：** 5-7 天

---

### P2 - 功能增强（中期规划）

#### 2.1 配置热更新
**需求：** 运行时调整参数，无需重启。

**方案 A：文件监听**
```python
# src/rws_tracking/config.py
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

class ConfigReloader(FileSystemEventHandler):
    def on_modified(self, event):
        if event.src_path.endswith('config.yaml'):
            new_config = load_config(event.src_path)
            pipeline.update_config(new_config)
```

**方案 B：HTTP API**
```python
# src/rws_tracking/tools/config_server.py
from flask import Flask, request

app = Flask(__name__)

@app.route('/config/pid', methods=['POST'])
def update_pid():
    params = request.json
    pipeline.controller.update_pid(params)
    return {'status': 'ok'}
```

**推荐：** 方案 A（轻量、无额外依赖）

**预计工作量：** 2 天

---

#### 2.2 远程监控后端
**需求：** 实时查看系统状态，支持远程调试。

**方案：** MQTT 遥测后端

```python
# src/rws_tracking/telemetry/mqtt_logger.py
import paho.mqtt.client as mqtt

class MqttTelemetryLogger:
    """通过 MQTT 发送遥测数据"""

    def __init__(self, broker: str, port: int, topic_prefix: str):
        self.client = mqtt.Client()
        self.client.connect(broker, port)
        self.topic_prefix = topic_prefix

    def log(self, event_type: str, timestamp: float, payload: dict):
        topic = f"{self.topic_prefix}/{event_type}"
        self.client.publish(topic, json.dumps(payload))
```

**配套工具：**
- Grafana 仪表盘（实时图表）
- MQTT 订阅脚本（命令行监控）

**预计工作量：** 3 天

---

#### 2.3 目标重识别（Re-ID）
**需求：** 遮挡后重新出现时保持 ID 不变。

**方案：** 添加外观特征缓存

```python
# src/rws_tracking/perception/reid.py
class ReIDFeatureExtractor:
    """提取目标外观特征用于重识别"""

    def __init__(self, model_path: str):
        # 加载轻量 Re-ID 模型（如 OSNet）
        pass

    def extract(self, frame: np.ndarray, bbox: BBox) -> np.ndarray:
        """提取 128 维特征向量"""
        pass

class ReIDTracker:
    """带 Re-ID 的跟踪器"""

    def __init__(self, base_tracker: Tracker, reid_model: ReIDFeatureExtractor):
        self.base_tracker = base_tracker
        self.reid = reid_model
        self.feature_cache = {}  # track_id -> feature

    def update(self, detections: List[Detection], timestamp: float):
        # 1. 基础跟踪
        tracks = self.base_tracker.update(detections, timestamp)

        # 2. Re-ID 匹配（处理长时间丢失的目标）
        # ...
```

**预计工作量：** 5-7 天

---

### P3 - 高级功能（长期规划）

#### 3.1 多云台协同跟踪
**现状：** 已有基础代码（`MultiGimbalPipeline`），需完善和测试。

**待完善：**
1. 改进成本函数（使用真实坐标变换）
2. 添加协同策略（区域划分、优先级分配）
3. 编写多云台集成测试
4. 添加配置示例

**预计工作量：** 7-10 天

---

#### 3.2 夜视/红外模态支持
**需求：** 支持红外相机输入。

**方案：**
1. 微调 YOLO 模型（红外数据集）
2. 添加图像预处理（直方图均衡化）
3. 支持多模态融合（可见光 + 红外）

**预计工作量：** 10-14 天（含数据采集和训练）

---

#### 3.3 自动化回归测试
**需求：** 录制真实场景作为回归数据集。

**方案：**
```python
# tests/regression/test_scenarios.py
import pytest

@pytest.mark.parametrize("scenario", [
    "fast_moving_target",
    "occlusion_recovery",
    "multi_target_switch",
])
def test_regression(scenario):
    # 加载录制的视频 + 标注
    video_path = f"tests/data/{scenario}.mp4"
    ground_truth = load_annotations(f"tests/data/{scenario}.json")

    # 运行 pipeline
    results = run_pipeline(video_path)

    # 验证指标
    assert results.lock_rate > ground_truth.min_lock_rate
    assert results.avg_error < ground_truth.max_error
```

**预计工作量：** 5 天（含数据录制）

---

## 二、技术债务清理

### 2.1 类型注解完善
**现状：** `pipeline.controller: object` 丢失类型信息。

**修复：**
```python
# src/rws_tracking/pipeline/pipeline.py
from ..control.interfaces import GimbalController

class VisionGimbalPipeline:
    def __init__(
        self,
        # ...
        controller: GimbalController,  # 改为具体类型
        # ...
    ):
        self.controller = controller
```

---

### 2.2 依赖版本锁定
**现状：** requirements.txt 使用 `>=`，可能导致版本不一致。

**建议：** 添加 `requirements-lock.txt`
```bash
pip freeze > requirements-lock.txt
```

---

## 三、实施路线图

### 第一阶段（1-2 周）：硬件集成
- [ ] 实现串口云台驱动
- [ ] 实现真实 IMU 接口
- [ ] 编写硬件集成文档

### 第二阶段（2-3 周）：质量提升
- [ ] 添加 CI/CD
- [ ] 补充单元测试（目标覆盖率 80%）
- [ ] 修复类型注解问题

### 第三阶段（3-4 周）：功能增强
- [ ] 配置热更新
- [ ] 远程监控后端
- [ ] 完善多云台协同

### 第四阶段（长期）：高级功能
- [ ] 目标重识别
- [ ] 夜视/红外支持
- [ ] 自动化回归测试

---

## 四、资源需求

### 人力
- 核心开发：1-2 人
- 测试工程师：1 人（兼职）
- 硬件工程师：1 人（阶段性）

### 硬件
- 测试云台：1 套（3000-8000 元）
- 工业相机：1 个（可选，2000-5000 元）
- 机器狗（如已有）：用于 IMU 集成测试

### 时间
- P0 功能：2-3 周
- P1 功能：4-6 周
- P2 功能：8-12 周

---

## 五、风险评估

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|---------|
| 硬件协议不兼容 | 中 | 高 | 提前调研，支持多种协议 |
| 测试覆盖不足 | 低 | 中 | 强制 CI 检查覆盖率 |
| 性能下降 | 低 | 中 | 添加性能基准测试 |
| 依赖冲突 | 低 | 低 | 使用虚拟环境，锁定版本 |

---

## 六、成功指标

### 技术指标
- [ ] 测试覆盖率 > 80%
- [ ] CI 通过率 > 95%
- [ ] 真实硬件集成成功
- [ ] Lock Rate > 90%（真实场景）

### 文档指标
- [ ] 硬件集成文档完整
- [ ] API 文档自动生成
- [ ] 示例代码覆盖所有功能

### 社区指标（如开源）
- [ ] GitHub Stars > 100
- [ ] Issues 响应时间 < 48h
- [ ] 外部贡献者 > 3

---

## 附录：快速参考

### 当前项目统计
- 源代码文件：~50 个
- 代码行数：~8000 行
- 测试文件：4 个
- 文档页数：5 篇
- 依赖数量：6 个核心依赖

### 推荐工具
- 测试：pytest, pytest-cov
- 类型检查：mypy
- 代码风格：ruff
- 文档生成：sphinx
- 性能分析：py-spy, line_profiler

---

**文档版本：** v1.0
**最后更新：** 2026-02-15
**维护者：** RWS 开发团队
