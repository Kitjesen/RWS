"""诊断测试 - 详细输出运行状态"""

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
from src.rws_tracking.tools.simulation import SimTarget, SyntheticScene


def main():
    print("=" * 70)
    print("RWS 诊断测试 - 详细状态输出")
    print("=" * 70)

    # 相机模型
    cam = CameraModel(
        width=1280,
        height=720,
        fx=970.0,
        fy=965.0,
        cx=640.0,
        cy=360.0,
    )

    transform = PixelToGimbalTransform(cam)

    # 简单的 PID 配置
    controller_cfg = GimbalControllerConfig(
        yaw_pid=PIDConfig(
            kp=15.0,
            ki=0.5,
            kd=0.3,
            integral_limit=30.0,
            output_limit=180.0,
            derivative_lpf_alpha=0.4,
            feedforward_kv=0.8,
        ),
        pitch_pid=PIDConfig(
            kp=15.0,
            ki=0.5,
            kd=0.3,
            integral_limit=30.0,
            output_limit=180.0,
            derivative_lpf_alpha=0.4,
            feedforward_kv=0.8,
        ),
        command_lpf_alpha=0.6,
        lock_error_threshold_deg=2.0,  # 放宽到 2 度
        lock_hold_time_s=0.2,
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

    # 创建场景：目标从接近中心开始，慢速移动
    scene = SyntheticScene(cam.width, cam.height, seed=42)
    scene.add_target(
        SimTarget(
            x=600,
            y=340,  # 接近中心 (640, 360)
            w=80,
            h=120,
            vx=3,
            vy=2,  # 很慢的速度
            confidence=0.95,
            class_id="person",
        )
    )

    print("\n初始设置：")
    print(f"  画面中心: ({cam.cx}, {cam.cy})")
    print("  目标起点: (600, 340)")
    print("  目标速度: (3, 2) px/s")
    print("  LOCK 阈值: 2.0 deg")
    print("  Kp: 15.0")
    print()

    ts = 0.0
    dt = 0.033  # 30 Hz
    duration = 10.0

    print(
        f"{'时间':<6} {'状态':<8} {'目标位置':<20} {'误差(deg)':<20} {'云台角度(deg)':<20} {'命令(dps)':<20}"
    )
    print("-" * 110)

    step_count = 0
    while ts < duration:
        detections = scene.step(dt)
        pipeline.step(detections, ts)

        # 每 10 帧打印一次（约 0.33 秒）
        if step_count % 10 == 0:
            # 获取当前状态
            events = pipeline.telemetry.events
            if events:
                last_event = events[-1]
                payload = last_event.payload

                # 状态映射：0=SEARCH, 1=TRACK, 2=LOCK, 3=LOST
                state_map = {0.0: "SEARCH", 1.0: "TRACK", 2.0: "LOCK", 3.0: "LOST"}
                state = state_map.get(payload.get("state", -1), "?")

                error_yaw = payload.get("yaw_error_deg", 0.0)
                error_pitch = payload.get("pitch_error_deg", 0.0)
                cmd_yaw = payload.get("yaw_cmd_dps", 0.0)
                cmd_pitch = payload.get("pitch_cmd_dps", 0.0)

                # 从 driver 获取云台角度
                gimbal_yaw = pipeline.driver._yaw
                gimbal_pitch = pipeline.driver._pitch

                # 获取目标位置
                if detections:
                    det = detections[0]
                    bbox = det["bbox"]
                    cx = bbox[0] + bbox[2] / 2
                    cy = bbox[1] + bbox[3] / 2
                    target_pos = f"({cx:.0f}, {cy:.0f})"
                else:
                    target_pos = "无目标"

                error_str = f"Y:{error_yaw:+6.2f} P:{error_pitch:+6.2f}"
                gimbal_str = f"Y:{gimbal_yaw:+6.2f} P:{gimbal_pitch:+6.2f}"
                cmd_str = f"Y:{cmd_yaw:+6.1f} P:{cmd_pitch:+6.1f}"

                print(
                    f"{ts:5.2f}  {state:<8} {target_pos:<20} {error_str:<20} {gimbal_str:<20} {cmd_str:<20}"
                )

        ts += dt
        step_count += 1

    # 最终指标
    metrics = pipeline.telemetry.snapshot_metrics()

    print("\n" + "=" * 70)
    print("最终指标")
    print("=" * 70)
    print(f"  Lock Rate:  {metrics['lock_rate'] * 100:6.2f}%")
    print(f"  Avg Error:  {metrics['avg_abs_error_deg']:6.2f} deg")
    print(f"  Switches:   {metrics['switches_per_min']:6.2f} /min")
    print(f"  总帧数:     {step_count}")

    # 分析状态分布
    state_map = {0.0: "SEARCH", 1.0: "TRACK", 2.0: "LOCK", 3.0: "LOST"}
    states = [state_map.get(e.payload.get("state", -1), "?") for e in pipeline.telemetry.events]
    from collections import Counter

    state_counts = Counter(states)

    print("\n状态分布：")
    for state, count in state_counts.most_common():
        percentage = count / len(states) * 100
        print(f"  {state:<8}: {count:4d} 帧 ({percentage:5.1f}%)")

    print("\n" + "=" * 70)
    print("诊断结论")
    print("=" * 70)

    if metrics["lock_rate"] > 0.5:
        print("\n[成功] 系统能够锁定目标")
    elif metrics["lock_rate"] > 0.1:
        print("\n[部分成功] 系统偶尔能锁定目标")
        print("  建议：进一步放宽 LOCK 条件或增大 Kp")
    else:
        print("\n[失败] 系统无法锁定目标")
        print("  可能原因：")
        if metrics["avg_abs_error_deg"] > 5.0:
            print("    - 平均误差过大 (>5 deg)，PID 响应不足")
            print("    - 建议：增大 Kp 到 20-30")
        if state_counts.get("LOCK", 0) == 0:
            print("    - 从未进入 LOCK 状态")
            print("    - 建议：放宽 lock_error_threshold_deg 到 3-5 deg")
        if state_counts.get("SEARCH", 0) > len(states) * 0.5:
            print("    - 大部分时间在 SEARCH 状态")
            print("    - 建议：检查目标检测和选择器配置")


if __name__ == "__main__":
    main()
