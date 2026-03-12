"""快速测试脚本 - 仿真模式演示"""

import time

import cv2
import numpy as np

from src.rws_tracking.algebra import CameraModel
from src.rws_tracking.pipeline.app import build_sim_pipeline
from src.rws_tracking.tools.dashboard import RealtimeDashboard
from src.rws_tracking.tools.simulation import SimTarget, SyntheticScene


def main():
    """运行仿真演示，带实时仪表盘"""
    print("[RWS] 启动仿真测试...")

    # 创建相机模型
    cam = CameraModel(
        width=1280,
        height=720,
        fx=970.0,
        fy=965.0,
        cx=640.0,
        cy=360.0,
    )

    # 构建仿真 pipeline
    pipeline = build_sim_pipeline(cam)

    # 创建合成场景
    scene = SyntheticScene(cam.width, cam.height, seed=42)
    scene.add_target(
        SimTarget(x=300, y=200, w=80, h=120, vx=50, vy=30, confidence=0.92, class_id="person")
    )
    scene.add_target(
        SimTarget(x=900, y=400, w=100, h=90, vx=-40, vy=-15, confidence=0.85, class_id="vehicle")
    )

    # 创建实时仪表盘
    dashboard = RealtimeDashboard(
        pipeline.telemetry,
        window_size_s=10.0,
        width=1000,
        height=750,
    )

    print("[RWS] 仿真运行中... 按 'q' 退出")

    ts = 0.0
    dt = 0.033  # 30 Hz

    try:
        while ts < 30.0:  # 运行 30 秒
            # 生成合成帧（检测结果）
            detections = scene.step(dt)

            # 创建可视化图像
            display = np.zeros((cam.height, cam.width, 3), dtype=np.uint8)

            # 绘制所有检测到的目标
            for det in detections:
                x, y, w, h = det["bbox"]
                x, y, w, h = int(x), int(y), int(w), int(h)
                color = (100, 100, 100)  # 灰色表示未选中的目标
                cv2.rectangle(display, (x, y), (x + w, y + h), color, 1)

            # Pipeline 处理（使用检测结果）
            output = pipeline.step(detections, ts)

            # 绘制选中的目标
            if output.selected_target is not None:
                t = output.selected_target
                x, y, w, h = int(t.bbox.x), int(t.bbox.y), int(t.bbox.w), int(t.bbox.h)

                # 绘制边界框（绿色高亮）
                cv2.rectangle(display, (x, y), (x + w, y + h), (0, 255, 0), 3)

                # 绘制目标信息
                label = f"ID:{t.track_id} {t.class_id} {t.confidence:.2f}"
                cv2.putText(
                    display, label, (x, y - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2
                )

                # 绘制中心十字
                cx, cy = int(t.bbox.center[0]), int(t.bbox.center[1])
                cv2.drawMarker(display, (cx, cy), (0, 255, 0), cv2.MARKER_CROSS, 20, 2)

            # 绘制画面中心十字（瞄准点）
            center_x, center_y = cam.width // 2, cam.height // 2
            cv2.drawMarker(display, (center_x, center_y), (0, 0, 255), cv2.MARKER_CROSS, 30, 2)

            # 显示控制命令
            cmd = output.command
            state_names = ["SEARCH", "TRACK", "LOCK", "LOST"]
            state_idx = int(cmd.metadata.get("state", 0))
            state_name = state_names[state_idx] if 0 <= state_idx < 4 else "UNKNOWN"

            # 状态颜色
            state_colors = {
                "SEARCH": (100, 100, 100),
                "TRACK": (0, 255, 255),
                "LOCK": (0, 255, 0),
                "LOST": (0, 0, 255),
            }
            state_color = state_colors.get(state_name, (255, 255, 255))

            info_lines = [
                f"State: {state_name}",
                f"Yaw: {cmd.yaw_rate_cmd_dps:+.1f} dps",
                f"Pitch: {cmd.pitch_rate_cmd_dps:+.1f} dps",
                f"Time: {ts:.1f}s",
            ]

            for i, line in enumerate(info_lines):
                color = state_color if i == 0 else (0, 200, 255)
                cv2.putText(
                    display, line, (10, 30 + i * 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2
                )

            # 更新仪表盘
            dashboard.update(ts)

            # 显示视频帧和仪表盘
            cv2.imshow("RWS Tracking - Simulation", display)
            dashboard.show("RWS Dashboard")

            if cv2.waitKey(1) & 0xFF == ord("q"):
                break

            ts += dt
            time.sleep(dt)  # 模拟实时运行

    finally:
        cv2.destroyAllWindows()

        # 显示最终指标
        metrics = pipeline.telemetry.snapshot_metrics()
        print("\n[RWS] 仿真完成，性能指标：")
        print(f"  Lock Rate: {metrics['lock_rate'] * 100:.1f}%")
        print(f"  Avg Error: {metrics['avg_abs_error_deg']:.2f} deg")
        print(f"  Switches: {metrics['switches_per_min']:.1f} /min")


if __name__ == "__main__":
    main()
