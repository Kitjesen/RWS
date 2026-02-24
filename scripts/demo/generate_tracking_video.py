"""
RWS Tactical Tracking Demo Video Generator
Generates a ~30-second synthetic demo video at logs/tracking_demo.mp4
No camera or YOLO required — all targets are procedurally animated.
"""

import math
import os
import time
from typing import Optional, Tuple

import cv2
import numpy as np

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
WIDTH, HEIGHT = 1280, 720
FPS = 30
TOTAL_FRAMES = 900  # 30 seconds
OUTPUT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "logs",
    "tracking_demo.mp4",
)

# Military HUD colors (BGR)
HUD_GREEN = (0, 220, 0)
HUD_YELLOW = (0, 220, 220)
HUD_RED = (0, 0, 220)
HUD_CYAN = (220, 220, 0)
HUD_ORANGE = (0, 140, 255)
HUD_WHITE = (255, 255, 255)
HUD_GRAY = (130, 130, 130)
HUD_MAGENTA = (220, 0, 220)
HUD_DARK = (20, 30, 20)
BG_DARK = (18, 25, 30)

FONT = cv2.FONT_HERSHEY_SIMPLEX
FONT_SMALL = 0.42
FONT_MED = 0.55
FONT_LARGE = 0.85
THICK_THIN = 1
THICK_MED = 2


# ---------------------------------------------------------------------------
# Background generation
# ---------------------------------------------------------------------------

def make_background() -> np.ndarray:
    """Create a dark tactical background with gradient + noise."""
    bg = np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)

    # Dark blue-gray gradient top-to-bottom
    for y in range(HEIGHT):
        t = y / HEIGHT
        r = int(12 + t * 8)
        g = int(18 + t * 10)
        b = int(24 + t * 14)
        bg[y, :] = (r, g, b)

    # Subtle horizontal banding (terrain / atmosphere lines)
    rng = np.random.default_rng(42)
    noise = rng.integers(0, 10, (HEIGHT, WIDTH, 3), dtype=np.uint8)
    bg = np.clip(bg.astype(np.int16) + noise - 5, 0, 255).astype(np.uint8)

    # Add a few faint far-horizon "hills" using simple polylines
    pts = np.array([[0, 500], [200, 450], [400, 480], [600, 420],
                    [800, 460], [1000, 440], [1280, 470], [1280, 720], [0, 720]], np.int32)
    cv2.fillPoly(bg, [pts], (15, 22, 20))

    pts2 = np.array([[0, 540], [300, 510], [500, 530], [700, 505],
                     [900, 525], [1100, 500], [1280, 520], [1280, 720], [0, 720]], np.int32)
    cv2.fillPoly(bg, [pts2], (10, 16, 14))

    return bg


# Precompute background and vignette
_BG = make_background()


def make_vignette() -> np.ndarray:
    """Create a vignette mask (float32 0–1)."""
    cx, cy = WIDTH // 2, HEIGHT // 2
    Y, X = np.mgrid[0:HEIGHT, 0:WIDTH]
    dist = np.sqrt(((X - cx) / cx) ** 2 + ((Y - cy) / cy) ** 2)
    vig = 1.0 - np.clip(dist * 0.65, 0, 1) ** 1.5
    return vig.astype(np.float32)


_VIGNETTE = make_vignette()


# ---------------------------------------------------------------------------
# Per-frame noise seed for animated texture
# ---------------------------------------------------------------------------

def get_frame_bg(frame_num: int) -> np.ndarray:
    """Return a fresh background with per-frame animated noise."""
    bg = _BG.copy()
    rng = np.random.default_rng(frame_num * 7 + 13)
    noise = rng.integers(0, 6, (HEIGHT, WIDTH, 3), dtype=np.uint8)
    bg = np.clip(bg.astype(np.int16) + noise - 3, 0, 255).astype(np.uint8)
    return bg


# ---------------------------------------------------------------------------
# Helper: alpha-blend a color onto a region
# ---------------------------------------------------------------------------

def alpha_blend(frame: np.ndarray, overlay: np.ndarray, alpha: float) -> np.ndarray:
    return cv2.addWeighted(frame, 1.0 - alpha, overlay, alpha, 0)


# ---------------------------------------------------------------------------
# draw_scanlines
# ---------------------------------------------------------------------------

