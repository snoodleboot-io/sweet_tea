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
Generic type parameterization shared by the abstract factories.

Provides the machinery that binds a generic type parameter to a factory, so that
``SomeFactory[MyBaseClass]`` resolves against ``MyBaseClass`` and nothing else.
"""

import threading
from typing import Any, Type, TypeVar

from sweet_tea.sweet_tea_error import SweetTeaError

T = TypeVar("T")


class TypeParameterizedFactory:
    """
    Binds a generic type parameter to a distinct subclass per parameterization.

    Subscripting (``SomeFactory[MyBaseClass]``) returns a genuine, cached subclass
    carrying its own ``_type`` attribute, rather than a ``typing`` alias.

    Why a real subclass is required:
        ``typing._GenericAlias`` forwards attribute reads *and writes* through to
        its ``__origin__``. Assigning ``_type`` onto an alias therefore lands on
        the shared origin class, so every parameterization in the process
        overwrites the same attribute and the last subscription silently wins.
        Attribute access through an alias also resolves to the *origin's* bound
        method, meaning ``cls`` inside a classmethod is the origin and can never
        observe which parameterization was used. A real subclass is the only
        construct that makes ``cls`` carry the bound type (see SWE-1).

    Thread-safe: parameterization is synchronized, so concurrent subscription of
    the same type yields one shared subclass and ``Factory[X] is Factory[X]``
    holds.
    """

    # Sentinel until parameterized. Each generated subclass shadows this with a
    # concrete type in its own __dict__, which is what keeps parameterizations
    # isolated from one another.
    _type: Any = T

    # Cache of (owner class, bound type) -> generated subclass. The owner is part
    # of the key so AbstractFactory[X] and AbstractInverterFactory[X] stay
    # distinct, and so identity is preserved across repeated subscriptions.
    __parameterizations: dict[tuple[type, type], type] = {}

    # Threading lock guarding the parameterization cache.
    __lock = threading.RLock()

    @classmethod
    def __class_getitem__(cls, item: Any) -> Any:
        """
        Create (or return the cached) parameterized subclass for the given type.

        Args:
            item: The base type to bind. Non-type arguments (TypeVars, tuples,
                and other typing constructs) fall through to standard typing
                behavior so generic class definitions keep working.

        Returns:
            A subclass of ``cls`` whose ``_type`` is ``item``, or a typing alias
            when ``item`` is not a concrete type.
        """
        # A TypeVar arrives here while a generic subclass body is being evaluated
        # (e.g. `class Foo(TypeParameterizedFactory, Generic[T])`). Those must keep
        # standard typing behavior rather than producing a bogus subclass.
        if not isinstance(item, type):
            return super().__class_getitem__(item)  # type: ignore[misc]

        cache_key = (cls, item)

        with cls.__lock:
            parameterized = cls.__parameterizations.get(cache_key)
            if parameterized is None:
                parameterized = type(
                    f"{cls.__name__}[{item.__name__}]",
                    (cls,),
                    {"_type": item},
                )
                cls.__parameterizations[cache_key] = parameterized
            return parameterized

    @classmethod
    def _get_generic_type(cls) -> Type[T]:
        """
        Get the generic type parameter bound to this parameterization.

        Returns:
            The type this factory was parameterized with.

        Raises:
            SweetTeaError: When the factory has not been parameterized.
        """
        if isinstance(cls._type, TypeVar):
            error_message = (
                f"{cls.__name__} is not parameterized. Subscript it with a base type "
                f"before use, e.g. {cls.__name__}[MyBaseClass].create('my_key')."
            )
            raise SweetTeaError(error_message)
        return cls._type
