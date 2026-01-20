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
Abstract inverter factory implementation with generic type constraints.

This factory combines the type constraints of AbstractFactory with the
class-definition-returning behavior of InverterFactory. It allows instantiation
of class definitions that are subclasses of a specified generic type, enabling
type-safe factory patterns for lazy construction scenarios.
"""

from typing import Any, Generic, Type, TypeVar

from sweet_tea.inverter_factory import InverterFactory

T = TypeVar("T")


class AbstractInverterFactory(Generic[T], InverterFactory):
    """
    A generic inverter factory that constrains class retrieval to subclasses of type T.

    Usage:
        factory = AbstractInverterFactory[MyBaseClass]
        class_def = factory.create('my_key')
        # Only classes inheriting from MyBaseClass will be available
        instance = class_def(**kwargs)  # Instantiate when ready
    """

    _type = T  # type: ignore[misc]

    @classmethod
    def __class_getitem__(cls, item: Type[T]) -> Type["AbstractInverterFactory[T]"]:
        """Create a parameterized generic subclass with the specified type."""
        result = super().__class_getitem__(item)  # type: ignore[attr-defined,misc]
        result._type = item  # type: ignore[misc]
        return result

    @classmethod
    def _get_generic_type(cls) -> Type[T]:
        """Get the generic type parameter."""
        return cls._type

    @classmethod
    def create(
        cls,
        key: str,
        library: str = "",
        label: str = "",
    ) -> Type[Any]:
        """
        Retrieve the class definition for a registered class that is a subclass of the generic type.

        Args:
            key: Name to reference the class from the registry.
            library: Optional library filter for the class.
            label: Optional label filter for the class.

        Returns:
            The class definition that can be instantiated by the caller.

        Raises:
            SweetTeaError: When the key is not found or filters don't match.
        """
        # Find all entries that have the specified key value and match the generic type
        entries = []
        key_variations = cls._generate_key_variations(key)
        typed_entries = cls._registry.typed_entries(lookup_type=cls._get_generic_type())

        for variation in key_variations:
            entries.extend([entry for entry in typed_entries if entry.key == variation])
            if entries:  # Found entries with this variation
                break

        return cls._create_from_entries(entries, key, library, label)
