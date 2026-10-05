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

`configuration` may be a dict or a pydantic `BaseModel`. A model is spread as
`class_def(**dict(model))` — shallow, so nested models arrive as models, every field
(defaults included) is sent, and `extra="allow"` extras are included. It is never
passed as a single positional argument; to hand a class the model itself, use
`configuration={"settings": model}`.

A class may set `__configuration__` to a `BaseModel` subclass. The factory then
validates the configuration into that model before construction — dicts, `None`,
and other models alike; an instance of the declared model is used as is. Failure
raises `SweetTeaError` naming the key, with the `ValidationError` as `__cause__`.
Unknown keys are dropped unless the model sets `extra="forbid"`. A non-model
declaration raises `SweetTeaError` on construction. `InverterFactory` ignores it.

`fill_registry` registers the classes a module defines, judged by `__module__`, so an
imported class is not registered again under every module importing it. One exception:
a class built by a helper elsewhere in the same package — `Thing = make_class("Thing")`,
where `type()` stamps `__module__` with the helper's module — belongs to no module at
all, and is registered where it is bound. A class built by a helper in a *different*
distribution is still not registered.

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

### Threads

**Contract:** the registry's lock covers its own state only. It is never held across a
module import, and `SingletonFactory`'s lock is never held across a constructor, so a
module body that reads the registry and a constructor that resolves a collaborator are
both safe. A singleton is still built exactly once per key.

**Must not:** assume a fill is atomic. Concurrent fills and lookups interleave; the
registry is consistent at every point, but a reader may observe a fill in progress.

### Lazy filling

**Contract:** `Registry.fill_registry(lazy=True)` registers the same keys by parsing
each module instead of importing it, and imports a module the first time a factory
needs a class from it. A resolved module matches eager registration exactly, plus any
entry registered by hand with `register_lazy`.

`Registry.register_lazy(key, module, attribute, library="", label="")` adds one
deferred entry with no scan and no tree walk, keeping the key, library and label as
given. Resolving its module also registers what discovery finds there, so an alias and
the class's own discovered key both survive — two keys, one class. An entry whose
`attribute` the imported module does not bind to a class is dropped on resolution, the
same rule a scanned name is held to.

**Must not:** expect a key registered this way to need the sweep. It names its own
module, so resolution imports that module and stops — including under
`lazy="strict"`.

**Must not:** assume the registry is complete during import. Code that calls
`Factory.create` or reads `Registry.entries()` from a module body fails under lazy
filling; name those modules in `eager=[...]`, or defer the lookup.

`Registry.entries()` includes unresolved entries. Reading `entry.class_def` imports
that entry's module and returns the class, so introspection keeps working — but the
read can raise `SweetTeaError`, and touching every entry's `class_def` is an eager
fill. `entry.is_lazy` checks the state without resolving; `entry.class_object` is the
stored class, `None` while unresolved. `entry.model_dump()` names the class
`class_def` and reports it as stored — `None` for an unresolved entry, importing
nothing — and is not JSON-serialisable once resolved, because a live class is not
data; use `Registry.export(path)` for that.

A name read out of source is a guess: if the module turns out to bind a class from
another package there, it is dropped, matching what an eager fill registers. A name
passed to `Registry.register_lazy` is a request and is kept, re-exports included.

`Registry.lazy_audit(path=..., module=...)` reports what in a tree would not survive
lazy filling, and `fill_registry(lazy=True, eager="auto")` acts on that report. The
audit sees module-level statements and one hop into functions they call, so an
import-time lookup buried deeper is caught at runtime instead.

A lazy fill parses instead of importing, so source it cannot handle is its own case:
unparsable source is skipped and recorded like an unimportable module, while
unreadable source is imported instead (bytecode may still load it). A non-UTF-8
coding declaration is honoured, not an error. Either way the fill continues.

Classes created at runtime (`globals()[name] = type(...)`) cannot be seen in source.
Requesting one imports every module still pending and warns; `lazy="strict"` raises
instead. `eager` without `lazy` raises `SweetTeaError`.

### Snapshotting

