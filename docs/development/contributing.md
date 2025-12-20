# Contributing

Thank you for your interest in contributing to the Sweet Tea Factory System!

## Development Setup

```bash
# Clone the repository
git clone https://github.com/snoodleboot-io/sweet_tea.git
cd sweet_tea

# Install development dependencies
uv sync

# Install pre-commit hooks
uv run pre-commit install

# Run tests
uv run pytest
```

## Code Quality

This project uses several tools to maintain code quality:

- **Black**: Code formatting
- **isort**: Import sorting
- **Ruff**: Fast linting
- **MyPy**: Type checking
- **Bandit**: Security scanning

All tools run automatically via pre-commit hooks on git commit.

## Testing

- Write comprehensive tests for new features
- Maintain 97%+ code coverage
- Test thread safety for concurrent operations
- Test error conditions and edge cases

```bash
# Run all tests with coverage
uv run pytest --cov=sweet_tea --cov-report=term-missing

# Run specific test file
uv run pytest tests/test_factory.py
```

## Documentation

- Update documentation for new features
- Use MkDocs with Material theme for consistency
- Include code examples and type hints

```bash
# Build documentation locally
uv run mkdocs build

# Serve documentation locally
uv run mkdocs serve
```

## Pull Request Process

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Run tests and ensure they pass
5. Update documentation if needed
6. Submit a pull request

## Code Style

- Follow PEP 8 conventions
- Use type hints throughout
- Write descriptive docstrings
- Keep functions focused and testable

## Reporting Issues

- Use GitHub issues for bug reports and feature requests
- Include reproduction steps and expected behavior
- Add code examples when possible
