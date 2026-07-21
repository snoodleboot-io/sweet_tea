# AGENTIC_USE — sweet_tea

> A registry and factory system that instantiates classes by string key, with
> optional filtering by library, label, and base type — it does NOT provide
> dependency resolution, lifecycle management, configuration parsing, or
> scoping. It maps a key to a class and calls it with your keyword arguments.

Format: [AGENTIC_USE.md](https://github.com/snoodleboot-io/agentic_use).

---

## Mental model

Everything routes through one process-global **Registry**. An **entry** is the
unit it stores: a `key`, a `class_def`, and two optional filter fields,
`library` and `label`. Entries arrive either explicitly via `Registry.register`
or by discovery via `Registry.fill_registry`, which walks a package tree,
imports every module, and registers each class *defined in* that module.

The **key** is derived from the class name and lowercased at registration —
`class PostgresConnection` registers as `postgresconnection`. Lookup is
forgiving: `Factory.create` expands the key you pass into **variations**
(lowercase, camel-to-snake, underscores stripped) and takes the first that
matches. `library` and `label` are also lowercased when stored, and your filter
arguments are lowercased before comparison, so case never matters on either
side. What does matter is that a key must resolve to exactly **one** entry;
two matches is an error, not a preference order.

**Factories** are classmethod-only — you never instantiate one. Four exist,
along two independent axes. *Instance vs. class definition*: `Factory` returns
`class_def(**configuration)`, `InverterFactory` returns the bare class for you
to construct later. *Untyped vs. type-constrained*: `AbstractFactory[Base]` and
`AbstractInverterFactory[Base]` restrict candidates to subclasses of `Base`.
`SingletonFactory` sits outside the grid — it caches against the resolved
registry entry and returns the same instance on every call.

Subscripting a factory (`AbstractFactory[Base]`) returns a genuine cached
subclass, not a `typing` alias, and `AbstractFactory[Base] is
AbstractFactory[Base]` holds. Registration, parameterization, and singleton
caching are each lock-guarded and safe to call from multiple threads.

---

## Source map

```
sweet_tea/
├── registry.py                    ← Registry: register(), fill_registry(), entries(), typed_entries()
├── factory.py                     ← Factory: key → configured instance
├── inverter_factory.py            ← InverterFactory: key → class definition, you construct it
├── abstract_factory.py            ← AbstractFactory[T]: instance, constrained to subclasses of T
├── abstract_inverter_factory.py   ← AbstractInverterFactory[T]: class definition, constrained to T
├── singleton_factory.py           ← SingletonFactory: cached instance per key; clear(), pop(), list_singletons()
├── entry.py                       ← Entry: pydantic model of one registration
├── sweet_tea_error.py             ← SweetTeaError: every failure below raises this
├── base_factory.py                ← internal: key-variation matching shared by the factories
└── type_parameterized_factory.py  ← internal: makes SomeFactory[T] a real subclass
```

`sweet_tea/__init__.py` is empty. Import from the submodule, always.

---

## Canonical pattern

```python
from sweet_tea.registry import Registry
from sweet_tea.factory import Factory

class PostgresConnection:
    def __init__(self, host: str = "localhost", port: int = 5432) -> None:
        self.host = host
        self.port = port

Registry.register(
    key=PostgresConnection.__name__,   # stored lowercased: "postgresconnection"
    class_def=PostgresConnection,
    library="db",
)

connection = Factory.create(
    key="PostgresConnection",          # any spelling variation resolves
    library="db",
    configuration={"host": "prod.example.com"},
)
print(connection.host, connection.port)
# prod.example.com 5432
```

To discover classes across a package instead of registering them one by one:

```python
# In a module file — not a REPL; see the constraint on caller inference below.
from sweet_tea.registry import Registry

Registry.fill_registry(library="db", exclude=["*.tests"])
# Walks the calling module's directory, imports every module, registers each
# class defined in it. Regular and PEP 420 namespace packages are both traversed.
```

---

## Extension points

### Registrable class

**Contract:** any class may be registered. It is constructed as
`class_def(**configuration)`, so every field you intend to pass through
`configuration` must be accepted as a **keyword argument**. A class taking only
positional-only parameters cannot be built by `Factory`; register it with
`InverterFactory` instead and construct it yourself.

**Must not:** rely on the constructor being called with no arguments when
`configuration` is omitted — it is called as `class_def()`, so any parameter
without a default raises `TypeError` from your own `__init__`, not from
sweet_tea. The traceback points at your class, which makes this easy to
misread as a registry failure.

```python
class CacheClient:
    def __init__(self, url: str = "redis://localhost", timeout: int = 5) -> None:
        self.url = url
        self.timeout = timeout
# Factory.create(key="CacheClient", configuration={"timeout": 30}) -> CacheClient
```

### Type-constrained factory

**Contract:** subscript with the base class the results must inherit from:
`AbstractFactory[Animal]`. Candidates are filtered by `issubclass` before the
key is matched. The base class itself need not be registered.

**Must not:** call `create` on the unsubscripted factory. Raises
`SweetTeaError: AbstractFactory is not parameterized. Subscript it with a base
type before use, e.g. AbstractFactory[MyBaseClass].create('my_key').`

```python
from sweet_tea.registry import Registry
from sweet_tea.abstract_factory import AbstractFactory

class Animal: pass
class Dog(Animal):
    def __init__(self, name: str = "rex") -> None:
        self.name = name

Registry.register(key="Dog", class_def=Dog, library="pets")
print(AbstractFactory[Animal].create(key="Dog").name)
# rex
```

---

## Anti-patterns

### Importing from the package root

**Looks right because:** every other library re-exports its public API, and
`from sweet_tea import Factory` is what an editor's autocomplete suggests.
**Wrong because:** `sweet_tea/__init__.py` contains a licence header and
nothing else. No name is re-exported, so this fails at import time with
`ImportError: cannot import name 'Factory' from 'sweet_tea'`.
**Do instead:** import from the submodule — `from sweet_tea.factory import
Factory`, `from sweet_tea.registry import Registry`.

### Reading "key not present" as "the class was never registered"

**Looks right because:** the message is unambiguous —
`SweetTeaError: The key Robot not present.`
**Wrong because:** a type-constrained factory filters by `issubclass` *before*
matching the key, so a registered class that fails the type constraint is
reported identically to one that was never registered at all. `Robot` is in the
registry; `AbstractFactory[Animal]` simply cannot see it. Chasing this as a
registration or discovery bug is the natural next move and it leads nowhere.
**Do instead:** check `Registry.entries()` for the key first. If it is present,
the type parameter is the problem, not registration.

### Trusting a lookup that returned an instance

**Looks right because:** `create` either raises `SweetTeaError` or hands back an
object, so a returned object reads as proof the right class was found.
**Wrong because:** key variations are expanded from the key *you pass*, and the
first variation that matches anything wins. Asking for `"TestClass"` expands to
`["testclass", "test_class", "test"]`; if only a class named `Test` is
registered, the third variation matches and you receive a `Test` instance. No
error, no warning — the wrong class, fully constructed. Suffix stripping applies
to any name ending in `class`, so this fires for `ConfigClass` against `Config`,
and so on.
**Do instead:** register and request keys with `Cls.__name__` at both ends so
the exact variation matches first. When a returned object surprises you, check
`Registry.entries()` for what the key actually resolved against.

---

## Constraints and gotchas

- **The registry is process-global with no public reset**: `Registry.register`
  mutates class-level state shared by every caller in the process. There is no
  public `clear()`. Tests reach into the name-mangled internals
  (`Registry._Registry__registry.clear()`, plus `__lookup` and `__lookup_keys`)
  — do the same in a `setUp`, and clear all three or stale lookup caches leak
  between tests.
- **`fill_registry()` without `path` infers the caller's directory from the
  stack**: it needs a real module file. From a REPL, `python -c`, or `exec` it
  raises `SweetTeaError: Cannot determine module path automatically`. Pass
  `path=` explicitly in those contexts.
- **`fill_registry` imports every module it finds**: import-time side effects —
  connections, `logging.basicConfig`, monkeypatching — all execute during
  discovery. Use `exclude` to keep such modules out.
- **`fill_registry` swallows missing dependencies**: an `ImportError` or
  `ModuleNotFoundError` emits a `SweetTeaWarning` and skips that module. Any
  other exception raises `SweetTeaError`. If classes are missing after
  discovery, check for warnings before suspecting the registry.
- **`exclude` patterns match the full dotted path, case-sensitively**:
  `exclude=["*.tests"]` — a bare `"tests"` matches nothing, because the value
  tested is `mypkg.sub.tests`. Excluding a package prunes its whole subtree.
- **Duplicate registration is a silent no-op, but only for identical entries**:
  equality covers all four fields. Re-registering the same class under the same
  key, library, and label does nothing; registering a *different* class under
  an existing key succeeds and creates an ambiguity that surfaces later, at
  `create` time, as `did not return a unique result`.
- **`library` and `label` are lowercased on both sides**: stored lowercased at
  registration, and lowercased again when used as filters. `library="LibA"` and
  `library="liba"` are the same filter.
- **An empty-string filter means "no filter", not "match empty"**: entries
  registered without a `library` cannot be selected by asking for one. Passing
  `library=""` matches every entry regardless of its library.
- **`AbstractFactory[X]` is a real class, not a `typing` alias**: it is built
  with `type()`, so `typing.get_args(AbstractFactory[X])` returns `()` and
  `get_origin` returns `None`. Do not introspect it as a generic alias.
- **`SingletonFactory.list_keys()` does not list singletons**: it returns every
  key in the registry, whether instantiated or not. The cached instances are
  `list_singletons()`.
- **`SingletonFactory` caches against the resolved registry entry**: the cache
  key is `(key, library, label)` of the entry that matched, not the spelling you
  passed. Every spelling of one key returns one instance, and entries differing
  only by `library` or `label` get separate instances. `pop` takes the same
  filters — `pop(key="Conn", library="redis")` — and popping without them cannot
  reach an entry that needed a filter to resolve.
- **The first call's `configuration` wins**: later calls return the cached
  instance and ignore their `configuration` argument entirely. No error marks
  the discarded config.

---

## Quick reference

| Task | How |
|------|-----|
| Register one class | `Registry.register(key=Cls.__name__, class_def=Cls, library="db")` |
| Discover a package tree | `Registry.fill_registry(library="db")` |
| Keep `tests/` out of discovery | `Registry.fill_registry(exclude=["*.tests"])` |
| Build an instance | `Factory.create(key="Cls", configuration={"host": "x"})` |
| Get the class, construct later | `InverterFactory.create(key="Cls")` |
| Restrict results to a base type | `AbstractFactory[Base].create(key="Cls")` |
| Restrict, but get the class | `AbstractInverterFactory[Base].create(key="Cls")` |
| Reuse one instance per key | `SingletonFactory.create(key=Cls.__name__)` |
| Disambiguate two same-named classes | add `library="liba"` and/or `label="prod"` |
| See everything registered | `Registry.entries()` |
| See what a base type matches | `Registry.typed_entries(lookup_type=Base)` |
| Reset between tests | `Registry._Registry__registry.clear()` + `__lookup` + `__lookup_keys`; `SingletonFactory.clear()` |
| Drop one cached singleton | `SingletonFactory.pop(key="Cls")`, plus `library=`/`label=` if the entry needed them |
| Catch any failure | `except SweetTeaError` |

---

*Generated for agent use. Covers sweet_tea on `main`; release versions are
generated at publish time, so `pyproject.toml` carries a `0.0.0` placeholder.*
