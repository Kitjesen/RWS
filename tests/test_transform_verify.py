"""验证坐标变换是否正确"""

from src.rws_tracking.algebra import CameraModel, PixelToGimbalTransform


def main():
    print("=" * 70)
    print("坐标变换验证测试")
    print("=" * 70)

    # 创建相机模型
    cam = CameraModel(
        width=1280,
        height=720,
        fx=970.0,
        fy=965.0,
        cx=640.0,
        cy=360.0,
    )

    transform = PixelToGimbalTransform(cam)

    print("\n相机参数：")
    print(f"  分辨率: {cam.width} x {cam.height}")
    print(f"  中心: ({cam.cx}, {cam.cy})")
    print(f"  焦距: fx={cam.fx}, fy={cam.fy}")

    # 测试几个关键点
    test_points = [
        (640, 360, "画面中心"),
        (600, 340, "左上方（测试起点）"),
        (680, 380, "右下方"),
        (640, 300, "正上方"),
        (640, 420, "正下方"),
        (700, 360, "正右方"),
        (580, 360, "正左方"),
    ]

    print(f"\n{'像素坐标':<20} {'描述':<15} {'Yaw误差(deg)':<15} {'Pitch误差(deg)':<15}")
    print("-" * 70)

    for px, py, desc in test_points:
        yaw_err, pitch_err = transform.pixel_to_angle_error(px, py)
        print(f"({px:4d}, {py:4d}){'':<8} {desc:<15} {yaw_err:>+8.2f}{'':<7} {pitch_err:>+8.2f}")

    print("\n" + "=" * 70)
    print("预期行为：")
    print("=" * 70)
    print("  - 目标在中心右侧 → Yaw 误差为正（需要向右转）")
    print("  - 目标在中心左侧 → Yaw 误差为负（需要向左转）")
    print("  - 目标在中心上方 → Pitch 误差为正（需要向上转）")
    print("  - 目标在中心下方 → Pitch 误差为负（需要向下转）")
    print("\n如果符号相反，说明坐标变换有问题！")


if __name__ == "__main__":
    main()
