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
Registry entry model for storing class registration information.
"""

from pydantic import BaseModel, Field


class Entry(BaseModel):
    """
    A registry entry containing information about a registered class.

    Each entry represents a class that has been registered with the factory system,
    including metadata for filtering and instantiation.
    """

    key: str = Field(
        description="Lowercase key used to reference this class for instantiation",
        examples=["myclass", "databaseconnection"],
    )

    class_def: type | None = Field(
        default=None,
        description=(
            "The actual class type that can be instantiated, or None while the entry "
            "is registered lazily and its module has not been imported yet"
        ),
    )

    library: str = Field(
        default="",
        description="Name of the library or module group this class belongs to",
        examples=["mylib", "database"],
    )

    label: str = Field(
        default="",
        description="Optional label for categorizing classes (e.g., by environment or feature set)",
        examples=["production", "testing", "v2"],
    )

    module: str = Field(
        default="",
        description="Dotted module path holding the class, set only for lazy entries",
        examples=["mypkg.services.database"],
    )

    attribute: str = Field(
        default="",
        description="Module attribute the class is bound to, set only for lazy entries",
        examples=["DatabaseConnection"],
    )

    @property
    def is_lazy(self) -> bool:
        """Whether this entry still needs its module imported before use."""
        return self.class_def is None

    @property
    def identity(self) -> tuple[str, object, str, str]:
        """
        The four values that decide whether two registrations are duplicates.

        Mirrors what ``Entry.__eq__`` compares for eager entries. A lazy entry has no
        class object yet, so it identifies its target by ``module:attribute`` instead
        — which also means a lazy and an eager registration of one class do not
        collapse into a single entry (see SWE-10).
        """
        target: object = (
            self.class_def
            if self.class_def is not None
            else f"{self.module}:{self.attribute}"
        )
        return (self.key, target, self.library, self.label)
