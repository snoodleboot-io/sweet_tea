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

## Modules That Will Not Import

A fill walks a tree and imports what it finds, and some of what it finds cannot be
imported here. `fill_registry` warns and moves on, whatever the import raised, so such
a module costs its own classes and no others:

```python
Registry.fill_registry(path="/.../site-packages/click", module="click")
# SweetTeaWarning: Skipping module click._winconsole: import failed: AssertionError.
# Nothing it defines is registered. If the module is meant to import here, that
# exception is a bug rather than a platform or environment guard.

Registry.skipped()
# {'click._winconsole': 'import failed: AssertionError'}
```

`click._winconsole` opens with `assert sys.platform == "win32"`. Before SWE-15 only
`ImportError` and `ModuleNotFoundError` were survivable and everything else raised
`SweetTeaError`, so filling over an installed click on Linux abandoned the walk at
that module: 9 of click's 80 classes registered, and the fill itself failed.

`Registry.skipped()` maps each such module to
`<category>: <ExceptionType>[: <message>]`. The category separates the two things a
caller does about them:

- `missing optional dependency` — an `ImportError`. Install the package, or exclude
  the module from the fill.
- `import failed` — anything else. A platform guard, or a module wanting an
  environment it does not have, which is normal and needs nothing; or a genuine bug
  in that module, which the exception type is there to let you spot.

Nothing from a module that failed is registered: its classes are collected before any
of them is registered, so a skip is never half-applied.

### Source a lazy fill cannot read

A lazy fill parses rather than imports, which gives it two failure modes of its own.
Neither aborts the fill, and the two are handled differently because they do not mean
the same thing:

- **Unparsable source** — a Python 2 leftover, a generated file, a vendored sample —
  could not be imported either, so the module is skipped and recorded exactly as an
  unimportable one is. Both modes then register the same classes.
- **Unreadable source** — a file whose permissions deny the fill — may still import
  from cached bytecode, since CPython needs to stat the source but not read it. The
  eager path would register its classes, so the lazy path imports the module rather
  than skipping it.

A module declaring a non-UTF-8 encoding is neither: the scan reads bytes and applies
the PEP 263 coding declaration the way an import does, so it is scanned normally.

A caller who would rather not continue needs no option for it, because the warning is
that switch:

```python
import warnings
from sweet_tea.sweet_tea_warning import SweetTeaWarning

warnings.simplefilter("error", SweetTeaWarning)
Registry.fill_registry(path="...", module="myapp")  # raises on the first skip
```

The escalated warning is raised from inside the handler for the original exception, so
its traceback comes out chained to it. The module is recorded in `skipped()` before the
warning is issued, so the reason is readable either way. The traceback is also logged
at `DEBUG` for a failure that is not a missing dependency.

Lazy filling reports the same thing in the same words, but at the lookup that first
needed the module rather than during the walk: its entries are dropped, the key stops
resolving, and `skipped()` gains the identical line. Reading `Entry.class_def` for one
named class in such a module still raises `SweetTeaError` — that call has to hand back
a class, and there is none — with the exception type in the message, which a bare
`assert` supplies no other way.

## Symlinked Subpackages

A fill descends into a symlinked subpackage, which is usually what you want — a
subpackage linked into a shared directory or a sibling checkout is registered like any
other. But a tree can offer two names for one directory, and a directory is registered
once per *directory*, not once per path that reaches it:

```python
# aliased/plugins/widget.py       defines Widget
# aliased/plugins_alias -> aliased/plugins

Registry.fill_registry(path=".../aliased", module="aliased")
Registry.registry()
# ['widget']                      one entry, module aliased.plugins.widget
```

Before SWE-40 that registered `widget` twice, once under each name. The two imports
produce two distinct class objects, so the identity dedupe in `register` could not see
they were the same class, and `Factory.create("widget")` then refused the key as
ambiguous — a convenience symlink made the package unusable. A self-referential link
(`loop -> .`) was worse: the walk recursed until the kernel refused the 41st link, so
one class came back as 41 entries under 41 module names.

Where two names compete, the first in walk order wins. Walk order is alphabetical, so
which one that is stays the same between runs and between machines, and a snapshot taken
on one records a module name that imports on the other.

