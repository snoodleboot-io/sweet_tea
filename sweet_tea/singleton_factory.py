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
Singleton factory for registering and retrieving pre-configured instances.

This factory provides a service locator pattern where pre-configured instances
(singletons) can be registered and retrieved by key. Unlike the regular Factory
which creates new instances each time, SingletonFactory returns the same
registered instance.
"""

import logging
import threading
from typing import Any, Dict

from sweet_tea.base_factory import BaseFactory
from sweet_tea.factory import Factory
from sweet_tea.sweet_tea_error import SweetTeaError


class SingletonFactory(BaseFactory):
    """
    Factory for registering and retrieving singleton instances.

    This implements the service locator pattern where pre-configured instances
    can be registered once and retrieved multiple times. This is useful for:

    - Singleton services that should only exist once
    - Pre-configured database connections
    - Dependency injection containers
    - Caching expensive-to-create objects

    Thread-safe: All operations are synchronized to prevent race conditions.
    """

    # Threading lock for synchronizing operations
    __lock = threading.RLock()

    # Registry of singleton instances
    __instances: Dict[str, Any] = {}

    # Logger instance
    _logger = logging.getLogger(__name__)

    @classmethod
    def create(
        cls,
        key: str,
        library: str = "",
        label: str = "",
        configuration: dict[str, Any] | None = None,
    ) -> Any:
        """
        Get an existing singleton instance or create a new one if it doesn't exist.

        This method provides lazy initialization - instances are created only when first requested.
        Subsequent calls with the same key will return the same cached instance.

        Args:
            key: Name to reference the class from the registry.
            library: Optional library filter for the class.
            label: Optional label filter for the class.
            configuration: Configuration parameters as keyword arguments.

        Returns:
            The existing singleton instance, or a newly created and registered instance.

        Raises:
            SweetTeaError: If the key is not found in the registry or filters don't match.
        """
        # Find the normalized key using the same logic as Factory
        key_variations = cls._generate_key_variations(key)
        normalized_key = key_variations[0] if key_variations else key.lower()

        with cls.__lock:
            # Return existing instance if available
            if normalized_key in cls.__instances:
                return cls.__instances[normalized_key]

            # Create new instance using the regular Factory
            new_instance = Factory.create(
                key=key, library=library, label=label, configuration=configuration
            )

            # Register the new instance as a singleton
            cls.__instances[normalized_key] = new_instance
            cls._logger.info(f"Created and registered singleton instance: {key}")

            return new_instance

    @classmethod
    def clear(cls) -> None:
        """
        Remove all registered instances.

        This is primarily useful for testing or resetting the factory state.
        """
        with cls.__lock:
            count = len(cls.__instances)
            cls.__instances.clear()
            cls._logger.info(f"Cleared {count} singleton instances")

    @classmethod
    def pop(cls, key: str) -> Any:
        """
        Remove and return a registered instance.

        This removes the instance and all its key variations from the registry,
        ensuring complete cleanup of the singleton.

        Args:
            key: The key of the instance to remove.

        Returns:
            The removed instance.

        Raises:
            SweetTeaError: If no instance is registered for the given key.
        """
        # Find all key variations that could match
        key_variations = cls._generate_key_variations(key)

        with cls.__lock:
            # Find which variation actually has the instance
            instance = None
            found_key = None

            for variation in key_variations:
                if variation in cls.__instances:
                    instance = cls.__instances[variation]
                    found_key = variation
                    break

            if instance is None:
                available_keys = list(cls.__instances.keys())
                raise SweetTeaError(
                    f"No singleton instance registered for key '{key}'. "
                    f"Available keys: {available_keys}"
                )

            # Remove all variations that could match this instance
            # This ensures complete cleanup of the singleton
            for variation in key_variations:
                if variation in cls.__instances:
                    del cls.__instances[variation]

            # Python's garbage collector will handle destruction automatically
            # when all references are removed

            cls._logger.info(f"Removed singleton instance: {key} (key: {found_key})")
            return instance

    @classmethod
    def list_keys(cls) -> list[str]:
        """
        Get a list of all class keys that can be created.

        Returns:
            List of available class keys from the registry in alphabetical order.
        """
        # Return keys from the Registry that can be created
        entries = cls._registry.entries()
        return sorted([entry.key for entry in entries])

    @classmethod
    def list_singletons(cls) -> list[str]:
        """
        Get a list of all cached singleton instance keys.

        Returns:
            List of registered singleton keys in alphabetical order.
        """
        with cls.__lock:
            return sorted(cls.__instances.keys())
