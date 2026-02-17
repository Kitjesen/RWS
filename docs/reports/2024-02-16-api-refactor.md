# API 重构完成总结

## 完成内容

### 1. 创建 API 模块
- ✅ `src/rws_tracking/api/__init__.py` - API 模块入口
- ✅ `src/rws_tracking/api/server.py` - REST API 服务器
- ✅ `src/rws_tracking/api/client.py` - Python 客户端

### 2. 创建脚本
- ✅ `scripts/run_api_server.py` - API 服务器启动脚本
- ✅ `scripts/api_client_example.py` - 客户端使用示例

### 3. 创建文档
- ✅ `docs/API_GUIDE.md` - 完整 API 文档

### 4. 更新依赖
- ✅ 更新 `requirements.txt` 添加 Flask 相关依赖

## API 功能

### REST 端点
1. **GET** `/api/health` - 健康检查
2. **POST** `/api/start` - 启动跟踪
3. **POST** `/api/stop` - 停止跟踪
4. **GET** `/api/status` - 获取状态
5. **POST** `/api/gimbal/position` - 设置云台位置
6. **POST** `/api/gimbal/rate` - 设置云台速率
7. **GET** `/api/telemetry` - 获取遥测数据
8. **POST** `/api/config` - 更新配置

### Python 客户端
```python
from rws_tracking.api import TrackingClient

client = TrackingClient("http://192.168.1.100:5000")
client.start_tracking(camera_source=0)
status = client.get_status()
client.set_gimbal_position(yaw_deg=10.0, pitch_deg=5.0)
client.stop_tracking()
```

## 使用方法

### 1. 安装依赖
```bash
pip install flask flask-cors requests
```

### 2. 启动 API 服务器
```bash
python scripts/run_api_server.py --host 0.0.0.0 --port 5000
```

### 3. 使用客户端
```bash
python scripts/api_client_example.py
```

### 4. 使用 cURL
```bash
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
```

## 架构设计

### 服务器端
- **TrackingAPI**: 封装 VisionGimbalPipeline，提供 API 接口
- **Flask App**: 处理 HTTP 请求，路由到 API 方法
- **Threading**: 跟踪循环在独立线程运行，不阻塞 API 请求

### 客户端
- **TrackingClient**: 简单的 HTTP 客户端，封装所有 API 调用
- **错误处理**: 自动处理网络错误和超时

## 特性

1. **线程安全**: 跟踪循环和 API 请求在不同线程
2. **CORS 支持**: 允许跨域请求（Web 前端）
3. **错误处理**: 完善的错误处理和日志记录
4. **灵活配置**: 支持自定义主机、端口、配置文件
5. **多语言支持**: 提供 Python、JavaScript、C++ 示例

## 下一步

1. 运行 API 服务器测试
2. 使用客户端示例验证功能
3. 根据需要添加认证（JWT、API Key）
4. 添加 HTTPS 支持（生产环境）
5. 实现 WebSocket 支持（实时视频流）

## 文件清单

```
RWS/
├── src/rws_tracking/api/
│   ├── __init__.py          # API 模块入口
│   ├── server.py            # REST API 服务器
│   └── client.py            # Python 客户端
├── scripts/
│   ├── run_api_server.py    # 服务器启动脚本
│   └── api_client_example.py # 客户端示例
├── docs/
│   └── API_GUIDE.md         # API 文档
└── requirements.txt         # 更新依赖
```
