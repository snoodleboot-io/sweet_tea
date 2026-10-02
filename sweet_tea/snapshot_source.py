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
One package tree an exported snapshot was built from.
"""

import hashlib
import os

from pydantic import BaseModel, Field


class SnapshotSource(BaseModel):
    """
    A tree that was walked to build a snapshot, with a digest of its sources.

    A stale snapshot is worse than walking the tree again, so a snapshot records what
    it was built from and can be checked against the files on disk.
    """

    module: str = Field(
        description="Dotted module path the fill started from",
        examples=["mypkg"],
    )

    path: str = Field(
        description="Directory that was walked",
        examples=["/srv/app/mypkg"],
    )

    digest: str = Field(
        description="Hex digest over the Python sources found under path",
    )

    @staticmethod
    def digest_of(path: str) -> str:
        """
        Hash every Python source under a directory.

        Covers file names as well as contents, so adding, renaming or removing a module
        changes the digest. ``__pycache__`` is skipped, since bytecode is derived.

        Excluded modules are hashed too: a snapshot cannot know which patterns a future
        fill will pass, so the digest is deliberately conservative — an edit to a file
        that was never registered still marks the snapshot stale.

        Args:
            path: Directory to hash.

        Returns:
            Hex digest.
        """
        hasher = hashlib.sha256()
        for directory, directory_names, file_names in os.walk(path):
            directory_names[:] = sorted(
                name for name in directory_names if name != "__pycache__"
            )
            for file_name in sorted(file_names):
                if not file_name.endswith(".py"):
                    continue
                full_path = os.path.join(directory, file_name)
                hasher.update(os.path.relpath(full_path, path).encode())
                try:
                    with open(full_path, "rb") as handle:
                        hasher.update(handle.read())
                except OSError:
                    # Unreadable now means a different tree than the one exported.
                    hasher.update(b"<unreadable>")
        return hasher.hexdigest()

    def is_stale(self) -> bool:
        """
        Whether the tree on disk differs from the one this records.

        Returns:
            True when the directory is gone or its sources have changed.
        """
        if not os.path.isdir(self.path):
            return True
        return self.digest_of(self.path) != self.digest
