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
import os
import stat
import tempfile
import warnings
from typing import ClassVar

from pydantic import BaseModel, Field

from sweet_tea.snapshot_entry import SnapshotEntry
from sweet_tea.snapshot_source import SnapshotSource
from sweet_tea.sweet_tea_error import SweetTeaError
from sweet_tea.sweet_tea_warning import SweetTeaWarning


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
    #:
    #: 2 added ``relative_path`` to each source (SWE-18). Readers that ignore it reach a
    #: *different verdict* on the same file rather than merely losing detail — they
    #: check the absolute export directory and declare a perfectly current snapshot
    #: stale — so the version moved rather than the field being added quietly. A
    #: version 1 file still loads here: no relative record means check the absolute
    #: path, exactly as before.
    #:
    #: 3 changed how a source digest is computed (SWE-28): the records inside it are
    #: framed, and symlinked subpackages are followed. No key moved, but every digest
    #: value did, which is the same situation by the same test — two readers reach
    #: different verdicts about one unchanged file. Both verdicts are "stale", so
    #: nothing is taken for current either way, and the version earns its keep in the
    #: message instead: a format 2 file read here verifies as stale and says to
    #: re-export, which is a riddle when nothing changed, whereas a format 3 file read
    #: by a sweet_tea that predates the framing is refused outright and says precisely
    #: why. The remedy in both directions is to re-export, and the version is what lets
    #: a reader say so.
    #:
    #: 4 added ``provisional`` to each entry (SWE-41). Omitting it was not a loss of
    #: detail either: a reader that cannot tell a scanned name from a requested one
    #: treats every scanned name as requested, which registers classes the package
    #: never defined and lets them shadow real registrations. A format 3 file still
    #: loads here, with every entry read as a guess, and :meth:`read` warns about what
    #: reading it that way costs.
    #:
    #: 5 widened what a source digest covers (SWE-44): sourceless bytecode and
    #: extension modules are hashed, because the fill imports and registers from them.
    #: Unlike 3, this does not move every digest value — a tree of nothing but sources
    #: hashes exactly as it did, which is almost every tree. It moves the digest of a
    #: tree holding a compiled or sourceless module, and those are the digests that
    #: were wrong: before this, a tree with a sourceless module and a tree without it
    #: hashed *identically*, so verification could not tell them apart. A format 4 file
    #: still loads here, and re-verifies as stale only if its tree contains such a
    #: module.
    FORMAT_VERSION: ClassVar[int] = 5

    version: int = Field(
        default=FORMAT_VERSION,
        ge=1,
        strict=True,
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
        Write this snapshot to a file as JSON, atomically.

        The JSON is built in a temporary file beside its destination and moved into
        place with :func:`os.replace`, which is atomic on POSIX and on Windows. Writing
        in place truncated the file and then filled it, and a reader arriving in
        between saw an empty or half-written document: one exporter against four
        loaders on one path produced 194 unparseable reads in six seconds (SWE-26). The
        unparseable read is the loud failure. The dangerous one is the truncated
        document that happens to parse, since that registers a silently incomplete
        registry instead of raising.

        A rename is the right instrument rather than a lock. :meth:`read` takes no lock
        — deliberately, so that reading a snapshot contends with nothing — and a lock
        could not help anyway when the exporter and the reader are different processes,
        which for a build step writing what a running service reads is the normal case.
        Durability is a separate problem and deliberately left alone: nothing is
        fsynced, so a crash can still lose this write. What a reader must never see is
        a file that is neither the old snapshot nor the new one.

        The destination is resolved through symlinks before any of that happens, and
        the replacement lands on what it resolves to (SWE-45). A snapshot path is
        commonly an indirection somebody chose — ``snapshot.json ->
        /var/cache/myapp/snapshot.json`` — and :func:`os.replace` onto the link itself
        replaces the *link* with a regular file. Nothing fails and nothing warns; the
        indirection is simply gone, and every reader that went through it afterwards
        gets a file nobody is updating any more. Resolving first also keeps the
        temporary file on the same file system as the file actually being replaced,
        which is what the atomicity depends on: beside the link is the wrong directory
        when the link crosses a mount. A chain of links resolves to its end, so every
        hop survives; a link pointing at nothing resolves to the target it names and
        the write creates it, which is what writing to a dangling link has always done
        and leaves the link whole rather than consuming it.

        That resolution is of the *destination*, not of the snapshot's contents: what
        gets recorded about the trees that were filled is unaffected.

        The directory holding the resolved destination has to be writable, and that is
        a real requirement rather than an incidental one: the temporary file is created
        there. A writable ``snapshot.json`` inside a directory this process cannot
        write is therefore refused, where the old in-place write would have succeeded.
        That trade is deliberate. The alternative — falling back to truncating the
        destination in place — would reintroduce SWE-26 exactly where it is hardest to
        see, in the rare environment nobody tests, and would make the one guarantee
        this method exists to give conditional on a file system property no caller can
        read off the API. A guarantee that holds unless it quietly does not is worth
        less than a refusal that names the directory, which is what this raises.

        Args:
            path: Destination file. A symlink is followed and its target replaced,
                rather than the link.

        Raises:
            SweetTeaError: When the file cannot be written — including when the
                directory holding it will not take the temporary file, which is
                reported against the directory rather than against the file.
        """
        # Resolved rather than merely absolute: a destination that is a symlink must
        # have its target rewritten, and the temporary file has to sit beside that
        # target to be renameable onto it (SWE-45).
        destination = os.path.realpath(path)
        directory = os.path.dirname(destination)
        try:
            # The same directory, so that the move is a rename rather than a copy —
            # across file systems os.replace is neither atomic nor even possible.
            descriptor, temporary = tempfile.mkstemp(
                dir=directory,
                prefix=f".{os.path.basename(destination)}.",
                suffix=".tmp",
            )
        except OSError as error:
            # Reported against the directory, because that is what is wrong. "Permission
            # denied: /ro/.snapshot.json.ab12cd.tmp" names a file the caller never asked
            # for and cannot find afterwards, and reads as a bug in sweet_tea rather
            # than as a directory they cannot write (SWE-45).
            raise SweetTeaError(
                self.__unusable_directory(path, destination, directory, error)
            ) from error

        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(self.model_dump(), handle, indent=2, sort_keys=False)
                handle.write("\n")
            os.chmod(temporary, self.__destination_mode(destination))
            os.replace(temporary, destination)
        except OSError as error:
            self.__discard(temporary)
            raise SweetTeaError(f"Cannot write snapshot to {path}: {error}") from error
        except BaseException:
            # Not every failure here is the file system's — a model that will not dump,
            # or an interrupt — and none of them may leave a temp file behind.
            self.__discard(temporary)
            raise

    @staticmethod
    def __unusable_directory(
        path: str, destination: str, directory: str, error: OSError
    ) -> str:
        """
        Say why a temporary file could not be created, against the directory.

        The failure a caller actually meets here is a destination file they can write
        inside a directory they cannot, and the errno alone sends them to look at the
        file. The message therefore names the directory, says why the write needs it,
        and names the resolution when the path they gave was a link — otherwise the
        directory in the message belongs to a path they never typed.

        The cause is re-derived rather than read off the errno: EACCES, EROFS, ENOENT
        and ENOTDIR all arrive here and all mean something a caller can act on, but
        only after being translated out of a number.

        Args:
            path: Destination exactly as the caller gave it.
            destination: What that resolves to.
            directory: The directory the temporary file would have gone in.
            error: What :func:`tempfile.mkstemp` raised.

        Returns:
            The message for the SweetTeaError.
        """
        if not os.path.isdir(directory):
            cause = f"the directory {directory} does not exist"
        elif not os.access(directory, os.W_OK | os.X_OK):
            cause = f"the directory {directory} is not writable"
        else:
            cause = f"the directory {directory} would not take a temporary file"

        resolution = (
            f" {path} resolves to {destination}."
            if destination != os.path.abspath(path)
            else ""
        )
        return (
            f"Cannot write snapshot to {path}: {cause} ({error}).{resolution} The "
            f"snapshot is built in a temporary file in that directory and renamed over "
            f"the destination, which is what stops a concurrent read from seeing a "
            f"half-written document (SWE-26), so a writable destination file is not "
            f"enough on its own. Export somewhere this process can create a file, or "
            f"make the directory writable."
        )

    @staticmethod
    def __destination_mode(path: str) -> int:
        """
        The permissions a freshly written snapshot should carry.

        :func:`tempfile.mkstemp` creates a file only its owner can read, which is right
        for a secret and wrong for a snapshot: a build writes it and everything that
        loads it has to read it. Whatever mode the file being replaced already had is
        somebody's decision, so it is kept; a snapshot being written for the first time
        gets the ordinary readable default.

        Args:
            path: Destination file, which need not exist yet.

        Returns:
            Permission bits to put on the replacement.
        """
        try:
            return stat.S_IMODE(os.stat(path).st_mode)
        except OSError:
            return 0o644

    @staticmethod
    def __discard(path: str) -> None:
        """
        Remove a temporary file, ignoring a failure to do so.

        Args:
            path: Temporary file to remove.
        """
        try:
            os.unlink(path)
        except OSError:
            # The caller is about to report why the write failed, and that is the more
            # useful error of the two; a temp file left behind is not worth losing it.
            pass

    @classmethod
    def read(cls, path: str) -> "RegistrySnapshot":
        """
        Read a snapshot from a file.

        A snapshot written by format 3 or earlier records no provenance for its
        entries, so there is no way to tell which of its names a scan guessed at. Every
        entry is read as a guess, which is the safe direction: a guess read as a guess
        is overruled by discovery when its module is imported, whereas a guess read as
        a request registers classes the package never defined and lets them shadow real
        registrations (SWE-41).

        Reading them as guesses is not free, which is why it warns rather than happening
        quietly. A guess is only overruled where discovery disagrees, so a name that
        really is bound to a class in its own module survives either way — including an
        explicit alias, which is the common case. What an older snapshot loses is a name
        discovery cannot confirm: an alias pointing at a re-export, whose class belongs
        to another module. :meth:`~sweet_tea.registry.Registry.load` also declines to
        treat an older snapshot's ``(library, label)`` pairs as fill-owned, since it
        cannot tell which of them a fill established, so a class only *discovery* can
        see — built at runtime, where no scan reaches it — is not registered from an
        older snapshot where a lazy fill of the same tree would have found it.

        Both costs are paid in names that go missing rather than names that appear
        wrongly, and both are repaired by re-exporting. Escalating
        :class:`~sweet_tea.sweet_tea_warning.SweetTeaWarning` to an error turns the
        warning into the refusal a caller who would rather re-export now wants.

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

        # 4 is where provisional arrived, not the current version: a format 4 file
        # records provenance and is read as it stands.
        if snapshot.version < 4 and snapshot.entries:
            # Mutated rather than rebuilt: the field is the only thing being decided
            # and the rest of the entry is already what it should be.
            for entry in snapshot.entries:
                entry.provisional = True
            warnings.warn(
                f"Snapshot {path} is version {snapshot.version}, which records no "
                f"provenance for its entries, so every name in it is read as one a "
                f"scan guessed at. Discovery overrules a guess it cannot confirm, so "
                f"this snapshot registers no name whose class belongs to another "
                f"module, and no class that only discovery can see. Re-export it to "
                f"record which names were asked for.",
                SweetTeaWarning,
                stacklevel=2,
            )

        return snapshot

    def stale_sources(self) -> list[SnapshotSource]:
        """
        The recorded trees whose sources no longer match.

        Returns:
            Sources that have changed on disk, empty when the snapshot is current.
        """
        return [source for source in self.sources if source.is_stale()]
