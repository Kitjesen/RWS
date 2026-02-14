"""简单的命令行测试 - 无 GUI 窗口"""
from src.rws_tracking.pipeline.app import run_demo

def main():
    """运行 10 秒仿真测试，输出性能指标"""
    print("=" * 60)
    print("RWS 二自由度云台跟踪系统 - 仿真测试")
    print("=" * 60)
    print()
    print("测试配置：")
    print("  - 持续时间: 10 秒")
    print("  - 帧率: 30 Hz")
    print("  - 目标数量: 2 个（person + vehicle）")
    print("  - 控制器: PID (已调优)")
    print()
    print("开始测试...")
    print("-" * 60)

    # 运行仿真
    metrics = run_demo(duration_s=10.0, dt_s=0.033)

    print("-" * 60)
    print()
    print("测试完成！性能指标：")
    print()
    print(f"  Lock Rate (锁定率):        {metrics['lock_rate']*100:6.2f}%")
    print(f"  Avg Error (平均误差):      {metrics['avg_abs_error_deg']:6.2f} deg")
    print(f"  Switches (目标切换频率):   {metrics['switches_per_min']:6.2f} /min")
    print()
    print("指标说明：")
    print("  - Lock Rate: 云台处于 LOCK 状态的时间占比（越高越好）")
    print("  - Avg Error: 目标中心与画面中心的平均角度误差（越小越好）")
    print("  - Switches: 每分钟切换目标的次数（越少越好，说明跟踪稳定）")
    print()

    # 评估性能
    if metrics['lock_rate'] > 0.5:
        print("[优秀] 性能评估: 锁定率超过 50%")
    elif metrics['lock_rate'] > 0.2:
        print("[良好] 性能评估: 锁定率在 20-50% 之间")
    else:
        print("[需改进] 性能评估: 锁定率低于 20%")
        print("         建议: 调整 PID 参数或降低目标移动速度")

    print()
    print("=" * 60)
    print("测试完成！")
    print("=" * 60)

if __name__ == "__main__":
    main()
