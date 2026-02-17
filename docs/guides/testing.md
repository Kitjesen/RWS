# Testing Guide

## Quick Start

### Run All Tests

**Linux/Mac:**
```bash
chmod +x run_tests.sh
./run_tests.sh
```

**Windows:**
```bash
run_tests.bat
```

### Run Specific Tests

```bash
# Run only unit tests (fast)
pytest tests/ --ignore=tests/benchmarks -v

# Run only benchmarks
pytest tests/benchmarks/ -v --benchmark-only

# Run specific test file
pytest tests/test_selector.py -v

# Run specific test
pytest tests/test_selector.py::TestWeightedTargetSelector::test_confidence_weight -v

# Run with coverage
pytest tests/ --cov=src/rws_tracking --cov-report=html
```

## Test Organization

```
tests/
├── test_selector.py              # Target selector tests (20+ cases)
├── test_controller.py            # Controller tests (30+ cases)
├── test_kalman.py                # Kalman filter tests (NEW)
├── test_coordinate_transform.py  # Coordinate transform tests (NEW)
├── test_tracking_flow.py         # Integration tests
├── test_body_compensation.py     # Body motion tests
├── test_p2_improvements.py       # Telemetry tests
├── test_sil.py                   # MuJoCo SIL tests
└── benchmarks/
    └── test_performance.py       # Performance benchmarks (NEW)
```

## Coverage Goals

- **Target:** 80%+ overall coverage
- **Current:** Run `pytest --cov` to check

### View Coverage Report

```bash
# Generate HTML report
pytest tests/ --cov=src/rws_tracking --cov-report=html

# Open in browser
open htmlcov/index.html  # Mac
xdg-open htmlcov/index.html  # Linux
start htmlcov/index.html  # Windows
```

## Code Quality Checks

### Linting

```bash
# Check code style
ruff check src/ tests/

# Auto-fix issues
ruff check src/ tests/ --fix

# Format code
ruff format src/ tests/
```

### Type Checking

```bash
# Run mypy
mypy src/rws_tracking --ignore-missing-imports
```

### Security Scan

```bash
# Check for vulnerabilities
safety check
```

## Pre-commit Hooks

Install pre-commit hooks to run checks automatically:

```bash
# Install pre-commit
pip install pre-commit

# Install hooks
pre-commit install

# Run manually
pre-commit run --all-files
```

Hooks will run on every commit:
- Trailing whitespace removal
- YAML/TOML validation
- Ruff linting and formatting
- Mypy type checking
- Pytest tests

## Continuous Integration

Tests run automatically on GitHub Actions:
- On every push to `master` or `develop`
- On every pull request
- Multiple Python versions (3.9, 3.10, 3.11)

See `.github/workflows/ci.yml` for details.

## Writing Tests

### Test Structure

```python
import pytest
from src.rws_tracking.module import Component

class TestComponent:
    """Test suite for Component."""

    def test_basic_functionality(self):
        """Test basic functionality."""
        component = Component()
        result = component.do_something()
        assert result == expected

    def test_edge_case(self):
        """Test edge case."""
        component = Component()
        with pytest.raises(ValueError):
            component.do_invalid_thing()
```

### Fixtures

```python
@pytest.fixture
def component():
    """Create component for testing."""
    return Component(param=value)

def test_with_fixture(component):
    """Test using fixture."""
    assert component.param == value
```

### Parametrized Tests

```python
@pytest.mark.parametrize("input,expected", [
    (1, 2),
    (2, 4),
    (3, 6),
])
def test_multiply(input, expected):
    assert multiply(input, 2) == expected
```

### Benchmarks

```python
def test_performance(benchmark):
    """Benchmark function."""
    result = benchmark(expensive_function)
    assert benchmark.stats['mean'] < 0.001  # < 1ms
```

## Troubleshooting

### Tests Fail with Import Errors

```bash
# Make sure you're in the project root
cd /path/to/RWS

# Install in development mode
pip install -e .
```

### Coverage Not Working

```bash
# Install coverage plugin
pip install pytest-cov

# Run with coverage
pytest --cov=src/rws_tracking
```

### Benchmarks Not Running

```bash
# Install benchmark plugin
pip install pytest-benchmark

# Run benchmarks
pytest tests/benchmarks/ --benchmark-only
```

### Slow Tests

```bash
# Run tests in parallel
pip install pytest-xdist
pytest tests/ -n auto

# Skip slow tests
pytest tests/ -m "not slow"
```

## Test Markers

Mark tests with decorators:

```python
@pytest.mark.slow
def test_slow_operation():
    """This test takes a long time."""
    pass

@pytest.mark.integration
def test_full_pipeline():
    """Integration test."""
    pass
```

Run specific markers:

```bash
# Run only fast tests
pytest -m "not slow"

# Run only integration tests
pytest -m integration
```

## Performance Targets

| Component | Target | Current |
|-----------|--------|---------|
| Coordinate transform | < 100 µs | ✅ |
| Kalman update | < 100 µs | ✅ |
| Selector (10 tracks) | < 200 µs | ✅ |
| Control loop iteration | < 200 µs | ✅ |
| Full frame (no YOLO) | < 500 µs | ✅ |

Run benchmarks to verify:

```bash
pytest tests/benchmarks/ -v --benchmark-only
```

## Next Steps

1. ✅ Run test suite: `./run_tests.sh`
2. ✅ Check coverage: Open `htmlcov/index.html`
3. ✅ Install pre-commit: `pre-commit install`
4. ⏳ Add more tests for uncovered code
5. ⏳ Set up CI/CD on GitHub

---

**Last Updated:** 2026-02-15
