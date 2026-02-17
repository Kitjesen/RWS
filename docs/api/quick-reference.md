# RWS Tracking API 快速参考

## 🌐 基础信息
- **地址**: `http://localhost:5000`
- **协议**: HTTP REST API
- **格式**: JSON
- **CORS**: 已启用

---

## 📡 API 端点总览（8 个）

### 系统控制

| 端点 | 方法 | 功能 |
|------|------|------|
| `/api/health` | GET | 健康检查 |
| `/api/start` | POST | 启动跟踪 |
| `/api/stop` | POST | 停止跟踪 |

### 状态查询

| 端点 | 方法 | 功能 |
|------|------|------|
| `/api/status` | GET | 获取状态（FPS、云台位置等） |
| `/api/telemetry` | GET | 获取遥测数据（性能指标） |

### 云台控制

| 端点 | 方法 | 功能 |
|------|------|------|
| `/api/gimbal/position` | POST | 设置云台位置（绝对） |
| `/api/gimbal/rate` | POST | 设置云台速率（速度） |

### 配置管理

| 端点 | 方法 | 功能 |
|------|------|------|
| `/api/config` | POST | 更新配置 |

---

## 💡 Python 快速示例

```python
from rws_tracking.api import TrackingClient

# 连接
client = TrackingClient("http://localhost:5000")

# 启动
client.start_tracking(camera_source=0)

# 获取状态
status = client.get_status()
print(f"FPS: {status['fps']}, Yaw: {status['gimbal']['yaw_deg']}°")

# 控制云台
client.set_gimbal_position(yaw_deg=10.0, pitch_deg=5.0)

# 停止
client.stop_tracking()
```

---

## 🔧 cURL 快速命令

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

## 📊 响应格式

### 成功响应
```json
{
  "success": true,
  "message": "Operation completed",
  "data": { ... }
}
```

### 错误响应
```json
{
  "success": false,
  "error": "Error description"
}
```

### 状态响应
```json
{
  "running": true,
  "frame_count": 1234,
  "fps": 30.5,
  "gimbal": {
    "yaw_deg": 10.5,
    "pitch_deg": 5.2,
    "yaw_rate_dps": 2.3,
    "pitch_rate_dps": 1.1
  }
}
```

---

## 🚀 启动服务器

```bash
# 基本启动
python scripts/run_api_server.py

# 自定义配置
python scripts/run_api_server.py --host 0.0.0.0 --port 5000 --config config.yaml

# 调试模式
python scripts/run_api_server.py --debug
```

---

## 📖 更多信息

- **完整文档**: `docs/API_GUIDE.md`
- **快速开始**: `docs/QUICK_START.md`
- **客户端示例**: `scripts/api_client_example.py`
