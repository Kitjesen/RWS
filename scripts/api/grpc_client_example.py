#!/usr/bin/env python3
"""
gRPC Client Example
===================

Demonstrates how to use the gRPC client to control the tracking system.
"""

import sys
import time
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from rws_tracking.api.grpc_client import TrackingGrpcClient


def main():
    print("=" * 70)
    print("RWS Tracking gRPC Client Example")
    print("=" * 70)

    # Connect to server
    client = TrackingGrpcClient(host="localhost", port=50051)

    try:
        # 1. Health check
        print("\n1. Health Check")
        print("-" * 70)
        health = client.health_check()
        print(f"Health: {health}")

        # 2. Start tracking
        print("\n2. Start Tracking")
        print("-" * 70)
        result = client.start_tracking(camera_source=0)
        print(f"Start result: {result}")

        if not result.get("success"):
            print("Failed to start tracking. Exiting.")
            return

        # Wait for initialization
        time.sleep(2)

        # 3. Get status
        print("\n3. Get Status")
        print("-" * 70)
        status = client.get_status()
        print(f"Running: {status.get('running')}")
        print(f"Frame count: {status.get('frame_count')}")
        print(f"FPS: {status.get('fps', 0):.1f}")
        print(f"Gimbal: {status.get('gimbal')}")

        # 4. Set gimbal position
        print("\n4. Set Gimbal Position")
        print("-" * 70)
        result = client.set_gimbal_position(yaw_deg=15.0, pitch_deg=10.0)
        print(f"Set position result: {result}")

        time.sleep(2)

        # 5. Set gimbal rate
        print("\n5. Set Gimbal Rate")
        print("-" * 70)
        result = client.set_gimbal_rate(yaw_rate_dps=20.0, pitch_rate_dps=10.0)
        print(f"Set rate result: {result}")

        time.sleep(1)

        # 6. Get telemetry
        print("\n6. Get Telemetry")
        print("-" * 70)
        telemetry = client.get_telemetry()
        if telemetry.get("success"):
            metrics = telemetry.get("metrics", {})
            print(f"Telemetry metrics ({len(metrics)} entries):")
            for key, value in list(metrics.items())[:5]:
                print(f"  {key}: {value:.3f}")
        else:
            print(f"Telemetry error: {telemetry.get('error')}")

        # 7. Stream status (for 5 seconds)
        print("\n7. Stream Status (5 seconds)")
        print("-" * 70)
        start_time = time.time()
        for update in client.stream_status(update_rate_hz=5.0):
            if "error" in update:
                print(f"Stream error: {update['error']}")
                break

            elapsed = time.time() - start_time
            if elapsed > 5.0:
                break

            print(
                f"[{elapsed:.1f}s] FPS: {update['fps']:.1f}, "
                f"Yaw: {update['gimbal']['yaw_deg']:.1f}°, "
                f"Pitch: {update['gimbal']['pitch_deg']:.1f}°"
            )

        # 8. Stop tracking
        print("\n8. Stop Tracking")
        print("-" * 70)
        result = client.stop_tracking()
        print(f"Stop result: {result}")

        print("\n" + "=" * 70)
        print("Example completed successfully!")
        print("=" * 70)

    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
        client.stop_tracking()

    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()

    finally:
        client.close()


if __name__ == "__main__":
    main()