A link that is the *only* route to a directory is still followed and still registered —
revisits are skipped, links are not. `lazy_audit` walks by the same rule, which matters
because `eager="auto"` audits every module before it fills anything.

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

`Registry.typed_entries` accepts whatever `issubclass` accepts as its second argument —
a class, a tuple of classes, a union, a runtime-checkable Protocol — and anything else
is refused with `issubclass`'s own `TypeError` rather than memoised and answered with
`[]`. Each accepted lookup gets a cache slot, and `register` refreshes every slot a new
class belongs in. The two used to disagree: a tuple built a slot that the refresh then
skipped, because the refresh only considered keys that were themselves classes, so a
tuple lookup answered its first question forever (SWE-43). Whatever is accepted is
cached, and whatever is cached is refreshed.

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

## Singleton Configuration

A cached singleton is returned as it is, and the `configuration` given to a later call
is discarded — the instance cannot be rebuilt without breaking the identity other
holders depend on. Since that used to happen silently, a configuration differing from
the one the instance was built with now warns:

```python
SingletonFactory.create("pg", configuration={"host": "primary"})
SingletonFactory.create("pg", configuration={"host": "replica"})
# SweetTeaWarning: Ignoring the configuration passed for singleton 'pg': an instance
# is already cached and is not rebuilt, so the configuration from the first call
# still applies.
```

### What counts as a different configuration

Drift is judged on the keyword arguments construction would use, not on what the caller
typed, so spellings that build one instance are one configuration:

- **No configuration at all.** Fetching an existing singleton without a configuration is
  the normal idiom and stays silent, and `configuration={}` says the same thing —
  `create(key, configuration=options.get("cfg", {}))` is a fetch, not a rebuild request.
- **A model and an equivalent dict**, in either order, including the model a declared
  `__configuration__` validates a dict into.
- **A declared default spelled out.** With `__configuration__` declaring `retries: int = 3`,
  `create(key)` and `create(key, {"retries": 3})` agree, because the schema is applied
  before the comparison. The schema also decides which spellings are equivalent: where
  it declares `retries: int`, passing `True` or `1.0` is coerced to `1` and agrees with
  `1`.
- **Values a constructor mutates.** The comparison basis is deep-copied before the
  constructor runs, so a constructor appending to a list it was handed does not make the
  next caller — who passed an equal list — look wrong.
- **NaN.** `float("nan")` passed twice is the same request both times. That
  `nan != nan` is a statement about arithmetic, not about what was asked for.

And these genuinely differ, so they warn:

- A configuration mutated between calls, **at any depth**: the basis is a snapshot, so
  `nested["opts"]["mode"] = "slow"` followed by another `create` is reported.
- `1` against `True`, and `1` against `1.0`, where no `__configuration__` declares them
  equivalent. They reach the constructor as different types and behave differently once
  there.
- A configuration a declared `__configuration__` rejects. It cannot be the one the cached
  instance was built from, and no `SweetTeaError` is raised for it either, since nothing
  is constructed.

Where drift cannot be judged, nothing is said:

- A configuration holding values whose comparison is not a plain boolean — a numpy
  array, say — or one that could not be reduced to keyword arguments at all.
- A configuration a declared `__configuration__` cannot be *applied* to, because a
  validator raised something other than a validation error — an `AttributeError` on a
  value of a type it did not expect, for instance. That is evidence about the validator
  and none about the configuration, so there is no verdict to give. Note the difference
  from the rejected configuration above, which warns: pydantic refusing a value is the
  schema's considered answer, while a validator breaking is not an answer at all. On a
  cache hit neither one raises out of `create()` — the caller asked for an instance that
  already exists and gets it.

A value that cannot be deep-copied, such as a lock or an open file, is kept by reference
instead, so it is compared as it is then; every other value in the configuration is
still snapshotted.

Judging drift applies any declared `__configuration__`, so a validator with a side
effect can observe it. It runs once per `create()` at most: once for a call that
constructs, whose comparison basis reuses what construction validated, and once for a
cache hit that was passed a configuration to judge. A cache hit passed no configuration,
or an empty one, asks no question and runs no validator at all.

Use `Factory` when each caller needs its own configuration, or
`SingletonFactory.pop(key)` to discard the cached instance before building a new one.

## Thread Safety

