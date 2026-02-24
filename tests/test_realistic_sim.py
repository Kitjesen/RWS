"""真实仿真测试 - 考虑云台转动对目标位置的影响"""
import math

from src.rws_tracking.algebra import CameraModel, PixelToGimbalTransform
from src.rws_tracking.config import GimbalControllerConfig, PIDConfig, SelectorConfig
from src.rws_tracking.control import TwoAxisGimbalController
from src.rws_tracking.hardware import SimulatedGimbalDriver
from src.rws_tracking.perception import (
    PassthroughDetector,
    SimpleIoUTracker,
    WeightedTargetSelector,
)
from src.rws_tracking.pipeline import VisionGimbalPipeline
from src.rws_tracking.telemetry import InMemoryTelemetryLogger


class RealisticSimulation:
    """真实仿真：目标在世界坐标系中，云台转动会改变目标在画面中的位置"""

    def __init__(self, cam: CameraModel):
        self.cam = cam
        # 目标在世界坐标系中的角度位置（相对于初始云台朝向）
        self.target_world_yaw = 0.0  # 度
        self.target_world_pitch = 0.0  # 度
        # 目标移动速度（世界坐标系）
        self.target_vel_yaw = 2.0  # deg/s
        self.target_vel_pitch = 1.0  # deg/s

    def step(self, dt: float, gimbal_yaw: float, gimbal_pitch: float) -> list:
        """
        更新仿真并返回检测结果

        参数：
        - dt: 时间步长
        - gimbal_yaw: 云台当前 yaw 角度（度）
        - gimbal_pitch: 云台当前 pitch 角度（度）
        """
        # 更新目标在世界坐标系中的位置
        self.target_world_yaw += self.target_vel_yaw * dt
        self.target_world_pitch += self.target_vel_pitch * dt

        # 限制目标移动范围（避免跑太远）
        self.target_world_yaw = max(-30, min(30, self.target_world_yaw))
        self.target_world_pitch = max(-20, min(20, self.target_world_pitch))

        # 计算目标相对于云台的角度误差
        relative_yaw = self.target_world_yaw - gimbal_yaw
        relative_pitch = self.target_world_pitch - gimbal_pitch

        # 将角度误差转换为像素坐标
        # 使用小角度近似：pixel_offset ≈ angle_rad * focal_length
        pixel_x = self.cam.cx + math.tan(math.radians(relative_yaw)) * self.cam.fx
        pixel_y = self.cam.cy - math.tan(math.radians(relative_pitch)) * self.cam.fy

        # 检查目标是否在画面内
        if 0 <= pixel_x < self.cam.width and 0 <= pixel_y < self.cam.height:
            # 目标在画面内，返回检测结果
            bbox_w, bbox_h = 80, 120
            return [{
                "bbox": (pixel_x - bbox_w/2, pixel_y - bbox_h/2, bbox_w, bbox_h),
                "confidence": 0.95,
                "class_id": "person",
            }]
        else:
            # 目标在画面外
            return []


