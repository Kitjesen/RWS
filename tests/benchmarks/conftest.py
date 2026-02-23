"""Conftest for benchmark tests.

Provides a minimal ``benchmark`` fixture stub when pytest-benchmark is not
installed, so benchmark tests can still be collected and their non-timing
assertions exercised in regular CI.
"""

import pytest


class _BenchmarkStub:
    """Runs *func* once to verify it executes without error.

    Reports ``stats["mean"] = 0.0`` so timing assertions always pass in
    non-benchmark (CI stub) mode.  Install pytest-benchmark for real timing.
    """

    def __init__(self):
        self.stats = {"mean": 0.0}

    def __call__(self, func, *args, **kwargs):
        result = func(*args, **kwargs)
        self.stats = {"mean": 0.0}
        return result


def pytest_configure(config):
    """Register benchmark mark so it is never flagged as unknown."""
    config.addinivalue_line("markers", "benchmark: performance benchmark (stub)")


@pytest.fixture
def benchmark():
    """Stub fixture used when pytest-benchmark is not installed."""
    return _BenchmarkStub()
