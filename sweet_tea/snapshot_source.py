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
import importlib.machinery
import importlib.util
import os
import sys
from collections.abc import Iterable
from typing import ClassVar

from pydantic import BaseModel, Field, field_validator


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

    Neither answer is trusted on its own. A root package may report several directories
    — a namespace package reports one per portion — so the directory this source means
    is the candidate whose sources still hash to :attr:`digest`, not simply the first
    one that happens to exist (SWE-28).
    """

    # Every suffix this interpreter's import machinery will load a module from,
    # rather than the ``.py`` the digest used to assume. The fill imports a
    # sourceless ``.pyc`` and a ``.so`` or ``.pyd`` extension as readily as a source
    # file and registers whatever it finds in them, so a digest blind to those files
    # kept vouching for names whose only file had been deleted (SWE-44). Asking the
    # machinery rather than listing suffixes here keeps the two in step: whatever
    # this interpreter can import, the digest covers.
    #
    # Longest first, because the suffixes overlap. A file named
    # ``accel.cpython-313-x86_64-linux-gnu.so`` must resolve to the module ``accel``
    # and not to ``accel.cpython-313-x86_64-linux-gnu`` — the bare ``.so`` matches it
    # too — because that module name is what decides whether a ``.pyc`` beside it is
    # derived. Equal lengths are broken alphabetically rather than left to set order,
    # so the tuple is the same on every run.
    IMPORTABLE_SUFFIXES: ClassVar[tuple[str, ...]] = tuple(
        sorted(
            {
                *importlib.machinery.SOURCE_SUFFIXES,
                *importlib.machinery.BYTECODE_SUFFIXES,
                *importlib.machinery.EXTENSION_SUFFIXES,
            },
            key=lambda suffix: (-len(suffix), suffix),
        )
    )

    # Bytecode is derived from something else unless it is all there is, so these
    # are the suffixes that need that question asked of them (SWE-44).
    BYTECODE_SUFFIXES: ClassVar[frozenset[str]] = frozenset(
        importlib.machinery.BYTECODE_SUFFIXES
    )

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
        description="Hex digest over the importable files found under path",
    )

    @field_validator("relative_path", mode="before")
    @classmethod
    def validate_relative_path(cls, value: object) -> object:
        """
        Treat a null relative record as an absent one, and refuse one that escapes.

        ``null`` and a missing key say the same thing — this snapshot has no relative
        record — so they are treated the same. Rejecting one and accepting the other
        made the reader's verdict depend on which of two equivalent spellings whoever
        wrote the file happened to use.

        An escaping record is a different matter. It is resolved against a directory
        this process locates at load time, so ``"../../../../etc"`` points verification
        at a tree that has nothing to do with the package, and a hand-edited snapshot
        can aim it wherever it likes: where the digest matches, verification passes and
        the snapshot's names are registered unchecked. The relative record only ever
        means "somewhere inside the root package", so anything else is refused here
        rather than normalised out of the package later (SWE-28). An absolute path is
        refused on the same grounds, since it ignores the located root entirely.

        Args:
            value: Raw field value as it appeared in the snapshot.

        Returns:
            The value, with ``None`` normalised to the empty default.

        Raises:
            ValueError: When the path is absolute, or climbs out of the root package.
        """
        if value is None:
            return ""
        if not isinstance(value, str) or not value:
            return value
        if os.path.isabs(value) or os.path.splitdrive(value)[0]:
            raise ValueError(
                f"relative_path {value!r} is absolute; it must name a directory "
                f"inside the root package"
            )
        normalised = os.path.normpath(value)
        if normalised == os.pardir or normalised.startswith(os.pardir + os.sep):
            raise ValueError(
                f"relative_path {value!r} leaves the root package; it must name a "
                f"directory inside it"
            )
        return value

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

    def candidate_paths(self) -> tuple[str, ...]:
        """
        Every directory this source could mean now, in the order to try them.

        The relative record resolved against the root package's own directories comes
        first, because that is the record that survives being shipped. Every one of
        those directories is offered rather than just the first: a namespace package
        reports one per portion, and the exported portion is not reliably the one
        search order puts first. Where one of them still *is* the directory the export
        walked, it goes ahead of its siblings — two portions can hold identical sources
        and then either would satisfy the digest, but it is the exported one whose
        changes this source is recording. The recorded absolute path comes last: it
        means nothing on another machine, and everything on the machine that wrote the
        snapshot, where the tree may not be installed anywhere the root package can be
        located at all.

        Returns:
            Candidate directories in preference order, without duplicates.
        """
        candidates: list[str] = []
        if self.relative_path:
            for directory in self.root_directories(self.root_module):
                candidate = os.path.normpath(
                    os.path.join(directory, self.relative_path)
                )
                if candidate not in candidates:
                    candidates.append(candidate)
        exported = os.path.realpath(self.path)
        # A stable sort, so search order still decides between the rest of them.
        candidates.sort(key=lambda directory: os.path.realpath(directory) != exported)
        if self.path not in candidates:
            candidates.append(self.path)
        return tuple(candidates)

    def __located(self) -> tuple[str, bool]:
        """
        Pick the directory this source describes, and say whether it still matches.

        A candidate is accepted because its sources hash to the recorded digest, never
        merely because a directory is there. Existing used to be the whole test, and
        for a namespace package it is the wrong one: with portions ``p1/ns`` and
        ``p2/ns`` both on the path, a snapshot of ``p2/ns`` was checked against
        ``p1/ns``, which calls an untouched tree stale — and, where that portion
        happens to hash equal, passes a tree that really did change (SWE-28). Walking
        on to the next candidate costs an extra digest only when the first one turns
        out not to be the directory the snapshot was built from.

        Returns:
            (directory, whether its sources match the recorded digest). The directory
            is the matching one when one matches, and otherwise the first candidate
            that exists, so that a staleness error names somewhere real.
        """
        fallback = ""
        for candidate in self.candidate_paths():
            if not os.path.isdir(candidate):
                continue
            if self.digest_of(candidate) == self.digest:
                return candidate, True
            if not fallback:
                fallback = candidate
        return (fallback or self.path), False

    def resolved_path(self) -> str:
        """
        The directory this source should be checked against, located now.

        Returns:
            The first candidate directory whose sources still hash to :attr:`digest`;
            failing that the first candidate that exists; failing that :attr:`path`.
        """
        return self.__located()[0]

    @staticmethod
    def directory_identity(path: str) -> tuple[int, int] | None:
        """
        What identifies a directory to the file system, rather than by name.

        Device and inode, so that one directory reached both through a symlink and
        under its real name is recognised as the same directory.

        Args:
            path: Directory to identify.

        Returns:
            (device, inode), or None when it cannot be stat'ed — a broken link, or a
            directory this process may not look at.
        """
        try:
            status = os.stat(path)
        except OSError:
            return None
        return status.st_dev, status.st_ino

    @staticmethod
    def module_name_of(file_name: str) -> tuple[str, str] | None:
        """
        The module a file would be imported as, and the suffix that says so.

        The longest matching suffix decides, because the import machinery's suffixes
        overlap: ``accel.cpython-313-x86_64-linux-gnu.so`` ends with ``.so`` as well,
        and taking the short match would call the module
        ``accel.cpython-313-x86_64-linux-gnu`` — a name no ``.pyc`` could ever be
        matched against (SWE-44).

        Args:
            file_name: Bare file name, without its directory.

        Returns:
            (module name, matched suffix), or None when nothing could import this file.
            A file that is nothing but a suffix — a bare ``.py`` — is not a module, so
            it comes back None as well.
        """
        for suffix in SnapshotSource.IMPORTABLE_SUFFIXES:
            if len(file_name) > len(suffix) and file_name.endswith(suffix):
                return file_name[: -len(suffix)], suffix
        return None

    @staticmethod
    def covered_files(file_names: Iterable[str]) -> tuple[str, ...]:
        """
        Which files in one directory the digest covers, in sorted order.

        Every file an import could come from, with one exclusion: bytecode that is not
        the whole of its module. A ``foo.pyc`` sitting beside ``foo.py`` — or beside a
        ``foo`` extension, which the machinery would prefer to either — is a build
        artifact, and hashing it would move the digest on every recompile and every
        interpreter version while telling us nothing the source did not already say. A
        *sourceless* ``foo.pyc``, which by convention sits beside its siblings rather
        than in ``__pycache__``, is the module itself and is covered (SWE-44).

        The ordinary case — compiled bytecode under ``__pycache__`` — never reaches
        here, because :meth:`digest_of` skips that directory by name before descending.
        This is the legacy layout, and the sourceless deployment, where the question has
        to be asked file by file.

        Args:
            file_names: Bare file names found in one directory.

        Returns:
            The names to hash, sorted, so the digest cannot depend on scandir order.
        """
        importable: dict[str, tuple[str, bool]] = {}
        # Modules with a file the machinery would rather import than any bytecode.
        authoritative: set[str] = set()
        for file_name in file_names:
            decided = SnapshotSource.module_name_of(file_name)
            if decided is None:
                continue
            module_name, suffix = decided
            is_bytecode = suffix in SnapshotSource.BYTECODE_SUFFIXES
            importable[file_name] = (module_name, is_bytecode)
            if not is_bytecode:
                authoritative.add(module_name)
        return tuple(
            sorted(
                file_name
                for file_name, (module_name, is_bytecode) in importable.items()
                if not (is_bytecode and module_name in authoritative)
            )
        )

    @staticmethod
    def digest_of(path: str) -> str:
        """
        Hash every file under a directory that a module could be imported from.

        Covers file names as well as contents, so adding, renaming or removing a module
        changes the digest.

        What counts as importable is asked of :mod:`importlib.machinery` rather than
        assumed to be ``.py``. The fill imports a sourceless ``.pyc`` and a ``.so`` or
        ``.pyd`` extension module as readily as a source file, and registers the
        classes it finds in them, so a digest that saw only sources kept vouching for
        names whose only file was gone: deleting the ``.pyc`` of a sourceless module
        left ``load(verify=True)`` passing, and rebuilding an extension with different
        classes in it was invisible (SWE-44). Extension modules are not exotic — any
        package with a compiled component has them, and a rebuilt one is exactly the
        staleness a digest exists to catch.

        Extension modules are hashed in full, deliberately, even though they can run to
        megabytes. Size and mtime would be cheaper, but mtime does not survive
        installation — a wheel's files are written out with whatever time the install
        happened at — so a snapshot built in CI would call every consumer's extension
        stale, which is the failure SWE-18 exists to prevent, and size alone misses a
        rebuild that lands on the same length. A full read costs one sequential pass per
        verification, which a ``load`` does once, against sources the same walk is
        already reading end to end.

        ``__pycache__`` is skipped, since bytecode compiled from a source file beside it
        is derived: hashing it would move the digest on every recompile and every
        interpreter version without describing anything a module's own file does not.
        Bytecode in the legacy layout, beside its source, is skipped for the same
        reason — see :meth:`covered_files`, which is where that judgement is made.

        Excluded modules are hashed too: a snapshot cannot know which patterns a future
        fill will pass, so the digest is deliberately conservative — an edit to a file
        that was never registered still marks the snapshot stale.

        Symlinked directories are followed, because the fill follows them.
        :func:`pkgutil.iter_modules` descends a symlinked subpackage and registers the
        classes it finds there, so a digest that stopped at the link covered less than
        the snapshot names: with ``app/plugins`` linked elsewhere, a class could be
        renamed and a module added inside the target and verification still passed,
        registering a name that no longer exists (SWE-28). Following links means the
        walk can meet the same directory twice, or — given a loop — forever, so a
        directory already hashed under another name is recorded as a revisit and not
        descended again. That bounds the walk by the number of real directories while
        leaving the second name visible in the digest, so making or breaking a link is
        still a change rather than a silent equality.

        Each file contributes a framed record — its name, the length of its contents,
        then the contents, the parts separated by NUL — rather than name and bytes run
        together. Unframed, the boundary between the two is ambiguous and two different
        trees hash identically: a module whose text happens to end with the next
        module's name followed by that module's source digests the same as the two
        modules do (SWE-28). Framed, a record cannot be read two ways, because a file
        name cannot contain a NUL and the length field is always decimal — which is
        also why the markers standing in for a length are words. Bytecode and extension
        files contribute that same record, so widening what is covered added no new kind
        of record for a reader to confuse with a file (SWE-44).

        Args:
            path: Directory to hash.

        Returns:
            Hex digest.
        """
        hasher = hashlib.sha256()
        visited: set[tuple[int, int]] = set()
        root_identity = SnapshotSource.directory_identity(path)
        if root_identity is not None:
            visited.add(root_identity)
        for directory, directory_names, file_names in os.walk(path, followlinks=True):
            descend = []
            for name in sorted(n for n in directory_names if n != "__pycache__"):
                child = os.path.join(directory, name)
                relative = os.path.relpath(child, path).encode()
                identity = SnapshotSource.directory_identity(child)
                if identity is None:
                    hasher.update(relative + b"\0unreadable\0")
                    continue
                if identity in visited:
                    hasher.update(relative + b"\0revisited\0")
                    continue
                visited.add(identity)
                descend.append(name)
            directory_names[:] = descend
            for file_name in SnapshotSource.covered_files(file_names):
                full_path = os.path.join(directory, file_name)
                relative = os.path.relpath(full_path, path).encode()
                try:
                    with open(full_path, "rb") as handle:
                        contents = handle.read()
                except OSError:
                    # Unreadable now means a different tree than the one exported.
                    hasher.update(relative + b"\0unreadable\0")
                    continue
                hasher.update(
                    relative + b"\0" + str(len(contents)).encode() + b"\0" + contents
                )
        return hasher.hexdigest()

    def is_stale(self) -> bool:
        """
        Whether the tree on disk differs from the one this records.

        The tree is looked for where the package is installed now rather than where it
        was exported from, so relocation alone is not a change. Everything else is:
        a package that cannot be found anywhere is still gone, and sources that hash
        differently are still different.

        Returns:
            True when no directory this source could mean still holds the sources it
            recorded — the directory is gone, or what is there has changed.
        """
        return not self.__located()[1]
