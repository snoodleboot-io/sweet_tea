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
Abstract factory implementation with generic type constraints.

This factory allows instantiation of classes that are subclasses of a specified
generic type, enabling type-safe factory patterns.
"""

from typing import Any, Generic, TypeVar

from sweet_tea.factory import Factory
from sweet_tea.type_parameterized_factory import TypeParameterizedFactory

T = TypeVar("T")


class AbstractFactory(TypeParameterizedFactory, Generic[T], Factory):
    """
    A generic factory that constrains instantiation to subclasses of type T.

    Usage:
        factory = AbstractFactory[MyBaseClass]
        instance = factory.create('my_key')
        # Only classes inheriting from MyBaseClass will be available

    Each parameterization is an independent subclass, so several may be held and
    used in any order without interfering with one another.
    """

    @classmethod
    def create(
        cls,
        key: str,
        library: str = "",
        label: str = "",
        configuration: dict[str, Any] | None = None,
    ) -> T:
        """
        Create an instance of a registered class that is a subclass of the generic type.

        Args:
            key: Name to reference the class from the registry.
            library: Optional library filter for the class.
            label: Optional label filter for the class.
            configuration: Configuration parameters as keyword arguments.

        Returns:
            Configured instance of the requested class.

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

        return cls._create_from_entries(entries, key, library, label, configuration)
