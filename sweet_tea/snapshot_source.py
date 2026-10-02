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
import importlib.util
import os
import sys

from pydantic import BaseModel, Field


class SnapshotSource(BaseModel):
    """
    A tree that was walked to build a snapshot, with a digest of its sources.

    A stale snapshot is worse than walking the tree again, so a snapshot records what
    it was built from and can be checked against the files on disk.

    Where that tree is gets recorded twice, because the two answers serve different
    lives. The absolute :attr:`path` is where it sat when the snapshot was written —
    useful only to the machine that wrote it. :attr:`relative_path` is the same
    directory expressed against its root package's own directory, and that is what
    survives being shipped: a snapshot built in CI under ``/home/runner/work/...`` and
    installed into a consumer's ``site-packages`` is still describing the same tree, so
    checking it against the CI directory would call every shipped snapshot stale
    (SWE-18). The digest is unchanged by all this; only how the directory is located.
    """

    module: str = Field(
        description="Dotted module path the fill started from",
        examples=["mypkg"],
    )

    path: str = Field(
        description="Directory that was walked, as it was when the snapshot was "
        "written; used only when the root package cannot be located",
        examples=["/srv/app/mypkg"],
    )

    relative_path: str = Field(
        default="",
        description="Directory that was walked, relative to the root package's own "
        "directory; empty when it could not be expressed that way",
        examples=[".", "sub"],
    )

    digest: str = Field(
        description="Hex digest over the Python sources found under path",
    )

    @property
    def root_module(self) -> str:
        """
        The top-level package of :attr:`module`.

        The root is what gets located, never the dotted module itself: locating
        ``mypkg.sub`` would execute ``mypkg/__init__.py``, and nothing about reading a
        snapshot may run consumer code.

        Returns:
            First dotted component of the module path.
        """
        return self.module.partition(".")[0]

    @staticmethod
    def root_directories(root_module: str) -> tuple[str, ...]:
        """
        Where a root package's own directory is now, without executing anything.

        An already-imported package is asked for its ``__path__`` directly; otherwise
        :func:`importlib.util.find_spec` is used, which for a top-level name consults
        the meta path finders and neither executes nor caches the module. A namespace
        package legitimately reports several directories, so all of them come back in
        search order.

        Args:
            root_module: Top-level package name.

        Returns:
            Candidate directories, empty when the package cannot be located.
        """
        imported = sys.modules.get(root_module)
        locations = getattr(imported, "__path__", None)
        if locations is None:
            try:
                spec = importlib.util.find_spec(root_module)
            except (ImportError, AttributeError, TypeError, ValueError):
                # A broken or spec-less entry in sys.modules is not a reason to fail a
                # staleness check; it just means the recorded path is all we have.
                return ()
            locations = spec.submodule_search_locations if spec is not None else None
        if locations is None:
            return ()
        return tuple(str(location) for location in locations)

    @classmethod
    def relative_to_root(cls, module: str, path: str) -> str:
        """
        Express a walked directory against its root package's directory.

        Args:
            module: Dotted module path the fill started from.
            path: Directory that was walked.

        Returns:
            The directory relative to its root package — ``"."`` when it is the root
            itself — or an empty string when the root cannot be located or the walked
            tree lies outside it, in which case only the absolute path means anything.
        """
        walked = os.path.realpath(path)
        for directory in cls.root_directories(module.partition(".")[0]):
            root = os.path.realpath(directory)
            if walked == root or walked.startswith(root + os.sep):
                return os.path.relpath(walked, root)
        return ""

    def resolved_path(self) -> str:
        """
        The directory this source should be checked against, located now.

        Returns:
            The recorded relative directory resolved against the installed root
            package, or :attr:`path` when there is no relative record, the package
            cannot be located, or it no longer holds that directory.
        """
        if self.relative_path:
            for directory in self.root_directories(self.root_module):
                candidate = os.path.normpath(
                    os.path.join(directory, self.relative_path)
                )
                if os.path.isdir(candidate):
                    return candidate
        return self.path

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

        The tree is looked for where the package is installed now rather than where it
        was exported from, so relocation alone is not a change. Everything else is:
        a package that cannot be found anywhere is still gone, and sources that hash
        differently are still different.

        Returns:
            True when the directory is gone or its sources have changed.
        """
        located = self.resolved_path()
        if not os.path.isdir(located):
            return True
        return self.digest_of(located) != self.digest