def draw_scanlines(frame: np.ndarray) -> np.ndarray:
    """Dim every other row by alpha=0.93 (CRT / night-vision feel)."""
    frame[1::2] = (frame[1::2].astype(np.float32) * 0.93).astype(np.uint8)
    return frame


# ---------------------------------------------------------------------------
# apply_vignette
# ---------------------------------------------------------------------------

def apply_vignette(frame: np.ndarray) -> np.ndarray:
    vig3 = np.stack([_VIGNETTE, _VIGNETTE, _VIGNETTE], axis=2)
    return (frame.astype(np.float32) * vig3).clip(0, 255).astype(np.uint8)


# ---------------------------------------------------------------------------
# draw_hud_header
# ---------------------------------------------------------------------------

def draw_hud_header(
    frame: np.ndarray,
    state: str,
    track_info: dict,
    frame_num: int,
) -> None:
    """Draw top-left info block."""
    fps_val = 30.0
    line1 = f"RWS v2.0  |  Frame: {frame_num:04d}  |  {fps_val:.1f} FPS"

    tid = track_info.get("id", "—")
    label = track_info.get("label", "—")
    conf = track_info.get("conf", 0.0)
    dist = track_info.get("dist", 0.0)
    threat = track_info.get("threat", 0.0)

    if tid != "—":
        line2 = f"Track: #{tid} {label}  conf:{conf:.2f}  dist:{dist:.1f}m"
        line3 = f"State: {state}  \u25cf  Threat: HIGH {threat:.2f}"
    else:
        line2 = "Track: --"
        line3 = f"State: {state}"

    # Semi-transparent background panel
    panel = frame.copy()
    cv2.rectangle(panel, (8, 8), (440, 80), (0, 0, 0), -1)
    cv2.addWeighted(panel, 0.55, frame, 0.45, 0, frame)

    cv2.putText(frame, line1, (14, 28), FONT, FONT_SMALL, HUD_GREEN, THICK_THIN, cv2.LINE_AA)
    cv2.putText(frame, line2, (14, 50), FONT, FONT_SMALL, HUD_GREEN, THICK_THIN, cv2.LINE_AA)
    cv2.putText(frame, line3, (14, 72), FONT, FONT_SMALL, HUD_GREEN, THICK_THIN, cv2.LINE_AA)

    # Top border line
    cv2.line(frame, (0, 86), (WIDTH, 86), (0, 100, 0), 1)


# ---------------------------------------------------------------------------
# draw_reticle
# ---------------------------------------------------------------------------

def draw_reticle(
    frame: np.ndarray,
    cx: int,
    cy: int,
    state: str,
    color: tuple,
    frame_num: int = 0,
) -> None:
    """Draw tactical targeting reticle centered at (cx, cy)."""
    R_OUTER = 60
    R_INNER = 8
    GAP_START = 14
    GAP_END = 55

    if state == "SEARCH":
        # Rotating scan line
        angle = (frame_num * 6) % 360
        rad = math.radians(angle)
        ex = int(cx + R_OUTER * math.cos(rad))
        ey = int(cy + R_OUTER * math.sin(rad))
        cv2.circle(frame, (cx, cy), R_OUTER, HUD_RED, 1, cv2.LINE_AA)
        cv2.line(frame, (cx, cy), (ex, ey), HUD_RED, 1, cv2.LINE_AA)
        return

    # Outer ring
    cv2.circle(frame, (cx, cy), R_OUTER, color, 1, cv2.LINE_AA)
    # Inner ring
    cv2.circle(frame, (cx, cy), R_INNER, color, 1, cv2.LINE_AA)

    # Gap crosshair lines — N/S/E/W
    dirs = [(0, -1), (0, 1), (-1, 0), (1, 0)]
    for dx, dy in dirs:
        x1 = cx + dx * GAP_START
        y1 = cy + dy * GAP_START
        x2 = cx + dx * GAP_END
        y2 = cy + dy * GAP_END
        cv2.line(frame, (x1, y1), (x2, y2), color, 1, cv2.LINE_AA)

    # Corner L-brackets at ±45° outside the outer circle
    blen = 18  # bracket arm length
    boff = R_OUTER + 8
    corners = [(-1, -1), (1, -1), (1, 1), (-1, 1)]
    for sx, sy in corners:
        bx = cx + sx * boff
        by = cy + sy * boff
        # horizontal arm
        cv2.line(frame, (bx, by), (bx + sx * blen, by), color, 1, cv2.LINE_AA)
        # vertical arm
        cv2.line(frame, (bx, by), (bx, by + sy * blen), color, 1, cv2.LINE_AA)

    # LOCK: add a pulsing dot at center
    if state == "LOCK":
        pulse = int(4 + 2 * math.sin(frame_num * 0.3))
        cv2.circle(frame, (cx, cy), pulse, color, -1, cv2.LINE_AA)


