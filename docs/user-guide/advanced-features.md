# Advanced Features

This guide covers advanced features and patterns for the Sweet Tea Factory System.

## Auto-Registration

Enable automatic class discovery and registration:

```python
# In your package's __init__.py
from sweet_tea.registry import Registry

# Automatically register all classes in this package
Registry.fill_registry()

# Classes are now available by their lowercase names
instance = Factory.create("my_class")  # Creates MyClass instance
```

## Thread Safety

All registry operations are thread-safe:

```python
import threading
from sweet_tea import Registry, SingletonFactory

def worker(thread_id):
    # Safe concurrent registration and singleton creation
    Registry.register(f"service_{thread_id}", MyService)
    instance = SingletonFactory.create(f"service_{thread_id}")

threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
for t in threads: t.start()
for t in threads: t.join()
```

## Singleton Management

The SingletonFactory provides comprehensive singleton lifecycle management:

```python
from sweet_tea import Registry, SingletonFactory

# Register classes
Registry.register("cache", RedisCache)
Registry.register("database", PostgreSQLConnection)

# Create singletons on-demand
cache = SingletonFactory.create("cache", configuration={"ttl": 3600})
db = SingletonFactory.create("database", configuration={"host": "localhost"})

# Inspect current singletons
singletons = SingletonFactory.list_singletons()  # ['cache', 'database']
available = SingletonFactory.list_keys()         # All registry keys

# Remove specific singleton
old_cache = SingletonFactory.pop("cache")        # Returns and removes instance

# Clear all singletons
SingletonFactory.clear()                         # Remove all cached instances
```

## Optional Dependencies

The system gracefully handles missing optional dependencies:

```python
# If a module has optional imports, it will warn but continue
# sweet_tea/registry.py will issue SweetTeaWarning for missing dependencies
# but registration continues for available classes
```

## Custom Error Handling

Handle factory errors appropriately:

```python
from sweet_tea import Factory, SweetTeaError

try:
    instance = Factory.create("nonexistent_key")
except SweetTeaError as e:
    print(f"Factory error: {e}")
```

## Type-Safe Abstract Factories

Use Protocol-based abstract factories for maximum type safety:

```python
from typing import Protocol
from sweet_tea import AbstractFactory

class LoggerProtocol(Protocol):
    def log(self, message: str) -> None: ...
    def set_level(self, level: str) -> None: ...

# Only classes implementing LoggerProtocol can be created
logger_factory = AbstractFactory[LoggerProtocol]

# Type checker will ensure compliance
logger = logger_factory.create("console_logger")
logger.log("Hello, World!")  # Type-safe!
```

## Performance Considerations

- Registry lookups are cached for performance
- Typed entries maintain separate caches per type
- Thread-safe operations use efficient RLock

## Integration Patterns

### Dependency Injection

```python
class Application:
    def __init__(self, db_factory, cache_factory):
        self.db = db_factory.create("postgres")
        self.cache = cache_factory.create("redis")

# Create specialized factories
db_factory = AbstractFactory[DatabaseInterface]
cache_factory = AbstractFactory[CacheInterface]

app = Application(db_factory, cache_factory)
```
