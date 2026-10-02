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
import fnmatch
import importlib
import inspect
import logging
import os
import pkgutil
import sys
import threading
import traceback
import warnings
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from sweet_tea.audit_finding import AuditFinding
from sweet_tea.entry import Entry, set_resolver
from sweet_tea.lazy_audit import LazyAudit
from sweet_tea.lazy_scanner import LazyScanner
from sweet_tea.registry_snapshot import RegistrySnapshot
from sweet_tea.snapshot_entry import SnapshotEntry
from sweet_tea.snapshot_source import SnapshotSource
from sweet_tea.sweet_tea_error import SweetTeaError
from sweet_tea.sweet_tea_warning import SweetTeaWarning


class Registry:
    """
    Global registry for class definitions that can be instantiated via factories.

    This registry automatically discovers and registers classes from packages,
    supporting optional dependencies that may not be installed. Classes with
    missing dependencies are skipped with a warning rather than failing registration.

    The registry supports typed lookups for abstract factories, allowing filtering
    by inheritance hierarchy.

    Thread-safe: All registry operations are synchronized to prevent race conditions
    in multi-threaded environments.
    """

    # Threading lock for synchronizing registry operations
    __lock = threading.RLock()

    # This is the registry of packages
    __registry: list[Entry] = []

    # Hash index mirroring __registry, holding the identity of every entry already in
    # it. register() used to test membership with ``new_entry not in cls.__registry``,
    # a linear scan calling Entry.__eq__ — a pydantic structural compare — on every
    # element, so filling a registry of n entries cost n(n-1)/2 of them (SWE-6). The
    # tuple holds exactly the four fields Entry.__eq__ compares, so which registrations
    # count as duplicates is unchanged.
    __seen: set[tuple[str, object, str, str]] = set()

    # Modules registered lazily whose import is still pending, mapped to the
    # (library, label) the fill used — so the reconcile after import can re-register
    # under the same categorisation — and the number of entries the scan contributed.
    # A module the scanner found nothing in is still listed, with a count of zero:
    # it may define classes the scan cannot see, and the fallback sweep can only
    # import modules it knows about.
    __unresolved: dict[str, tuple[str, str, int]] = {}

    # Set when any subtree was filled with lazy="strict": a key that no static scan
    # could see then raises instead of triggering a whole-tree sweep.
    __no_sweep: bool = False

    # Trees that have been filled, mapped to the directory walked. Only the outermost
    # call of each fill is recorded, so a snapshot names the roots a consumer asked
    # for rather than every subpackage underneath them.
    __fills: dict[str, str] = {}

    # Nesting depth of fill_registry, which recurses into subpackages.
    __fill_depth: int = 0

    # Modules that were not registered, mapped to why. Exported alongside the entries
    # so a snapshot's reader can tell "not registered" from "not installed".
    __skipped: dict[str, str] = {}

    __lookup: dict[Any, list[Entry]] = {}

    __lookup_keys: list[Any] = []

    # Logger instance using the global settings
    __logger = logging.getLogger()

    @classmethod
    def entries(cls) -> list[Entry]:
        """Get all registered entries."""
        with cls.__lock:
            return cls.__registry.copy()

    @classmethod
    def typed_entries(cls, lookup_type: Any = Any) -> list[Entry]:
        """
        Get entries that are subclasses of the specified type.

        Args:
            lookup_type: The base class to filter by. Defaults to Any.

        Returns:
            List of entries where the class_def is a subclass of lookup_type.
        """
        with cls.__lock:
            if lookup_type not in cls.__lookup_keys:
                cls.__lookup_keys.append(lookup_type)
                if lookup_type is Any:
                    # Any matches everything - return all entries without filtering
                    cls.__lookup[lookup_type] = cls.__registry.copy()
                else:
                    cls.__lookup[lookup_type] = [
                        filtered_type
                        for filtered_type in cls.__registry
                        # A lazy entry's class is unknown until its module is
                        # imported, so it cannot answer issubclass. Factories call
                        # ensure_resolved before reaching here, which turns every
                        # candidate for the requested key into a normal entry.
                        # class_object, not class_def: building a type slot must not
                        # import the whole tree through the resolving property.
                        if filtered_type.class_object is not None
                        and issubclass(filtered_type.class_object, lookup_type)
                    ]
            return cls.__lookup[lookup_type].copy()

    @classmethod
    def register(
        cls,
        key: str,
        class_def: type,
        library: str = "",
        label: str = "",
        attribute: str = "",
    ) -> None:
        """
        Register a class with the registry.

        Args:
            key: Name used to reference the class for instantiation.
            class_def: The class type to register.
            library: Name of the library the class belongs to.
            label: Optional label for categorizing classes (e.g., for different environments).
            attribute: Module attribute the class is bound to, when known. Discovery
                passes it so a snapshot can name the class the way it was found —
                ``Mismatch = type("InnerName", ...)`` is reachable as ``Mismatch`` and
                not as its ``__name__``. Omitted, export falls back to ``__qualname__``.
        """
        new_entry = Entry(
            key=key.lower(),
            class_def=class_def,
            module=getattr(class_def, "__module__", ""),
            attribute=attribute,
            library=library.lower(),
            label=label.lower(),
        )

        # key/library/label are lowercased above, so this compares the same normalised
        # values Entry.__eq__ would; class_def is a type and therefore hashable.
        dedupe_key = new_entry.identity

        with cls.__lock:
            cls.__resync_seen()
            # Add entry if it is not currently present. Prevents duplicate entry.
            if dedupe_key not in cls.__seen:
                cls.__seen.add(dedupe_key)
                cls.__registry.append(new_entry)
                # Refresh every previously-queried lookup slot whose type matches
                # this class. Without this, ancestor-type slots cached before the
                # registration go stale (see GH #6).
                for lookup_type in cls.__lookup_keys:
                    if lookup_type is Any:
                        cls.__lookup[lookup_type].append(new_entry)
                    elif isinstance(lookup_type, type) and issubclass(
                        class_def, lookup_type
                    ):
                        cls.__lookup[lookup_type].append(new_entry)

    @classmethod
    def register_lazy(
        cls,
        key: str,
        module: str,
        attribute: str,
        library: str = "",
        label: str = "",
    ) -> None:
        """
        Register a class by name, deferring its module's import until first use.

        The entry carries no class object. The module is imported, and the entry
        replaced with whatever eager registration would have produced, the first time
        a factory needs this key (see :meth:`ensure_resolved`).

        Args:
            key: Name used to reference the class for instantiation.
            module: Dotted path of the module that defines it.
            attribute: Module attribute the class is bound to.
            library: Name of the library the class belongs to.
            label: Optional label for categorizing classes.
        """
        new_entry = Entry(
            key=key.lower(),
            module=module,
            attribute=attribute,
            library=library.lower(),
            label=label.lower(),
        )

        with cls.__lock:
            cls.__resync_seen()
            if new_entry.identity not in cls.__seen:
                cls.__seen.add(new_entry.identity)
                cls.__registry.append(new_entry)
                # Deliberately not added to any __lookup slot: the entry cannot answer
                # issubclass until it is resolved.
                known_library, known_label, count = cls.__unresolved.get(
                    module, (library.lower(), label.lower(), 0)
                )
                cls.__unresolved[module] = (known_library, known_label, count + 1)

    @classmethod
    def ensure_resolved(cls, keys: Iterable[str], sweep: bool = True) -> None:
        """
        Import whatever is needed before the given keys can be looked up.

        Resolves only the modules holding lazy entries for these keys — the whole
        point of lazy filling. When no entry matches at all and modules remain
        unresolved, falls back to resolving everything: a class injected at runtime
        (``globals()[name] = type(...)``) or registered by a module's import-time side
        effects is invisible to the scanner, and a sweep is the only way to find it.

        Args:
            keys: Candidate key spellings, already normalised by the caller.
            sweep: Whether a total miss may trigger the fallback sweep.

        Raises:
            SweetTeaError: When a sweep is needed but the registry was filled with
                lazy="strict".
        """
        with cls.__lock:
            if not cls.__unresolved:
                return

            wanted = {key.lower() for key in keys}
            pending = {
                entry.module
                for entry in cls.__registry
                if entry.is_lazy and entry.key in wanted
            }
            for module_name in sorted(pending):
                cls.__resolve_module(module_name)

            if not sweep or not cls.__unresolved:
                return
            if any(entry.key in wanted for entry in cls.__registry):
                return

            # Before importing anything, harvest the pending modules something else
            # already imported — a module pulled in as a side effect of resolving
            # another is in sys.modules but still unreconciled, so a class it creates
            # at runtime is invisible. Reconciling those costs no imports and often
            # avoids the sweep entirely.
            for module_name in sorted(cls.__unresolved):
                if module_name in sys.modules:
                    cls.__resolve_module(module_name)

            if not cls.__unresolved:
                return
            if any(entry.key in wanted for entry in cls.__registry):
                return

            requested = ", ".join(sorted(wanted))
            if cls.__no_sweep:
                raise SweetTeaError(
                    f"No entry for {requested} and the registry was filled with "
                    f'lazy="strict", so the remaining {len(cls.__unresolved)} module(s) '
                    f"will not be imported to look for it. Name the module that "
                    f"defines it in fill_registry(eager=[...]) if it is created at "
                    f"runtime rather than by a class statement."
                )

            # Reported, not silent: a sweep undoes the saving lazy filling exists for,
            # so the caller needs to know which key caused it.
            warnings.warn(
                f"Importing {len(cls.__unresolved)} remaining module(s) to look for "
                f"{requested}: no lazily registered name matched. Add the defining "
                f"module to fill_registry(eager=[...]) to avoid this.",
                SweetTeaWarning,
                stacklevel=2,
            )
            cls.resolve_all()

    @classmethod
    def skipped(cls) -> dict[str, str]:
        """
        Modules that were not registered, mapped to why.

        Filling warns and skips a module whose import fails on a missing optional
        dependency. Without this, a caller cannot tell a class that was never written
        from one whose dependency is not installed.

        Returns:
            Copy of the skip record.
        """
        with cls.__lock:
            return dict(cls.__skipped)

    @classmethod
    def export(cls, path: str) -> None:
        """
        Write the filled registry to a file, so it can be read back without a walk.

        Nothing is imported: an unresolved entry is already named by module and
        attribute, and a resolved one is named from the class it holds. The trees that
        were filled are recorded with a digest of their sources, so :meth:`load` can
        tell whether the snapshot still matches the code.

        Args:
            path: Destination file.

        Raises:
            SweetTeaError: When an entry cannot be named — a class registered directly
                from a construct with no module or qualified name — or the file cannot
                be written.
        """
        with cls.__lock:
            entries = []
            for entry in cls.__registry:
                # class_object, never class_def: exporting must not import anything.
                module = entry.module or getattr(entry.class_object, "__module__", "")
                attribute = entry.attribute or getattr(
                    entry.class_object, "__qualname__", ""
                )
                if not module or not attribute or "." in attribute:
                    raise SweetTeaError(
                        f"Cannot export the entry for {entry.key!r}: it resolves to "
                        f"{module or '?'}:{attribute or '?'}, which is not a plain "
                        f"module attribute, so reading the snapshot back could not "
                        f"find it again."
                    )
                entries.append(
                    SnapshotEntry(
                        key=entry.key,
                        class_def=f"{module}:{attribute}",
                        library=entry.library,
                        label=entry.label,
                    )
                )

            sources = [
                SnapshotSource(
                    module=filled,
                    path=filled_path,
                    digest=SnapshotSource.digest_of(filled_path),
                )
                for filled, filled_path in sorted(cls.__fills.items())
            ]

            RegistrySnapshot(
                sources=sources, entries=entries, skipped=dict(cls.__skipped)
            ).write(path)

    @classmethod
    def load(cls, path: str, verify: bool = True) -> None:
        """
        Register everything a snapshot records, without walking or importing a tree.

        Entries are registered lazily, so a module is imported only when a factory or a
        read of :attr:`~sweet_tea.entry.Entry.class_def` needs it. This is what makes a
        snapshot cheaper than a fill rather than merely different: the walk, the parse
        and the imports are all skipped.

        Args:
            path: Snapshot file to read.
            verify: Whether to check the recorded source digests against the files on
                disk first. Leave it on unless the caller has already established that
                the snapshot is current — a stale snapshot registers names that no
                longer exist, and the failure surfaces far from the cause.

        Raises:
            SweetTeaError: When the snapshot cannot be read, is malformed, names a
                class in a form that cannot be resolved, or — with ``verify`` — no
                longer matches its sources.
        """
        snapshot = RegistrySnapshot.read(path)

        if verify:
            stale = snapshot.stale_sources()
            if stale:
                names = ", ".join(source.module for source in stale)
                raise SweetTeaError(
                    f"Snapshot {path} no longer matches its sources ({names}). "
                    f"Rebuild it with Registry.export(), or pass verify=False if the "
                    f"difference is known to be harmless."
                )

        with cls.__lock:
            for snapshot_entry in snapshot.entries:
                try:
                    module, attribute = snapshot_entry.coordinates
                except ValueError as error:
                    raise SweetTeaError(
                        f"Snapshot {path} names {snapshot_entry.key!r} as "
                        f"{snapshot_entry.class_def!r}: {error}"
                    ) from error

                cls.register_lazy(
                    key=snapshot_entry.key,
                    module=module,
                    attribute=attribute,
                    library=snapshot_entry.library,
                    label=snapshot_entry.label,
                )

            cls.__skipped.update(snapshot.skipped)

    @classmethod
    def _resolve_entry_class(cls, module: str, attribute: str) -> type:
        """
        Import a lazy entry's module and hand back the class it names.

        Installed on :mod:`sweet_tea.entry` so that reading ``Entry.class_def`` on an
        unresolved entry works like reading it on any other — which is what keeps code
        that introspects :meth:`entries` directly working under lazy filling (SWE-13).

        The registry's own copy of the entry is reconciled at the same time, so the
        import is paid once however it was triggered.

        Args:
            module: Dotted module path from the entry.
            attribute: Module attribute the class is bound to.

        Returns:
            The class.

        Raises:
            SweetTeaError: When the module cannot be imported, or no longer binds a
                class under that name — the case of a provisional guess that turned out
                to be something else.
        """
        with cls.__lock:
            cls.__resolve_module(module)

        try:
            module_object = importlib.import_module(module)
        except Exception as error:
            raise SweetTeaError(
                f"Cannot resolve {attribute} from {module}: {error}"
            ) from error

        resolved = getattr(module_object, attribute, None)
        if not isinstance(resolved, type):
            raise SweetTeaError(
                f"{module}.{attribute} is not a class, so the lazily registered name "
                f"{attribute!r} cannot be resolved. It was read from the source as a "
                f"possible class and turned out to be {type(resolved).__name__}."
            )
        return resolved

    @classmethod
    def resolve_all(cls) -> None:
        """
        Import every module still pending, leaving the registry fully eager.

        Use when an exact view of the registry matters more than the deferral — for
        example before reading :meth:`entries` for introspection.
        """
        with cls.__lock:
            for module_name in sorted(cls.__unresolved):
                cls.__resolve_module(module_name)

    @classmethod
    def __resolve_module(cls, module_name: str) -> None:
        """
        Import one pending module and replace its lazy entries with real ones.

        Reconciliation runs eager registration's own discovery over the imported
        module rather than trusting the scan, so the outcome for a resolved module is
        exactly what a non-lazy fill would have produced — including names no scan
        could predict, and minus provisional guesses that turned out not to be
        classes.

        The caller must hold ``__lock``.

        Args:
            module_name: Dotted path of the module to import.
        """
        if module_name not in cls.__unresolved:
            return

        library, label, scanned = cls.__unresolved.pop(module_name)

        # The documented reset clears __registry directly, which can leave this index
        # holding modules whose entries are gone. Importing them would resurrect
        # registrations the caller just cleared. A module that contributed nothing to
        # begin with (scanned == 0) is exempt: it has no entries to have lost, and is
        # exactly the case the sweep exists for.
        if scanned and not any(
            entry.is_lazy and entry.module == module_name for entry in cls.__registry
        ):
            return

        try:
            module = importlib.import_module(module_name)
        except (ImportError, ModuleNotFoundError):
            # Same contract as the eager path: an optional dependency that is not
            # installed removes the entry rather than failing the lookup.
            warnings.warn(
                f"Skipping module {module_name} due to missing optional dependency",
                SweetTeaWarning,
                stacklevel=2,
            )
            cls.__skipped[module_name] = "missing optional dependency"
            cls.__drop_lazy_entries(module_name)
            return
        except Exception:
            # Anything else is reported the way __add_entry_to_registry reports it, so
            # a module that breaks discovery fails the same way in both modes. The
            # difference deferral cannot remove is *when*: eager raises during the
            # fill, lazy during the lookup that first needed this module.
            cls.__drop_lazy_entries(module_name)
            error_message = traceback.format_exc()
            cls.__logger.error(
                f"Error processing module {module_name}: {error_message}"
            )
            raise SweetTeaError(error_message)

        cls.__drop_lazy_entries(module_name)

        for class_name, class_def in inspect.getmembers(module, inspect.isclass):
            if class_def.__module__ == module_name or cls.__is_orphaned(
                class_def, module_name
            ):
                cls.register(
                    key=class_name.lower(),
                    class_def=class_def,
                    library=library,
                    label=label,
                    attribute=class_name,
                )

    @classmethod
    def __drop_lazy_entries(cls, module_name: str) -> None:
        """
        Remove the unresolved entries belonging to one module.

        Dropping entries is what makes ``__lookup`` invalidation necessary: its slots
        are refreshed when entries are added but have no notion of removal, so a
        cached slot would keep reporting a class that is no longer registered. The
        slots are cleared wholesale and rebuilt on the next :meth:`typed_entries`
        call; ``__seen`` recovers through :meth:`__resync_seen`.

        The caller must hold ``__lock``.

        Args:
            module_name: Module whose lazy entries should go.
        """
        remaining = [
            entry
            for entry in cls.__registry
            if not (entry.is_lazy and entry.module == module_name)
        ]
        if len(remaining) != len(cls.__registry):
            cls.__registry[:] = remaining
            cls.__lookup.clear()
            cls.__lookup_keys.clear()

    @classmethod
    def __resync_seen(cls) -> None:
        """
        Rebuild the dedupe index if ``__registry`` was mutated behind its back.

        ``register`` is the only writer in this class and keeps the two in step, but the
        documented way to reset state between tests is to clear the underlying list
        directly — ``Registry._Registry__registry.clear()`` (see
        ``docs/development/testing.md``). An index left holding the cleared entries would
        make every re-registration after such a reset look like a duplicate and silently
        drop it, so the two are reconciled before each membership test.

        Comparing lengths keeps the normal, in-step path O(1); the O(n) rebuild runs only
        after an outside mutation. A mutation that happens to preserve the length is not
        detected — clearing and replacing wholesale, the only supported reset, is.

        The caller must hold ``__lock``.
        """
        if len(cls.__seen) != len(cls.__registry):
            # Mutated in place rather than rebound, so any existing reference to the set
            # keeps seeing the live index.
            cls.__seen.clear()
            cls.__seen.update(entry.identity for entry in cls.__registry)

    @classmethod
    def fill_registry(
        cls,
        path: str | None = None,
        module: str | None = None,
        library: str = "",
        label: str = "",
        exclude: Iterable[str] | None = None,
        lazy: bool | str = False,
        eager: Iterable[str] | str | None = None,
    ) -> None:
        """
        Recursively scan and register classes from packages starting from the given path.

        This method automatically discovers all classes in the package hierarchy,
        supporting optional dependencies by gracefully skipping modules that fail
        to import due to missing packages.

        Both regular packages and implicit namespace packages (PEP 420) are traversed;
        no flag is needed to opt in to the latter. Directories that cannot be imported
        are ignored — see :meth:`__is_namespace_package` for the exact rules.

        Directories that *are* importable but should not be registered — ``tests``,
        ``fixtures``, ``examples`` — cannot be detected automatically, since they are
        legitimate Python. Name them via ``exclude``:

        .. code-block:: python

            Registry.fill_registry(exclude=["*.tests", "*.examples"])

        Excluding a package prunes its whole subtree, so a single pattern is enough to
        drop everything beneath it.

        Args:
            path: Package path where modules are located. If None, uses the caller's module path.
            module: Name of the root module. If None, inferred from path.
            library: Name of the library for categorization.
            label: Optional label for categorizing classes.
            exclude: Glob patterns matched case-sensitively against the full dotted
                module path (``mypkg.sub.tests``). Matching modules are not imported and
                matching packages are not descended into. Applies to regular and
                namespace packages alike.
            lazy: When truthy, register names found by parsing each module instead of
                importing it; a module is imported the first time a factory needs a
                class from it. Pass ``"strict"`` to additionally refuse the fallback
                sweep, so a name no scan could see raises instead of importing the
                rest of the tree.
            eager: Glob patterns, matched like ``exclude``, naming modules to import at
                fill time despite ``lazy``. Use for modules that build classes at
                runtime or register during import. Only meaningful with ``lazy``.
                The reserved value ``"auto"`` — alone, or among the patterns — audits
                each module and imports the ones that would not survive lazy filling
                (see :meth:`lazy_audit`), leaving the rest lazy.

        Raises:
            SweetTeaError: When ``eager`` is given without ``lazy``, which would
                otherwise silently do nothing.
        """
        if eager is not None and not lazy:
            raise SweetTeaError(
                "fill_registry(eager=...) only applies when lazy filling is on. "
                "Pass lazy=True, or drop eager: without it every module is imported "
                "at fill time already."
            )
        if lazy == "strict":
            cls.__no_sweep = True
        with cls.__lock:
            # Determine the path to scan
            if path is None:
                _module = inspect.getmodule(inspect.stack()[1][0])
                if _module is None or _module.__file__ is None:
                    raise SweetTeaError("Cannot determine module path automatically")
                path = str(Path(_module.__file__).parent)

            # Ensure path is a string
            path_str = str(path)

            # Make sure the root module is correctly specified
            if module is None:
                module = os.path.basename(path_str)

            if not library:
                library = module

            # Location of package
            pkg_dir = path_str

            # Remember the tree so a snapshot can record what it was built from. Only
            # roots are kept: this method recurses into subpackages, and a module whose
            # ancestor is already recorded is part of that ancestor's walk. Judged by
            # ancestry rather than a depth counter so an exception mid-walk cannot leave
            # the bookkeeping wrong.
            if not any(
                module == filled or module.startswith(f"{filled}.")
                for filled in cls.__fills
            ):
                cls.__fills[module] = path_str

            # Materialised once so the recursive calls below share a single tuple rather
            # than re-consuming a caller-supplied iterator, which would be exhausted
            # after the first subpackage.
            exclude_patterns = tuple(exclude or ())
            # "auto" is a mode rather than a glob, so it is separated from the
            # patterns before matching and re-attached for the recursive call.
            eager_values: tuple[str, ...] = (
                (eager,) if isinstance(eager, str) else tuple(eager or ())
            )
            auto_eager = "auto" in eager_values
            eager_patterns = tuple(
                pattern for pattern in eager_values if pattern != "auto"
            )

            # Loop over the modules. If it is a package, the make recursive call, otherwise for each non-package
            # module imports the module and registers it.
            for name, is_a_package in cls.__iter_package_children(pkg_dir):
                pkg_name = f"{module}.{name}"
                if cls.__is_excluded(pkg_name, exclude_patterns):
                    # Logged rather than dropped silently; an under-filled registry with
                    # no explanation is the failure mode this whole area keeps hitting.
                    cls.__logger.debug(
                        f"Skipping {pkg_name}: matched an exclude pattern"
                    )
                    continue

                if not is_a_package:
                    source_file = os.path.join(pkg_dir, f"{name}.py")
                    # An eager pattern, a non-Python module (C extension), or no lazy
                    # request at all all mean: import it now, as before.
                    fill_lazily = (
                        bool(lazy)
                        and not cls.__is_excluded(pkg_name, eager_patterns)
                        and os.path.isfile(source_file)
                    )
                    if fill_lazily and auto_eager:
                        findings = LazyAudit.audit_file(source_file, pkg_name)
                        if findings:
                            # Logged rather than warned: this is the mode working as
                            # asked, not a problem the caller must act on.
                            cls.__logger.debug(
                                f"Filling {pkg_name} eagerly: {findings[0]}"
                            )
                            fill_lazily = False
                            cls.__warn_if_unfixable(findings)
                    if fill_lazily:
                        cls.__scan_entry_to_registry(
                            label=label,
                            library=library,
                            name_of_package=pkg_name,
                            source_file=source_file,
                        )
                    else:
                        cls.__add_entry_to_registry(
                            label=label, library=library, name_of_package=pkg_name
                        )
                else:
                    # Make recursive call to the
                    cls.fill_registry(
                        path=os.path.join(pkg_dir, name),
                        module=pkg_name,
                        library=library,
                        label=label,
                        exclude=exclude_patterns,
                        lazy=lazy,
                        eager=eager_values if lazy else None,
                    )

    @classmethod
    def __warn_if_unfixable(cls, findings: list[AuditFinding]) -> None:
        """
        Warn about a module importing eagerly cannot rescue.

        Importing a module early is enough for one that *writes* to the registry or
        builds classes at runtime: running it makes its names real. It is not enough
        for one that *reads* the registry while importing, because the read happens
        while the rest of the tree is still unresolved — so the lookup either misses
        or forces the very sweep lazy filling exists to avoid. Only changing that
        module helps, which is worth saying plainly rather than leaving the caller to
        infer it from a sweep warning later.

        Args:
            findings: The findings for one module.
        """
        blocking = [
            finding for finding in findings if finding.kind == "registry-read-at-import"
        ]
        if not blocking:
            return

        warnings.warn(
            f"{blocking[0].module} reads the registry while it is being imported "
            f"(line {blocking[0].line}). Filling it eagerly does not fix that: the "
            f"lookup still runs before the rest of the tree is resolved. Defer the "
            f"lookup to first use, or fill this package eagerly.",
            SweetTeaWarning,
            stacklevel=2,
        )

    @classmethod
    def lazy_audit(
        cls,
        path: str | None = None,
        module: str | None = None,
        exclude: Iterable[str] | None = None,
    ) -> list[AuditFinding]:
        """
        Report what in a package would not survive ``fill_registry(lazy=True)``.

        Walks the tree the way :meth:`fill_registry` does but imports nothing, and
        reports the three habits that assume eager filling: reading the registry while
        importing, registering while importing, and creating classes at runtime where
        no scan can see them (see :class:`~sweet_tea.lazy_audit.LazyAudit`).

        Read the report before turning ``lazy`` on, or pass ``eager="auto"`` to act on
        it automatically.

        Args:
            path: Package path to walk. If None, uses the caller's module path, the
                same default :meth:`fill_registry` applies.
            module: Name of the root module. If None, inferred from path.
            exclude: Glob patterns for modules to skip, matched as in
                :meth:`fill_registry`.

        Returns:
            Findings from every module walked, grouped by module in walk order.

        Raises:
            SweetTeaError: When no path is given and the caller's module cannot be
                determined.
        """
        if path is None:
            caller = inspect.getmodule(inspect.stack()[1][0])
            if caller is None or caller.__file__ is None:
                raise SweetTeaError("Cannot determine module path automatically")
            path = str(Path(caller.__file__).parent)

        path_str = str(path)
        if module is None:
            module = os.path.basename(path_str)

        exclude_patterns = tuple(exclude or ())
        findings: list[AuditFinding] = []

        # Filling never scans a package's __init__ — packages are descended into, not
        # registered from — but importing the package always runs it, so it is the
        # most likely place for work that assumes an already-populated registry.
        package_init = os.path.join(path_str, "__init__.py")
        if os.path.isfile(package_init):
            findings.extend(LazyAudit.audit_file(package_init, module))

        for name, is_a_package in cls.__iter_package_children(path_str):
            child = f"{module}.{name}"
            if cls.__is_excluded(child, exclude_patterns):
                continue

            if is_a_package:
                findings.extend(
                    cls.lazy_audit(
                        path=os.path.join(path_str, name),
                        module=child,
                        exclude=exclude_patterns,
                    )
                )
                continue

            source_file = os.path.join(path_str, f"{name}.py")
            if os.path.isfile(source_file):
                findings.extend(LazyAudit.audit_file(source_file, child))

        return findings

    @classmethod
    def __scan_entry_to_registry(
        cls, label: str, library: str, name_of_package: str, source_file: str
    ) -> None:
        """
        Register a module's classes by name, without importing it.

        The scanner reports the module-level bindings that eager registration would
        have registered, keyed the same way — on the attribute name rather than the
        class's ``__name__``. Names it cannot see, and guesses that turn out not to be
        classes, are corrected when the module is actually imported.

        Args:
            label: Optional label for categorizing classes.
            library: Name of the library the classes belong to.
            name_of_package: Full dotted module name.
            source_file: Path to the module's source.

        Raises:
            SweetTeaError: When the source cannot be read or parsed. The eager path
                fails on such a module too, by way of the import.
        """
        for attribute in LazyScanner.scan_file(source_file):
            cls.register_lazy(
                key=attribute.lower(),
                module=name_of_package,
                attribute=attribute,
                library=library,
                label=label,
            )

        with cls.__lock:
            # Recorded even when the scan found nothing: classes injected at runtime
            # leave no trace in the source, and the sweep can only reach a module it
            # has been told about.
            cls.__unresolved.setdefault(
                name_of_package, (library.lower(), label.lower(), 0)
            )

    @classmethod
    def __is_orphaned(cls, class_def: type, name_of_package: str) -> bool:
        """
        Whether a class was built by a helper in this package and belongs nowhere.

        Discovery registers the classes a module defines, judged by ``__module__``.
        That filter is what stops an imported class being registered again under every
        module that imports it — but it also drops a class built by a helper living
        somewhere else:

        .. code-block:: python

            # pkg/helpers.py
            def make_class(name):
                return type(name, (), {})

            # pkg/models.py
            Thing = make_class("Thing")

        ``type()`` stamps ``__module__`` from the calling frame, so ``Thing`` claims
        ``pkg.helpers`` — which does not hold it either, since it was never bound
        there. Before SWE-11 such a class was registered by nothing at all.

        An orphan is exactly that case: its home module does not have it under its own
        name. An ordinary imported class is not an orphan, because its home module does
        hold it, so this does not widen discovery to re-register imports.

        The home module must also sit inside the package being filled. Without that,
        C-implemented types caught this: ``types.MappingProxyType`` claims ``builtins``
        as its home and is named ``mappingproxy`` there, so ``builtins`` does not bind
        it under its own name and it looks orphaned — which would register a stdlib
        type into every registry that imported it. Requiring the same root keeps this
        to "a helper inside this package built this class", which is the case worth
        rescuing. A class built by a helper in some *other* distribution stays
        unregistered.

        Args:
            class_def: The class being considered.
            name_of_package: Dotted path of the module being scanned.

        Returns:
            True when the class was built inside this package and no module binds it.
        """
        home_name = getattr(class_def, "__module__", "") or ""
        if home_name.split(".")[0] != name_of_package.split(".")[0]:
            return False

        home = sys.modules.get(home_name)
        if home is None:
            # The home module is not imported, so nothing can be concluded. Staying
            # conservative keeps the previous behaviour rather than guessing.
            return False

        class_name = getattr(class_def, "__name__", "")
        return bool(class_name) and getattr(home, class_name, None) is not class_def

    @classmethod
    def __is_excluded(cls, dotted_name: str, patterns: tuple[str, ...]) -> bool:
        """
        Test a dotted module path against the caller's exclude patterns.

        Uses :func:`fnmatch.fnmatchcase` rather than :func:`fnmatch.fnmatch`; the latter
        applies ``os.path.normcase``, making matches case-insensitive on Windows. Module
        names are case-sensitive, so matching must not vary by platform.

        Args:
            dotted_name: Full dotted path of the module or package under consideration.
            patterns: Glob patterns supplied by the caller.

        Returns:
            True when any pattern matches.
        """
        return any(fnmatch.fnmatchcase(dotted_name, pattern) for pattern in patterns)

    @classmethod
    def __iter_package_children(cls, pkg_dir: str) -> list[tuple[str, bool]]:
        """
        List the importable children of a package directory.

        Extends :func:`pkgutil.iter_modules`, which reports a subdirectory only when it
        contains an ``__init__``. Implicit namespace packages (PEP 420) have no
        ``__init__`` and are therefore invisible to it — not reported as a package and
        not reported as a module — so their contents were silently skipped during
        registry filling.

        Args:
            pkg_dir: Directory to scan.

        Returns:
            Sorted (name, is_a_package) pairs, with namespace packages included.
        """
        children: dict[str, bool] = {
            name: is_a_package
            for _, name, is_a_package in pkgutil.iter_modules([pkg_dir])
        }

        if os.path.isdir(pkg_dir):
            with os.scandir(pkg_dir) as directory_entries:
                for directory_entry in directory_entries:
                    if directory_entry.name in children:
                        continue
                    if not directory_entry.is_dir(follow_symlinks=False):
                        continue
                    if cls.__is_namespace_package(
                        directory_entry.name, directory_entry.path
                    ):
                        children[directory_entry.name] = True

        return sorted(children.items())

    @classmethod
    def __is_namespace_package(cls, name: str, path: str) -> bool:
        """
        Decide whether a directory lacking ``__init__`` should be treated as a package.

        ``__init__.py`` used to act as a de-facto opt-in marker, so treating every bare
        directory as a package risks descending into directories that are not packages
        at all. These filters restore that boundary without making users opt in to
        namespace support.

        Args:
            name: Directory name.
            path: Full path to the directory.

        Returns:
            True when the directory is a plausible namespace package.
        """
        # Not importable under any circumstances - 'my-pkg', 'v1.2', 'sample data'.
        if not name.isidentifier():
            return False

        # Hidden ('.venv', '.git') and private or generated ('__pycache__') directories.
        if name.startswith(".") or name.startswith("_"):
            return False

        # A namespace package must eventually lead to a module; a directory holding only
        # data files is not one. Nested namespace packages are legal, so this recurses.
        with os.scandir(path) as directory_entries:
            for directory_entry in directory_entries:
                if directory_entry.is_file(follow_symlinks=False):
                    if inspect.getmodulename(directory_entry.name) is not None:
                        return True
                elif directory_entry.is_dir(follow_symlinks=False):
                    if cls.__is_namespace_package(
                        directory_entry.name, directory_entry.path
                    ):
                        return True

        return False

    @classmethod
    def __add_entry_to_registry(
        cls, label: str, library: str, name_of_package: str
    ) -> None:
        """
        Import a module and register all classes defined in it.

        Handles optional dependencies by issuing warnings for ImportError/ModuleNotFoundError
        and continuing, while raising SweetTeaError for other exceptions.

        Args:
            label: Optional label for categorizing classes.
            library: Name of the library the classes belong to.
            name_of_package: Full module name to import and scan.

        Raises:
            SweetTeaError: For non-import related errors during module processing.
        """
        try:
            # exec("import " + name_of_package)
            module = importlib.import_module(name_of_package)

            classes = []
            for name, obj in inspect.getmembers(module, inspect.isclass):
                if obj.__module__ == name_of_package or cls.__is_orphaned(
                    obj, name_of_package
                ):
                    classes.append((name, obj))

            for class_name, class_def in classes:
                Registry.register(
                    key=class_name.lower(),
                    class_def=class_def,
                    library=library,
                    label=label,
                    attribute=class_name,
                )

        except (ImportError, ModuleNotFoundError):
            # Optional dependency not installed - issue warning and skip this module
            warnings.warn(
                f"Skipping module {name_of_package} due to missing optional dependency",
                SweetTeaWarning,
                stacklevel=2,
            )
            cls.__skipped[name_of_package] = "missing optional dependency"
            # Continue without registering this module
        except Exception:
            # Other errors (e.g., syntax errors, runtime errors) should still fail
            error_message = traceback.format_exc()
            cls.__logger.error(
                f"Error processing module {name_of_package}: {error_message}"
            )
            raise SweetTeaError(error_message)


# Entry.class_def resolves through the registry; the hook is installed here because
# entry.py cannot import this module without a cycle.
set_resolver(Registry._resolve_entry_class)
