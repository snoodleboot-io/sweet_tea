# Sweet Tea Factory System

[![CI](https://github.com/snoodleboot-io/sweet_tea/actions/workflows/ci.yml/badge.svg)](https://github.com/snoodleboot-io/sweet_tea/actions/workflows/ci.yml)
[![PyPI version](https://badge.fury.io/py/sweet-tea.svg)](https://pypi.org/project/sweet-tea/)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![codecov](https://codecov.io/gh/snoodleboot-io/sweet_tea/branch/main/graph/badge.svg)](https://codecov.io/gh/snoodleboot-io/sweet_tea)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](https://github.com/snoodleboot-io/sweet_tea/blob/main/LICENSE)

A comprehensive, production-ready Python factory pattern implementation with advanced features for building extensible applications.

## 🚀 Features

- **Dual Factory Patterns**: Class-based factories (new instances) AND instance-based singletons (shared instances)
- **Thread-Safe Registry**: Concurrent operations with RLock synchronization
- **Type-Safe Generics**: Full TypeVar support with `__class_getitem__`
- **Flexible Key Matching**: Support for ClassName, class_name, classname variations
- **Optional Dependencies**: Graceful handling with custom warnings
- **Auto-Registration**: Classes automatically registered via package imports
- **Comprehensive Testing**: 58 tests with 97% coverage
- **Rich Documentation**: MkDocs with Dracula theme and API reference

## 📦 Installation

### Using uv (Recommended)

```bash
uv add sweet-tea
```

### Using pip

```bash
pip install sweet-tea
```

### Using Poetry

```bash
poetry add sweet-tea
```

## 🏁 Quick Start

```python
from sweet_tea import Registry, Factory, AbstractFactory, SingletonFactory

# === CLASS-BASED FACTORY (Creates new instances each time) ===
Registry.register("database", DatabaseConnection)
db1 = Factory.create("database", configuration={"host": "server1"})
db2 = Factory.create("database", configuration={"host": "server2"})
# db1 ≠ db2 (different instances)

# === INSTANCE-BASED SINGLETON FACTORY (Reuses same instance) ===
db_connection = DatabaseConnection(host="prod-db", pool_size=10)
SingletonFactory.register("database", db_connection)
db3 = SingletonFactory.get("database")
db4 = SingletonFactory.get("database")
# db3 === db4 (same instance)

# === TYPE-SAFE ABSTRACT FACTORIES ===
class DatabaseInterface:
    def connect(self) -> str: ...

db_factory = AbstractFactory[DatabaseInterface]
db = db_factory.create("postgres")  # Only classes implementing DatabaseInterface
```

### Three Factory Patterns

1. **Factory** - Class registration → New instances with configuration
2. **AbstractFactory** - Type-constrained → New instances with type safety
3. **SingletonFactory** - Instance registration → Shared singleton instances

## 📖 Documentation

Complete documentation is available at [https://snoodleboot-io.github.io/sweet_tea/](https://snoodleboot-io.github.io/sweet_tea/)

### User Guides
- [Getting Started](https://snoodleboot-io.github.io/sweet_tea/user-guide/getting-started/) - Installation and setup
- [Basic Usage](https://snoodleboot-io.github.io/sweet_tea/user-guide/basic-usage/) - Core factory patterns
- [Advanced Features](https://snoodleboot-io.github.io/sweet_tea/user-guide/advanced-features/) - Type constraints and threading

### API Reference
- [Registry](https://snoodleboot-io.github.io/sweet_tea/api/registry/) - Global class registry
- [Factory](https://snoodleboot-io.github.io/sweet_tea/api/factory/) - Basic factory implementation
- [AbstractFactory](https://snoodleboot-io.github.io/sweet_tea/api/abstract-factory/) - Generic type-constrained factories

### Development
- [Contributing](https://snoodleboot-io.github.io/sweet_tea/development/contributing/) - Development setup and guidelines
- [Testing](https://snoodleboot-io.github.io/sweet_tea/development/testing/) - Testing strategy and coverage

## 🔧 Development

### Prerequisites

- Python 3.12 or higher
- uv package manager (recommended)

### Setup

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

# Build documentation locally
uv run mkdocs serve
```

### Code Quality

This project uses several tools to maintain code quality:

- **Black**: Code formatting
- **isort**: Import sorting (compatible with Black)
- **Ruff**: Fast linting and additional formatting
- **Bandit**: Security scanning
- **MyPy**: Type checking

All tools run automatically via pre-commit hooks on git commit.

## 🤝 Contributing

We welcome contributions! Please see our [contributing guide](https://snoodleboot-io.github.io/sweet_tea/development/contributing/) for details.

### Development Workflow

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Run tests and ensure they pass
5. Update documentation if needed
6. Submit a pull request

## 📄 License

Copyright © 2025 snoodleboot, LLC. Licensed under the Apache License 2.0.

See [LICENSE](LICENSE) for the full license text.

## 🙏 Acknowledgments

- Built with [Pydantic](https://pydantic-docs.helpmanual.io/) for data validation
- Documentation powered by [MkDocs](https://www.mkdocs.org/) with [Material theme](https://squidfunk.github.io/mkdocs-material/)
- Testing framework: [pytest](https://pytest.org/) with [coverage](https://coverage.readthedocs.io/)
- Code quality: [Black](https://black.readthedocs.io/), [Ruff](https://ruff.rs/), [MyPy](https://mypy-lang.org/)

---

**Sweet Tea Factory System** - Production-ready factory patterns for Python applications.
