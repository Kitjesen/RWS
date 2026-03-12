"""激进参数测试 - 力求达到 Lock"""

import pytest

from src.rws_tracking.algebra import CameraModel
from src.rws_tracking.config import GimbalControllerConfig, PIDConfig
from src.rws_tracking.tools.simulation import SimTarget, SyntheticScene

pytestmark = pytest.mark.skip(reason="manual benchmark only, not a unit test")


def test_aggressive(kp_yaw, kp_pitch, target_speed, lock_threshold, duration=20.0):
    """测试激进参数"""
    print(f"\n{'=' * 60}")
    print("测试参数：")
    print(f"  Yaw Kp: {kp_yaw}")
    print(f"  Pitch Kp: {kp_pitch}")
    print(f"  目标速度: {target_speed} px/s")
    print(f"  LOCK 阈值: {lock_threshold} deg")
    print(f"  持续时间: {duration}s")
    print(f"{'=' * 60}\n")

    cam = CameraModel(
        width=1280,
        height=720,
        fx=970.0,
        fy=965.0,
        cx=640.0,
        cy=360.0,
    )

    from src.rws_tracking.algebra import PixelToGimbalTransform
    from src.rws_tracking.config import SelectorConfig
    from src.rws_tracking.control import TwoAxisGimbalController
    from src.rws_tracking.hardware import SimulatedGimbalDriver
    from src.rws_tracking.perception import (
        PassthroughDetector,
        SimpleIoUTracker,
        WeightedTargetSelector,
    )
    from src.rws_tracking.pipeline import VisionGimbalPipeline
    from src.rws_tracking.telemetry import InMemoryTelemetryLogger

    transform = PixelToGimbalTransform(cam)

    # 激进 PID 配置
    controller_cfg = GimbalControllerConfig(
        yaw_pid=PIDConfig(
            kp=kp_yaw,
            ki=0.8,
            kd=0.5,
            integral_limit=50.0,
            output_limit=180.0,
            derivative_lpf_alpha=0.3,
            feedforward_kv=1.0,
        ),
        pitch_pid=PIDConfig(
            kp=kp_pitch,
            ki=0.75,
            kd=0.5,
            integral_limit=50.0,
            output_limit=180.0,
            derivative_lpf_alpha=0.3,
            feedforward_kv=0.95,
        ),
        command_lpf_alpha=0.6,
        lock_error_threshold_deg=lock_threshold,
        lock_hold_time_s=0.15,  # 缩短保持时间
        latency_compensation_s=0.033,
    )

    pipeline = VisionGimbalPipeline(
        detector=PassthroughDetector(),
        tracker=SimpleIoUTracker(iou_threshold=0.18, max_misses=10),
        selector=WeightedTargetSelector(
            frame_width=cam.width,
            frame_height=cam.height,
            config=SelectorConfig(
                preferred_classes={"person": 1.0},
                min_hold_time_s=0.25,
                delta_threshold=0.08,
            ),
        ),
        controller=TwoAxisGimbalController(transform=transform, cfg=controller_cfg),
        driver=SimulatedGimbalDriver(),
        telemetry=InMemoryTelemetryLogger(),
    )

    # 创建慢速目标
    scene = SyntheticScene(cam.width, cam.height, seed=42)
    scene.add_target(
        SimTarget(
            x=400,
            y=300,
            w=80,
            h=120,
            vx=target_speed,
            vy=target_speed * 0.6,
            confidence=0.92,
            class_id="person",
        )
    )

    ts = 0.0
    dt = 0.033  # 30 Hz

    while ts < duration:
        detections = scene.step(dt)
        pipeline.step(detections, ts)
        ts += dt

    metrics = pipeline.telemetry.snapshot_metrics()

    print("\n结果：")
    print(f"  Lock Rate:  {metrics['lock_rate'] * 100:6.2f}%")
    print(f"  Avg Error:  {metrics['avg_abs_error_deg']:6.2f} deg")
    print(f"  Switches:   {metrics['switches_per_min']:6.2f} /min")

    return metrics


