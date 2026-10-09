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
One registry entry as it appears in an exported snapshot.
"""

from pydantic import BaseModel, Field


class SnapshotEntry(BaseModel):
    """
    A registration recorded as plain data, with the class named rather than held.

    ``Entry.class_def`` is a live class and cannot be serialised. Here it becomes
    ``module:attribute`` — the same coordinates a lazily registered entry carries — so
    reading a snapshot back produces lazy entries that resolve on use.

    ``provisional`` travels with the entry because it decides who wins when the module
    is finally imported. A scanned name is a guess and loses to discovery; an explicit
    registration is a request and is kept (SWE-20). Leaving it out of the written form
    made every guess come back as a request, which is the whole of SWE-41.
    """

    key: str = Field(
        description="Lowercase key used to reference this class",
        examples=["myclass", "databaseconnection"],
    )

    class_def: str = Field(
        description="The class as module and attribute, separated by a colon",
        examples=["mypkg.services:DatabaseConnection"],
    )

    library: str = Field(default="", description="Library this class belongs to")

    label: str = Field(default="", description="Label categorising this class")

    provisional: bool = Field(
        default=False,
        description=(
            "True when the name was read out of source rather than asked for, so "
            "discovery overrules it once the module is imported"
        ),
    )

    @property
    def coordinates(self) -> tuple[str, str]:
        """
        The module and attribute halves of :attr:`class_def`.

        Returns:
            (module, attribute).

        Raises:
            ValueError: When the value is not a ``module:attribute`` pair.
        """
        module, separator, attribute = self.class_def.rpartition(":")
        if not separator or not module or not attribute:
            raise ValueError(f"{self.class_def!r} is not a module:attribute reference")
        return module, attribute
