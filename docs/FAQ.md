# Frequently Asked Questions (FAQ)

## General Questions

### What is RWS?

RWS (Robot Weapon System) is a lightweight vision-gimbal tracking system for 2-DOF (yaw/pitch) target pursuit and lock-on. It uses YOLO11n-Seg for detection and BoT-SORT for tracking, with support for moving-base operation (e.g., robot dogs) using IMU feedforward compensation.

### Do I need ROS2 to use RWS?

No! RWS is designed as a non-ROS2 system. It's a standalone Python application that can run independently without any ROS dependencies.

### What hardware do I need?

**Minimum setup (simulation mode)**:
- Computer with Python 3.11+
- No physical hardware required

**Full hardware setup**:
- USB or IP camera
- Serial gimbal (yaw/pitch, UART protocol)
- IMU sensor (optional, for moving-base compensation)
- Computer with Python 3.11+ and optional GPU

See [Hardware Guide](guides/hardware-setup.md) for details.

### What platforms are supported?

- **Linux**: Ubuntu 20.04+, other distributions
- **Windows**: Windows 10/11
- **macOS**: macOS 11+ (including Apple Silicon)

## Installation & Setup

### How do I install RWS?

```bash
git clone https://github.com/Kitjesen/RWS.git
cd RWS
pip install -r requirements.txt
pip install -e .
```

See [Quick Start Guide](getting-started/quick-start.md) for detailed instructions.

### Do I need a GPU?

Not required, but recommended for better performance:
- **CPU only**: 10-15 FPS with YOLO11n
- **GPU (NVIDIA)**: 30+ FPS with YOLO11n

### What Python version do I need?

Python 3.11 or higher is required. Python 3.12 is recommended.

### Installation fails with "No module named 'torch'"

Install PyTorch first:
```bash
# CPU only
pip install torch torchvision

# GPU (CUDA 11.8)
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu118

# GPU (CUDA 12.1)
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu121
```

## Configuration

### How do I configure the camera?

Edit `config.yaml`:
```yaml
camera:
  source: 0  # 0 for USB camera, or "rtsp://..." for IP camera
  width: 640
  height: 480
  fps: 30
```

### How do I enable/disable hardware?

In `config.yaml`:
```yaml
gimbal:
  enabled: true  # Set to false for simulation
  port: "COM3"   # Serial port

imu:
  enabled: true  # Set to false to disable IMU
  port: "COM4"
```

### Can I change detection parameters?

Yes, edit the `perception` section in `config.yaml`:
```yaml
perception:
  detector:
    model_path: "models/yolo11n-seg.pt"
    conf_threshold: 0.25
    iou_threshold: 0.7
  tracker:
    track_high_thresh: 0.5
    track_low_thresh: 0.1
```

### How do I tune PID parameters?

Edit the `control` section in `config.yaml`:
```yaml
control:
  yaw_pid:
    kp: 0.8
    ki: 0.0
    kd: 0.1
  pitch_pid:
    kp: 0.6
    ki: 0.0
    kd: 0.08
```

See [Coordinate Math Guide](guides/coordinate-math.md) for tuning tips.

## Usage

### How do I run a simple demo?

```bash
# No camera required
python scripts/demo/run_simple_demo.py

# With camera
python scripts/demo/run_camera_demo.py
```

### How do I use the REST API?

Start the server:
```bash
python scripts/api/run_rest_server.py
```

Use the client:
```python
from rws_tracking.api import TrackingClient

client = TrackingClient("http://localhost:5000")
client.start_tracking(camera_source=0)
status = client.get_status()
client.stop_tracking()
```

See [API Guide](api/API_GUIDE.md) for more examples.

### How do I use the gRPC API?

Start the server:
```bash
python scripts/api/run_grpc_server.py
```

Use the client:
```python
from rws_tracking.api import TrackingGrpcClient

with TrackingGrpcClient("localhost", 50051) as client:
    client.start_tracking()
    for update in client.stream_status():
        print(f"FPS: {update['fps']}")
```

See [gRPC Guide](api/GRPC_GUIDE.md) for more examples.

### Can I run multiple tracking sessions?

No, currently only one tracking session is supported at a time. Starting a new session will stop the previous one.

## Troubleshooting

### Camera not detected

1. Check camera connection: `ls /dev/video*` (Linux) or Device Manager (Windows)
2. Try different source IDs: `source: 0`, `source: 1`, etc.
3. For IP cameras, verify RTSP URL: `ffplay rtsp://...`

### Gimbal not responding

