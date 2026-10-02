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

## Lazy Construction with Inverter Factory

The InverterFactory provides class definitions instead of instances, giving you complete control over instantiation:

```python
from sweet_tea import Registry, InverterFactory

# Register a class
Registry.register("expensive_service", ExpensiveService)

# Get the class definition (no instantiation yet)
service_class = InverterFactory.create("expensive_service")

# Instantiate when ready, with custom parameters
service1 = service_class(config="production", timeout=30)
service2 = service_class(config="testing", timeout=5)

# Perfect for:
# - Expensive object creation
# - Dependency injection frameworks
# - Metaprogramming scenarios
# - When instantiation parameters aren't known at factory call time
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

## Lazy Registration

`fill_registry` imports every module in the tree to find the classes in it. With
`lazy=True` it reads the names out of the source instead, and imports a module only
when a factory first needs a class from it:

```python
Registry.fill_registry(lazy=True)

Factory.create("database_connection")   # imports just that module
```

Measured on a 880-module package: filling drops from 1,165 ms, 46 MB and 1,600 imported
modules to 552 ms, 4.3 MB and none. The saving is whatever you never ask for — and it
persists for the life of the process, unlike the one-off startup cost.

### What it costs

Creation is not faster. The import still happens, just later and only if needed, so the
first `create()` for a module pays what the fill used to. For a package of small
pure-Python modules with warm `.pyc` files, parsing can even cost *more* than importing
would have; the win there is memory and unexecuted code, not wall clock.

### Names it cannot see

Registration keys off the module attribute a class is bound to, so ordinary classes,
aliases, `type()` calls, `namedtuple`, `Enum` and `create_model` results are all found
by reading the source. Classes injected at runtime — `globals()[name] = type(...)`,
`setattr(module, ...)` — leave no trace to read. Asking for one of those triggers a
fallback sweep that imports everything still pending and warns:

```
SweetTeaWarning: Importing 43 remaining module(s) to look for loopa: no lazily
registered name matched. Add the defining module to fill_registry(eager=[...]).
```

Name those modules up front and the sweep never happens:

```python
Registry.fill_registry(lazy=True, eager=["myapp.plugins.*"])
```

`eager` patterns match the same way `exclude` patterns do, and `exclude` still wins.
Passing `eager` without `lazy` is an error rather than a no-op.

Use `lazy="strict"` to refuse the sweep outright — a name no scan could see then raises,
naming the `eager` pattern that would fix it, instead of quietly importing the tree.

### Accuracy

Once a module is imported, its entries are rebuilt by the same discovery an eager fill
uses, so a resolved module matches eager registration exactly. Before that, the view is
approximate in both directions: a class replaced by a decorator, a `TYPE_CHECKING`-only
class, or a class behind an uninstalled dependency may appear in `list_keys()` and
vanish on resolution, and runtime-injected names are missing until something asks. Call
`Registry.resolve_all()` when you need an exact registry — it imports everything, which
is by definition eager.

### Reading the registry directly

`Registry.entries()` returns unresolved entries too, and reading `entry.class_def` on
one imports its module and hands back the class — so code that introspects the registry
keeps working:

```python
# resolves only the entries this filter actually selected
matches = [
    entry.class_def
    for entry in Registry.entries()
    if entry.key == name and entry.library == "mylib"
]
```

Because the filter runs first, only the matching entries' modules are imported. A loop
that touches `class_def` on *every* entry is effectively an eager fill.

Two things to know:

- **Reading an attribute can now raise.** A module that fails to import, or a name the
  scanner guessed at that turns out not to be a class, raises `SweetTeaError` on access.
- **`entry.is_lazy` does not resolve.** Use it to check whether a read would import
  anything. `entry.class_object` exposes the stored class without resolving, for code
  that wants to see unresolved entries as unresolved.

`Registry.resolve_all()` still materialises everything at once when that is what you
want.

### Adopting it

Lazy filling assumes nothing needs the registry to be complete *while modules are still
importing*. A package that resolves classes through the registry at import time — in a
module body, or in a function a module body calls — will fail under `lazy=True`, because
the entries it wants have not been resolved yet. Put such modules in `eager=[...]`, or
defer their lookups to first use.
