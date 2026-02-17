# RWS Tracking API Documentation

## Overview

The RWS Tracking API provides REST endpoints for controlling the vision-gimbal tracking system from external devices.

## Quick Start

### 1. Install Dependencies

```bash
pip install flask flask-cors requests
```

### 2. Start API Server

```bash
python scripts/run_api_server.py --host 0.0.0.0 --port 5000
```

### 3. Use Python Client

```python
from rws_tracking.api import TrackingClient

client = TrackingClient("http://192.168.1.100:5000")
client.start_tracking(camera_source=0)
status = client.get_status()
client.set_gimbal_position(yaw_deg=10.0, pitch_deg=5.0)
client.stop_tracking()
```

## API Endpoints

### Health Check

**GET** `/api/health`

Check if the API server is running.

**Response:**
```json
{
  "status": "ok",
  "service": "rws-tracking"
}
```

---

### Start Tracking

**POST** `/api/start`

Start the tracking pipeline.

**Request Body:**
```json
{
  "camera_source": 0
}
```

**Parameters:**
- `camera_source` (int|string): Camera device ID (0 for default) or video file path

**Response:**
```json
{
  "success": true,
  "message": "Tracking started"
}
```

---

### Stop Tracking

**POST** `/api/stop`

Stop the tracking pipeline.

**Response:**
```json
{
  "success": true,
  "message": "Tracking stopped"
}
```

---

### Get Status

**GET** `/api/status`

Get current tracking status.

**Response:**
```json
{
  "running": true,
  "frame_count": 1234,
  "error_count": 0,
  "last_error": null,
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

### Set Gimbal Position

**POST** `/api/gimbal/position`

Set gimbal to absolute position.

**Request Body:**
```json
{
  "yaw_deg": 10.0,
  "pitch_deg": 5.0
}
```

**Parameters:**
- `yaw_deg` (float): Target yaw angle in degrees
- `pitch_deg` (float): Target pitch angle in degrees

**Response:**
```json
{
  "success": true,
  "target": {
    "yaw_deg": 10.0,
    "pitch_deg": 5.0
  },
  "current": {
    "yaw_deg": 9.8,
    "pitch_deg": 4.9
  }
}
```

---

### Set Gimbal Rate

**POST** `/api/gimbal/rate`

Set gimbal velocity (rate control).

**Request Body:**
```json
{
  "yaw_rate_dps": 20.0,
  "pitch_rate_dps": 10.0
}
```

**Parameters:**
- `yaw_rate_dps` (float): Yaw rate in degrees per second
- `pitch_rate_dps` (float): Pitch rate in degrees per second

**Response:**
```json
{
  "success": true,
  "command": {
    "yaw_rate_dps": 20.0,
    "pitch_rate_dps": 10.0
  }
}
```

---

### Get Telemetry

**GET** `/api/telemetry`

Get telemetry metrics.

**Response:**
```json
{
  "success": true,
  "metrics": {
    "control.yaw_cmd_dps.mean": 5.2,
    "control.pitch_cmd_dps.mean": 2.1,
    "control.yaw_error_deg.mean": 0.8,
    "control.pitch_error_deg.mean": 0.5
  }
}
```

---

### Update Configuration

**POST** `/api/config`

Update system configuration (requires restart to apply).

**Request Body:**
```json
{
  "controller": {
    "yaw_pid": {
      "kp": 6.0,
      "ki": 0.5
    }
  }
}
```

**Response:**
```json
{
  "success": true,
  "message": "Config updated (restart required to apply)"
}
```

---

## Python Client API

### TrackingClient

```python
from rws_tracking.api import TrackingClient

client = TrackingClient(base_url="http://192.168.1.100:5000", timeout=5.0)
```

#### Methods

##### `health_check() -> dict`
Check server health.

##### `start_tracking(camera_source=0) -> dict`
Start tracking with specified camera source.

##### `stop_tracking() -> dict`
Stop tracking.

##### `get_status() -> dict`
Get current status including gimbal position and FPS.

##### `set_gimbal_position(yaw_deg, pitch_deg) -> dict`
Set gimbal to absolute position.

##### `set_gimbal_rate(yaw_rate_dps, pitch_rate_dps) -> dict`
Set gimbal velocity.

##### `get_telemetry() -> dict`
Get telemetry metrics.

##### `update_config(config) -> dict`
Update configuration.

---

## Usage Examples

### Example 1: Basic Control

```python
from rws_tracking.api import TrackingClient
import time

client = TrackingClient("http://localhost:5000")

# Start tracking
client.start_tracking(camera_source=0)

# Wait for initialization
time.sleep(2)

# Get status
status = client.get_status()
print(f"FPS: {status['fps']:.1f}")
print(f"Gimbal: {status['gimbal']}")

# Control gimbal
client.set_gimbal_position(yaw_deg=15.0, pitch_deg=10.0)
time.sleep(3)

# Stop tracking
client.stop_tracking()
```

### Example 2: Continuous Monitoring

```python
from rws_tracking.api import TrackingClient
import time

client = TrackingClient("http://localhost:5000")
client.start_tracking()

