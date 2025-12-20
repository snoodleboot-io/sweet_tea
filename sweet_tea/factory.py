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
"""
Base factory implementation for instantiating registered classes.
"""
import logging
from typing import Any

from sweet_tea.entry import Entry
from sweet_tea.registry import Registry
from sweet_tea.sweet_tea_error import SweetTeaError


class Factory:
    """
    Base factory class for creating instances of registered classes.

    This factory provides the core functionality for instantiating classes
    from the registry with optional filtering by library and label.
    """

    _registry: Registry = Registry

    _logger = logging.getLogger(__name__)

    @classmethod
    def create(
        cls,
        key: str,
        library: str | None = None,
        label: str | None = None,
        configuration: dict | None = None,
    ) -> Any:
        """
        Create an instance of a registered class.

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
        # Find all entries that have the specified key value.
        entries = [entry for entry in cls._registry.entries() if entry.key == key.lower()]

        return cls._create_from_entries(entries, key, library, label, configuration)

    @classmethod
    def _create_from_entries(cls, entries: list[Entry], key: str, library: str | None, label: str | None, configuration: dict | None) -> Any:
        """
        Create an instance from a filtered list of entries.

        Args:
            entries: List of candidate entries.
            key: The requested key.
            library: Optional library filter.
            label: Optional label filter.
            configuration: Configuration parameters.

        Returns:
            Instantiated and configured class instance.

        Raises:
            SweetTeaError: When no matching entry is found or multiple entries remain after filtering.
        """
        if len(entries) == 0:
            error_message = f"The key {key} not present."
            cls._logger.error(error_message)
            raise SweetTeaError(error_message)

        # If a library filter was specified, filter entries by library
        if library:
            entries = [entry for entry in entries if entry.library == library.lower()]
            if len(entries) == 0:
                error_message = f"The library {library} not present for key {key}."
                cls._logger.error(error_message)
                raise SweetTeaError(error_message)

        # If a label filter was specified, filter entries by label
        if label:
            entries = [entry for entry in entries if entry.label == label.lower()]
            if len(entries) == 0:
                error_message = f"The label {label} not present for key {key}."
                cls._logger.error(error_message)
                raise SweetTeaError(error_message)

        # If more than one entry remains, the filters are insufficient
        if len(entries) > 1:
            error_message = (
                f"The combination of key {key}, label {label}, and library {library} did not return "
                f"a unique result. A total of {len(entries)} possible entries were found."
            )
            cls._logger.error(error_message)
            raise SweetTeaError(error_message)

        # Return instantiated and configured class
        if not configuration:
            configuration = {}
        return entries[0].class_def(**configuration)
