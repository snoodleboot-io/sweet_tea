# Modifications © 2025 snoodleboot, LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""
Abstract singleton factory implementation with generic type constraints.

This factory combines the type constraints of AbstractFactory with the one-instance-
per-key caching of SingletonFactory, so a shared component can be asked for by key and
still arrive typed.
"""

from typing import Any, Generic, TypeVar

from pydantic import BaseModel

from sweet_tea.entry import Entry
from sweet_tea.singleton_factory import SingletonFactory
from sweet_tea.type_parameterized_factory import TypeParameterizedFactory

T = TypeVar("T")


class AbstractSingletonFactory(TypeParameterizedFactory, Generic[T], SingletonFactory):
    """
    A generic singleton factory that constrains instantiation to subclasses of type T.

    Completes the grid the other two axes already filled (SWE-47). ``Factory`` and
    ``InverterFactory`` are untyped; ``AbstractFactory[T]`` and
    ``AbstractInverterFactory[T]`` are type-constrained; ``SingletonFactory`` caches but
    returns ``Any``, so a caller wanting "the one instance registered under this key,
    and it must be a ``MyBase``" had to give up either the singleton or the narrowing.

    Usage:
        factory = AbstractSingletonFactory[MyBaseClass]
        instance = factory.create('my_key')
        # Only classes inheriting from MyBaseClass will be available, and the same
        # instance comes back on every later call.

    Each parameterization is an independent subclass, so several may be held and used in
    any order without interfering with one another.

    **The instance cache is shared with** :class:`SingletonFactory`, deliberately and
    not merely as an accident of inheritance. The guarantee is one instance per key for
    the process, so a key reached through this factory and the same key reached through
    the untyped one must give the same object; two caches would make two singletons of
    one key. The cache is keyed on the resolved entry, so this holds across every
    spelling of the key and across every parameterization that narrows to it. It also
    means :meth:`clear` and :meth:`pop` act on that one shared cache.

    What the narrowing adds over ``SingletonFactory`` is the type, not the protection.
    The ``library`` filter already stopped a foreign class being returned silently,
    because :meth:`_select_entry` applies it after key matching and raises when it
    empties the set. What was lost was the static type: the caller got ``Any`` and had
    to cast or re-check to get back to the base it asked about, which is the thing
    ``AbstractFactory[T]`` exists to avoid.

    :meth:`list_keys` is inherited unchanged and still lists the whole registry rather
    than the subset this parameterization would accept. Narrowing it would answer ``[]``
    for a lazily filled registry, since an unresolved entry cannot answer
    ``issubclass`` — ask :meth:`~sweet_tea.registry.Registry.typed_candidates` for that
    enumeration instead.

    Event-loop affinity applies here exactly as it does to ``SingletonFactory``; see
    that class's docstring. Narrowing on a type says nothing about which event loop an
    instance's resources belong to.
    """

    @classmethod
    def create(
        cls,
        key: str,
        library: str = "",
        label: str = "",
        configuration: dict[str, Any] | BaseModel | None = None,
    ) -> T:
        """
        Get the singleton instance of a registered subclass of the generic type.

        Behaves as :meth:`SingletonFactory.create` in every respect — lazy
        initialisation, one constructing thread per key, the configuration from the
        first call winning, and a reset landing mid-construction being honoured — and
        differs only in narrowing the candidates to subclasses of the bound type and in
        saying so in the return type.

        Args:
            key: Name to reference the class from the registry.
            library: Optional library filter for the class.
            label: Optional label filter for the class.
            configuration: Configuration parameters as keyword arguments, given as a
                dict or a pydantic model whose fields are spread into the constructor.
                Applied only when this call is the one that constructs; a later call
                passing a different configuration is warned about rather than rebuilt.

        Returns:
            The singleton instance, typed as the bound type.

        Raises:
            SweetTeaError: When the key is not found, no candidate is a subclass of the
                bound type, the filters do not match, the factory has not been
                parameterized, or the key is already being constructed by a thread this
                call would deadlock against.
        """
        # Deliberately nothing but a call up and a narrower return type. Every line of
        # the singleton guarantee -- the cache, the per-key construction lock, the
        # cycle detection, the commit token -- is subtle enough that reproducing any of
        # it here to add a type would be the wrong trade. The narrowing is applied in
        # _find_entries instead, which is the one step this class needs to change.
        return super().create(key, library, label, configuration)

    @classmethod
    def pop(cls, key: str, library: str = "", label: str = "") -> T:
        """
        Remove and return the cached instance, narrowed to the bound type.

        As :meth:`SingletonFactory.pop`, except that the key resolves against subclasses
        of the bound type, so this removes the instance :meth:`create` would have
        returned rather than whatever else shares the key.

        Args:
            key: The key of the instance to remove, in any supported spelling.
            library: Optional library filter, matching the one passed to create.
            label: Optional label filter, matching the one passed to create.

        Returns:
            The removed instance, typed as the bound type.

        Raises:
            SweetTeaError: When no instance is cached for the key, or the factory has
                not been parameterized.
        """
        return super().pop(key, library, label)

    @classmethod
    def _find_entries(
        cls, key: str, candidates: list[Entry] | None = None
    ) -> list[Entry]:
        """
        Find candidate entries for a key, narrowed to subclasses of the bound type.

        Overriding this rather than :meth:`create` is what lets the whole singleton
        machinery be reused untouched: ``create`` and ``pop`` both reach the registry
        through here, so both narrow, and they narrow identically — which is the
        property that matters, since a ``pop`` that resolved differently from ``create``
        would remove an instance the caller never asked about.

        Args:
            key: The requested key, in any supported spelling.
            candidates: Entries to search. When a caller has already narrowed and
                resolved, that work is honoured rather than repeated.

        Returns:
            Matching entries that are subclasses of the bound type, or an empty list.

        Raises:
            SweetTeaError: When the factory has not been parameterized.
        """
        if candidates is None:
            # Resolve before filtering by type, for the reason given in AbstractFactory:
            # a lazy entry has no class object, so it cannot answer issubclass until its
            # module is imported. Doing it here keeps it where it already happened --
            # the base implementation resolves at exactly this point when it is handed
            # no candidates -- so this adds a filter rather than an import.
            cls._resolve_for(key)
            candidates = cls._registry.typed_entries(
                lookup_type=cls._get_generic_type()
            )

        return super()._find_entries(key, candidates=candidates)
