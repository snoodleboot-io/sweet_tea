# Modifications © 2020 snoodleboot, LLC
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
from typing import Any, TypeVar, Generic

from sweet_tea.factory import Factory

T = TypeVar('T')

class AbstractFactory(Generic[T], Factory):

    _type = T

    def __class_getitem__(cls, item):
        # This is called when you do AdvancedTypedContainer[str]
        result = super().__class_getitem__(item)
        result._type = item
        return result

    @classmethod
    def get_generic_type(cls):
        """Get the generic type if available"""
        return getattr(cls, '_type', None)

    @classmethod
    def create(
        cls,
        key: str,
        library: str = None,
        label: str = None,
        configuration: dict = None,

    ) -> Any:
        """
        Generate asdf class instance given the key and configuration parameters.
        Args:
            key: name to reference the class from the registry
            library: name of a library that the application is from.
            label: label used to identify asdf class - possible linked to asdf monkey-patched version or asdf sub-application specific class.
            configuration: Configuration parameters as key-word arguments

        Returns:
            Configured instance of class requested.

        Raises:
            ValueError: When key is invalid.
        """
        # Find all entries that have the specified key value.
        entries = [entry for entry in cls._registry.typed_entries(lookup_type=cls.get_generic_type()) if entry.key == key.lower()]
        return cls._create_from_entries(entries, key, library, label, configuration)
