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

from sweet_tea.factory import Factory
from sweet_tea.registry import Registry
from sweet_tea.sweet_tea_error import SweetTeaError


class SingletonFactory:
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
    def register(cls, key: str, instance: Any, allow_override: bool = False) -> None:
        """
        Register a singleton instance.

        Args:
            key: Unique identifier for the instance.
            instance: The pre-configured instance to register.
            allow_override: If True, allows overwriting existing instances.

        Raises:
            SweetTeaError: If key already exists and allow_override is False.
        """
        normalized_key = key.lower()

        with cls.__lock:
            if normalized_key in cls.__instances and not allow_override:
                raise SweetTeaError(
                    f"Instance with key '{key}' is already registered. "
                    "Use allow_override=True to replace it."
                )

            cls.__instances[normalized_key] = instance
            cls._logger.info(f"Registered singleton instance: {key}")

    @classmethod
    def get(cls, key: str) -> Any:
        """
        Retrieve a registered singleton instance.

        Args:
            key: The key of the instance to retrieve.

        Returns:
            The registered instance.

        Raises:
            SweetTeaError: If no instance is registered for the given key.
        """
        normalized_key = key.lower()

        with cls.__lock:
            if normalized_key not in cls.__instances:
                available_keys = list(cls.__instances.keys())
                raise SweetTeaError(
                    f"No singleton instance registered for key '{key}'. "
                    f"Available keys: {available_keys}"
                )

            return cls.__instances[normalized_key]

    @classmethod
    def has(cls, key: str) -> bool:
        """
        Check if an instance is registered for the given key.

        Args:
            key: The key to check.

        Returns:
            True if an instance is registered, False otherwise.
        """
        normalized_key = key.lower()

        with cls.__lock:
            return normalized_key in cls.__instances

    @classmethod
    def unregister(cls, key: str) -> bool:
        """
        Remove a registered instance.

        Args:
            key: The key of the instance to remove.

        Returns:
            True if an instance was removed, False if key didn't exist.
        """
        normalized_key = key.lower()

        with cls.__lock:
            if normalized_key in cls.__instances:
                del cls.__instances[normalized_key]
                cls._logger.info(f"Unregistered singleton instance: {key}")
                return True
            return False

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
        normalized_key = key.lower()

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

        Args:
            key: The key of the instance to remove.

        Returns:
            The removed instance.

        Raises:
            SweetTeaError: If no instance is registered for the given key.
        """
        normalized_key = key.lower()

        with cls.__lock:
            if normalized_key not in cls.__instances:
                available_keys = list(cls.__instances.keys())
                raise SweetTeaError(
                    f"No singleton instance registered for key '{key}'. "
                    f"Available keys: {available_keys}"
                )

            instance = cls.__instances[normalized_key]
            del cls.__instances[normalized_key]
            cls._logger.info(f"Removed singleton instance: {key}")
            return instance

    @classmethod
    def list_keys(cls) -> list[str]:
        """
        Get a list of all class keys that can be created.

        Returns:
            List of available class keys from the registry in alphabetical order.
        """
        # Return keys from the Registry that can be created
        entries = Registry.entries()
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

    @classmethod
    def count(cls) -> int:
        """
        Get the number of registered instances.

        Returns:
            Number of registered singleton instances.
        """
        with cls.__lock:
            return len(cls.__instances)
