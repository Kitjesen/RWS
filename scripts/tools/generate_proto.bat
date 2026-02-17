@echo off
REM Generate gRPC protobuf files for Windows
REM Run this script from the project root directory

echo Generating gRPC protobuf files...

cd src\rws_tracking\api

python -m grpc_tools.protoc -I. --python_out=. --grpc_python_out=. tracking.proto

if %ERRORLEVEL% NEQ 0 (
    echo Error: Failed to generate protobuf files
    echo Make sure grpcio-tools is installed: pip install grpcio-tools
    exit /b 1
)

echo Generated tracking_pb2.py
echo Generated tracking_pb2_grpc.py

REM Fix imports in generated files
powershell -Command "(gc tracking_pb2_grpc.py) -replace 'import tracking_pb2', 'from . import tracking_pb2' | Out-File -encoding ASCII tracking_pb2_grpc.py"

echo Fixed imports
echo.
echo Protobuf generation complete!
echo You can now run the gRPC server: python scripts\run_grpc_server.py