**Contract:** `Registry.export(path)` writes the filled registry as JSON;
`Registry.load(path)` registers it back without walking or importing a tree. Loaded
entries are lazy. On an 880-module package: fill 497 ms, load 49 ms, load with
`verify=False` 8 ms.

**Must not:** load a snapshot built from different source. `load` verifies a digest of
the recorded trees by default and raises `SweetTeaError` when they differ; only pass
`verify=False` when something else guarantees freshness.

Moving the tree is not a difference. Sources are recorded relative to their root package
(format version 2) and located through `importlib.util.find_spec` on the top-level name,
which executes nothing, so a snapshot built in CI and shipped inside the wheel verifies
from the consumer's `site-packages`. A root package that locates to several directories —
a namespace package has one per portion — has all of them tried, and a directory is
accepted only when its sources hash to the recorded digest; the recorded absolute
directory is the last resort. A `relative_path` that is absolute or escapes its root
package is refused as malformed, as is a `version` that is not a positive integer.

The digest covers symlinked subpackages, because filling registers from them (format
version 3; the framing inside the digest changed with it, so every digest value moved).
An older snapshot parses but verifies as stale, and a reader that predates a format
refuses the newer file rather than mis-judging it; re-export either way.

`export` writes a temporary file beside the destination and renames it over the
destination, so a concurrent `load` — in this process or another — reads the old
snapshot or the new one, never a truncated one. No lock is held across the file I/O.

`Registry.skipped()` reports the modules a fill could not import, each mapped to
`<category>: <ExceptionType>[: <message>]`, where the category is
`missing optional dependency` for an `ImportError` and `import failed` for anything
else. A snapshot carries them, so "not registered" stays distinguishable from "not
installed" and from "does not import on this machine".

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
  between tests. Those three are the whole recipe: the `__seen` dedupe index
  rebuilds itself when it notices the registry was cleared underneath it.
- **`fill_registry()` without `path` infers the caller's directory from the
  stack**: it needs a real module file. From a REPL, `python -c`, or `exec` it
  raises `SweetTeaError: Cannot determine module path automatically`. Pass
  `path=` explicitly in those contexts.
- **`fill_registry` imports every module it finds**: import-time side effects —
  connections, `logging.basicConfig`, monkeypatching — all execute during
  discovery. Use `exclude` to keep such modules out.
- **`fill_registry` skips any module whose import raises**: whatever it raised —
  `ModuleNotFoundError`, a platform guard's `AssertionError`, a `SyntaxError` —
  it emits a `SweetTeaWarning` naming the module, the exception type and its
  message, records the same string in `Registry.skipped()`, and carries on with
  the rest of the tree. Nothing from that module is registered. So if classes
  are missing after discovery, read the warnings or `Registry.skipped()` before
  suspecting the registry; a fill that registers less than you expect no longer
  fails loudly. To make it fail, escalate the warning:
  `warnings.simplefilter("error", SweetTeaWarning)`. The lazy path does the same
  at the lookup that first needed the module, which is also when the warning
  appears; `Entry.class_def` on such a module still raises `SweetTeaError`.
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
  instance and ignore their `configuration` argument entirely. The instance is
  never rebuilt, since other holders rely on its identity. Passing a
  configuration that differs from the one it was built with raises a
  `SweetTeaWarning` naming the key; passing none, the ordinary way to fetch an
  existing singleton, is silent. Use `Factory` for per-call configuration, or
  `SingletonFactory.pop` to discard the instance first.
- **Drift is judged on the keyword arguments construction would use**, not on
  what you typed, so `None` and `{}` agree, a dict and the model a declared
  `__configuration__` validates it into agree, a schema default spelled out
  agrees with leaving it out, and two NaNs agree. The basis is deep-copied before
  the constructor runs, so mutating a configuration you passed — at any depth —
  is reported on the next call rather than silently rewriting what the first
  call is recorded as having asked for. Absent a declared schema, `1`, `1.0` and
  `True` are different requests. Where the comparison is undecidable — a value
  whose `==` is not boolean, a still-lazy entry — nothing is said and nothing is
  raised. Judging drift imports nothing and resolves nothing.

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
