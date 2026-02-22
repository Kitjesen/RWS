"""Mission debrief report generator.

Reads an AuditLogger's records and renders a self-contained HTML report
with a mission timeline, fire-event summary table, chain integrity status,
and per-operator statistics.

Usage::

    from rws_tracking.telemetry.audit import AuditLogger
    from rws_tracking.telemetry.report import generate_report

    logger = AuditLogger("logs/mission.jsonl")
    html = generate_report(logger, mission_name="Urban CQB 2026-02-23")
    Path("report.html").write_text(html)
"""

from __future__ import annotations

import datetime
import html as html_mod
from dataclasses import asdict
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .audit import AuditLogger, AuditRecord

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_STATE_COLOR = {
    "safe": "#6c757d",
    "armed": "#fd7e14",
    "fire_authorized": "#198754",
    "fire_requested": "#0d6efd",
    "fired": "#dc3545",
    "cooldown": "#0dcaf0",
}

_EVENT_ICON = {
    "arm": "🔓",
    "safe": "🔒",
    "fire_authorized": "✅",
    "fire_requested": "🎯",
    "fired": "💥",
    "cooldown_expired": "⏱",
    "auth_lost": "❌",
    "operator_heartbeat": "♥",
}


def _ts_str(ts: float) -> str:
    return datetime.datetime.fromtimestamp(ts).strftime("%H:%M:%S.%f")[:-3]


def _badge(text: str, color: str) -> str:
    return (
        f'<span style="background:{color};color:#fff;border-radius:4px;'
        f'padding:2px 6px;font-size:0.8em;white-space:nowrap">'
        f"{html_mod.escape(text)}</span>"
    )


