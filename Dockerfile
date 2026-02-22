# ============================================================
# RWS — Robot Weapon Station — Backend API Server
# ============================================================
# Multi-stage build:
#   stage 1 (builder): install Python deps with UV into a venv
#   stage 2 (runtime): copy venv + source, run Flask server
#
# Usage:
#   docker build -t rws-backend .
#   docker run -p 5000:5000 --device /dev/video0 rws-backend
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
COPY src/ src/

# Create venv and install deps (no editable install for prod)
RUN uv venv /opt/venv && \
    /opt/venv/bin/pip install --no-cache-dir -e . 2>/dev/null || \
    /opt/venv/bin/pip install --no-cache-dir .

# -----------------------------------------------------------------------

FROM python:3.11-slim AS runtime

WORKDIR /app

# Runtime system libraries for OpenCV
RUN apt-get update && apt-get install -y --no-install-recommends \
    libglib2.0-0 libsm6 libxext6 libxrender1 libgl1-mesa-glx \
    && rm -rf /var/lib/apt/lists/*

# Copy built venv from builder
COPY --from=builder /opt/venv /opt/venv

# Copy application source
COPY src/ src/
COPY profiles/ profiles/

# Create writable directories for runtime artifacts
RUN mkdir -p logs/clips logs/reports

# Non-root user for security
RUN useradd -m -u 1000 rws
RUN chown -R rws:rws /app
USER rws

ENV PATH="/opt/venv/bin:$PATH"
ENV PYTHONPATH="/app"
ENV FLASK_ENV=production
ENV PYTHONUNBUFFERED=1

EXPOSE 5000

# Health check: verify the API responds
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:5000/api/health')" || exit 1

CMD ["python", "-m", "src.rws_tracking.api.server", "--host", "0.0.0.0", "--port", "5000"]
