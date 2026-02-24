# ============================================================
# RWS — Robot Weapon Station — Backend API Server
# ============================================================
# Multi-stage build:
#   stage 1 (builder): install Python deps with UV into a venv
#   stage 2 (runtime): copy venv + source, run Flask server
#
# Usage:
#   docker build -t rws-backend .
#   docker run -p 5000:5000 rws-backend
#   docker run -p 5000:5000 --device /dev/video0 rws-backend  # with camera
# ============================================================

FROM python:3.11-slim AS builder

WORKDIR /build

# System packages needed to build OpenCV / numpy wheels
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ libglib2.0-0 libsm6 libxext6 libxrender-dev \
    libgl1-mesa-glx libgstreamer1.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Install UV for fast dependency resolution
RUN pip install --no-cache-dir uv

COPY pyproject.toml .
COPY requirements.txt .
COPY src/ src/

# Create venv, install runtime deps + opencv-python-headless (no display needed)
# opencv-python-headless replaces opencv-python: same API, no GUI libraries
RUN uv venv /opt/venv && \
    /opt/venv/bin/pip install --no-cache-dir \
        flask>=2.3.0 \
        flask-cors>=4.0.0 \
        requests>=2.31.0 \
        grpcio>=1.60.0 \
        grpcio-tools>=1.60.0 \
        protobuf>=4.25.0 \
        ultralytics>=8.3.0 \
        opencv-python-headless>=4.8.0 \
        numpy>=1.24.0 \
        scipy>=1.11.0 \
        pyyaml>=6.0 && \
    /opt/venv/bin/pip install --no-cache-dir --no-deps -e .

# -----------------------------------------------------------------------

FROM python:3.11-slim AS runtime

WORKDIR /app

# Runtime system libraries for OpenCV headless
RUN apt-get update && apt-get install -y --no-install-recommends \
    libglib2.0-0 libsm6 libxext6 libxrender1 libgl1-mesa-glx \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy built venv from builder
COPY --from=builder /opt/venv /opt/venv

# Copy application source, config, scripts, and mission profiles
COPY src/ src/
COPY scripts/ scripts/
COPY profiles/ profiles/
COPY config.yaml .

# Create writable directories for runtime artifacts
RUN mkdir -p logs/clips logs/reports models

# Non-root user for security
RUN useradd -m -u 1000 rws && \
    chown -R rws:rws /app
USER rws

ENV PATH="/opt/venv/bin:$PATH"
ENV PYTHONPATH="/app/src"
ENV FLASK_ENV=production
ENV PYTHONUNBUFFERED=1
ENV RWS_CONFIG_PATH=/app/config.yaml

EXPOSE 5000 50051

# Health check: verify the API responds (uses curl installed above)
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -sf http://localhost:5000/api/health || exit 1

CMD ["python", "scripts/api/run_rest_server.py", \
     "--host", "0.0.0.0", \
     "--port", "5000", \
     "--config", "/app/config.yaml"]