def _state_badge(state: str) -> str:
    color = _STATE_COLOR.get(state, "#495057")
    return _badge(state, color)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def generate_report(
    audit_logger: "AuditLogger",
    mission_name: str = "Mission Debrief",
    output_path: str | None = None,
) -> str:
    """Render a self-contained HTML mission debrief report.

    Parameters
    ----------
    audit_logger : AuditLogger
        The logger instance whose records to report on.
    mission_name : str
        Title displayed at the top of the report.
    output_path : str | None
        If provided, also write the HTML to this file path.

    Returns
    -------
    str
        Full HTML content of the report.
    """
    records = audit_logger._records  # noqa: SLF001
    chain_ok, chain_err = audit_logger.verify_chain()
    html_str = _render(records, mission_name, chain_ok, chain_err)

    if output_path:
        from pathlib import Path
        Path(output_path).write_text(html_str, encoding="utf-8")

    return html_str


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _render(
    records: "list[AuditRecord]",
    mission_name: str,
    chain_ok: bool,
    chain_err: str,
) -> str:
    generated_at = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # ---- aggregate stats --------------------------------------------------
    fire_events = [r for r in records if r.event_type == "fired"]
    operators: dict[str, dict] = {}
    for r in records:
        op = operators.setdefault(r.operator_id, {"arms": 0, "fires": 0, "safes": 0})
        if r.event_type == "arm":
            op["arms"] += 1
        elif r.event_type == "fired":
            op["fires"] += 1
        elif r.event_type == "safe":
            op["safes"] += 1

    mission_start = _ts_str(records[0].timestamp) if records else "—"
    mission_end = _ts_str(records[-1].timestamp) if records else "—"

    # ---- chain integrity badge --------------------------------------------
    integrity_badge = (
        _badge("✔ Chain valid", "#198754")
        if chain_ok
        else _badge(f"✘ Chain broken: {html_mod.escape(chain_err)}", "#dc3545")
    )

    # ---- timeline rows ----------------------------------------------------
    timeline_rows = _build_timeline_rows(records)

    # ---- fire events table ------------------------------------------------
    fire_table_rows = _build_fire_table_rows(fire_events)

    # ---- operator stats rows ----------------------------------------------
    op_rows = "".join(
        f"<tr><td>{html_mod.escape(op)}</td><td>{s['arms']}</td>"
        f"<td>{s['fires']}</td><td>{s['safes']}</td></tr>"
        for op, s in operators.items()
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html_mod.escape(mission_name)}</title>
<style>
  body {{font-family:system-ui,sans-serif;margin:0;background:#f8f9fa;color:#212529}}
  .container {{max-width:1100px;margin:0 auto;padding:24px}}
  h1 {{margin-bottom:4px}}
  .meta {{color:#6c757d;font-size:0.9em;margin-bottom:24px}}
  .grid {{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:16px;margin-bottom:24px}}
  .card {{background:#fff;border-radius:8px;padding:16px;box-shadow:0 1px 3px rgba(0,0,0,.1)}}
  .card .num {{font-size:2em;font-weight:700}}
  .card .label {{color:#6c757d;font-size:0.85em}}
  table {{width:100%;border-collapse:collapse;background:#fff;border-radius:8px;overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,.1)}}
  th {{background:#343a40;color:#fff;padding:10px 12px;text-align:left;font-size:0.85em}}
  td {{padding:8px 12px;border-bottom:1px solid #dee2e6;font-size:0.85em;vertical-align:middle}}
  tr:last-child td {{border-bottom:none}}
  tr:hover td {{background:#f1f3f5}}
  .section-title {{font-size:1.1em;font-weight:600;margin:24px 0 8px}}
  .integrity {{margin-bottom:16px}}
</style>
</head>
<body>
<div class="container">
  <h1>{html_mod.escape(mission_name)}</h1>
  <div class="meta">Generated {generated_at} &nbsp;|&nbsp; {len(records)} events &nbsp;|&nbsp; {mission_start} – {mission_end}</div>

  <div class="integrity">{integrity_badge}</div>

  <div class="grid">
    <div class="card"><div class="num">{len(records)}</div><div class="label">Total events</div></div>
    <div class="card"><div class="num">{len(fire_events)}</div><div class="label">Shots fired</div></div>
    <div class="card"><div class="num">{len(operators)}</div><div class="label">Operators</div></div>
    <div class="card"><div class="num">{'OK' if chain_ok else 'FAIL'}</div><div class="label">Chain integrity</div></div>
  </div>

  <div class="section-title">Operator Statistics</div>
  <table>
    <tr><th>Operator</th><th>Arms</th><th>Fires</th><th>Safes</th></tr>
    {op_rows if op_rows else '<tr><td colspan="4" style="color:#6c757d">No operator data</td></tr>'}
  </table>

  {_fire_events_section(fire_table_rows)}

  <div class="section-title">Full Event Timeline</div>
  <table>
    <tr><th>#</th><th>Time</th><th>Event</th><th>State</th><th>Operator</th><th>Target</th><th>Threat</th><th>Distance (m)</th></tr>
    {timeline_rows if timeline_rows else '<tr><td colspan="8" style="color:#6c757d">No events recorded</td></tr>'}
  </table>
</div>
</body>
</html>"""


def _fire_events_section(rows: str) -> str:
    if not rows:
        return ""
    return f"""
  <div class="section-title">Fire Events</div>
  <table>
    <tr><th>Time</th><th>Operator</th><th>Target</th><th>Threat Score</th><th>Distance (m)</th></tr>
    {rows}
  </table>"""


def _build_timeline_rows(records: "list[AuditRecord]") -> str:
    parts = []
    for r in records:
        icon = _EVENT_ICON.get(r.event_type, "•")
        target_cell = f"#{r.target_id}" if r.target_id is not None else "—"
        threat_cell = f"{r.threat_score:.3f}" if r.threat_score else "—"
        dist_cell = f"{r.distance_m:.1f}" if r.distance_m else "—"
        parts.append(
            f"<tr>"
            f"<td>{r.seq}</td>"
            f"<td>{_ts_str(r.timestamp)}</td>"
            f"<td>{icon} {html_mod.escape(r.event_type)}</td>"
            f"<td>{_state_badge(r.chain_state)}</td>"
            f"<td>{html_mod.escape(r.operator_id or '—')}</td>"
            f"<td>{target_cell}</td>"
            f"<td>{threat_cell}</td>"
            f"<td>{dist_cell}</td>"
            f"</tr>"
        )
    return "".join(parts)


def _build_fire_table_rows(fire_events: "list[AuditRecord]") -> str:
    parts = []
    for r in fire_events:
        target_cell = f"#{r.target_id}" if r.target_id is not None else "—"
        parts.append(
            f"<tr>"
            f"<td>{_ts_str(r.timestamp)}</td>"
            f"<td>{html_mod.escape(r.operator_id or '—')}</td>"
            f"<td>{target_cell}</td>"
            f"<td>{r.threat_score:.3f}</td>"
            f"<td>{r.distance_m:.1f}</td>"
            f"</tr>"
        )
    return "".join(parts)