def main():
    print("=" * 60)
    print("RWS 激进参数测试")
    print("=" * 60)
    print("\n目标：通过极端参数达到 Lock 状态\n")

    results = []

    # 测试 1：超慢目标 + 放宽条件
    print("\n[测试 1] 超慢目标 (5 px/s) + 放宽 LOCK (2.0 deg)")
    m1 = test_aggressive(
        kp_yaw=10.0, kp_pitch=10.5, target_speed=5, lock_threshold=2.0, duration=20.0
    )
    results.append(("超慢+放宽", m1))

    # 测试 2：超慢目标 + 超大 Kp + 放宽条件
    print("\n[测试 2] 超慢目标 (5 px/s) + 超大 Kp (20) + 放宽 LOCK (2.5 deg)")
    m2 = test_aggressive(
        kp_yaw=20.0, kp_pitch=20.5, target_speed=5, lock_threshold=2.5, duration=20.0
    )
    results.append(("超慢+超大Kp+放宽", m2))

    # 测试 3：极慢目标 + 大 Kp + 极度放宽
    print("\n[测试 3] 极慢目标 (3 px/s) + 大 Kp (15) + 极度放宽 (3.0 deg)")
    m3 = test_aggressive(
        kp_yaw=15.0, kp_pitch=15.5, target_speed=3, lock_threshold=3.0, duration=20.0
    )
    results.append(("极慢+极度放宽", m3))

    # 测试 4：静止目标 + 标准条件
    print("\n[测试 4] 静止目标 (0 px/s) + 标准 LOCK (0.8 deg)")
    m4 = test_aggressive(
        kp_yaw=10.0, kp_pitch=10.5, target_speed=0, lock_threshold=0.8, duration=20.0
    )
    results.append(("静止目标", m4))

    # 汇总结果
    print("\n" + "=" * 60)
    print("测试结果汇总")
    print("=" * 60)
    print(f"\n{'配置':<20} {'Lock Rate':<12} {'Avg Error':<12} {'Switches':<12}")
    print("-" * 60)

    for name, metrics in results:
        print(
            f"{name:<20} {metrics['lock_rate'] * 100:>10.2f}%  "
            f"{metrics['avg_abs_error_deg']:>10.2f} deg  "
            f"{metrics['switches_per_min']:>10.2f} /min"
        )

    # 找出最佳配置
    best_idx = max(range(len(results)), key=lambda i: results[i][1]["lock_rate"])
    best_name, best_metrics = results[best_idx]

    print("\n" + "=" * 60)
    print(f"最佳配置: {best_name}")
    print(f"  Lock Rate: {best_metrics['lock_rate'] * 100:.2f}%")
    print(f"  Avg Error: {best_metrics['avg_abs_error_deg']:.2f} deg")
    print("=" * 60)

    # 给出建议
    print("\n" + "=" * 60)
    print("调优建议")
    print("=" * 60)
    if best_metrics["lock_rate"] > 0.5:
        print("\n[优秀] Lock Rate > 50%")
        print("  - 系统性能良好")
        print("  - 可以尝试增加目标速度或收紧 LOCK 条件")
    elif best_metrics["lock_rate"] > 0.2:
        print("\n[良好] Lock Rate 20-50%")
        print("  - 系统基本可用")
        print("  - 建议微调 PID 参数或略微放宽 LOCK 条件")
    else:
        print("\n[需改进] Lock Rate < 20%")
        print("  - 建议：")
        print("    1. 进一步降低目标速度")
        print("    2. 继续放宽 LOCK 条件 (3.0-5.0 deg)")
        print("    3. 增大 Kp 值 (20-30)")
        print("    4. 启用自适应 PID")


if __name__ == "__main__":
    main()
