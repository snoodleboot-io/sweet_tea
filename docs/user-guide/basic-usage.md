# Basic Usage

This guide covers the fundamental patterns for using the Sweet Tea Factory System.

## Three Factory Patterns

The Sweet Tea Factory System provides three distinct factory patterns:

### 1. Class-Based Factory (Factory)

Creates new instances each time with optional configuration:

```python
from sweet_tea import Registry, Factory

class DatabaseConnection:
    def __init__(self, host="localhost", port=5432):
        self.host = host
        self.port = port

    def connect(self):
        return f"Connected to {self.host}:{self.port}"

# Register the class
Registry.register("database", DatabaseConnection)

# Create new instances with different configurations
db1 = Factory.create("database", configuration={"host": "server1"})
db2 = Factory.create("database", configuration={"host": "server2"})
# db1 ≠ db2 (different instances)
```

### 2. Instance-Based Singleton Factory (SingletonFactory)

Creates and caches singleton instances on-demand:

```python
from sweet_tea import Registry, SingletonFactory

# Register the class in the registry
Registry.register("database", DatabaseConnection)

# Create singleton instances (lazy initialization)
db1 = SingletonFactory.create("database", configuration={"host": "prod-db", "pool_size": 10})
db2 = SingletonFactory.create("database")
# db1 === db2 (same cached instance)

# Alternative: Pre-register an instance
db_connection = DatabaseConnection(host="prod-db", pool_size=10)
SingletonFactory.register("database", db_connection)
db3 = SingletonFactory.get("database")  # Retrieve pre-registered instance
```

### 3. Type-Safe Abstract Factory (AbstractFactory)

Creates instances with compile-time type constraints:

```python
from sweet_tea import AbstractFactory
from typing import Protocol

class DatabaseProtocol(Protocol):
    def connect(self) -> str: ...

# Only classes implementing DatabaseProtocol can be created
db_factory = AbstractFactory[DatabaseProtocol]
db = db_factory.create("postgres")
```

## Library and Label Filtering

You can organize classes by library and label for better organization:

```python
# Register with library and label
Registry.register("mysql", MySQLConnection, library="database", label="production")
Registry.register("postgres", PostgreSQLConnection, library="database", label="production")
Registry.register("sqlite", SQLiteConnection, library="database", label="testing")

# Create with filters
mysql_db = Factory.create("mysql", library="database", label="production")
```

## Abstract Factories

For type-safe factory patterns, use AbstractFactory:

```python
from sweet_tea import AbstractFactory
from typing import Protocol

class DatabaseProtocol(Protocol):
    def connect(self) -> str: ...

# Create a type-constrained factory
db_factory = AbstractFactory[DatabaseProtocol]

# Only classes implementing DatabaseProtocol can be created
db = db_factory.create("postgres")
```

## Key Variations

The factory system supports flexible key matching:

```python
# All of these will work for a class registered as "my_service"
Factory.create("my_service")    # exact match
Factory.create("MyService")     # CamelCase
Factory.create("myService")     # camelCase
Factory.create("my_service")    # snake_case (if registered differently)
```

## Configuration Patterns

Pass configuration through the `configuration` parameter:

```python
class Service:
    def __init__(self, api_key: str, timeout: int = 30):
        self.api_key = api_key
        self.timeout = timeout

# Configuration as keyword arguments
service = Factory.create("service", configuration={
    "api_key": "secret-key",
    "timeout": 60
})
```

### Pydantic Models as Configuration

`configuration` also accepts a pydantic `BaseModel`. Its fields are spread into the
constructor exactly like a dict, so the registered class keeps an ordinary
keyword-argument `__init__`:

```python
from pydantic import BaseModel

class ServiceSettings(BaseModel):
    api_key: str
    timeout: int = 30

service = Factory.create("service", configuration=ServiceSettings(api_key="secret-key"))
```

This works with `Factory`, `AbstractFactory[T]`, and `SingletonFactory`.

- **Conversion is shallow.** The model is converted with `dict(model)`, not
  `model_dump()`, so nested models and other objects reach your class as themselves
  rather than as plain dicts.
- **Every field is sent, defaults included.** A default on the model overrides the
  default on your class's `__init__`.
- **Extras are included.** Fields accepted through `extra="allow"` are passed along
  with declared ones.
- **Field names, not aliases.** Keyword arguments use the model's field names.

### Declaring a Configuration Model

A class can declare the pydantic model its configuration must satisfy by setting
`__configuration__`. The factory validates the configuration against it before
constructing the class, so bad input fails at the factory boundary instead of deep
inside `__init__`:

```python
from pydantic import BaseModel

class PgSettings(BaseModel):
    host: str
    port: int = 5432

class PgConnection:
    __configuration__ = PgSettings

    def __init__(self, host: str, port: int):
        self.host = host
        self.port = port

conn = Factory.create("pg_connection", configuration={"host": "db", "port": "6543"})
conn.port  # 6543 -- coerced to int

Factory.create("pg_connection", configuration={"port": 1})
# SweetTeaError: Invalid configuration for key pgconnection (PgSettings): 1 validation error for PgSettings
# host
#   Field required [type=missing, input_value={'port': 1}, input_type=dict]
```

It works with explicit registration and with `fill_registry`, and applies to `Factory`,
`AbstractFactory[T]`, and `SingletonFactory`. Classes without `__configuration__` are not
validated.

- **Everything is validated, even no configuration.** A dict, `None`, or a different
  model is validated into the declared model, so required fields are enforced and
  defaults applied. An instance of the declared model is used as is.
- **Errors are `SweetTeaError`.** The message names the key and the failing fields; the
  original `ValidationError` is available as `__cause__`.
- **Unknown keys are ignored by default.** This is pydantic's default. Set
  `model_config = ConfigDict(extra="forbid")` on the model to reject typos.
- **The declaration is inherited.** Subclasses use their parent's model unless they set
  their own.