try:
    while True:
        status = client.get_status()
        if status.get("running"):
            gimbal = status.get("gimbal", {})
            print(f"Yaw: {gimbal.get('yaw_deg', 0):.1f}°, "
                  f"Pitch: {gimbal.get('pitch_deg', 0):.1f}°, "
                  f"FPS: {status.get('fps', 0):.1f}")
        time.sleep(0.5)
except KeyboardInterrupt:
    client.stop_tracking()
```

### Example 3: Scan Pattern

```python
from rws_tracking.api import TrackingClient
import time
import math

client = TrackingClient("http://localhost:5000")
client.start_tracking()

# Execute scan pattern
for i in range(100):
    t = i * 0.1
    yaw = 30 * math.sin(t)
    pitch = 15 * math.cos(t * 0.5)
    client.set_gimbal_position(yaw_deg=yaw, pitch_deg=pitch)
    time.sleep(0.1)

client.stop_tracking()
```

---

## cURL Examples

### Start Tracking
```bash
curl -X POST http://localhost:5000/api/start \
  -H "Content-Type: application/json" \
  -d '{"camera_source": 0}'
```

### Get Status
```bash
curl http://localhost:5000/api/status
```

### Set Gimbal Position
```bash
curl -X POST http://localhost:5000/api/gimbal/position \
  -H "Content-Type: application/json" \
  -d '{"yaw_deg": 10.0, "pitch_deg": 5.0}'
```

### Stop Tracking
```bash
curl -X POST http://localhost:5000/api/stop
```

---

## Integration with Other Languages

### JavaScript/Node.js

```javascript
const axios = require('axios');

const API_URL = 'http://192.168.1.100:5000';

async function startTracking() {
  const response = await axios.post(`${API_URL}/api/start`, {
    camera_source: 0
  });
  console.log(response.data);
}

async function getStatus() {
  const response = await axios.get(`${API_URL}/api/status`);
  console.log(response.data);
}

async function setGimbalPosition(yaw, pitch) {
  const response = await axios.post(`${API_URL}/api/gimbal/position`, {
    yaw_deg: yaw,
    pitch_deg: pitch
  });
  console.log(response.data);
}
```

### C++ (using libcurl)

```cpp
#include <curl/curl.h>
#include <string>

class TrackingClient {
public:
    TrackingClient(const std::string& base_url) : base_url_(base_url) {
        curl_global_init(CURL_GLOBAL_DEFAULT);
    }

    bool startTracking(int camera_source = 0) {
        std::string url = base_url_ + "/api/start";
        std::string json = "{\"camera_source\": " + std::to_string(camera_source) + "}";
        return post(url, json);
    }

    bool setGimbalPosition(double yaw_deg, double pitch_deg) {
        std::string url = base_url_ + "/api/gimbal/position";
        std::string json = "{\"yaw_deg\": " + std::to_string(yaw_deg) +
                          ", \"pitch_deg\": " + std::to_string(pitch_deg) + "}";
        return post(url, json);
    }

private:
    std::string base_url_;

    bool post(const std::string& url, const std::string& json) {
        CURL* curl = curl_easy_init();
        if (!curl) return false;

        curl_easy_setopt(curl, CURLOPT_URL, url.c_str());
        curl_easy_setopt(curl, CURLOPT_POSTFIELDS, json.c_str());

        struct curl_slist* headers = NULL;
        headers = curl_slist_append(headers, "Content-Type: application/json");
        curl_easy_setopt(curl, CURLOPT_HTTPHEADER, headers);

        CURLcode res = curl_easy_perform(curl);

        curl_slist_free_all(headers);
        curl_easy_cleanup(curl);

        return res == CURLE_OK;
    }
};
```

---

## Error Handling

All endpoints return a JSON response with a `success` field:

**Success:**
```json
{
  "success": true,
  "message": "Operation completed"
}
```

**Error:**
```json
{
  "success": false,
  "error": "Error description"
}
```

Common error codes:
- `400 Bad Request`: Missing or invalid parameters
- `500 Internal Server Error`: Server-side error

---

## Security Considerations

1. **Network Security**: The API server binds to `0.0.0.0` by default, making it accessible from any network interface. For production:
   - Use a firewall to restrict access
   - Consider adding authentication (JWT tokens, API keys)
   - Use HTTPS with SSL/TLS certificates

2. **Rate Limiting**: Consider implementing rate limiting to prevent abuse.

3. **Input Validation**: All inputs are validated, but additional checks may be needed for your use case.

---

## Troubleshooting

### Server won't start
- Check if port 5000 is already in use: `netstat -an | grep 5000`
- Try a different port: `python scripts/run_api_server.py --port 5001`

### Cannot connect from remote device
- Ensure firewall allows incoming connections on port 5000
- Check that server is bound to `0.0.0.0`, not `127.0.0.1`

### Tracking not starting
- Verify camera is accessible: `ls /dev/video*` (Linux)
- Check camera permissions
- Review server logs for error messages

---

## Performance Tips

1. **Reduce latency**: Run API server on the same machine as the camera
2. **Network optimization**: Use wired Ethernet instead of WiFi for control
3. **Concurrent requests**: The server handles requests in separate threads
4. **Monitoring**: Use `/api/status` endpoint to monitor FPS and performance
