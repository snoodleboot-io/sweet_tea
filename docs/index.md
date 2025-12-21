# Sweet Tea Factory System

A comprehensive, production-ready Python factory pattern implementation with advanced features for building extensible applications.

## 🚀 Features

- **Thread-Safe Registry**: Concurrent operations with RLock synchronization
- **Type-Safe Generics**: Full TypeVar support with `__class_getitem__`
- **Flexible Key Matching**: Support for ClassName, class_name, classname variations
- **Optional Dependencies**: Graceful handling with custom warnings
- **Auto-Registration**: Classes automatically registered via package imports
- **Lazy Singletons**: SingletonFactory.create() for on-demand singleton instantiation
- **Comprehensive Testing**: 58 tests with 97% coverage

## 📦 Installation

```bash
# Using uv (recommended)
uv add sweet-tea

# Using pip
pip install sweet-tea

# Using Poetry
poetry add sweet-tea
```

## 🏁 Quick Start

```python
from sweet_tea import Factory, AbstractFactory, Registry

# Register a class
Registry.register("my_service", MyServiceClass)

# Create instances
instance = Factory.create("my_service", configuration={"param": "value"})

# Use type-safe abstract factories
service_factory = AbstractFactory[BaseService]
instance = service_factory.create("implementation")
```

## 📖 Documentation

- [Getting Started](user-guide/getting-started.md) - Installation and basic setup
- [Basic Usage](user-guide/basic-usage.md) - Core factory patterns
- [Advanced Features](user-guide/advanced-features.md) - Type constraints and threading
- [API Reference](api/registry.md) - Complete API documentation

## 🤝 Contributing

We welcome contributions! See our [contributing guide](development/contributing.md) for details.

## 📄 License

Copyright © 2025 snoodleboot, LLC. Licensed under the Apache License 2.0.
