# Getting Started

Welcome to the Sweet Tea Factory System! This guide will help you get up and running quickly.

## Prerequisites

- Python 3.12 or higher
- uv package manager (recommended)

## Installation

### Using uv (Recommended)

```bash
# Clone the repository
git clone https://github.com/snoodleboot-io/sweet_tea.git
cd sweet_tea

# Install dependencies
uv sync

# Run tests to verify installation
uv run pytest
```

### Using pip

```bash
# Install from PyPI
pip install sweet-tea

# Or for development
git clone https://github.com/snoodleboot-io/sweet_tea.git
cd sweet_tea
pip install -e .
```

### Using Hatchling

```bash
# Clone the repository
git clone https://github.com/snoodleboot-io/sweet_tea.git
cd sweet_tea

# Build with Hatchling
python -m build

# Install the built package
pip install dist/sweet_tea-0.1.2.tar.gz
```

### Using Poetry

```bash
# Clone the repository
git clone https://github.com/snoodleboot-io/sweet_tea.git
cd sweet_tea

# Install with Poetry
poetry install

# Run tests
poetry run pytest
```

## Basic Concepts

The Sweet Tea Factory System provides three main components:

1. **Registry**: Global storage for class registrations
2. **Factory**: Basic factory for creating instances
3. **AbstractFactory**: Type-safe factory with generic constraints

## Hello World Example

```python
from sweet_tea import Registry, Factory

# Define a simple class
class HelloWorld:
    def __init__(self, message="Hello, World!"):
        self.message = message

    def greet(self):
        return self.message

# Register the class
Registry.register("hello", HelloWorld)

# Create an instance
greeter = Factory.create("hello", configuration={"message": "Hi there!"})
print(greeter.greet())  # Output: Hi there!
```

## Auto-Registration

For larger projects, you can enable automatic class registration:

```python
# In your package's __init__.py
from sweet_tea.registry import Registry

# This will scan and register all classes in the package
Registry.fill_registry()

# Now you can create instances of any class in the package
instance = Factory.create("my_class_name")
```

## Next Steps

- Learn about [basic usage patterns](../user-guide/basic-usage.md)
- Explore [advanced features](../user-guide/advanced-features.md)
- Check the [API reference](../api/registry.md)
