# RWS Tracking gRPC API Guide

## Overview

The RWS Tracking system now provides both REST and gRPC APIs for remote control. gRPC offers:

- **Better Performance**: Binary protocol, HTTP/2, multiplexing
- **Streaming Support**: Real-time status updates
- **Type Safety**: Strong typing with Protocol Buffers
- **Multi-Language**: Easy client generation for C++, Java, Go, etc.

## Quick Start

### 1. Install Dependencies

```bash
pip install grpcio grpcio-tools protobuf
```

### 2. Generate Protobuf Code

```bash
cd src/rws_tracking/api
python -m grpc_tools.protoc -I. --python_out=. --grpc_python_out=. tracking.proto
```

This generates:
- `tracking_pb2.py` - Message definitions
- `tracking_pb2_grpc.py` - Service stubs

### 3. Start gRPC Server

```bash
python scripts/run_grpc_server.py --host 0.0.0.0 --port 50051
```

### 4. Use Python Client

```python
from rws_tracking.api.grpc_client import TrackingGrpcClient

client = TrackingGrpcClient(host="localhost", port=50051)
client.start_tracking(camera_source=0)
status = client.get_status()
client.set_gimbal_position(yaw_deg=10.0, pitch_deg=5.0)
client.stop_tracking()
client.close()
```

## gRPC Methods

### Unary RPCs (Request-Response)

| Method | Description |
|--------|-------------|
| `HealthCheck` | Check server health |
| `StartTracking` | Start tracking with camera source |
| `StopTracking` | Stop tracking |
| `GetStatus` | Get current status |
| `SetGimbalPosition` | Set gimbal absolute position |
| `SetGimbalRate` | Set gimbal velocity |
| `GetTelemetry` | Get performance metrics |
| `UpdateConfig` | Update configuration |

### Streaming RPCs

| Method | Description |
|--------|-------------|
| `StreamStatus` | Real-time status updates (server streaming) |

## Python Client API

### Basic Usage

```python
from rws_tracking.api.grpc_client import TrackingGrpcClient

# Connect
client = TrackingGrpcClient(host="192.168.1.100", port=50051, timeout=5.0)

# Health check
health = client.health_check()
print(health)  # {'status': 'ok', 'service': 'rws-tracking'}

# Start tracking
result = client.start_tracking(camera_source=0)
print(result)  # {'success': True, 'message': '...'}

# Get status
status = client.get_status()
print(f"FPS: {status['fps']:.1f}")
print(f"Gimbal: {status['gimbal']}")

# Control gimbal
client.set_gimbal_position(yaw_deg=15.0, pitch_deg=10.0)
client.set_gimbal_rate(yaw_rate_dps=20.0, pitch_rate_dps=10.0)

# Get telemetry
telemetry = client.get_telemetry()
print(telemetry['metrics'])

# Stop tracking
client.stop_tracking()

# Close connection
client.close()
```

### Context Manager

```python
with TrackingGrpcClient(host="localhost", port=50051) as client:
    client.start_tracking()
    status = client.get_status()
    client.stop_tracking()
# Automatically closes connection
```

### Streaming Status Updates

```python
client = TrackingGrpcClient()
client.start_tracking()

# Stream at 10 Hz
for update in client.stream_status(update_rate_hz=10.0):
    print(f"FPS: {update['fps']:.1f}, "
          f"Yaw: {update['gimbal']['yaw_deg']:.1f}°")

    # Break after some condition
    if update['frame_count'] > 1000:
        break

client.stop_tracking()
client.close()
```

## C++ Client Example

### 1. Generate C++ Code

```bash
protoc -I. --cpp_out=. --grpc_out=. --plugin=protoc-gen-grpc=`which grpc_cpp_plugin` tracking.proto
```

### 2. C++ Client

```cpp
#include <grpcpp/grpcpp.h>
#include "tracking.grpc.pb.h"

using grpc::Channel;
using grpc::ClientContext;
using grpc::Status;
using rws_tracking::TrackingService;
using rws_tracking::StartTrackingRequest;
using rws_tracking::StartTrackingResponse;

class TrackingClient {
public:
    TrackingClient(std::shared_ptr<Channel> channel)
        : stub_(TrackingService::NewStub(channel)) {}

    bool StartTracking(int camera_id) {
        StartTrackingRequest request;
        request.set_camera_id(camera_id);

        StartTrackingResponse response;
        ClientContext context;

        Status status = stub_->StartTracking(&context, request, &response);

        if (status.ok()) {
            return response.success();
        } else {
            std::cerr << "RPC failed: " << status.error_message() << std::endl;
            return false;
        }
    }

private:
    std::unique_ptr<TrackingService::Stub> stub_;
};

int main() {
    auto channel = grpc::CreateChannel("localhost:50051",
                                      grpc::InsecureChannelCredentials());
    TrackingClient client(channel);

    if (client.StartTracking(0)) {
        std::cout << "Tracking started" << std::endl;
    }

    return 0;
}
```