The registry's lock guards the registry's own state. It is deliberately **not** held
while a module is imported, and `SingletonFactory`'s lock is **not** held while a
constructor runs.

That matters because both used to be, and both deadlocked. Importing a module runs its
body; if that body touches the registry — `Factory.create(...)` or `Registry.entries()`
at module scope — then a thread importing it holds Python's per-module import lock and
wants the registry's, while a fill or a lookup holds the registry's and wants the
import lock. Neither ever proceeds, and because CPython's import deadlock detector only
looks for cycles among import locks, nothing reports it.

What this means in practice:

- **Concurrent fills and lookups interleave.** Registration dedupes by identity, and
  resolution re-reads the registry after importing rather than trusting what it saw
  before, so interleaving is safe rather than merely tolerated.
- **Imports overlap.** Four modules that each take 0.5s to import cost about 0.5s
  across four threads, not 2s, and an unrelated `Registry.entries()` is not blocked
  behind them.
- **A singleton is still constructed exactly once.** Construction is admitted by a
  per-key lock, so one thread builds a given key while every other key and every cache
  read proceeds. Verified with 32 threads against four spellings of one key, and again
  over 96,000 `create()` calls across 48 threads and four keys: one instance and one
  constructor invocation per key, with never more than one constructor for a key
  running at a time. That holds across a concurrent `clear()`, which is why `clear()`
  keeps the per-key construction locks it used to discard.

A constructor that resolves another registered class, or a module body that creates a
singleton, is therefore safe. Neither was before.

### Circular singleton dependencies

A constructor may resolve or create, so it may also ask for a singleton whose
construction it is already inside — directly, or round a chain of collaborators:

```python
class Alpha:
    def __init__(self):
        self.beta = SingletonFactory.create("beta")    # whose __init__ creates "alpha"
```

That instance cannot exist until the constructor asking for it returns, so there is
nothing to wait for. `SingletonFactory` raises instead, naming the path round the
cycle:

```
SweetTeaError: Circular singleton construction for key 'alpha': alpha -> beta ->
alpha. A constructor asked SingletonFactory for a singleton whose construction it is
already inside ...
```

Circular dependencies are a mistake in the calling code; reporting them is the
container's job. Break the cycle by taking the collaborator as a constructor argument,
or by looking it up after construction rather than during it.

Two threads can also enter one cycle from opposite ends, each holding the construction
lock the other needs. No thread's own call stack shows that, so the factory tracks which
thread is constructing which key and what each blocked thread is waiting for; a thread
whose wait would close the circle is refused with `Deadlocked singleton construction`
rather than blocked. There is no timeout involved, so an honestly slow constructor — a
connection pool, a model load — is never mistaken for a deadlock, however long it takes.

