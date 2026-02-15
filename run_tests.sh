#!/bin/bash
# Run all tests with coverage

set -e

echo "🧪 Running RWS Test Suite..."
echo ""

# Check if virtual environment is activated
if [ -z "$VIRTUAL_ENV" ]; then
    echo "⚠️  Warning: No virtual environment detected"
    echo "   Consider activating venv: source venv/bin/activate"
    echo ""
fi

# Install dependencies if needed
echo "📦 Checking dependencies..."
pip install -q -r requirements.txt

echo ""
echo "🔍 Running linter (ruff)..."
ruff check src/ tests/ || true

echo ""
echo "🎨 Checking code format..."
ruff format --check src/ tests/ || true

echo ""
echo "🔎 Running type checker (mypy)..."
mypy src/rws_tracking --ignore-missing-imports || true

echo ""
echo "✅ Running unit tests..."
pytest tests/ \
    --ignore=tests/benchmarks \
    -v \
    --cov=src/rws_tracking \
    --cov-report=term-missing \
    --cov-report=html \
    --cov-report=xml

echo ""
echo "⚡ Running benchmarks..."
pytest tests/benchmarks/ -v --benchmark-only || true

echo ""
echo "📊 Coverage report generated:"
echo "   - Terminal: see above"
echo "   - HTML: htmlcov/index.html"
echo "   - XML: coverage.xml"

echo ""
echo "✨ Test suite complete!"
