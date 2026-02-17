#!/bin/bash
# Generate gRPC protobuf files
# Run this script from the project root directory

set -e

echo "Generating gRPC protobuf files..."

cd src/rws_tracking/api

python -m grpc_tools.protoc \
    -I. \
    --python_out=. \
    --grpc_python_out=. \
    tracking.proto

echo "✓ Generated tracking_pb2.py"
echo "✓ Generated tracking_pb2_grpc.py"

# Fix imports in generated files (Python 3.10+ compatibility)
if [[ "$OSTYPE" == "darwin"* ]]; then
    # macOS
    sed -i '' 's/import tracking_pb2/from . import tracking_pb2/g' tracking_pb2_grpc.py
else
    # Linux/Windows Git Bash
    sed -i 's/import tracking_pb2/from . import tracking_pb2/g' tracking_pb2_grpc.py
fi

echo "✓ Fixed imports"
echo ""
echo "Protobuf generation complete!"
echo "You can now run the gRPC server: python scripts/run_grpc_server.py"
