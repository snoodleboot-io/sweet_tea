# Testing

This document describes the testing strategy and practices for the Sweet Tea Factory System.

## Test Structure

```
tests/
├── test_registry.py          # Registry functionality
├── test_factory.py           # Basic factory operations
├── test_abstract_factory.py  # Generic factory constraints
├── test_entry.py             # Pydantic entry model
├── test_sweet_tea_error.py   # Exception handling
└── test_sweet_tea_warning.py # Warning system
```

## Test Categories

### Unit Tests
- Test individual components in isolation
- Mock external dependencies
- Focus on business logic

### Integration Tests
- Test component interactions
- Verify end-to-end functionality
- Include `test_fill_registry_integration` for auto-registration

### Thread Safety Tests
- Concurrent registry operations
- Race condition prevention
- Lock contention scenarios

## Running Tests

```bash
# Run all tests
uv run pytest

# Run with coverage
uv run pytest --cov=sweet_tea --cov-report=term-missing

# Run specific test file
uv run pytest tests/test_factory.py

# Run specific test
uv run pytest tests/test_factory.py::TestFactory::test_create_simple
```

## Test Coverage Goals

- **Target**: 95%+ line coverage
- **Current**: 97% overall coverage
- **Exceptions**: Only error handling paths are uncovered (acceptable)

## Testing Patterns

### Registry Testing
```python
def setup_method(self):
    # Clear registry between tests
    Registry._Registry__registry.clear()
    Registry._Registry__lookup.clear()
    Registry._Registry__lookup_keys.clear()
```

### Factory Testing
```python
# Test configuration passing
instance = Factory.create("my_class", configuration={"param": "value"})
assert instance.param == "value"
```

### Error Testing
```python
# Test exception handling
with pytest.raises(SweetTeaError, match="expected message"):
    Factory.create("nonexistent")
```

## Continuous Integration

Tests run automatically via:
- Pre-commit hooks on git commit
- GitHub Actions CI/CD pipeline on every push/PR
- Local development workflow

### GitHub Actions Workflow

The CI/CD pipeline consists of four stages:

1. **Test & Lint** (Python 3.12, 3.13)
   - Install dependencies with uv
   - Run all pre-commit hooks (Black, isort, Ruff, Bandit, MyPy)
   - Execute test suite with pytest and coverage reporting
   - Upload coverage to Codecov

2. **Build & Test Package** (main branch only)
   - Build package distribution
   - Test installation in isolated environment
   - Verify basic functionality works

3. **Publish to PyPI** (releases only)
   - Build final package distribution
   - Publish to PyPI using trusted publisher workflow

### Coverage Reporting

Coverage reports are generated for every test run and uploaded to Codecov. The project maintains 97%+ test coverage across all modules.

## Test Quality Guidelines

- **Descriptive names**: `test_create_with_valid_config`
- **Single responsibility**: One assertion per test when possible
- **Independent tests**: No test should depend on others
- **Fast execution**: Keep tests under 1 second each
- **Comprehensive coverage**: Test happy paths, error cases, and edge conditions

## Adding New Tests

1. Create test file matching source module: `test_<module>.py`
2. Use `unittest.TestCase` for consistency
3. Include docstrings explaining test purpose
4. Run full test suite before committing

## Performance Testing

For performance-critical code paths:
- Use `pytest-benchmark` for micro-benchmarks
- Profile with `cProfile` for larger operations
- Test concurrent operations with threading
