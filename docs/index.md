---
hide:
  - navigation
  - toc
---

<div class="st-hero" markdown>

<span class="st-hero__eyebrow">Open Source · Python · snoodleboot</span>

# The factory system<br>Python deserves

Thread-safe. Type-safe. Zero magic.<br>Register once, create anything.
{.st-hero__sub}

<div class="st-install">
  <span class="st-install__prompt">$</span>
  <span>uv add sweet-tea</span>
</div>

<div class="st-badges">

[![PyPI](https://img.shields.io/pypi/v/sweet-tea?style=flat-square&logo=pypi&logoColor=white&color=f97316)](https://pypi.org/project/sweet-tea/)
[![Python](https://img.shields.io/pypi/pyversions/sweet-tea?style=flat-square&logo=python&logoColor=white&color=f97316)](https://pypi.org/project/sweet-tea/)
[![CI](https://img.shields.io/github/actions/workflow/status/snoodleboot-io/sweet_tea/ci.yml?style=flat-square&logo=githubactions&logoColor=white&label=CI&color=f97316)](https://github.com/snoodleboot-io/sweet_tea/actions)
[![License](https://img.shields.io/pypi/l/sweet-tea?style=flat-square&color=f97316)](https://github.com/snoodleboot-io/sweet_tea/blob/main/LICENSE)

</div>

<div class="st-cta">
  <a href="user-guide/getting-started/" class="st-btn st-btn--primary">Get started</a>
  <a href="api/registry/" class="st-btn st-btn--ghost">API reference</a>
  <a href="https://github.com/snoodleboot-io/sweet_tea" class="st-btn st-btn--ghost">GitHub</a>
</div>

</div>

---

## What's in the box

<div class="st-grid" markdown>

<div class="st-card" markdown>
<div class="st-card__icon">🔒</div>
<div class="st-card__title">Thread-Safe Registry</div>
<div class="st-card__body">RLock-backed global registry. Concurrent reads and writes without races.</div>
</div>

<div class="st-card" markdown>
<div class="st-card__icon">🧬</div>
<div class="st-card__title">Type-Safe Generics</div>
<div class="st-card__body">Full TypeVar support with <code>__class_getitem__</code>. Your IDE stays happy.</div>
</div>

<div class="st-card" markdown>
<div class="st-card__icon">🔍</div>
<div class="st-card__title">Flexible Key Matching</div>
<div class="st-card__body"><code>MyClass</code>, <code>my_class</code>, or <code>myclass</code> — all resolve to the same entry.</div>
</div>

<div class="st-card" markdown>
<div class="st-card__icon">🔁</div>
<div class="st-card__title">Lazy Singletons</div>
<div class="st-card__body">SingletonFactory caches on first create. No decorators, no metaclasses.</div>
</div>

<div class="st-card" markdown>
<div class="st-card__icon">🔌</div>
<div class="st-card__title">Optional Dependencies</div>
<div class="st-card__body">Graceful fallbacks with clear warnings. Nothing blows up at import time.</div>
</div>

<div class="st-card" markdown>
<div class="st-card__icon">📦</div>
<div class="st-card__title">Auto-Registration</div>
<div class="st-card__body">Call <code>fill_registry()</code> and every class in your package is registered instantly.</div>
</div>

</div>

---

## 60-second quickstart

=== "Factory"

    ```python
    from sweet_tea import Registry, Factory

    class PostgresDB:
        def __init__(self, host="localhost", port=5432):
            self.host = host

    Registry.register("postgres", PostgresDB)

    db = Factory.create("postgres", configuration={"host": "prod.db"})
    ```

=== "Singleton"

    ```python
    from sweet_tea import Registry, SingletonFactory

    class AppConfig:
        def __init__(self, env="prod"):
            self.env = env

    Registry.register("config", AppConfig)

    # Same instance every time
    cfg = SingletonFactory.create("config", configuration={"env": "staging"})
    ```

=== "Abstract (type-safe)"

    ```python
    from sweet_tea import Registry, AbstractFactory

    class BaseService: ...

    class EmailService(BaseService): ...

    Registry.register("email", EmailService)

    # Only accepts subclasses of BaseService
    svc_factory = AbstractFactory[BaseService]
    svc = svc_factory.create("email")
    ```

---

## Installation

=== "uv (recommended)"

    ```bash
    uv add sweet-tea
    ```

=== "pip"

    ```bash
    pip install sweet-tea
    ```

=== "Poetry"

    ```bash
    poetry add sweet-tea
    ```

---

*Built by [snoodleboot, LLC](https://github.com/snoodleboot-io) · Apache 2.0*
