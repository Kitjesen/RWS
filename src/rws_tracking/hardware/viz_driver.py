"""
Matplotlib 3D real-time gimbal visualizer — no extra dependencies.
==================================================================

Wraps SimulatedGimbalDriver and opens a live 3D window showing the
gimbal's physical posture as the pipeline sends commands.

The 3D view shows:
  • Aluminium base plate
  • Pan (yaw) motor housing — rotates around Z
  • Tilt (pitch) arm + camera body — tilts around Y of the yaw frame
  • Lens element
  • Coordinate frame arrows at each joint
  • Live readout: Yaw=X.X°  Pitch=Y.Y°  YawRate=±  PitchRate=±

Usage::

    from rws_tracking.hardware.viz_driver import MatplotlibGimbalDriver

    driver = MatplotlibGimbalDriver()
    pipeline = VisionGimbalPipeline(..., driver=driver)
    # The 3D window updates automatically while the pipeline runs.

    # Or standalone demo (no pipeline):
    if __name__ == "__main__":
        from rws_tracking.hardware.viz_driver import standalone_demo
        standalone_demo()
"""

from __future__ import annotations

import math
import threading
import time

import matplotlib
import matplotlib.pyplot as plt
import numpy as np
from mpl_toolkits.mplot3d.art3d import Poly3DCollection

from ..types import GimbalFeedback
from .driver import DriverLimits, SimulatedGimbalDriver

# Use a non-blocking backend; swap to Qt5Agg / TkAgg if Agg doesn't suit.
matplotlib.use("TkAgg")


# ──────────────────────────────────────────────────────────────────────────────
# 3D geometry helpers
# ──────────────────────────────────────────────────────────────────────────────

def _rot_z(deg: float) -> np.ndarray:
    r = math.radians(deg)
    return np.array([
        [ math.cos(r), -math.sin(r), 0],
        [ math.sin(r),  math.cos(r), 0],
        [           0,            0, 1],
    ], dtype=float)


def _rot_y(deg: float) -> np.ndarray:
    r = math.radians(deg)
    return np.array([
        [ math.cos(r), 0, math.sin(r)],
        [           0, 1,           0],
        [-math.sin(r), 0, math.cos(r)],
    ], dtype=float)


def _box_vertices(size, origin=None):
    """Return 8×3 array of box corners in local frame."""
    dx, dy, dz = size[0]/2, size[1]/2, size[2]/2
    v = np.array([
        [-dx, -dy, -dz], [ dx, -dy, -dz], [ dx,  dy, -dz], [-dx,  dy, -dz],
        [-dx, -dy,  dz], [ dx, -dy,  dz], [ dx,  dy,  dz], [-dx,  dy,  dz],
    ], dtype=float)
    if origin is not None:
        v += np.asarray(origin, dtype=float)
    return v


def _draw_box(ax, size, R, T, color, alpha=0.55):
    """Draw a coloured box with rotation R and translation T."""
    v = _box_vertices(size)
    v = (R @ v.T).T + T
    faces = [
        [v[0],v[1],v[2],v[3]],  # bottom
        [v[4],v[5],v[6],v[7]],  # top
        [v[0],v[1],v[5],v[4]],  # front
        [v[2],v[3],v[7],v[6]],  # back
        [v[0],v[3],v[7],v[4]],  # left
        [v[1],v[2],v[6],v[5]],  # right
    ]
    poly = Poly3DCollection(
        faces, alpha=alpha,
        facecolor=color, edgecolor=[0.3, 0.3, 0.3],
        linewidth=0.5,
    )
    ax.add_collection3d(poly)


