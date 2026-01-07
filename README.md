# Sweet Tea Factory System

[![CI](https://github.com/snoodleboot-io/sweet_tea/actions/workflows/ci.yml/badge.svg)](https://github.com/snoodleboot-io/sweet_tea/actions/workflows/ci.yml)
[![PyPI version](https://badge.fury.io/py/sweet-tea.svg)](https://pypi.org/project/sweet-tea/)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![codecov](https://codecov.io/github/snoodleboot-io/sweet_tea/coverage.svg?branch=main)](https://codecov.io/gh/snoodleboot-io/sweet_tea)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](https://github.com/snoodleboot-io/sweet_tea/blob/main/LICENSE)

A comprehensive, production-ready Python dependency injection framework using factory patterns with configuration-based object management and lifecycle control.

## 🚀 Features

- **Configuration-Based Dependency Injection**: Register classes once, create instances with runtime configuration
- **Dual Factory Patterns**: Class-based factories (new instances) AND instance-based singletons (shared instances)
- **Thread-Safe Registry**: Concurrent operations with RLock synchronization
- **Type-Safe Generics**: Full TypeVar support with `__class_getitem__`
- **Flexible Key Matching**: Support for ClassName, class_name, classname variations
- **Optional Dependencies**: Graceful handling with custom warnings
- **Auto-Registration**: Classes automatically registered via package imports
- **Lazy Singletons**: SingletonFactory.create() for on-demand singleton instantiation
- **Comprehensive Testing**: 58 tests with 97% coverage
- **Rich Documentation**: MkDocs with Dracula theme and API reference

## 🏗️ Dependency Injection

Sweet Tea provides a powerful configuration-based dependency injection system that separates object creation from usage:

### Service Registration
```python
# Register services once at application startup
Registry.register("database", PostgreSQLConnection)
Registry.register("cache", RedisCache)
Registry.register("email", SMTPEmailService)
```

### Constructor Injection with Configuration Dictionaries
```python
# Inject configuration dictionaries that define dependencies
class UserService:
    def __init__(self, db_config, cache_config):
        # Store configuration dictionaries
        self.db_config = db_config
        self.cache_config = cache_config

        # Create factory instances immediately or lazily
        self.db = Factory.create(
            db_config["class_name"],
            configuration=db_config["configuration"]
        )
        self.cache = SingletonFactory.create(
            cache_config["class_name"],
            configuration=cache_config["configuration"]
        )

# Usage with configuration dictionaries
db_config = {
    "class_name": "database",
    "configuration": {"host": "prod-db", "port": 5432}
}

cache_config = {
    "class_name": "cache",
    "configuration": {"host": "redis", "ttl": 3600}
}

user_service = UserService(db_config, cache_config)
```

### Constructor Injection with Factories
```python
# Inject factories into constructors for on-demand dependency creation
class UserService:
    def __init__(self, db_factory, cache_factory):
        self.db_factory = db_factory  # Store factory reference
        self.cache_factory = cache_factory

    def get_user(self, user_id):
        # Create database connection when needed
        db = self.db_factory.create("database", configuration={
            "host": "prod-db",
            "port": 5432,
            "credentials": {...}
        })

        # Create cache when needed
        cache = self.cache_factory.create("cache", configuration={
            "host": "redis-cluster",
            "ttl": 3600
        })

        # Use dependencies...
        user_data = db.query(f"SELECT * FROM users WHERE id = {user_id}")
        cached_user = cache.get(f"user:{user_id}")
        return user_data or cached_user
```

### Direct Dependency Injection
```python
# Traditional approach: inject pre-configured instances
class UserService:
    def __init__(self, database, cache):
        self.database = database  # Pre-configured instance
        self.cache = cache        # Pre-configured instance
```

### Lifecycle Management
```python
# Singletons for shared resources
auth_service = SingletonFactory.create("auth", configuration={"jwt_secret": "..."})
# Same instance returned on subsequent calls

# New instances for request-scoped objects
request_handler = Factory.create("request_handler", configuration={"user_id": 123})
# Fresh instance for each request
```

### Benefits
- **Separation of Concerns**: Configuration separate from implementation
- **Testability**: Easy mocking and dependency substitution
- **Flexibility**: Runtime configuration changes without code changes
- **Maintainability**: Centralized dependency management
- **Type Safety**: Compile-time interface checking with AbstractFactory

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

# === LAZY SINGLETON FACTORY (Creates and caches instances on-demand) ===
Registry.register("database", DatabaseConnection)
db3 = SingletonFactory.create("database", configuration={"host": "prod-db", "pool_size": 10})
db4 = SingletonFactory.create("database")  # Returns cached instance
# db3 === db4 (same cached instance)

# === TYPE-SAFE ABSTRACT FACTORIES ===
class DatabaseInterface:
    def connect(self) -> str: ...

db_factory = AbstractFactory[DatabaseInterface]
db = db_factory.create("postgres")  # Only classes implementing DatabaseInterface
```

### Four Factory Patterns

1. **Factory** - Class registration → New instances with configuration
2. **AbstractFactory** - Type-constrained → New instances with type safety
3. **SingletonFactory** - Lazy singletons → Cached instances created on-demand
4. **InverterFactory** - Lazy construction → Class definitions for user-controlled instantiation

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

- Python 3.10 or higher
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
