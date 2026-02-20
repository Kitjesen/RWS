# Contributing to RWS Tracking System

Thank you for your interest in contributing to RWS! This document provides guidelines for contributing to the project.

## 🚀 Getting Started

### Development Setup

1. **Fork and Clone**
   ```bash
   git clone https://github.com/Kitjesen/RWS.git
   cd RWS
   ```

2. **Create Virtual Environment**
   ```bash
   python -m venv rws
   source rws/bin/activate  # On Windows: rws\Scripts\activate
   ```

3. **Install Dependencies**
   ```bash
   pip install -r requirements.txt
   pip install -e ".[dev]"
   ```

4. **Install Pre-commit Hooks**
   ```bash
   pre-commit install
   ```

## 📝 Code Style

### Python Style Guide

- Follow **PEP 8** style guide
- Use **type hints** for all function signatures
- Maximum line length: **100 characters**
- Use **docstrings** for all public functions and classes

### Code Formatting

We use **Ruff** for linting and formatting:

```bash
# Format code
ruff format .

# Check linting
ruff check .

# Fix auto-fixable issues
ruff check --fix .
```

### Type Checking

We use **mypy** for static type checking:

```bash
mypy src/rws_tracking
```

## 🧪 Testing

### Running Tests

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=rws_tracking --cov-report=html

# Run specific test file
pytest tests/test_algebra.py

# Run benchmarks
pytest tests/benchmarks/ --benchmark-only
```

### Writing Tests

- Place tests in `tests/` directory
- Name test files as `test_*.py`
- Use descriptive test names: `test_<function>_<scenario>_<expected_result>`
- Aim for >80% code coverage for new code

Example:
```python
def test_kalman_filter_predicts_position_correctly():
    """Test that Kalman filter predicts position with constant velocity."""
    kf = Kalman2D(dt=0.1)
    kf.update(np.array([0.0, 0.0]))
    kf.predict()
    state = kf.get_state()
    assert state[0] == pytest.approx(0.0, abs=0.1)
```

## 🔀 Git Workflow

### Branch Naming

- `feature/description` - New features
- `fix/description` - Bug fixes
- `docs/description` - Documentation updates
- `refactor/description` - Code refactoring
- `test/description` - Test additions/updates

### Commit Messages

Follow [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<scope>): <subject>

<body>

<footer>
```

Types:
- `feat`: New feature
- `fix`: Bug fix
- `docs`: Documentation changes
- `style`: Code style changes (formatting, etc.)
- `refactor`: Code refactoring
- `test`: Test additions/updates
- `chore`: Build process or auxiliary tool changes

Examples:
```
feat(api): add gRPC streaming support

Add StreamStatus method to gRPC API for real-time status updates.

Closes #123
```

```
fix(control): correct PID integral windup

Limit integral term to prevent windup during saturation.
```

### Pull Request Process

1. **Create a Branch**
   ```bash
   git checkout -b feature/your-feature-name
   ```

2. **Make Changes**
   - Write code
   - Add tests
   - Update documentation

3. **Commit Changes**
   ```bash
   git add .
   git commit -m "feat: add new feature"
   ```

4. **Push to Fork**
   ```bash
   git push origin feature/your-feature-name
   ```

5. **Create Pull Request**
   - Go to GitHub and create a PR
   - Fill in the PR template
   - Link related issues

6. **Code Review**
   - Address review comments
   - Update PR as needed

7. **Merge**
   - Squash and merge when approved

## 📚 Documentation

### Docstring Format

Use **NumPy-style** docstrings:

```python
def function_name(param1: int, param2: str) -> bool:
    """
    Brief description of function.

    Longer description if needed.

    Parameters
    ----------
    param1 : int
        Description of param1
    param2 : str
        Description of param2

    Returns
    -------
    bool
        Description of return value

    Examples
    --------
    >>> function_name(1, "test")
    True
    """
    pass
```

### Documentation Updates

- Update relevant `.md` files in `docs/`
- Keep README.md in sync with major changes
- Add examples for new features
- Update API documentation for API changes

## 🐛 Reporting Bugs

### Before Submitting

1. Check existing issues
2. Try latest version
3. Collect debug information

### Bug Report Template

```markdown
**Describe the bug**
A clear description of what the bug is.

**To Reproduce**
Steps to reproduce:
1. ...
2. ...

**Expected behavior**
What you expected to happen.

**Actual behavior**
What actually happened.

**Environment**
- OS: [e.g., Ubuntu 22.04]
- Python version: [e.g., 3.11]
- RWS version: [e.g., 1.2.0]

**Additional context**
Any other relevant information.
```

## 💡 Feature Requests

### Feature Request Template

```markdown
**Is your feature request related to a problem?**
A clear description of the problem.

**Describe the solution you'd like**
A clear description of what you want to happen.

**Describe alternatives you've considered**
Alternative solutions or features you've considered.

**Additional context**
Any other context or screenshots.
```

## 🏗️ Architecture Guidelines

### Module Organization

- Keep modules focused and cohesive
- Use clear interfaces between modules
- Avoid circular dependencies
- Follow existing project structure

### Adding New Features

1. **Design First**
   - Discuss in an issue first
   - Consider impact on existing code
   - Plan API changes carefully

2. **Implementation**
   - Follow existing patterns
   - Add comprehensive tests
   - Update documentation

3. **Review**
   - Self-review before submitting
   - Address CI failures
   - Respond to feedback promptly

## 📋 Checklist

Before submitting a PR, ensure:

- [ ] Code follows style guidelines
- [ ] All tests pass
- [ ] New tests added for new features
- [ ] Documentation updated
- [ ] Commit messages follow conventions
- [ ] No merge conflicts
- [ ] CI checks pass

## 🤝 Code of Conduct

### Our Standards

- Be respectful and inclusive
- Welcome newcomers
- Accept constructive criticism
- Focus on what's best for the project

### Unacceptable Behavior

- Harassment or discrimination
- Trolling or insulting comments
- Personal or political attacks
- Publishing others' private information

## 📞 Getting Help

- **Questions**: Open a [Discussion](https://github.com/Kitjesen/RWS/discussions)
- **Bugs**: Open an [Issue](https://github.com/Kitjesen/RWS/issues)
- **Chat**: Join our community (if available)

## 📜 License

By contributing, you agree that your contributions will be licensed under the MIT License.

---

Thank you for contributing to RWS! 🎉
