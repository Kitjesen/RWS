# API Documentation

RWS Tracking System provides both REST and gRPC APIs for remote control.

## Quick Links

- **[REST API](rest-api.md)** - HTTP/JSON API (port 5000)
- **[gRPC API](grpc-api.md)** - High-performance binary API (port 50051)
- **[Quick Reference](quick-reference.md)** - API endpoints at a glance

## Choosing an API

- Use **REST API** for web frontends, simple integration, debugging
- Use **gRPC API** for high performance, streaming, embedded systems

## Getting Started

### REST API
```bash
python scripts/api/run_rest_server.py
```

### gRPC API
```bash
python scripts/api/run_grpc_server.py
```

See the full guides for detailed usage and examples.