# ---------------------------------------------------------------------------
# draw_bounding_box
# ---------------------------------------------------------------------------

def draw_bounding_box(
    frame: np.ndarray,
    x: int,
    y: int,
    w: int,
    h: int,
    label: str,
    conf: float,
    state: str,
    track_id: int = 1,
    vx: float = 0.0,
    vy: float = 0.0,
    alloc_label: str = "",
) -> None:
    """Draw bounding box + label + velocity arrow."""
    if state == "SEARCH":
        return

    if state == "LOCK":
        color = HUD_GREEN
    elif state == "TRACK":
        color = HUD_YELLOW
    else:
        color = HUD_GRAY

    cv2.rectangle(frame, (x, y), (x + w, y + h), color, 2)

    # Label above box
    lbl_text = f"#{track_id} {label}  {conf:.2f}"
    lbl_y = max(y - 6, 16)
    cv2.putText(frame, lbl_text, (x, lbl_y), FONT, FONT_SMALL, color, THICK_THIN, cv2.LINE_AA)

    # Allocation label (G0 / G1) below box
    if alloc_label:
        cv2.putText(
            frame, alloc_label, (x + w // 2 - 10, y + h + 16),
            FONT, FONT_SMALL, HUD_CYAN, THICK_THIN, cv2.LINE_AA,
        )

    # Velocity arrow from center
    cx = x + w // 2
    cy = y + h // 2
    arrow_scale = 12.0
    ex = int(cx + vx * arrow_scale)
    ey = int(cy + vy * arrow_scale)
    if abs(ex - cx) + abs(ey - cy) > 2:
        cv2.arrowedLine(frame, (cx, cy), (ex, ey), color, 1, cv2.LINE_AA, tipLength=0.35)


# ---------------------------------------------------------------------------
# draw_gimbal_crosshair
# ---------------------------------------------------------------------------

def draw_gimbal_crosshair(frame: np.ndarray, aim_x: int, aim_y: int) -> None:
    """Full-screen thin crosshair in cyan at gimbal aim point (alpha-blended)."""
    overlay = frame.copy()
    cv2.line(overlay, (aim_x, 0), (aim_x, HEIGHT), HUD_CYAN, 1)
    cv2.line(overlay, (0, aim_y), (WIDTH, aim_y), HUD_CYAN, 1)
    # Small center mark
    cv2.circle(overlay, (aim_x, aim_y), 4, HUD_CYAN, 1, cv2.LINE_AA)
    cv2.addWeighted(overlay, 0.6, frame, 0.4, 0, frame)


# ---------------------------------------------------------------------------
# draw_fire_chain
# ---------------------------------------------------------------------------

def draw_fire_chain(frame: np.ndarray, chain_state: str, frame_num: int = 0) -> None:
    """Right-side fire chain status panel (120px wide strip)."""
    px = WIDTH - 130
    py = 100
    pw, ph = 120, 160

    # Background rect
    overlay = frame.copy()
    cv2.rectangle(overlay, (px, py), (px + pw, py + ph), (0, 0, 0), -1)
    cv2.addWeighted(overlay, 0.65, frame, 0.35, 0, frame)

    # Border
    cv2.rectangle(frame, (px, py), (px + pw, py + ph), HUD_GREEN, 1)

    # Title
    cv2.putText(frame, "FIRE CHAIN", (px + 8, py + 18),
                FONT, 0.38, HUD_GREEN, 1, cv2.LINE_AA)
    cv2.line(frame, (px, py + 24), (px + pw, py + 24), HUD_GREEN, 1)

    states_order = ["SAFE", "ARMED", "FIRE AUTH", "FIRED"]
    state_map = {
        "SAFE": "SAFE",
        "ARMED": "ARMED",
        "FIRE_AUTH": "FIRE AUTH",
        "FIRED": "FIRED",
    }
    active_display = state_map.get(chain_state, "SAFE")

    for i, s in enumerate(states_order):
        ty = py + 44 + i * 28
        is_active = s == active_display

        # Flashing for ARMED
        if is_active and s == "ARMED":
            flash = (frame_num // 8) % 2 == 0
            dot_color = HUD_ORANGE if flash else HUD_GRAY
            txt_color = HUD_ORANGE if flash else HUD_GRAY
        elif is_active and s == "FIRE AUTH":
            flash = (frame_num // 4) % 2 == 0
            dot_color = HUD_RED if flash else HUD_GRAY
            txt_color = HUD_RED if flash else HUD_GRAY
        elif is_active and s == "FIRED":
            dot_color = HUD_WHITE
            txt_color = HUD_WHITE
        elif is_active:
            dot_color = HUD_GREEN
            txt_color = HUD_GREEN
        else:
            dot_color = HUD_GRAY
            txt_color = (60, 60, 60)

        # Circle indicator
        if is_active:
            cv2.circle(frame, (px + 14, ty), 5, dot_color, -1, cv2.LINE_AA)
        else:
            cv2.circle(frame, (px + 14, ty), 5, dot_color, 1, cv2.LINE_AA)

        cv2.putText(frame, s, (px + 24, ty + 4),
                    FONT, 0.38, txt_color, 1, cv2.LINE_AA)


# ---------------------------------------------------------------------------
# draw_status_bar
# ---------------------------------------------------------------------------

def draw_status_bar(
    frame: np.ndarray,
    state: str,
    track_id: int,
    yaw_err: float,
    pitch_err: float,
    chain_state: str,
    frame_num: int = 0,
) -> None:
    """Bottom status bar: state pill + PID error bars."""
    bar_y = HEIGHT - 36
    bar_h = 36

    # Background
    overlay = frame.copy()
    cv2.rectangle(overlay, (0, bar_y), (WIDTH, HEIGHT), (0, 0, 0), -1)
    cv2.addWeighted(overlay, 0.7, frame, 0.3, 0, frame)
    cv2.line(frame, (0, bar_y), (WIDTH, bar_y), HUD_GREEN, 1)

    # State pill
    if chain_state == "FIRE_AUTH":
        flash = (frame_num // 5) % 2 == 0
        pill_color = HUD_RED if flash else (80, 0, 0)
        pill_text = "[ FIRE AUTHORIZED ]"
        txt_color = HUD_WHITE if flash else HUD_RED
    elif chain_state == "FIRED":
        pill_color = (240, 240, 240)
        pill_text = "[ FIRE EXECUTED ]"
        txt_color = (0, 0, 0)
    elif chain_state == "ARMED":
        flash = (frame_num // 8) % 2 == 0
        pill_color = HUD_ORANGE if flash else (60, 40, 0)
        pill_text = "[ \u26a0 ARMED ]"
        txt_color = HUD_WHITE if flash else HUD_ORANGE
    elif state == "LOCK":
        pill_color = (0, 100, 0)
        pill_text = f"[ LOCKED #{track_id} ]"
        txt_color = HUD_GREEN
    elif state == "TRACK":
        pill_color = (60, 60, 0)
        pill_text = f"[ TRACKING #{track_id} ]"
        txt_color = HUD_YELLOW
    else:  # SEARCH
        pill_color = (40, 40, 40)
        pill_text = "[ SEARCH ]"
        txt_color = HUD_GRAY

    pill_x, pill_y = 10, bar_y + 5
    (tw, th), _ = cv2.getTextSize(pill_text, FONT, FONT_SMALL, THICK_THIN)
    cv2.rectangle(frame, (pill_x, pill_y), (pill_x + tw + 14, pill_y + th + 8), pill_color, -1)
    cv2.putText(frame, pill_text, (pill_x + 7, pill_y + th + 4),
                FONT, FONT_SMALL, txt_color, THICK_THIN, cv2.LINE_AA)

    # PID error bars — right side
    bar_area_x = WIDTH - 280
    _draw_error_bar(frame, bar_area_x, bar_y + 8, 120, 12, yaw_err, "Yaw")
    _draw_error_bar(frame, bar_area_x, bar_y + 22, 120, 12, pitch_err, "Pitch")


def _draw_error_bar(
    frame: np.ndarray,
    x: int, y: int, w: int, h: int,
    error_deg: float,
    label: str,
) -> None:
    max_err = 5.0
    ratio = min(abs(error_deg) / max_err, 1.0)
    fill_w = int(w * ratio)

    if abs(error_deg) < 1.0:
        bar_color = HUD_GREEN
    elif abs(error_deg) < 3.0:
        bar_color = HUD_ORANGE
    else:
        bar_color = HUD_RED

    cv2.rectangle(frame, (x, y), (x + w, y + h), (50, 50, 50), -1)
    if fill_w > 0:
        cv2.rectangle(frame, (x, y), (x + fill_w, y + h), bar_color, -1)
    cv2.rectangle(frame, (x, y), (x + w, y + h), HUD_GRAY, 1)
    cv2.putText(frame, f"{label} {error_deg:.2f}\u00b0",
                (x - 120, y + h - 1), FONT, 0.36, HUD_GREEN, 1, cv2.LINE_AA)


# ---------------------------------------------------------------------------
# draw_fire_flash
# ---------------------------------------------------------------------------

def draw_fire_flash(
    frame: np.ndarray,
    intensity: float,
    cx: int,
    cy: int,
    frame_offset: int,
) -> None:
    """White/orange flash + expanding rings for fire event."""
    if intensity <= 0:
        return

    # Full-frame flash
    if frame_offset == 0:
        flash_color = HUD_WHITE
        alpha = 0.7 * intensity
    elif frame_offset == 1:
        flash_color = (100, 200, 255)  # orange-white in BGR
        alpha = 0.5 * intensity
    else:
        flash_color = HUD_WHITE
        alpha = 0.25 * intensity

    overlay = np.full_like(frame, flash_color, dtype=np.uint8)
    cv2.addWeighted(overlay, alpha, frame, 1.0 - alpha, 0, frame)

    # Expanding rings
    for ring in range(3):
        r = int((frame_offset * 40 + ring * 30) * intensity)
        if r > 0:
            alpha_ring = max(0.0, 1.0 - frame_offset * 0.18 - ring * 0.25)
            ring_overlay = frame.copy()
            cv2.circle(ring_overlay, (cx, cy), r, HUD_ORANGE, 2, cv2.LINE_AA)
            cv2.addWeighted(ring_overlay, alpha_ring, frame, 1.0 - alpha_ring, 0, frame)


# ---------------------------------------------------------------------------
# draw_mission_summary
# ---------------------------------------------------------------------------

def draw_mission_summary(frame: np.ndarray, stats: dict) -> None:
    """Semi-transparent mission debrief overlay."""
    ow = int(WIDTH * 0.60)
    oh = int(HEIGHT * 0.55)
    ox = (WIDTH - ow) // 2
    oy = (HEIGHT - oh) // 2

    overlay = frame.copy()
    cv2.rectangle(overlay, (ox, oy), (ox + ow, oy + oh), (0, 0, 0), -1)
    cv2.addWeighted(overlay, 0.78, frame, 0.22, 0, frame)
    cv2.rectangle(frame, (ox, oy), (ox + ow, oy + oh), HUD_GREEN, 2)

    sep = "\u2550" * 36
    lines = [
        sep,
        "     MISSION DEBRIEF",
        sep,
        f"  Duration          {stats.get('duration', 0):.1f}s",
        f"  Targets tracked   {stats.get('targets', 0)}",
        f"  Shots fired       {stats.get('shots', 0)}",
        f"  Lock rate         {stats.get('lock_rate', 0):.0f}%",
        f"  Avg yaw error     {stats.get('avg_yaw', 0):.2f}\u00b0",
        f"  Max threat score  {stats.get('max_threat', 0):.2f}",
        sep,
    ]
    for i, line in enumerate(lines):
        ty = oy + 38 + i * 28
        color = HUD_GREEN if i not in (0, 2, 9) else (0, 160, 0)
        cv2.putText(frame, line, (ox + 20, ty),
                    FONT, FONT_SMALL, color, THICK_THIN, cv2.LINE_AA)


# ---------------------------------------------------------------------------
# Multi-target header
# ---------------------------------------------------------------------------

def draw_multi_gimbal_header(frame: np.ndarray) -> None:
    txt = "MULTI-GIMBAL MODE  \u2014  2 UNITS ACTIVE"
    (tw, _), _ = cv2.getTextSize(txt, FONT, FONT_MED, THICK_THIN)
    tx = (WIDTH - tw) // 2
    cv2.putText(frame, txt, (tx, 115), FONT, FONT_MED, HUD_CYAN, THICK_THIN, cv2.LINE_AA)


# ---------------------------------------------------------------------------
# Fire-executed text
# ---------------------------------------------------------------------------

def draw_fire_executed_text(frame: np.ndarray, alpha: float) -> None:
    txt = "FIRE EXECUTED"
    (tw, th), _ = cv2.getTextSize(txt, FONT, 2.0, 3)
    tx = (WIDTH - tw) // 2
    ty = HEIGHT // 2 + th // 2
    overlay = frame.copy()
    cv2.putText(overlay, txt, (tx, ty), FONT, 2.0, HUD_RED, 3, cv2.LINE_AA)
    cv2.addWeighted(overlay, alpha, frame, 1.0 - alpha, 0, frame)


# ---------------------------------------------------------------------------
# SEARCH scan-line full-frame
# ---------------------------------------------------------------------------

def draw_search_sweep(frame: np.ndarray, frame_num: int) -> None:
    """Rotating full-screen search sweep line."""
    cx, cy = WIDTH // 2, HEIGHT // 2
    angle = (frame_num * 4) % 360
    rad = math.radians(angle)
    length = max(WIDTH, HEIGHT)
    ex = int(cx + length * math.cos(rad))
    ey = int(cy + length * math.sin(rad))

    overlay = frame.copy()
    cv2.line(overlay, (cx, cy), (ex, ey), (0, 80, 0), 1)
    cv2.addWeighted(overlay, 0.4, frame, 0.6, 0, frame)

    # Radar circle at center
    cv2.circle(frame, (cx, cy), 5, HUD_GREEN, -1, cv2.LINE_AA)
    for r in [100, 200, 300]:
        cv2.circle(frame, (cx, cy), r, (0, 60, 0), 1, cv2.LINE_AA)


# ---------------------------------------------------------------------------
# Target simulation helpers
# ---------------------------------------------------------------------------

def target_a_pos(f: int) -> Optional[Tuple[int, int, int, int, float, float]]:
    """
    Returns (x, y, w, h, vx, vy) for Target A at frame f, or None if not visible.
    Enters at f=60 (x=180, y=310, 80x120), moves right 1.5px/frame,
    sinusoidal vertical wobble ±8px period 40 frames.
    Disappears at f=240.
    Re-enters at f=215 from left (new spawn from x=50).
    """
    if 60 <= f < 240:
        elapsed = f - 60
        x = int(180 + elapsed * 1.5)
        y = int(310 + 8 * math.sin(2 * math.pi * elapsed / 40))
        w, h = 80, 120
        vx = 1.5
        vy = 8 * (2 * math.pi / 40) * math.cos(2 * math.pi * elapsed / 40)
        return x, y, w, h, vx, vy
    if 215 <= f < 900:
        elapsed2 = f - 215
        x = int(50 + elapsed2 * 1.2)
        y = int(330 + 6 * math.sin(2 * math.pi * elapsed2 / 35))
        w, h = 80, 120
        vx = 1.2
        vy = 6 * (2 * math.pi / 35) * math.cos(2 * math.pi * elapsed2 / 35)
        return x, y, w, h, vx, vy
    return None


def target_b_pos(f: int) -> Optional[Tuple[int, int, int, int, float, float]]:
    """Returns (x, y, w, h, vx, vy) for Target B, or None."""
    if 190 <= f < 300:
        elapsed = f - 190
        x = int(900 - elapsed * 2.0)
        y = int(380 + 4 * math.sin(2 * math.pi * elapsed / 50))
        w, h = 140, 80
        vx = -2.0
        vy = 4 * (2 * math.pi / 50) * math.cos(2 * math.pi * elapsed / 50)
        return x, y, w, h, vx, vy
    return None


# ---------------------------------------------------------------------------
# State machine simulation
# ---------------------------------------------------------------------------

def get_track_state(f: int) -> str:
    """Simulate track state machine per frame."""
    if f < 60:
        return "SEARCH"
    if 60 <= f < 90:
        return "TRACK"
    if 90 <= f < 151:
        return "LOCK"
    if 151 <= f < 181:
        return "ARMED"
    if 181 <= f < 183:
        return "FIRE_AUTH"
    if 183 <= f < 215:
        return "SEARCH"
    if 215 <= f < 900:
        return "LOCK"
    return "SEARCH"


def get_chain_state(f: int) -> str:
    if f < 151:
        return "SAFE"
    if 151 <= f < 181:
        return "ARMED"
    if 181 <= f < 183:
        return "FIRE_AUTH"
    if 183 <= f < 215:
        return "FIRED"
    return "SAFE"


def get_yaw_error(f: int) -> float:
    """Simulate converging yaw error."""
    if f < 60:
        return 0.0
    if 60 <= f < 90:
        t = (f - 60) / 30.0
        return 3.2 * (1 - t) + 1.0 * t
    if 90 <= f < 151:
        t = (f - 90) / 61.0
        return 1.0 * math.exp(-t * 3.0) + 0.08
    if 151 <= f < 183:
        return 0.08 + 0.05 * math.sin(f * 0.3)
    if 183 <= f < 215:
        return 0.0
    if 215 <= f < 900:
        t = min((f - 215) / 40.0, 1.0)
        return 2.0 * math.exp(-t * 2.5) + 0.1
    return 0.0


def get_pitch_error(f: int) -> float:
    return get_yaw_error(f) * 0.6 + 0.05 * math.sin(f * 0.17)


def get_threat_score(f: int) -> float:
    if f < 60:
        return 0.0
    if 60 <= f < 90:
        return 0.3 + 0.2 * (f - 60) / 30.0
    if 90 <= f < 151:
        return 0.5 + 0.22 * (f - 90) / 61.0
    if 151 <= f < 183:
        return 0.72
    if 183 <= f < 215:
        return 0.0
    if 215 <= f < 900:
        return 0.60 + 0.08 * math.sin(f * 0.05)
    return 0.0


def get_dist(f: int) -> float:
    if f < 60:
        return 0.0
    base = 18.3 - (f - 60) * 0.02
    noise = 0.3 * math.sin(f * 0.13)
    return max(5.0, base + noise)


# ---------------------------------------------------------------------------
# Gimbal aim point (exponential convergence to target)
# ---------------------------------------------------------------------------

class GimbalAim:
    def __init__(self, x: int, y: int):
        self.x = float(x)
        self.y = float(y)

    def update(self, target_x: float, target_y: float, tau: float = 0.12) -> Tuple[int, int]:
        self.x += tau * (target_x - self.x)
        self.y += tau * (target_y - self.y)
        return int(self.x), int(self.y)


# ---------------------------------------------------------------------------
# Main render loop
# ---------------------------------------------------------------------------

def render_video(output_path: str) -> None:
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(output_path, fourcc, FPS, (WIDTH, HEIGHT))
    if not writer.isOpened():
        raise RuntimeError(f"Could not open VideoWriter for {output_path}")

    print(f"Rendering {TOTAL_FRAMES} frames to {output_path} ...")

    # Gimbal aim trackers — one per "gimbal"
    aim_g0 = GimbalAim(WIDTH // 2, HEIGHT // 2)
    aim_g1 = GimbalAim(WIDTH // 2, HEIGHT // 2)

    stats = {
        "duration": TOTAL_FRAMES / FPS,
        "targets": 2,
        "shots": 1,
        "lock_rate": 78,
        "avg_yaw": 0.42,
        "max_threat": 0.72,
    }

    start_time = time.time()

    for f in range(TOTAL_FRAMES):
        frame = get_frame_bg(f)

        state = get_track_state(f)
        chain_state = get_chain_state(f)
        yaw_err = get_yaw_error(f)
        pitch_err = get_pitch_error(f)
        threat = get_threat_score(f)
        dist = get_dist(f)

        pos_a = target_a_pos(f)
        pos_b = target_b_pos(f)

        # ---- Scanlines first (applied to bg layer)
        draw_scanlines(frame)

        # ---- SEARCH sweep
        if state == "SEARCH" and pos_a is None:
            draw_search_sweep(frame, f)

        # ---- Target A
        track_info: dict = {}
        if pos_a is not None:
            ax, ay, aw, ah, avx, avy = pos_a
            acx = ax + aw // 2
            acy = ay + ah // 2

            # Track ID depends on entry
            tid_a = 1 if f < 240 else 2
            conf_a = 0.87 - 0.01 * math.sin(f * 0.07)

            draw_bounding_box(frame, ax, ay, aw, ah,
                              "Person", conf_a, state, tid_a, avx, avy,
                              alloc_label="G0" if pos_b is not None else "")

            # Reticle color
            if pos_b is not None:
                reticle_color_a = HUD_CYAN
            elif state == "LOCK":
                reticle_color_a = HUD_GREEN
            elif state == "TRACK":
                reticle_color_a = HUD_YELLOW
            else:
                reticle_color_a = HUD_RED
            draw_reticle(frame, acx, acy, state, reticle_color_a, f)

            # Gimbal 0 converges to target A
            gx0, gy0 = aim_g0.update(acx, acy)
            draw_gimbal_crosshair(frame, gx0, gy0)

            track_info = {
                "id": tid_a,
                "label": "Person",
                "conf": conf_a,
                "dist": dist,
                "threat": threat,
            }
        else:
            # No target — gimbal drifts to center
            gx0, gy0 = aim_g0.update(WIDTH // 2, HEIGHT // 2, tau=0.04)
            if state != "SEARCH":
                draw_gimbal_crosshair(frame, gx0, gy0)

        # ---- Target B
        if pos_b is not None:
            bx, by, bw, bh, bvx, bvy = pos_b
            bcx = bx + bw // 2
            bcy = by + bh // 2
            conf_b = 0.74 + 0.02 * math.sin(f * 0.09)

            draw_bounding_box(frame, bx, by, bw, bh,
                              "Vehicle", conf_b, "LOCK", 3, bvx, bvy,
                              alloc_label="G1")

            draw_reticle(frame, bcx, bcy, "LOCK", HUD_MAGENTA, f)

            # Gimbal 1 converges to target B
            gx1, gy1 = aim_g1.update(bcx, bcy)
            # Draw second crosshair in magenta
            overlay = frame.copy()
            cv2.line(overlay, (gx1, 0), (gx1, HEIGHT), HUD_MAGENTA, 1)
            cv2.line(overlay, (0, gy1), (WIDTH, gy1), HUD_MAGENTA, 1)
            cv2.circle(overlay, (gx1, gy1), 4, HUD_MAGENTA, 1, cv2.LINE_AA)
            cv2.addWeighted(overlay, 0.5, frame, 0.5, 0, frame)

            draw_multi_gimbal_header(frame)
        else:
            aim_g1.update(WIDTH // 2, HEIGHT // 2, tau=0.02)

        # ---- Fire flash (frames 183–188)
        if 183 <= f < 189:
            offset = f - 183
            intensity = max(0.0, 1.0 - offset * 0.15)
            fa_cx = WIDTH // 2
            fa_cy = HEIGHT // 2
            if pos_a is not None:
                fa_cx = pos_a[0] + pos_a[2] // 2
                fa_cy = pos_a[1] + pos_a[3] // 2
            draw_fire_flash(frame, intensity, fa_cx, fa_cy, offset)

        # ---- "FIRE EXECUTED" text (frames 183–212)
        if 183 <= f < 213:
            fade = max(0.0, 1.0 - (f - 183) / 30.0)
            draw_fire_executed_text(frame, fade)

        # ---- Mission summary (frames 270–300)
        if 270 <= f < 900:
            draw_mission_summary(frame, stats)

        # ---- HUD elements (drawn on top)
        draw_hud_header(frame, state, track_info, f)
        draw_fire_chain(frame, chain_state, f)
        draw_status_bar(frame, state,
                        track_info.get("id", 1),
                        yaw_err, pitch_err,
                        chain_state, f)

        # ---- Vignette last
        apply_vignette(frame)

        writer.write(frame)

        if f % 30 == 0:
            elapsed = time.time() - start_time
            pct = f / TOTAL_FRAMES * 100
            eta = (elapsed / max(f, 1)) * (TOTAL_FRAMES - f)
            print(f"  Frame {f:4d}/{TOTAL_FRAMES}  ({pct:5.1f}%)  "
                  f"elapsed {elapsed:5.1f}s  ETA {eta:5.1f}s")

    writer.release()

    elapsed_total = time.time() - start_time
    file_size = os.path.getsize(output_path)
    duration_s = TOTAL_FRAMES / FPS

    print()
    print(f"Demo video saved: {output_path} ({TOTAL_FRAMES} frames, {duration_s:.1f}s)")
    print(f"File size: {file_size / 1024 / 1024:.2f} MB  |  Render time: {elapsed_total:.1f}s")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    render_video(OUTPUT_PATH)