## Go Client Example

### 1. Generate Go Code

```bash
protoc -I. --go_out=. --go-grpc_out=. tracking.proto
```

### 2. Go Client

```go
package main

import (
    "context"
    "log"
    "time"

    "google.golang.org/grpc"
    pb "path/to/tracking"
)

func main() {
    conn, err := grpc.Dial("localhost:50051", grpc.WithInsecure())
    if err != nil {
        log.Fatalf("Failed to connect: %v", err)
    }
    defer conn.Close()

    client := pb.NewTrackingServiceClient(conn)
    ctx, cancel := context.WithTimeout(context.Background(), time.Second*5)
    defer cancel()

    // Start tracking
    startReq := &pb.StartTrackingRequest{
        CameraSource: &pb.StartTrackingRequest_CameraId{CameraId: 0},
    }
    startResp, err := client.StartTracking(ctx, startReq)
    if err != nil {
        log.Fatalf("StartTracking failed: %v", err)
    }
    log.Printf("Started: %v", startResp.Success)

    // Get status
    statusResp, err := client.GetStatus(ctx, &pb.GetStatusRequest{})
    if err != nil {
        log.Fatalf("GetStatus failed: %v", err)
    }
    log.Printf("FPS: %.1f", statusResp.Fps)
}
```

## Comparison: REST vs gRPC

| Feature | REST API | gRPC API |
|---------|----------|----------|
| Protocol | HTTP/1.1 JSON | HTTP/2 Protobuf |
| Performance | Good | Excellent |
| Streaming | No | Yes (StreamStatus) |
| Browser Support | Native | Requires grpc-web |
| Type Safety | Runtime | Compile-time |
| Code Generation | Manual | Automatic |
| Latency | ~5-10ms | ~1-3ms |
| Bandwidth | Higher | Lower (binary) |

## When to Use Each

**Use REST API when:**
- Building web frontends
- Need simple HTTP access
- Debugging with curl/browser
- Working with languages without gRPC support

**Use gRPC API when:**
- Need high performance
- Want real-time streaming
- Building microservices
- Using C++/Go/Java clients
- Need strong typing

## Testing

### Test Both APIs

```bash
# Terminal 1: Start REST server
python scripts/run_api_server.py

# Terminal 2: Start gRPC server
python scripts/run_grpc_server.py

# Terminal 3: Run tests
python scripts/test_api.py
```

### Test gRPC Only

```bash
# Terminal 1: Start server
python scripts/run_grpc_server.py

# Terminal 2: Run client example
python scripts/grpc_client_example.py
```

## Troubleshooting

### Protobuf Generation Failed

```bash
# Install grpcio-tools
pip install grpcio-tools

# Generate from project root
cd src/rws_tracking/api
python -m grpc_tools.protoc -I. --python_out=. --grpc_python_out=. tracking.proto
```

### Import Error

If you get `ImportError: cannot import name 'tracking_pb2'`:

1. Make sure protobuf files are generated
2. Check that `__init__.py` exists in `api/` directory
3. Verify Python path includes `src/`

### Connection Refused

- Ensure server is running: `python scripts/run_grpc_server.py`
- Check firewall allows port 50051
- Verify host/port in client matches server

### Streaming Interrupted

- Check network stability
- Increase timeout in client
- Monitor server logs for errors

## Performance Tips

1. **Use Streaming**: For continuous monitoring, use `StreamStatus` instead of polling `GetStatus`
2. **Connection Pooling**: Reuse client connections instead of creating new ones
3. **Compression**: Enable gRPC compression for large messages
4. **Async Clients**: Use async gRPC for concurrent requests

## Security

For production deployment:

1. **Enable TLS**: Use SSL/TLS certificates
2. **Authentication**: Add token-based auth
3. **Rate Limiting**: Prevent abuse
4. **Firewall**: Restrict access to trusted IPs

Example with TLS:

```python
# Server
credentials = grpc.ssl_server_credentials([(private_key, certificate)])
server.add_secure_port(f'{host}:{port}', credentials)

# Client
credentials = grpc.ssl_channel_credentials(root_certificates)
channel = grpc.secure_channel(f'{host}:{port}', credentials)
```

## Next Steps

1. Generate protobuf code: `python -m grpc_tools.protoc ...`
2. Start gRPC server: `python scripts/run_grpc_server.py`
3. Test with client: `python scripts/grpc_client_example.py`
4. Integrate into your application
5. Add TLS for production use
