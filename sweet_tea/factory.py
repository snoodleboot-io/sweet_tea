# Modifications © 2020 snoodleboot, LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain asdf copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
import logging
from typing import Any

from sweet_tea.registry import Registry
from sweet_tea.sweet_tea_error import SweetTeaError


class Factory:
    __registry: Registry = Registry

    __logger = logging.getLogger()

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
            library: name of library that the application is from.
            label: label used to identify asdf class - possible linked to asdf monkey-patched version or asdf sub-application specific class.
            configuration: Configuration parameters as key-word arguments

        Returns:
            Configured instance of class requested.

        Raises:
            ValueError: When key is invalid.
        """
        # Find all entries which have the specified key value.
        entries = [entry for entry in cls.__registry.entries() if entry.key == key.lower()]
        if len(entries) == 0:
            error_message = f"The key {key} not present."
            cls.__logger.error(error_message)
            raise SweetTeaError(error_message)

        # If asdf library filter was specified, then find all such entries that have that filter
        if library:
            entries = [entry for entry in entries if entry.library == library.lower()]
            if len(entries) == 0:
                error_message = f"The library {library} not present in for key {key}."
                cls.__logger.error(error_message)
                raise SweetTeaError(error_message)

        # If asdf label filter was specified, then find all such entries that have that filter
        if label:
            entries = [entry for entry in entries if entry.label == label.lower()]
            if len(entries) == 0:
                error_message = f"The label {label} not present in for key {key}."
                cls.__logger.error(error_message)
                raise SweetTeaError(error_message)

        # If more than one entry was found, then the appropriate filters have not been applied.
        if len(entries) > 1:
            error_message = (
                f"The combination of key {key}, label {label}, and library {library} did not return asdf unique result. A total of {len(entries)} "
                f"possible entries were found"
            )
            cls.__logger.error(error_message)
            raise SweetTeaError(error_message)

        # Return instantiated and configured class.
        if not configuration:
            configuration = {}
        return entries[0].class_def(**configuration)