1. Check serial port: `ls /dev/ttyUSB*` (Linux) or Device Manager (Windows)
2. Verify baud rate matches your gimbal (default: 115200)
3. Check cable connections
4. Test with simulation mode first: `gimbal.enabled: false`

### Low FPS / Performance issues

1. **Use smaller model**: Switch to YOLO11n (fastest)
2. **Reduce resolution**: Lower camera width/height in config
3. **Disable visualization**: Set `visualization.enabled: false`
4. **Use GPU**: Install CUDA-enabled PyTorch
5. **Close other applications**: Free up CPU/GPU resources

### "CUDA out of memory" error

1. Use smaller YOLO model (n instead of s/m/l)
2. Reduce camera resolution
3. Reduce batch size (if applicable)
4. Use CPU mode: `device: "cpu"` in config

### Import errors after installation

Make sure you installed in editable mode:
```bash
pip install -e .
```

Or add to PYTHONPATH:
```bash
export PYTHONPATH="${PYTHONPATH}:/path/to/RWS/src"
```

### Tests failing

1. Install test dependencies: `pip install pytest pytest-cov`
2. Check Python version: `python --version` (must be 3.11+)
3. Run specific test: `pytest tests/test_specific.py -v`

## Performance

### What FPS can I expect?

- **YOLO11n + CPU**: 10-15 FPS
- **YOLO11n + GPU**: 30-40 FPS
- **YOLO11s + GPU**: 20-30 FPS
- **YOLO11m + GPU**: 15-20 FPS

### How accurate is the tracking?

- **Detection accuracy**: 85-95% (depends on model and scene)
- **Tracking stability**: High (BoT-SORT with Kalman filtering)
- **Control precision**: ±1-2 degrees (depends on PID tuning)

### What's the latency?

- **Detection**: 30-50ms (YOLO11n on GPU)
- **Tracking**: <10ms (BoT-SORT)
- **Control**: 10ms (100 Hz update rate)
- **Total end-to-end**: 50-70ms

## Development

### How do I contribute?

See [Contributing Guide](CONTRIBUTING.md) for:
- Code style guidelines
- Testing requirements
- Pull request process

### How do I run tests?

```bash
# All tests
pytest tests/

# With coverage
pytest tests/ --cov=rws_tracking --cov-report=html

# Specific test file
pytest tests/test_perception.py -v
```

### How do I add a new feature?

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/my-feature`
3. Make changes and add tests
4. Run tests: `pytest tests/`
5. Run linting: `ruff check .`
6. Run type checking: `mypy src/`
7. Submit a pull request

### Where can I find API documentation?

- [API Quick Reference](api/API_QUICK_REFERENCE.md)
- [API Guide](api/API_GUIDE.md)
- [gRPC Guide](api/GRPC_GUIDE.md)

## Advanced Topics

### Can I use custom YOLO models?

Yes! Train your own model and update `config.yaml`:
```yaml
perception:
  detector:
    model_path: "path/to/your/model.pt"
```

See [Training Guide](guides/training.md) for details.

### How do I add IMU compensation?

1. Enable IMU in config: `imu.enabled: true`
2. Configure serial port: `imu.port: "COM4"`
3. The system automatically applies feedforward compensation

See [Hardware Guide](guides/hardware-setup.md) for IMU setup.

### Can I integrate with other systems?

Yes! Use the REST or gRPC API to integrate with:
- Web applications (REST API)
- High-performance systems (gRPC API)
- ROS2 (via API bridge)
- Custom control systems

### How do I log telemetry data?

Telemetry is automatically logged to `logs/` directory. Configure in `config.yaml`:
```yaml
telemetry:
  enabled: true
  log_dir: "logs"
  log_level: "INFO"
```

## Support

### Where can I get help?

- **Documentation**: [docs/](../docs/)
- **GitHub Issues**: [Report bugs](https://github.com/Kitjesen/RWS/issues)
- **GitHub Discussions**: [Ask questions](https://github.com/Kitjesen/RWS/discussions)
- **Support Guide**: [SUPPORT.md](SUPPORT.md)

### How do I report a bug?

Use our [Bug Report Template](.github/ISSUE_TEMPLATE/bug_report.md) and include:
- Environment details (OS, Python version, hardware)
- Steps to reproduce
- Expected vs actual behavior
- Logs and error messages

### How do I request a feature?

Use our [Feature Request Template](.github/ISSUE_TEMPLATE/feature_request.md) and describe:
- The problem you're trying to solve
- Your proposed solution
- Use cases and benefits

---

**Can't find your question?** Ask in [GitHub Discussions](https://github.com/Kitjesen/RWS/discussions) or check the [full documentation](README.md).

**Last Updated**: 2024-02-17
