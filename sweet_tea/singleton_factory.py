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

    # Cached instances, keyed by the identity of the registry entry they were built
    # from: (key, library, label). Keying on the resolved entry rather than on the
    # caller's spelling is what makes the singleton guarantee hold — every spelling
    # of one key resolves to the same entry and therefore the same slot (see SWE-5).
    __instances: Dict[tuple[str, str, str], Any] = {}

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
        with cls.__lock:
            # Resolve through the shared path first, so the cache is keyed on the entry
            # that would be instantiated rather than on however the caller spelled it.
            # Resolution happens inside the lock so two threads cannot both miss the
            # cache and each construct an instance.
            entry = cls._select_entry(cls._find_entries(key), key, library, label)
            cache_key = (entry.key, entry.library, entry.label)

            # Return existing instance if available
            if cache_key in cls.__instances:
                return cls.__instances[cache_key]

            new_instance = entry.class_def(**(configuration or {}))

            # Register the new instance as a singleton
            cls.__instances[cache_key] = new_instance
            cls._logger.info(f"Created and registered singleton instance: {entry.key}")

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
    def pop(cls, key: str, library: str = "", label: str = "") -> Any:
        """
        Remove and return a cached instance.

        Resolves through the same path as :meth:`create`, so any spelling of the key
        removes the instance that spelling would have returned.

        Args:
            key: The key of the instance to remove, in any supported spelling.
            library: Optional library filter, matching the one passed to create.
            label: Optional label filter, matching the one passed to create.

        Returns:
            The removed instance.

        Raises:
            SweetTeaError: If no instance is cached for the given key.
        """
        with cls.__lock:
            try:
                entry = cls._select_entry(cls._find_entries(key), key, library, label)
            except SweetTeaError:
                # Unresolvable keys and resolvable-but-uncached ones report the same
                # way; from the caller's side both mean "nothing to remove".
                entry = None

            cache_key = (
                (entry.key, entry.library, entry.label) if entry is not None else None
            )

            if cache_key is None or cache_key not in cls.__instances:
                raise SweetTeaError(
                    f"No singleton instance registered for key '{key}'. "
                    f"Available keys: {cls.list_singletons()}"
                )

            instance = cls.__instances.pop(cache_key)

            # Python's garbage collector will handle destruction automatically
            # when all references are removed

            cls._logger.info(f"Removed singleton instance: {key} (key: {entry.key})")
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
            List of cached singleton keys in alphabetical order. Entries that share a
            key across libraries or labels appear once per cached instance.
        """
        with cls.__lock:
            return sorted(entry_key for entry_key, _, _ in cls.__instances)
