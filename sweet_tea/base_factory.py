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

import re
from typing import Type

from sweet_tea.registry import Registry


class BaseFactory:
    """
    Base factory class with common functionality for key handling and registry access.

    Provides shared methods for key variation generation and registry access
    used by Factory and SingletonFactory.
    """

    _registry: Type[Registry] = Registry

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
