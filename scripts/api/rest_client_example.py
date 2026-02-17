#!/usr/bin/env python3
"""
Example: Control RWS Tracking via API Client
=============================================

Demonstrates how to use the TrackingClient to control the system remotely.
"""

import time
from rws_tracking.api import TrackingClient


def main():
    # Connect to API server
    client = TrackingClient("http://localhost:5000")

    print("╔══════════════════════════════════════════════════════════════╗")
    print("║          RWS Tracking API Client Example                    ║")
    print("╚══════════════════════════════════════════════════════════════╝\n")

    # 1. Health check
    print("1. Checking server health...")
    health = client.health_check()
    print(f"   Response: {health}\n")

    # 2. Start tracking
    print("2. Starting tracking...")
    result = client.start_tracking(camera_source=0)
    print(f"   Response: {result}\n")

    if not result.get("success"):
        print("Failed to start tracking. Exiting.")
        return

    # 3. Monitor status for a few seconds
    print("3. Monitoring status...")
    for i in range(5):
        status = client.get_status()
        print(f"   Frame: {status.get('frame_count', 0)}, "
              f"FPS: {status.get('fps', 0):.1f}, "
              f"Running: {status.get('running', False)}")

        if "gimbal" in status:
            gimbal = status["gimbal"]
            print(f"   Gimbal: Yaw={gimbal['yaw_deg']:.1f}°, "
                  f"Pitch={gimbal['pitch_deg']:.1f}°")

        time.sleep(1)
    print()

    # 4. Control gimbal manually
    print("4. Controlling gimbal manually...")

    # Move to position
    print("   Moving to yaw=10°, pitch=5°...")
    result = client.set_gimbal_position(yaw_deg=10.0, pitch_deg=5.0)
    print(f"   Response: {result}")
    time.sleep(2)

    # Set rate
    print("   Setting rate: yaw=20 dps, pitch=10 dps...")
    result = client.set_gimbal_rate(yaw_rate_dps=20.0, pitch_rate_dps=10.0)
    print(f"   Response: {result}")
    time.sleep(2)

    # Return to center
    print("   Returning to center...")
    result = client.set_gimbal_position(yaw_deg=0.0, pitch_deg=0.0)
    print(f"   Response: {result}\n")
    time.sleep(2)

    # 5. Get telemetry
    print("5. Getting telemetry...")
    telemetry = client.get_telemetry()
    if telemetry.get("success"):
        metrics = telemetry.get("metrics", {})
        print(f"   Metrics: {metrics}\n")
    else:
        print(f"   Error: {telemetry.get('error')}\n")

    # 6. Stop tracking
    print("6. Stopping tracking...")
    result = client.stop_tracking()
    print(f"   Response: {result}\n")

    print("╔══════════════════════════════════════════════════════════════╗")
    print("║                    Example Complete                          ║")
    print("╚══════════════════════════════════════════════════════════════╝")


if __name__ == "__main__":
    main()