def _draw_cylinder(ax, radius, height, R, T, color, alpha=0.55, n=24):
    """Draw a filled cylinder."""
    theta = np.linspace(0, 2*math.pi, n)
    x_c = radius * np.cos(theta)
    y_c = radius * np.sin(theta)
    # Top and bottom rings
    for z_off in [0.0, height]:
        pts = np.stack([x_c, y_c, np.full(n, z_off)], axis=1)
        pts = (R @ pts.T).T + T
        ax.plot(pts[:, 0], pts[:, 1], pts[:, 2],
                color=color, linewidth=0.6, alpha=alpha*0.7)
    # Side quads
    faces = []
    for i in range(n - 1):
        p0 = np.array([x_c[i],   y_c[i],   0.0])
        p1 = np.array([x_c[i+1], y_c[i+1], 0.0])
        p2 = np.array([x_c[i+1], y_c[i+1], height])
        p3 = np.array([x_c[i],   y_c[i],   height])
        faces.append([(R @ p + T) for p in [p0, p1, p2, p3]])
    poly = Poly3DCollection(
        faces, alpha=alpha,
        facecolor=color, edgecolor='none',
    )
    ax.add_collection3d(poly)
    # Cap discs
    for z_off in [0.0, height]:
        face = [(R @ np.array([x_c[i], y_c[i], z_off]) + T) for i in range(n)]
        poly2 = Poly3DCollection(
            [face], alpha=alpha, facecolor=color, edgecolor='none',
        )
        ax.add_collection3d(poly2)


def _draw_frame(ax, R, T, length=0.035):
    """Draw XYZ coordinate frame arrows."""
    for axis, color in zip(np.eye(3), ['#FF4444', '#44FF44', '#4488FF']):
        end = T + R @ axis * length
        ax.quiver(T[0], T[1], T[2],
                  end[0]-T[0], end[1]-T[1], end[2]-T[2],
                  color=color, linewidth=1.5, arrow_length_ratio=0.25)


# ──────────────────────────────────────────────────────────────────────────────
# Scene renderer
# ──────────────────────────────────────────────────────────────────────────────

class _GimbalScene:
    """Renders the gimbal model onto a matplotlib Axes3D."""

    # Colours
    C_BASE    = '#8a9bb5'   # aluminium
    C_YAW_MTR = '#2266cc'   # pan motor blue
    C_PITCH   = '#cc3322'   # tilt arm red
    C_CAMERA  = '#1a1a1a'   # camera body black
    C_LENS    = '#1155bb'   # lens glass blue

    def render(self, ax, yaw_deg: float, pitch_deg: float) -> None:
        ax.cla()

        # ── World / base frame ──────────────────────────────────────────
        identity = np.eye(3)

        # Base plate (150×150×50 mm)
        _draw_box(ax, (0.150, 0.150, 0.050), identity, np.array([0, 0, -0.025]),
                  self.C_BASE, alpha=0.50)

        # ── Yaw stage ───────────────────────────────────────────────────
        Ry = _rot_z(yaw_deg)          # rotation at yaw joint (origin = [0,0,0])
        Ty = np.zeros(3)

        # Pan motor cylinder (Ø80 × 60 mm)
        _draw_cylinder(ax, 0.040, 0.060, Ry, Ty + Ry @ [0, 0, 0],
                       self.C_YAW_MTR)

        # Mounting ears
        for sign in [+1, -1]:
            ear_local = np.array([0, sign*0.048, 0.055])
            _draw_box(ax, (0.020, 0.016, 0.020),
                      Ry, Ty + Ry @ ear_local,
                      self.C_BASE, alpha=0.60)

        # Yaw joint frame indicator
        _draw_frame(ax, Ry, Ty, length=0.030)

        # ── Pitch stage ─────────────────────────────────────────────────
        # Pitch joint origin in yaw frame: [0, 0, 0.075]
        T_pitch_joint = Ty + Ry @ np.array([0, 0, 0.075])
        # Combined rotation: first yaw, then pitch around transformed Y
        Rp_local = _rot_y(pitch_deg)
        Rp = Ry @ Rp_local            # world rotation of pitch link

        # Camera carrier body (100×60×65 mm, offset +40 mm along X_pitch)
        cam_body_local = np.array([0.040, 0, 0])
        _draw_box(ax, (0.100, 0.060, 0.065),
                  Rp, T_pitch_joint + Rp @ cam_body_local,
                  self.C_PITCH, alpha=0.60)

        # Tilt motor (cylinder on +Y side)
        motor_local = np.array([0, 0.050, 0])
        _draw_cylinder(ax, 0.022, 0.025,
                       Rp @ _rot_z(90) @ _rot_y(90),
                       T_pitch_joint + Rp @ motor_local,
                       self.C_BASE, alpha=0.55)

        # Pitch joint frame
        _draw_frame(ax, Rp, T_pitch_joint, length=0.028)

        # ── Camera head ─────────────────────────────────────────────────
        # Lens barrel (cylinder, axis = local X)
        lens_origin = T_pitch_joint + Rp @ np.array([0.095, 0, 0])
        Rlens = Rp @ _rot_y(90)   # cylinder axis along pitch X
        _draw_cylinder(ax, 0.025, 0.032, Rlens, lens_origin,
                       self.C_CAMERA, alpha=0.75)

        # Lens glass cap
        _draw_cylinder(ax, 0.020, 0.003,
                       Rlens, lens_origin + Rp @ [0.030, 0, 0],
                       self.C_LENS, alpha=0.85)

        # Camera optical frame (blue = boresight = +X of camera)
        T_cam = T_pitch_joint + Rp @ np.array([0.126, 0, 0])
        _draw_frame(ax, Rp, T_cam, length=0.040)

        # ── Labels & axes ───────────────────────────────────────────────
        ax.set_xlim([-0.20, 0.20])
        ax.set_xlabel('X (forward)', fontsize=8)
        ax.set_ylim([-0.20, 0.20])
        ax.set_ylabel('Y', fontsize=8)
        ax.set_zlim([-0.05, 0.22])
        ax.set_zlabel('Z (up)', fontsize=8)
        ax.set_title(
            f'RWS 2-DOF Gimbal\n'
            f'Yaw={yaw_deg:+7.2f}°    Pitch={pitch_deg:+6.2f}°',
            fontsize=10, fontweight='bold',
        )
        ax.tick_params(labelsize=7)
        ax.view_init(elev=22, azim=135)


