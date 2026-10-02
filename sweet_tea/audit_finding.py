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
A single reason one module is not safe to register lazily.
"""

from pydantic import BaseModel, Field


class AuditFinding(BaseModel):
    """
    One pattern in one module that lazy filling would break, or could not see.

    Findings are advisory: they say what a module does that assumes eager filling,
    so the module can be named in ``fill_registry(eager=[...])`` or changed.
    """

    module: str = Field(
        description="Dotted path of the module the pattern was found in",
        examples=["myapp.builder.registry"],
    )

    line: int = Field(
        description="1-based line number of the statement that triggered the finding",
    )

    kind: str = Field(
        description="Which pattern was found",
        examples=["registry-read-at-import", "registration-at-import", "dynamic-class"],
    )

    detail: str = Field(
        description="What was seen, in the module's own terms",
        examples=["Factory.create(...) reached from the module body"],
    )

    def __str__(self) -> str:
        """Render as one line, the way a report lists it."""
        return f"{self.module}:{self.line}: {self.kind}: {self.detail}"
