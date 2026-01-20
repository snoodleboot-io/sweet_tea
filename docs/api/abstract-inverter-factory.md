# Abstract Inverter Factory API

## `sweet_tea.abstract_inverter_factory.AbstractInverterFactory`

```python
class AbstractInverterFactory(Generic[T], InverterFactory):
```

A generic inverter factory that constrains class retrieval to subclasses of type T.

This factory combines the type constraints of AbstractFactory with the class-definition-returning behavior of InverterFactory. It allows retrieval of class definitions that are subclasses of a specified generic type, enabling type-safe factory patterns for lazy construction scenarios.

**Usage:**
```python
factory = AbstractInverterFactory[MyBaseClass]
class_def = factory.create('my_key')
# Only classes inheriting from MyBaseClass will be available
instance = class_def(**kwargs)  # Instantiate when ready
```

### `create(key, library='', label='')` `classmethod`

Retrieve the class definition for a registered class that is a subclass of the generic type.

**Parameters:**

- `key` (`str`): Name to reference the class from the registry.
- `library` (`str`, default `''`): Optional library filter for the class.
- `label` (`str`, default `''`): Optional label filter for the class.

**Returns:** `Type[Any]` - The class definition that can be instantiated by the caller.

**Raises:** `SweetTeaError` - When the key is not found or filters don't match.

**Example:**
```python
from sweet_tea import AbstractInverterFactory, Registry

class Service:
    def __init__(self, config=None):
        self.config = config

class DatabaseService(Service):
    pass

Registry.register("database", DatabaseService)

# Get class definition with type constraints
factory = AbstractInverterFactory[Service]
db_class = factory.create("database")

# Instantiate later
db = db_class(config={"host": "localhost"})
```

### `_get_generic_type()` `classmethod`

Get the generic type parameter.

**Returns:** `Type[T]` - The generic type parameter.

### `__class_getitem__(item)` `classmethod`

Create a parameterized generic subclass with the specified type.

**Parameters:**

- `item` (`Type[T]`): The base class type to constrain to.

**Returns:** `Type[AbstractInverterFactory[T]]` - A parameterized factory class.

## Related Classes

- [`AbstractFactory`](abstract-factory.md) - Creates instances with type constraints
- [`InverterFactory`](inverter-factory.md) - Returns class definitions without type constraints
- [`Factory`](factory.md) - Basic factory for creating instances