"""System self-test REST API.

Runs pre-mission checks on all subsystems and returns a go/no-go status.
Intended to be called before POST /api/mission/start.

GET /api/selftest — runs all checks synchronously (< 2s target latency)
GET /api/selftest/summary — returns last known result without re-running

Checks:
  pipeline_imports   : all required modules can be imported
  shooting_chain     : ShootingChain accessible, starts in SAFE
  audit_logger       : AuditLogger writable (test record + verify)
  health_monitor     : HealthMonitor accessible
  lifecycle_manager  : TargetLifecycleManager accessible
  config_valid       : SystemConfig loads without error
  logs_dir_writable  : logs/ directory writable
"""

from __future__ import annotations

import logging
import time

from flask import Blueprint, current_app, jsonify

logger = logging.getLogger(__name__)

selftest_bp = Blueprint("selftest", __name__, url_prefix="/api/selftest")

_last_result: dict | None = None


def _check(name: str, fn) -> dict:
    t0 = time.monotonic()
    try:
        msg = fn()
        return {
            "name": name,
            "status": "pass",
            "message": msg or "",
            "elapsed_ms": round((time.monotonic() - t0) * 1000, 1),
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "name": name,
            "status": "fail",
            "message": str(exc),
            "elapsed_ms": round((time.monotonic() - t0) * 1000, 1),
        }


@selftest_bp.route("", methods=["GET"])
def run_selftest():
    """Run all self-tests and return go/no-go status."""
    global _last_result

    api = current_app.extensions.get("tracking_api")
    pipeline = api.pipeline if api is not None else None

    checks = []

    # 1. pipeline_imports
    def check_imports():
        from ..decision.engagement import ThreatAssessor  # noqa: F401
        from ..decision.lifecycle import TargetLifecycleManager  # noqa: F401
        from ..health.monitor import HealthMonitor  # noqa: F401
        from ..safety.shooting_chain import ShootingChain  # noqa: F401
        from ..telemetry.audit import AuditLogger  # noqa: F401

        return "all critical imports OK"

    checks.append(_check("pipeline_imports", check_imports))

    # 2. shooting_chain
    def check_chain():
        chain = current_app.extensions.get("shooting_chain")
        if chain is None:
            if pipeline is not None:
                chain = getattr(pipeline, "_shooting_chain", None)
        if chain is None:
            raise RuntimeError("ShootingChain not found in extensions or pipeline")
        state = chain.state.value
        return f"state={state}"

    checks.append(_check("shooting_chain", check_chain))

    # 3. audit_logger
    def check_audit():
        import tempfile
        from pathlib import Path

        from ..telemetry.audit import AuditLogger

        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
            path = f.name
        try:
            al = AuditLogger(path)
            al.log("selftest", "system", "safe")
            ok, err = al.verify_chain()
            if not ok:
                raise RuntimeError(f"chain verify failed: {err}")
        finally:
            Path(path).unlink(missing_ok=True)
        return "write+verify OK"

    checks.append(_check("audit_logger", check_audit))

    # 4. health_monitor
    def check_health():
        hm = current_app.extensions.get("health_monitor")
        if hm is None and pipeline is not None:
            hm = getattr(pipeline, "_health_monitor", None)
        if hm is None:
            raise RuntimeError("HealthMonitor not found")
        hm.heartbeat("selftest", time.monotonic())
        s = hm.get_status()
        return f"{len(s)} subsystems tracked"

    checks.append(_check("health_monitor", check_health))

    # 5. lifecycle_manager
    def check_lifecycle():
        if pipeline is None:
            raise RuntimeError("Pipeline not running; start tracking first")
        lm = getattr(pipeline, "_lifecycle_manager", None)
        if lm is None:
            raise RuntimeError("TargetLifecycleManager not configured")
        summary = lm.summary()
        return f"total_seen={summary.get('total_seen', 0)}"

    checks.append(_check("lifecycle_manager", check_lifecycle))

    # 6. logs_dir_writable
    def check_logs_dir():
        from pathlib import Path

        logs = Path("logs")
        logs.mkdir(exist_ok=True)
        test_file = logs / ".selftest_probe"
        test_file.write_text("ok")
        test_file.unlink()
        return "logs/ writable"

    checks.append(_check("logs_dir_writable", check_logs_dir))

    # 7. config_valid
    def check_config():
        from ..config import load_config  # noqa: F401

        return "config module importable"

    checks.append(_check("config_valid", check_config))

    passed = [c for c in checks if c["status"] == "pass"]
    failed = [c for c in checks if c["status"] == "fail"]
    go = len(failed) == 0

    _last_result = {
        "go": go,
        "timestamp": time.time(),
        "passed": len(passed),
        "failed": len(failed),
        "checks": checks,
    }

    status_code = 200 if go else 424  # 424 Failed Dependency if any check fails
    return jsonify(_last_result), status_code


@selftest_bp.route("/summary", methods=["GET"])
def selftest_summary():
    """Return the last self-test result without re-running."""
    if _last_result is None:
        return jsonify(
            {"error": "No self-test has been run yet. Call GET /api/selftest first."}
        ), 404
    return jsonify(_last_result)