# ──────────────────────────────────────────────────────────────────────────────
# MatplotlibGimbalDriver
# ──────────────────────────────────────────────────────────────────────────────

class MatplotlibGimbalDriver:
    """
    Drop-in GimbalDriver that shows a live 3D gimbal window.

    Internally wraps ``SimulatedGimbalDriver`` for the physics, and runs
    a background thread that redraws the matplotlib figure at *viz_fps*.

    Parameters
    ----------
    limits : DriverLimits or None
        Physical limits forwarded to SimulatedGimbalDriver.
    viz_fps : float
        Target redraw rate for the 3D window (default 20 Hz).
    window_title : str
        Title of the matplotlib window.
    """

    def __init__(
        self,
        limits: DriverLimits | None = None,
        viz_fps: float = 20.0,
        window_title: str = "RWS Gimbal — Live Simulation",
    ) -> None:
        self._sim    = SimulatedGimbalDriver(limits or DriverLimits())
        self._scene  = _GimbalScene()
        self._fps    = viz_fps
        self._title  = window_title
        self._lock   = threading.Lock()
        self._yaw    = 0.0
        self._pitch  = 0.0
        self._yaw_rate   = 0.0
        self._pitch_rate = 0.0
        self._running = True

        # Start the viz thread
        self._thread = threading.Thread(
            target=self._viz_loop, name="gimbal-viz", daemon=True,
        )
        self._thread.start()

    # ------------------------------------------------------------------
    # GimbalDriver Protocol
    # ------------------------------------------------------------------

    def set_yaw_pitch_rate(
        self,
        yaw_rate_dps: float,
        pitch_rate_dps: float,
        timestamp: float,
    ) -> None:
        self._sim.set_yaw_pitch_rate(yaw_rate_dps, pitch_rate_dps, timestamp)

    def get_feedback(self, timestamp: float) -> GimbalFeedback:
        fb = self._sim.get_feedback(timestamp)
        with self._lock:
            self._yaw        = fb.yaw_deg
            self._pitch      = fb.pitch_deg
            self._yaw_rate   = fb.yaw_rate_dps
            self._pitch_rate = fb.pitch_rate_dps
        return fb

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Stop the visualization thread and close the figure."""
        self._running = False
        try:
            plt.close(self._fig)
        except Exception:
            pass

    def __del__(self) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Background viz thread
    # ------------------------------------------------------------------

    def _viz_loop(self) -> None:
        """Runs in a daemon thread; redraws the 3D figure at self._fps."""
        plt.ion()
        self._fig = plt.figure(figsize=(7, 6))
        self._fig.canvas.manager.set_window_title(self._title)
        ax = self._fig.add_subplot(111, projection='3d')
        self._fig.tight_layout()

        interval = 1.0 / self._fps
        while self._running:
            t0 = time.monotonic()
            with self._lock:
                yaw, pitch = self._yaw, self._pitch

            self._scene.render(ax, yaw, pitch)

            try:
                self._fig.canvas.draw()
                self._fig.canvas.flush_events()
            except Exception:
                break  # window was closed

            elapsed = time.monotonic() - t0
            sleep   = max(0.0, interval - elapsed)
            time.sleep(sleep)


# ──────────────────────────────────────────────────────────────────────────────
# Standalone interactive demo
# ──────────────────────────────────────────────────────────────────────────────

def standalone_demo() -> None:
    """
    Open the 3D gimbal viewer and animate a programmed trajectory:

    Phase 1 (0–4 s)   : full pan sweep ±120°
    Phase 2 (4–8 s)   : pitch sweep −40° … +60°
    Phase 3 (8–14 s)  : combined sinusoidal motion (pan+tilt)
    Phase 4 (14–18 s) : return-to-zero
    """
    import time as _time

    driver = MatplotlibGimbalDriver(viz_fps=30.0)

    print("RWS Gimbal — standalone demo (close window to exit)")
    print("  Phase 1 : yaw sweep ±120°")
    print("  Phase 2 : pitch sweep −40° … +60°")
    print("  Phase 3 : sinusoidal multi-axis")
    print("  Phase 4 : return to zero\n")

    dt      = 1.0 / 120.0       # 120 Hz control loop
    t_start = _time.monotonic()

    try:
        while driver._running:
            t = _time.monotonic() - t_start
            ts = _time.monotonic()

            fb = driver.get_feedback(ts)

            if t < 4.0:
                # Phase 1: yaw sweep
                target_yaw   = 120.0 * math.sin(2*math.pi * t / 4.0)
                target_pitch = 0.0
            elif t < 8.0:
                # Phase 2: pitch sweep
                target_yaw   = 0.0
                target_pitch = 50.0 * math.sin(2*math.pi * (t-4) / 4.0) + 10.0
            elif t < 14.0:
                # Phase 3: combined
                target_yaw   = 90.0 * math.sin(2*math.pi * (t-8) / 3.0)
                target_pitch = 30.0 * math.sin(2*math.pi * (t-8) / 2.0) + 15.0
            elif t < 18.0:
                # Phase 4: return to zero
                target_yaw   = 0.0
                target_pitch = 0.0
            else:
                break

            # Simple proportional controller (kp = 8 dps/deg)
            kp = 8.0
            yaw_rate   = kp * (target_yaw   - fb.yaw_deg)
            pitch_rate = kp * (target_pitch - fb.pitch_deg)

            driver.set_yaw_pitch_rate(yaw_rate, pitch_rate, ts)

            _time.sleep(dt)

    except KeyboardInterrupt:
        pass
    finally:
        print(f"\nFinal position: yaw={fb.yaw_deg:.1f}°  pitch={fb.pitch_deg:.1f}°")
        driver.close()
        print("Done.")


if __name__ == "__main__":
    standalone_demo()
