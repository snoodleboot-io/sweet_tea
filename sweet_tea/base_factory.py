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
Base factory class with common functionality for key handling and registry access.
"""

import logging
import re
from typing import Type

from sweet_tea.entry import Entry
from sweet_tea.registry import Registry
from sweet_tea.sweet_tea_error import SweetTeaError


class BaseFactory:
    """
    Base factory class with common functionality for key handling and registry access.

    Provides shared methods for key variation generation and registry access
    used by Factory and SingletonFactory.
    """

    _registry: Type[Registry] = Registry

    _logger = logging.getLogger(__name__)

    @classmethod
    def _generate_key_variations(cls, key: str) -> list[str]:
        """
        Generate key variations for flexible class name matching.

        Since registry keys are stored in lowercase, this generates multiple
        normalized variations of the input key to match against stored keys.

        Args:
            key: The input key to generate variations for.

        Returns:
            List of normalized key variations to try, in order of preference.
        """
        variations = []
        lower_key = key.lower()

        # Always try the exact lowercase version first
        variations.append(lower_key)

        # Try converting camelCase to snake_case (e.g., "MyClass" -> "my_class")
        def camel_to_snake(s):
            # Insert underscore between lowercase and uppercase
            s = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s)
            # Insert underscore between uppercase sequences
            s = re.sub(r"([A-Z])([A-Z][a-z])", r"\1_\2", s)
            return s.lower()

        snake_case = camel_to_snake(key)
        if snake_case not in variations:
            variations.append(snake_case)

        # Try removing underscores (e.g., "my_class" -> "myclass")
        no_underscores = lower_key.replace("_", "")
        if no_underscores not in variations:
            variations.append(no_underscores)

        # Try removing "class" suffix (e.g., "myclass" -> "my")
        if lower_key.endswith("class") and len(lower_key) > 5:
            without_class = lower_key[:-5]
            if without_class not in variations:
                variations.append(without_class)

        if lower_key.endswith("_class") and len(lower_key) > 6:
            without_class = lower_key[:-6]
            if without_class not in variations:
                variations.append(without_class)

        # Special case: if the key looks like it should have underscores
        # (consecutive capitals), add that variation
        if re.search(r"[A-Z]{2,}", key):
            with_underscores = camel_to_snake(key)
            if with_underscores not in variations:
                variations.append(with_underscores)

        return variations

    @classmethod
    def _find_entries(
        cls, key: str, candidates: list[Entry] | None = None
    ) -> list[Entry]:
        """
        Find candidate entries whose key matches any variation of the requested key.

        Variations are tried in order and the first that matches anything wins, so an
        exact match takes precedence over a looser one.

        Args:
            key: The requested key, in any supported spelling.
            candidates: Entries to search. Defaults to the whole registry; the
                type-constrained factories pass a pre-filtered list.

        Returns:
            Matching entries, or an empty list when no variation matches.
        """
        pool = cls._registry.entries() if candidates is None else candidates

        for variation in cls._generate_key_variations(key):
            matched = [entry for entry in pool if entry.key == variation]
            if matched:
                return matched

        return []

    @classmethod
    def _select_entry(
        cls, entries: list[Entry], key: str, library: str, label: str
    ) -> Entry:
        """
        Narrow candidate entries to exactly one, applying the optional filters.

        This is the single resolution path for every factory. Keeping it in one place
        is what lets SingletonFactory cache against the same entry that Factory would
        have instantiated (see SWE-5).

        Args:
            entries: Candidate entries from :meth:`_find_entries`.
            key: The requested key, used only for error messages.
            library: Library filter; an empty string applies no filter.
            label: Label filter; an empty string applies no filter.

        Returns:
            The single matching entry.

        Raises:
            SweetTeaError: When nothing matches, or when the filters leave more than one.
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

        return entries[0]
