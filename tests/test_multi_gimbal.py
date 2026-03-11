"""Demo script for multi-gimbal coordinated tracking."""

import math

from src.rws_tracking.algebra import CameraModel, PixelToGimbalTransform
from src.rws_tracking.config import GimbalControllerConfig, PIDConfig, SelectorConfig
from src.rws_tracking.control import TwoAxisGimbalController
from src.rws_tracking.hardware import SimulatedGimbalDriver
from src.rws_tracking.perception import PassthroughDetector, SimpleIoUTracker
from src.rws_tracking.perception.multi_target import TargetAllocator
from src.rws_tracking.perception.multi_target_selector import WeightedMultiTargetSelector
from src.rws_tracking.pipeline.multi_gimbal_pipeline import GimbalUnit, MultiGimbalPipeline
from src.rws_tracking.telemetry import InMemoryTelemetryLogger


class MultiTargetSimulation:
    """Simulation with multiple targets in world coordinates."""

    def __init__(self, cam: CameraModel, num_targets: int = 3):
        self.cam = cam
        self.targets = []

        # Create multiple targets at different positions
        for i in range(num_targets):
            angle = i * (360 / num_targets)  # Spread around
            self.targets.append({
                'world_yaw': math.cos(math.radians(angle)) * 10.0,  # 10° radius
                'world_pitch': math.sin(math.radians(angle)) * 5.0,  # 5° radius
                'vel_yaw': 1.0 + i * 0.5,  # Different speeds
                'vel_pitch': 0.5 + i * 0.3,
                'class_id': 'person',
                'confidence': 0.9 + i * 0.03,
            })

    def step(self, dt: float, gimbal_positions: list) -> list:
        """Update simulation and return detections.

        Parameters
        ----------
        dt : float
            Time step
        gimbal_positions : list
            List of (yaw, pitch) for each gimbal (not used in this simple sim)

        Returns
        -------
        list
            List of detection dicts
        """
        detections = []

        for i, target in enumerate(self.targets):
            # Update world position
            target['world_yaw'] += target['vel_yaw'] * dt
            target['world_pitch'] += target['vel_pitch'] * dt

            # Limit range
            target['world_yaw'] = max(-25, min(25, target['world_yaw']))
            target['world_pitch'] = max(-15, min(15, target['world_pitch']))

            # Bounce at boundaries
            if abs(target['world_yaw']) >= 24:
                target['vel_yaw'] *= -1
            if abs(target['world_pitch']) >= 14:
                target['vel_pitch'] *= -1

            # Convert to pixel coordinates (assume gimbal at origin for simplicity)
            # In real multi-gimbal, each gimbal would see different pixel positions
            pixel_x = self.cam.cx + math.tan(math.radians(target['world_yaw'])) * self.cam.fx
            pixel_y = self.cam.cy - math.tan(math.radians(target['world_pitch'])) * self.cam.fy

            # Check if in frame
            if 0 <= pixel_x < self.cam.width and 0 <= pixel_y < self.cam.height:
                bbox_w, bbox_h = 60 + i * 20, 90 + i * 30  # Different sizes
                detections.append({
                    "bbox": (pixel_x - bbox_w/2, pixel_y - bbox_h/2, bbox_w, bbox_h),
                    "confidence": target['confidence'],
                    "class_id": target['class_id'],
                })

        return detections


def main():
    print("="*70)
    print("Multi-Gimbal Coordinated Tracking Demo")
    print("="*70)

    # Camera model
    cam = CameraModel(
        width=1280, height=720,
        fx=970.0, fy=965.0,
        cx=640.0, cy=360.0,
    )

    # Create 3 gimbal units
    num_gimbals = 3
    gimbal_units = []

    for i in range(num_gimbals):
        transform = PixelToGimbalTransform(cam)

        controller_cfg = GimbalControllerConfig(
            yaw_pid=PIDConfig(
                kp=8.0, ki=0.3, kd=0.2,
                integral_limit=20.0, output_limit=180.0,
                derivative_lpf_alpha=0.4,
                feedforward_kv=0.5,
            ),
            pitch_pid=PIDConfig(
                kp=8.0, ki=0.3, kd=0.2,
                integral_limit=20.0, output_limit=180.0,
                derivative_lpf_alpha=0.4,
                feedforward_kv=0.5,
            ),
            command_lpf_alpha=0.6,
            lock_error_threshold_deg=1.5,
            lock_hold_time_s=0.3,
            latency_compensation_s=0.033,
        )

        unit = GimbalUnit(
            unit_id=i,
            controller=TwoAxisGimbalController(transform=transform, cfg=controller_cfg),
            driver=SimulatedGimbalDriver(),
            telemetry=InMemoryTelemetryLogger(),
        )
        gimbal_units.append(unit)

    # Create pipeline
    pipeline = MultiGimbalPipeline(
        detector=PassthroughDetector(),
        tracker=SimpleIoUTracker(iou_threshold=0.2, max_misses=10),
        selector=WeightedMultiTargetSelector(
            frame_width=cam.width,
            frame_height=cam.height,
            config=SelectorConfig(
                preferred_classes={"person": 1.0},
                min_hold_time_s=0.2,
                delta_threshold=0.1,
            ),
        ),
        allocator=TargetAllocator(num_executors=num_gimbals),
        gimbal_units=gimbal_units,
    )

    # Create simulation with 3 targets
    sim = MultiTargetSimulation(cam, num_targets=3)

    print("\nSetup:")
    print(f"  Gimbals: {num_gimbals}")
    print("  Targets: 3")
    print("  Duration: 10s")
    print()

    ts = 0.0
    dt = 0.033  # 30 Hz
    duration = 10.0

    print(f"{'Time':<6} {'Gimbal 0':<25} {'Gimbal 1':<25} {'Gimbal 2':<25}")
    print("-"*85)

    step_count = 0
    while ts < duration:
        # Get gimbal positions (for simulation)
        gimbal_positions = [
            (unit.driver._yaw, unit.driver._pitch)
            for unit in gimbal_units
        ]

        # Generate detections
        detections = sim.step(dt, gimbal_positions)

        # Run pipeline
        pipeline.step(detections, ts)

        # Print status every 10 frames
        if step_count % 10 == 0:
            status_strs = []
            for unit in gimbal_units:
                events = unit.telemetry.events
                if events:
                    last = events[-1].payload
                    state_map = {0.0: "SEARCH", 1.0: "TRACK", 2.0: "LOCK", 3.0: "LOST"}
                    state = state_map.get(last.get("state", -1), "?")
                    target_id = int(last.get("target_id", -1))
                    if target_id >= 0:
                        status = f"{state} T{target_id}"
                    else:
                        status = state
                else:
                    status = "?"
                status_strs.append(f"{status:<25}")

            print(f"{ts:5.2f}  {''.join(status_strs)}")

        ts += dt
        step_count += 1

    # Final statistics
    print("\n" + "="*70)
    print("Final Statistics")
    print("="*70)

    for unit in gimbal_units:
        metrics = unit.telemetry.snapshot_metrics()
        print(f"\nGimbal {unit.unit_id}:")
        print(f"  Lock Rate:  {metrics['lock_rate']*100:6.2f}%")
        print(f"  Avg Error:  {metrics['avg_abs_error_deg']:6.2f} deg")
        print(f"  Switches:   {metrics['switches_per_min']:6.2f} /min")

    print("\n" + "="*70)
    print("Multi-gimbal coordination successful!")
    print("="*70)


if __name__ == "__main__":
    main()