The one cycle this cannot see is one that leaves the factory: a constructor blocking on
a lock of your own that is held by a thread waiting on a singleton. Nothing inside
`sweet_tea` can observe that lock, so it remains a genuine deadlock; keep your own locks
out of constructors that resolve.

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
uses, so a resolved module matches eager registration exactly — plus anything registered
by hand with `register_lazy`, which is carried forward rather than rebuilt (see
[Registering one class lazily](#registering-one-class-lazily)).

Registering one name registers one name. Resolving it imports its module, but the
module's other classes are registered only under the `(library, label)` pairs a *fill*
asked for — an alias does not drag its module's whole class list in behind it. And a
registration made *while* a module is being imported, including from the module's own
body, survives the resolution that triggered it.

That difference is the point: a name the *scan* guessed at is overruled by what the
module turned out to hold, while a name you *asked for* is kept. So a binding the
scanner saw that leads to a class from another package — the `try: from otherlib import
X / except ImportError: class X` fallback is the common shape — is dropped rather than
registered, because an eager fill would not have registered it either. An alias you
registered yourself is kept even when it points at a re-export, which is usually
exactly why you registered it. Before that, the view is
approximate in both directions: a class replaced by a decorator, a `TYPE_CHECKING`-only
class, or a class behind an uninstalled dependency may appear in `list_keys()` and
vanish on resolution, and runtime-injected names are missing until something asks. Call
`Registry.resolve_all()` when you need an exact registry — it imports everything, which
is by definition eager.

### Registering one class lazily

`Registry.register_lazy(key, module, attribute, library="", label="")` adds a single
deferred entry, without a scan or a tree walk. Use it to register a class you already
know the location of — most usefully under a key of your own:

```python
Registry.register_lazy(
    key="pattern_alias",
    module="myapp.patterns.retry",
    attribute="RetryPattern",
    library="mylib",
    label="alias",
)

Factory.create("pattern_alias")     # imports myapp.patterns.retry, and nothing else
```

The key, library and label are kept exactly as given. Resolving the module registers
everything discovery finds in it as well, so an alias and the class's own discovered key
both end up registered — two keys, one class. An entry whose `attribute` the module turns
out not to bind to a class is dropped on resolution, which is the same rule a scanned
name is held to.

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
- **Reading does not alter the entry.** `entries()` copies the list, not the entries, so
  the objects you get are the registry's own. Resolving through one caches the class for
  your reads but leaves `is_lazy` and `class_object` saying what the registry believes,
  because a reader changing those corrupted the registry under concurrent lookups.
- **`entry.is_lazy` does not resolve.** Use it to check whether a read would import
  anything. `entry.class_object` exposes the stored class without resolving, for code
  that wants to see unresolved entries as unresolved.
- **`entry.model_dump()` reports stored state.** It names the class `class_def` — the
  name entries are constructed with — and gives `None` for an unresolved entry rather
  than importing to fill it in. Pass `by_alias=False` if you want the storage field
  name instead. A dump of a resolved entry holds a live class, which no JSON encoder
  accepts, so `Registry.export()` is the way to write the registry as data.

`Registry.resolve_all()` still materialises everything at once when that is what you
want.

### Adopting it

Lazy filling assumes nothing needs the registry to be complete *while modules are still
importing*. A package that resolves classes through the registry at import time — in a
module body, or in a function a module body calls — will fail under `lazy=True`, because
the entries it wants have not been resolved yet. Put such modules in `eager=[...]`, or
defer their lookups to first use.

## Snapshotting the Registry

Filling a registry walks a package tree. Lazy filling skips the imports but still reads
every source file. A snapshot skips both — write the filled registry once, read it back
as data:

```python
Registry.fill_registry(lazy=True)
Registry.export("registry.json")      # build step

Registry.load("registry.json")        # every run after
Factory.create("database_connection")
```

Measured on an 880-module package, all producing the same 799 entries:

| | time |
| -- | -- |
| `fill_registry(lazy=True)` | 497 ms |
| `load("registry.json")` | **49 ms** |
| `load("registry.json", verify=False)` | **8 ms** |

Loaded entries are lazy entries, so nothing is imported until a factory — or a read of
`entry.class_def` — needs it.

`export` replaces the file rather than emptying and refilling it: the JSON is written to
a temporary file beside the destination and renamed over it, which is atomic. So a
process loading the snapshot at the moment a build writes it reads either the old file
or the new one, never half of one, and that holds across processes, where no lock would
have.

### Staleness

A stale snapshot is worse than walking the tree: it registers names that no longer
exist, and the failure surfaces far from the cause. So a snapshot records the trees it
was built from with a digest over their Python sources, and `load` checks it by default.
A changed, added or removed module, or a tree that is gone, raises `SweetTeaError`
naming the source and telling you to rebuild.

A tree that merely *moved* does not. Each source is recorded by where it sits inside its
root package as well as by the absolute directory the export walked, and verification
looks for it where that package is installed now. That is what makes the obvious build
step work: export the snapshot in CI, ship it inside the wheel, and it still verifies
from the consumer's `site-packages` rather than being refused for not being under
`/home/runner/work/...`. Locating the package uses `importlib.util.find_spec` on the
top-level name, which executes nothing — loading a snapshot never runs the code it
describes.

Locating a root package can produce more than one directory, because a namespace
package (PEP 420) has one per portion. All of them are tried, and a candidate is
accepted because its sources hash to the recorded digest rather than because a
directory is there: with portions `p1/ns` and `p2/ns` both importable, a snapshot of
`p2/ns` is checked against `p2/ns`. The directory the export walked is tried first where
it is still there, and the recorded absolute directory is the last resort, so an
uninstalled tree is still checked exactly where it was built.

Verification costs a hash of every source file — 41 ms of the 49 ms above. Pass
`verify=False` where something else already guarantees the snapshot is current, such as
a build that regenerates it.

The digest covers excluded modules too. A snapshot cannot know which `exclude` patterns
a later fill would pass, so it is deliberately conservative: editing a file that was
never registered still marks the snapshot stale. `__pycache__` is ignored, since
bytecode is derived.

Symlinked directories are followed, because filling follows them: a subpackage that is a
link into a shared directory or another checkout is walked and registered, so the digest
has to cover it or verification would pass over renamed and added classes. A directory
the walk reaches twice — or a loop — is hashed once and noted as a revisit, so the link
itself still shows up in the digest without the walk running away. The fill applies the
same rule to deciding what to register (see [Symlinked Subpackages](#symlinked-subpackages));
the two have to agree about which directories are in scope.

A `relative_path` that is absolute or climbs out of its root package is refused when the
snapshot is read, rather than resolved: it decides which directory gets verified, so a
hand-edited one must not be able to aim that anywhere it likes. `version` has to be a
positive integer no greater than this reader's format.

### What a snapshot records

```json
{
  "version": 4,
  "sources": [{"module": "myapp", "path": "/srv/myapp", "relative_path": ".",
               "digest": "..."}],
  "entries": [{"key": "database_connection", "class_def": "myapp.db:DatabaseConnection",
               "library": "myapp", "label": "", "provisional": false}],
  "skipped": {"myapp.optional_backend":
                "missing optional dependency: ModuleNotFoundError: No module named 'redis'"}
}
```

`class_def` is `module:attribute` — the attribute the class is *bound to*, which is how
the registry keys it and is not always the class's own `__name__`.

`provisional` says whether the name was read out of source or asked for. It decides who
wins when the module is finally imported: a scanned name is a guess and discovery
overrules it, an explicit registration is a request and is kept. Leaving it out of the
file made every guess come back as a request, so a snapshot of a lazily filled tree
registered names the package never defined — one of them a class from another
distribution, under this library's name (SWE-41). With it recorded, `export` → `load` →
`resolve_all` lands exactly where a fill of the same tree lands.

`path` is where the tree sat when the snapshot was written; `relative_path` is the same
directory relative to its root package's own directory — `"."` when the filled module
*is* the root, `"sub"` when `myapp.sub` was filled. Verification prefers the relative
one, which is why a shipped snapshot still works.

`version` is 4. Format 2 added `relative_path`; format 3 changed how a digest is
computed — the records inside it are framed, and symlinked subpackages are followed — so
the same unchanged tree hashes to a different value than it did before; format 4 added
`provisional`. Each is a reason to move the version rather than change behaviour quietly:
a sweet_tea that predates any of them refuses a newer file outright and says so, instead
of ignoring what it does not know and reaching the wrong verdict. An older snapshot still
parses here, but its digest was computed under the older rules, so verification will call
it stale; the answer either way is the one the error gives — re-export it.

A format 3 or earlier snapshot read here records no provenance, so every name in it is
read as a guess and `load` warns. That is the safe direction — a guess read as a request
is the bug above — and it costs less than it sounds like: a guess is only overruled where
discovery disagrees, so a name genuinely bound to a class in the module it names survives
either way, aliases included. What is lost is a name discovery cannot confirm (an alias
pointing at a re-export, whose class belongs to another module) and a class only
discovery can see (one built at runtime, where no scan reaches it), because `load` also
declines to treat an older file's `(library, label)` pairs as filled — it cannot tell
which of them a fill established, and assuming they all were registered one class under
two libraries and made its key ambiguous. Both costs are names that go missing rather
than names that appear wrongly, and both are repaired by re-exporting. Escalating
`SweetTeaWarning` to an error turns the warning into a refusal.

Skips are recorded on purpose. Filling warns and skips a module whose import raises; a
snapshot that dropped that would bake in the install profile *and the platform* of the
machine that built it, and a reader could not tell "not registered" from "not
installed", or either of those from "that module does not import here".
`Registry.skipped()` reports them either way, with the exception type in the reason.

### Determinism

Because a snapshot is read rather than discovered, its contents do not depend on what
happens to be imported when it is read. Registry membership from a live fill can vary
with interpreter state; a loaded registry cannot.
