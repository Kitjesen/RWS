#!/usr/bin/env python3
"""
API Test Suite
==============

Tests both REST and gRPC APIs to ensure they work correctly.
"""

import sys
import time
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


def test_rest_api():
    """Test REST API endpoints."""
    print("\n" + "=" * 70)
    print("Testing REST API")
    print("=" * 70)

    try:
        from rws_tracking.api.client import TrackingClient

        client = TrackingClient("http://localhost:5000")

        # Health check
        print("\n[REST] Health Check...")
        health = client.health_check()
        print(f"  Result: {health}")
        assert health.get("status") == "ok", "Health check failed"

        # Start tracking
        print("\n[REST] Starting tracking...")
        result = client.start_tracking(camera_source=0)
        print(f"  Result: {result}")

        if result.get("success"):
            time.sleep(2)

            # Get status
            print("\n[REST] Getting status...")
            status = client.get_status()
            print(f"  Running: {status.get('running')}")
            print(f"  FPS: {status.get('fps', 0):.1f}")
            print(f"  Gimbal: {status.get('gimbal')}")

            # Set gimbal position
            print("\n[REST] Setting gimbal position...")
            result = client.set_gimbal_position(yaw_deg=10.0, pitch_deg=5.0)
            print(f"  Result: {result}")

            time.sleep(1)

            # Get telemetry
            print("\n[REST] Getting telemetry...")
            telemetry = client.get_telemetry()
            if telemetry.get("success"):
                metrics = telemetry.get("metrics", {})
                print(f"  Metrics count: {len(metrics)}")

            # Stop tracking
            print("\n[REST] Stopping tracking...")
            result = client.stop_tracking()
            print(f"  Result: {result}")

        print("\n✓ REST API tests passed")
        return True

    except Exception as e:
        print(f"\n✗ REST API tests failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_grpc_api():
    """Test gRPC API endpoints."""
    print("\n" + "=" * 70)
    print("Testing gRPC API")
    print("=" * 70)

    try:
        from rws_tracking.api.grpc_client import TrackingGrpcClient

        client = TrackingGrpcClient(host="localhost", port=50051)

        # Health check
        print("\n[gRPC] Health Check...")
        health = client.health_check()
        print(f"  Result: {health}")
        assert health.get("status") == "ok", "Health check failed"

        # Start tracking
        print("\n[gRPC] Starting tracking...")
        result = client.start_tracking(camera_source=0)
        print(f"  Result: {result}")

        if result.get("success"):
            time.sleep(2)

            # Get status
            print("\n[gRPC] Getting status...")
            status = client.get_status()
            print(f"  Running: {status.get('running')}")
            print(f"  FPS: {status.get('fps', 0):.1f}")
            print(f"  Gimbal: {status.get('gimbal')}")

            # Set gimbal position
            print("\n[gRPC] Setting gimbal position...")
            result = client.set_gimbal_position(yaw_deg=10.0, pitch_deg=5.0)
            print(f"  Result: {result}")

            time.sleep(1)

            # Get telemetry
            print("\n[gRPC] Getting telemetry...")
            telemetry = client.get_telemetry()
            if telemetry.get("success"):
                metrics = telemetry.get("metrics", {})
                print(f"  Metrics count: {len(metrics)}")

            # Stream status (3 seconds)
            print("\n[gRPC] Streaming status (3 seconds)...")
            start_time = time.time()
            count = 0
            for update in client.stream_status(update_rate_hz=5.0):
                if "error" in update:
                    print(f"  Stream error: {update['error']}")
                    break

                elapsed = time.time() - start_time
                if elapsed > 3.0:
                    break

                count += 1
                print(f"  [{count}] FPS: {update['fps']:.1f}, Yaw: {update['gimbal']['yaw_deg']:.1f}°")

            # Stop tracking
            print("\n[gRPC] Stopping tracking...")
            result = client.stop_tracking()
            print(f"  Result: {result}")

        client.close()
        print("\n✓ gRPC API tests passed")
        return True

    except Exception as e:
        print(f"\n✗ gRPC API tests failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    print("=" * 70)
    print("RWS Tracking API Test Suite")
    print("=" * 70)
    print("\nThis script tests both REST and gRPC APIs.")
    print("Make sure the servers are running before testing:")
    print("  REST: python scripts/run_api_server.py")
    print("  gRPC: python scripts/run_grpc_server.py")
    print()

    input("Press Enter to start testing...")

    results = []

    # Test REST API
    try:
        rest_passed = test_rest_api()
        results.append(("REST API", rest_passed))
    except Exception as e:
        print(f"\nFailed to test REST API: {e}")
        results.append(("REST API", False))

    time.sleep(2)

    # Test gRPC API
    try:
        grpc_passed = test_grpc_api()
        results.append(("gRPC API", grpc_passed))
    except Exception as e:
        print(f"\nFailed to test gRPC API: {e}")
        results.append(("gRPC API", False))

    # Summary
    print("\n" + "=" * 70)
    print("Test Summary")
    print("=" * 70)
    for name, passed in results:
        status = "✓ PASSED" if passed else "✗ FAILED"
        print(f"{name:20s} {status}")

    all_passed = all(passed for _, passed in results)
    print("\n" + "=" * 70)
    if all_passed:
        print("All tests passed! ✓")
    else:
        print("Some tests failed. ✗")
    print("=" * 70)

    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