def main():
    print("="*70)
    print("真实仿真测试 - 云台转动会改变目标在画面中的位置")
    print("="*70)

    # 相机模型
    cam = CameraModel(
        width=1280, height=720,
        fx=970.0, fy=965.0,
        cx=640.0, cy=360.0,
    )

    transform = PixelToGimbalTransform(cam)

    # PID 配置
    controller_cfg = GimbalControllerConfig(
        yaw_pid=PIDConfig(
            kp=10.0, ki=0.3, kd=0.2,
            integral_limit=20.0, output_limit=180.0,
            derivative_lpf_alpha=0.4,
            feedforward_kv=0.5,
        ),
        pitch_pid=PIDConfig(
            kp=10.0, ki=0.3, kd=0.2,
            integral_limit=20.0, output_limit=180.0,
            derivative_lpf_alpha=0.4,
            feedforward_kv=0.5,
        ),
        command_lpf_alpha=0.6,
        lock_error_threshold_deg=1.5,
        lock_hold_time_s=0.3,
        latency_compensation_s=0.033,
    )

    pipeline = VisionGimbalPipeline(
        detector=PassthroughDetector(),
        tracker=SimpleIoUTracker(iou_threshold=0.2, max_misses=10),
        selector=WeightedTargetSelector(
            frame_width=cam.width,
            frame_height=cam.height,
            config=SelectorConfig(
                preferred_classes={"person": 1.0},
                min_hold_time_s=0.2,
                delta_threshold=0.1,
            ),
        ),
        controller=TwoAxisGimbalController(transform=transform, cfg=controller_cfg),
        driver=SimulatedGimbalDriver(),
        telemetry=InMemoryTelemetryLogger(),
    )

    # 创建真实仿真
    sim = RealisticSimulation(cam)

    print("\n初始设置：")
    print("  目标初始位置: Yaw=0°, Pitch=0°（世界坐标系）")
    print("  目标移动速度: Yaw=2°/s, Pitch=1°/s")
    print("  LOCK 阈值: 1.5°")
    print("  Kp: 10.0")
    print()

    ts = 0.0
    dt = 0.033  # 30 Hz
    duration = 15.0

    print(f"{'时间':<6} {'状态':<8} {'目标世界位置':<20} {'云台角度':<20} {'误差':<20} {'Lock?':<6}")
    print("-"*90)

    step_count = 0
    while ts < duration:
        # 获取云台当前角度
        gimbal_yaw = pipeline.driver._yaw
        gimbal_pitch = pipeline.driver._pitch

        # 生成检测结果（考虑云台转动）
        detections = sim.step(dt, gimbal_yaw, gimbal_pitch)

        # 运行 pipeline
        pipeline.step(detections, ts)

        # 每 10 帧打印一次
        if step_count % 10 == 0:
            events = pipeline.telemetry.events
            if events:
                last_event = events[-1]
                payload = last_event.payload

                state_map = {0.0: "SEARCH", 1.0: "TRACK", 2.0: "LOCK", 3.0: "LOST"}
                state = state_map.get(payload.get("state", -1), "?")

                error_yaw = payload.get("yaw_error_deg", 0.0)
                error_pitch = payload.get("pitch_error_deg", 0.0)

                target_world = f"Y:{sim.target_world_yaw:+6.2f} P:{sim.target_world_pitch:+6.2f}"
                gimbal_pos = f"Y:{gimbal_yaw:+6.2f} P:{gimbal_pitch:+6.2f}"
                error_str = f"Y:{error_yaw:+6.2f} P:{error_pitch:+6.2f}"
                is_lock = "LOCK" if state == "LOCK" else ""

                print(f"{ts:5.2f}  {state:<8} {target_world:<20} {gimbal_pos:<20} {error_str:<20} {is_lock:<6}")

        ts += dt
        step_count += 1

    # 最终指标
    metrics = pipeline.telemetry.snapshot_metrics()

    print("\n" + "="*70)
    print("最终指标")
    print("="*70)
    print(f"  Lock Rate:  {metrics['lock_rate']*100:6.2f}%")
    print(f"  Avg Error:  {metrics['avg_abs_error_deg']:6.2f} deg")
    print(f"  Switches:   {metrics['switches_per_min']:6.2f} /min")

    # 分析状态分布
    state_map = {0.0: "SEARCH", 1.0: "TRACK", 2.0: "LOCK", 3.0: "LOST"}
    states = [state_map.get(e.payload.get("state", -1), "?") for e in pipeline.telemetry.events]
    from collections import Counter
    state_counts = Counter(states)

    print("\n状态分布：")
    for state, count in state_counts.most_common():
        percentage = count / len(states) * 100
        print(f"  {state:<8}: {count:4d} 帧 ({percentage:5.1f}%)")

    print("\n" + "="*70)
    if metrics['lock_rate'] > 0.5:
        print("[SUCCESS] System can lock onto moving target")
    elif metrics['lock_rate'] > 0.2:
        print("[PARTIAL] System occasionally locks onto target")
    else:
        print("[FAIL] System cannot lock onto target")
    print("="*70)


if __name__ == "__main__":
    main()
