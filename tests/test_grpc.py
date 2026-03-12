"""gRPC 服务端/客户端单元测试。"""

from unittest.mock import MagicMock, patch

import pytest


class TestGrpcServerImport:
    def test_import(self):
        from src.rws_tracking.api import grpc_server

        assert grpc_server is not None


class TestGrpcClientImport:
    def test_import(self):
        from src.rws_tracking.api import grpc_client

        assert grpc_client is not None


class TestGrpcServer:
    @pytest.fixture
    def server_cls(self):
        from src.rws_tracking.api.grpc_server import TrackingGrpcServer

        return TrackingGrpcServer

    def test_init(self, server_cls):
        with patch("src.rws_tracking.api.grpc_server.grpc") as mock_grpc:
            mock_grpc.server.return_value = MagicMock()
            s = server_cls.__new__(server_cls)
            s._pipeline = MagicMock()
            s._server = MagicMock()
            assert s is not None


class TestGrpcClient:
    @pytest.fixture
    def client_cls(self):
        from src.rws_tracking.api.grpc_client import TrackingGrpcClient

        return TrackingGrpcClient

    def test_init(self, client_cls):
        with patch("src.rws_tracking.api.grpc_client.grpc") as mock_grpc:
            mock_grpc.insecure_channel.return_value = MagicMock()
            c = client_cls.__new__(client_cls)
            c._channel = MagicMock()
            c._stub = MagicMock()
            assert c is not None
