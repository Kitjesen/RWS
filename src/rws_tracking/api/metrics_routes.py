"""Prometheus-compatible metrics endpoint.

Exposes operational metrics in Prometheus text format at GET /metrics.
Compatible with Grafana → Prometheus scrape or any tool that reads
the text-based exposition format.

Metrics exposed:
  rws_tracks_total           — current active track count
  rws_threat_score{id}       — threat score per track
  rws_fire_chain_state       — encoded fire chain state (0=safe, 1=armed, 2=fire_auth, 3=req, 4=fired, 5=cooldown)
  rws_shots_fired_total      — cumulative shots fired (from audit log)
  rws_lifecycle_by_state{state} — target counts per lifecycle state
  rws_health_subsystem{name} — subsystem health (0=unknown, 1=ok, 2=degraded, 3=failed)
  rws_operator_heartbeat_age_s — seconds since last operator heartbeat
  rws_pipeline_fps           — estimated pipeline FPS (frames in last second)

Blueprint is registered by create_flask_app() in server.py.
"""

from __future__ import annotations

import time
import logging
from collections import deque
from flask import Blueprint, Response, current_app

logger = logging.getLogger(__name__)

metrics_bp = Blueprint("metrics", __name__)

# Simple FPS estimator — tracks pipeline step() timestamps
_frame_times: deque = deque(maxlen=100)


def record_frame(timestamp: float) -> None:
    """Call from pipeline loop to track frame rate."""
    _frame_times.append(timestamp)


def _fps() -> float:
    if len(_frame_times) < 2:
        return 0.0
    now = time.monotonic()
    recent = [t for t in _frame_times if now - t <= 1.0]
    return float(len(recent))


# Fire chain state encoding
_CHAIN_STATE_CODES = {
    "safe": 0,
    "armed": 1,
    "fire_authorized": 2,
    "fire_requested": 3,
    "fired": 4,
    "cooldown": 5,
    "not_configured": -1,
}

_HEALTH_CODES = {"ok": 1, "degraded": 2, "failed": 3, "unknown": 0}


def _escape(s: str) -> str:
    return s.replace('"', '\\"').replace("\\", "\\\\").replace("\n", "\\n")


def _gauge(name: str, value: float, labels: dict | None = None, help_text: str = "") -> str:
    label_str = ""
    if labels:
        pairs = ",".join(f'{k}="{_escape(str(v))}"' for k, v in labels.items())
        label_str = f"{{{pairs}}}"
    lines = []
    if help_text:
        lines.append(f"# HELP {name} {help_text}")
        lines.append(f"# TYPE {name} gauge")
    lines.append(f"{name}{label_str} {value}")
    return "\n".join(lines)


@metrics_bp.route("/metrics", methods=["GET"])
def metrics():
    """Prometheus text format metrics."""
    api = current_app.extensions.get("tracking_api")
    pipeline = api.pipeline if api is not None else None

    lines: list[str] = []

    # ---- track count ----
    tracks = getattr(api, "_last_tracks", []) if api else []
    lines.append(_gauge("rws_tracks_total", float(len(tracks)),
                        help_text="Number of active tracks"))

    # ---- threat scores ----
    lines.append("# HELP rws_threat_score Threat score per track")
    lines.append("# TYPE rws_threat_score gauge")
    assessments = getattr(api, "_last_threat_assessments", []) if api else []
    for ta in assessments:
        lines.append(f'rws_threat_score{{track_id="{ta.track_id}"}} {ta.threat_score:.4f}')

    # ---- fire chain state ----
    chain = current_app.extensions.get("shooting_chain")
    chain_code = _CHAIN_STATE_CODES.get(
        chain.state.value if chain else "not_configured", -1
    )
    lines.append(_gauge("rws_fire_chain_state", float(chain_code),
                        help_text="Fire chain state (0=safe,1=armed,2=auth,3=req,4=fired,5=cooldown)"))

    # ---- shots fired (from audit log) ----
    audit = current_app.extensions.get("audit_logger")
    shots = sum(1 for r in (audit._records if audit else []) if r.event_type == "fired")  # noqa: SLF001
    lines.append(_gauge("rws_shots_fired_total", float(shots),
                        help_text="Total shots fired this session"))

    # ---- lifecycle by state ----
    lines.append("# HELP rws_lifecycle_by_state Target counts per lifecycle state")
    lines.append("# TYPE rws_lifecycle_by_state gauge")
    if pipeline is not None:
        lm = getattr(pipeline, "_lifecycle_manager", None)
        if lm is not None:
            s = lm.summary()
            for state_name, count in s.get("by_state", {}).items():
                lines.append(f'rws_lifecycle_by_state{{state="{state_name}"}} {count}')

    # ---- health subsystems ----
    hm = current_app.extensions.get("health_monitor")
    lines.append("# HELP rws_health_subsystem Subsystem health (0=unknown,1=ok,2=degraded,3=failed)")
    lines.append("# TYPE rws_health_subsystem gauge")
    if hm is not None:
        for name, status in hm.get_status().items():
            # get_status() returns plain dicts with a 'status' key
            status_str = status.get("status", "unknown") if isinstance(status, dict) else status.compute_status()
            code = _HEALTH_CODES.get(status_str, 0)
            lines.append(f'rws_health_subsystem{{name="{_escape(name)}"}} {code}')

    # ---- operator watchdog ----
    wd = current_app.extensions.get("operator_watchdog")
    if wd is not None:
        lines.append(_gauge("rws_operator_heartbeat_age_s",
                            round(wd.seconds_since_heartbeat, 1),
                            help_text="Seconds since last operator heartbeat"))

    # ---- pipeline FPS ----
    lines.append(_gauge("rws_pipeline_fps", round(_fps(), 1),
                        help_text="Estimated pipeline frames per second"))

    return Response("\n".join(lines) + "\n", mimetype="text/plain; version=0.0.4")
