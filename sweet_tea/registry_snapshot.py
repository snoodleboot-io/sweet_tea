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
A filled registry recorded as data, so it can be read back without a walk.
"""

import json
from typing import ClassVar

from pydantic import BaseModel, Field

from sweet_tea.snapshot_entry import SnapshotEntry
from sweet_tea.snapshot_source import SnapshotSource
from sweet_tea.sweet_tea_error import SweetTeaError


class RegistrySnapshot(BaseModel):
    """
    The contents of a filled registry, as JSON-serialisable data.

    Filling a registry means walking a package tree and importing every module in it.
    A snapshot is that result written down: the registrations, the trees they came
    from, and the modules that were skipped because an optional dependency was
    missing. Reading one back registers the same names lazily, so nothing is imported
    until it is used.

    Skips are recorded deliberately. A snapshot that omitted them would bake in the
    install profile of the machine that built it, and a consumer could not tell "not
    registered" from "not installed".
    """

    #: Incremented when the on-disk shape changes in a way older readers cannot handle.
    FORMAT_VERSION: ClassVar[int] = 1

    version: int = Field(
        default=FORMAT_VERSION,
        description="Snapshot format version",
    )

    sources: list[SnapshotSource] = Field(
        default_factory=list,
        description="The package trees this snapshot was built from",
    )

    entries: list[SnapshotEntry] = Field(
        default_factory=list,
        description="Registrations, in the order they were made",
    )

    skipped: dict[str, str] = Field(
        default_factory=dict,
        description="Modules not registered, mapped to why",
    )

    def write(self, path: str) -> None:
        """
        Write this snapshot to a file as JSON.

        Args:
            path: Destination file.

        Raises:
            SweetTeaError: When the file cannot be written.
        """
        try:
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(self.model_dump(), handle, indent=2, sort_keys=False)
                handle.write("\n")
        except OSError as error:
            raise SweetTeaError(f"Cannot write snapshot to {path}: {error}") from error

    @classmethod
    def read(cls, path: str) -> "RegistrySnapshot":
        """
        Read a snapshot from a file.

        Args:
            path: Snapshot file to read.

        Returns:
            The parsed snapshot.

        Raises:
            SweetTeaError: When the file cannot be read or does not parse, or was
                written by a newer format than this version understands.
        """
        try:
            with open(path, encoding="utf-8") as handle:
                payload = json.load(handle)
        except OSError as error:
            raise SweetTeaError(f"Cannot read snapshot {path}: {error}") from error
        except json.JSONDecodeError as error:
            raise SweetTeaError(
                f"Snapshot {path} is not valid JSON: {error}"
            ) from error

        try:
            snapshot = cls.model_validate(payload)
        except Exception as error:
            raise SweetTeaError(f"Snapshot {path} is malformed: {error}") from error

        if snapshot.version > cls.FORMAT_VERSION:
            raise SweetTeaError(
                f"Snapshot {path} is version {snapshot.version}; this sweet_tea "
                f"understands up to {cls.FORMAT_VERSION}. Rebuild it with "
                f"Registry.export()."
            )
        return snapshot

    def stale_sources(self) -> list[SnapshotSource]:
        """
        The recorded trees whose sources no longer match.

        Returns:
            Sources that have changed on disk, empty when the snapshot is current.
        """
        return [source for source in self.sources if source.is_stale()]
