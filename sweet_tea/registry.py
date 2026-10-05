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
from types import ModuleType
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

    This registry automatically discovers and registers classes from packages. A
    module whose import raises — a missing optional dependency, a platform guard, or
    a bug — is skipped with a warning naming what it raised rather than failing the
    whole registration; :meth:`skipped` records them.

    The registry supports typed lookups for abstract factories, allowing filtering
    by inheritance hierarchy.

    Thread-safe: every read and write of the registry's own state is synchronized.
    The lock guards that state and nothing else — in particular it is **not** held
    while a module is imported, because running a module body under it deadlocks
    against CPython's per-module import locks (SWE-22). Concurrent fills and
    resolutions therefore interleave, which is safe: registration dedupes by
    identity, and resolution re-reads the registry after importing rather than
    trusting what it saw before.
    """

    # Threading lock for the registry's own state. Never held across an import; see
    # the class docstring and __resolve_module.
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
    # Keyed by module, then by the (library, label) each fill used, mapped to how
    # many entries that fill's scan contributed. One pair per module was not enough:
    # the same tree may be filled under several libraries, and resolution registered
    # everything discovery found under whichever pair arrived first, losing the
    # classes only discovery can see for every other pair (SWE-30).
    __unresolved: dict[str, dict[tuple[str, str], int]] = {}

    # Set when any subtree was filled with lazy="strict": a key that no static scan
    # could see then raises instead of triggering a whole-tree sweep.
    # Roots filled with lazy="strict". Strictness belongs to a tree, not to the
    # process: a library doing its own strict fill must not stop an application's
    # unrelated tree from sweeping (SWE-25). Keyed by the root module the fill
    # started from, which is also how __fills keys itself.
    __strict_fills: set[str] = set()

    # Trees that have been filled, mapped to the directory walked. Only the outermost
    # call of each fill is recorded, so a snapshot names the roots a consumer asked
    # for rather than every subpackage underneath them.
    __fills: dict[str, str] = {}

    # Nesting depth of fill_registry, which recurses into subpackages.
    __fill_depth: int = 0

    # Modules that were not registered, mapped to why: the category of the failure
    # and the exception that caused it. Exported alongside the entries so a
    # snapshot's reader can tell "not registered" from "not installed", and either of
    # those from "this module is broken here".
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
                if lookup_type is Any:
                    # Any matches everything - return all entries without filtering
                    slot = cls.__registry.copy()
                else:
                    slot = [
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

                # Recorded only once the slot exists. Appending the key first meant
                # that an argument issubclass refuses -- this parameter is typed Any,
                # so a Protocol, a tuple of non-types or a plain int reaches it --
                # left the key registered with no slot, and every later call with it
                # raised a bare KeyError out of the library instead of repeating the
                # honest TypeError (SWE-31).
                cls.__lookup[lookup_type] = slot
                cls.__lookup_keys.append(lookup_type)
            return cls.__lookup[lookup_type].copy()

    @classmethod
    def register(
        cls,
        key: str,
        class_def: type,
        library: str = "",
        label: str = "",
        attribute: str = "",
        module: str = "",
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
            module: Module the class is *bound to*, when known — which is not always
                where the class says it lives. A class built by a helper elsewhere in
                the package carries that helper's ``__module__`` (``type()`` stamps it
                from the calling frame), so a snapshot naming it that way names a pair
                that does not exist (SWE-24). Discovery passes the module it was
                walking. Omitted, this falls back to ``class_def.__module__``, which is
                the best available answer for a direct ``register`` call.
        """
        new_entry = Entry(
            key=key.lower(),
            class_def=class_def,
            module=module or getattr(class_def, "__module__", ""),
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
        provisional: bool = False,
    ) -> None:
        """
        Register a class by name, deferring its module's import until first use.

        The entry carries no class object. The module is imported, and the entry
        resolved to the class it names, the first time a factory needs this key (see
        :meth:`ensure_resolved`). Resolving the module also registers everything else
        eager discovery finds in it, so a key this registration happens to share with
        a discovered class ends up with one entry rather than two.

        The key, library and label are kept as given. Resolution carries an entry
        discovery would not reproduce — an alias, or a registration categorised
        differently from the module it lives in — forward onto the resolved class
        rather than replacing it with what discovery found (SWE-17), so an alias
        survives first use. The one way such an entry disappears is the honest one:
        the module no longer binds a class under ``attribute``, in which case nothing
        was there to register.

        Args:
            key: Name used to reference the class for instantiation.
            module: Dotted path of the module that defines it.
            attribute: Module attribute the class is bound to.
            library: Name of the library the class belongs to.
            label: Optional label for categorizing classes.
            provisional: True when the name was read out of source rather than asked
                for. A scanned name is a guess, so discovery overrules it once the
                module is imported; an explicit registration is a request, so it is
                kept (SWE-20). Callers outside this class leave it False, which is
                what makes an alias survive resolution.
        """
        new_entry = Entry(
            key=key.lower(),
            module=module,
            attribute=attribute,
            provisional=provisional,
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
                categories = cls.__unresolved.setdefault(module, {})
                pair = (library.lower(), label.lower())
                categories[pair] = categories.get(pair, 0) + 1

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
        wanted = {key.lower() for key in keys}

        # Each phase reads state under the lock and then releases it, because
        # __resolve_module imports and must not be called holding it (SWE-22). State
        # can therefore change between phases; every phase re-reads rather than
        # trusting what the previous one saw.
        with cls.__lock:
            if not cls.__unresolved:
                return
            pending = sorted(
                {
                    entry.module
                    for entry in cls.__registry
                    if entry.is_lazy and entry.key in wanted
                }
            )

        for module_name in pending:
            cls.__resolve_module(module_name)

        with cls.__lock:
            if not sweep or not cls.__unresolved:
                return
            if any(entry.key in wanted for entry in cls.__registry):
                return
            # Before importing anything, harvest the pending modules something else
            # already imported — a module pulled in as a side effect of resolving
            # another is in sys.modules but still unreconciled, so a class it creates
            # at runtime is invisible. Reconciling those costs no imports and often
            # avoids the sweep entirely.
            already_imported = sorted(
                name for name in cls.__unresolved if name in sys.modules
            )

        for module_name in already_imported:
            cls.__resolve_module(module_name)

        with cls.__lock:
            if not cls.__unresolved:
                return
            if any(entry.key in wanted for entry in cls.__registry):
                return

            requested = ", ".join(sorted(wanted))
            # Strictness is per tree, so the pending modules split in two: those a
            # strict fill owns, which will not be imported, and the rest, which the
            # sweep may still have.
            sweepable = sorted(
                name for name in cls.__unresolved if not cls.__strict_owner(name)
            )
            refused = sorted(
                {
                    owner
                    for name in cls.__unresolved
                    if (owner := cls.__strict_owner(name))
                }
            )

        # Out of the lock before raising, warning or sweeping: resolving imports, and
        # a warning filter that escalates must not unwind holding the registry.
        if sweepable:
            # Reported, not silent: a sweep undoes the saving lazy filling exists
            # for, so the caller needs to know which key caused it.
            warnings.warn(
                f"Importing {len(sweepable)} remaining module(s) to look for "
                f"{requested}: no lazily registered name matched. Add the defining "
                f"module to fill_registry(eager=[...]) to avoid this.",
                SweetTeaWarning,
                stacklevel=2,
            )
            for module_name in sweepable:
                cls.__resolve_module(module_name)

            with cls.__lock:
                if any(entry.key in wanted for entry in cls.__registry):
                    return

        if refused:
            trees = ", ".join(refused)
            raise SweetTeaError(
                f"No entry for {requested}, and {trees} was filled with "
                f'lazy="strict", so its remaining modules will not be imported to '
                f"look for it. Name the module that defines it in "
                f"fill_registry(eager=[...]) if it is created at runtime rather "
                f"than by a class statement."
            )

    @classmethod
    def skipped(cls) -> dict[str, str]:
        """
        Modules that were not registered, mapped to why.

        Filling warns and skips a module whose import raises, whatever it raised.
        Without this, a caller cannot tell a class that was never written from one
        whose module could not be imported on this machine.

        Each reason reads ``<category>: <ExceptionType>[: <message>]``. The category
        is either ``missing optional dependency`` — an ``ImportError``, so the
        install profile showing through — or ``import failed`` for anything else: a
        platform guard like ``click._winconsole``'s ``assert sys.platform ==
        "win32"``, a module wanting an environment variable, or a genuine bug. The
        exception type is part of the reason precisely so the last of those can be
        told from the first two without re-running the fill.

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
        attribute, and a resolved one is named from the class it holds. Locating a
        tree's root package to record its relative position goes through
        :func:`importlib.util.find_spec` on the top-level name, which executes nothing
        either. The trees that were filled are recorded with a digest of their sources
        and their position inside their root package, so :meth:`load` can tell whether
        the snapshot still matches the code wherever that package is installed.

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
                    relative_path=SnapshotSource.relative_to_root(filled, filled_path),
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
                longer exist, and the failure surfaces far from the cause. The sources
                are looked for where their root package is installed now, so a snapshot
                built elsewhere — in CI, then shipped inside the wheel — verifies on
                its own merits rather than being refused for having moved.

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

            # The trees the snapshot describes become this registry's fill roots, so
            # a later export describes them too. Without this, export built sources
            # from __fills, load never populated it, and a load-then-export cycle
            # produced a snapshot with no sources at all — one whose verify=True can
            # never fail, which looks like a verified load and is not one (SWE-27).
            # Recorded at the directory the source resolves to now rather than the
            # one it was exported from, so a re-export digests the live tree.
            for source in snapshot.sources:
                cls.__fills.setdefault(source.module, source.resolved_path())

    @classmethod
    def _resolve_entry_class(cls, module: str, attribute: str) -> type:
        """
        Import a lazy entry's module and hand back the class it names.

        Installed on :mod:`sweet_tea.entry` so that reading ``Entry.class_def`` on an
        unresolved entry works like reading it on any other — which is what keeps code
        that introspects :meth:`entries` directly working under lazy filling (SWE-13).

        The registry's own copy of the entry is reconciled at the same time, so the
        import is paid once however it was triggered.

        A module whose import raises is only warned about during a fill, but reading
        one specific class from it still raises here: the property has to hand back a
        class, and there is none. What :meth:`skipped` records is the fill's verdict
        on a module; this is a caller asking for a named class in it.

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
        cls.__resolve_module(module)

        try:
            module_object = importlib.import_module(module)
        except Exception as error:
            # Named by type as well as message: a bare ``assert`` raises an
            # AssertionError carrying no message at all, and a report built from
            # str(error) alone is empty exactly where it matters (SWE-15).
            raise SweetTeaError(
                f"Cannot resolve {attribute} from {module}: "
                f"{cls.__describe_exception(error)}"
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
    def __strict_owner(cls, module_name: str) -> str | None:
        """
        The strictly filled root that owns a module, if any.

        Args:
            module_name: Dotted path of a pending module.

        Returns:
            The root it belongs to, or None when no strict fill covers it.
        """
        for root in cls.__strict_fills:
            if module_name == root or module_name.startswith(f"{root}."):
                return root
        return None

    @classmethod
    def resolve_all(cls) -> None:
        """
        Import every module still pending, leaving the registry fully eager.

        Use when an exact view of the registry matters more than the deferral — for
        example before reading :meth:`entries` for introspection.
        """
        # Snapshot under the lock, resolve without it: __resolve_module imports.
        # A module another thread resolves meanwhile is a no-op here, and one added
        # meanwhile is picked up by the loop's re-read.
        while True:
            with cls.__lock:
                pending = sorted(cls.__unresolved)
            if not pending:
                return
            for module_name in pending:
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

        Discovery alone is not the whole answer, because not every lazy entry came
        from a scan. ``register_lazy`` is public, and a caller using it to register an
        alias — its own key, library or label, pointing at one attribute — asks for
        something discovery cannot reproduce by construction. Rebuilding from
        discovery only would therefore destroy the registration that triggered the
        import (SWE-17), so entries discovery will not reproduce are carried forward
        by :meth:`__carry_forward_lazy_entries` instead of being dropped.

        A module whose import raises is reported and its lazy entries dropped, the
        way the eager fill reports and skips it (see :meth:`__skip_module`), so the
        lookup that triggered this sees the same registry an eager fill would have
        built. It is popped from the pending index either way, so an import known to
        fail is attempted once rather than once per lookup.

        The caller must NOT hold ``__lock``. Importing a module runs its body, and
        running third-party code under the registry's lock is what deadlocked against
        CPython's per-module import locks: a thread importing such a module holds its
        import lock and wants the registry's, while this held the registry's and
        wanted the import lock (SWE-22). So the work is three phases — claim the
        module under the lock, import and read it with no lock held, apply the result
        under the lock again — and the last phase tolerates another thread having
        resolved the same module in between.

        Args:
            module_name: Dotted path of the module to import.
        """
        with cls.__lock:
            if module_name not in cls.__unresolved:
                return

            categories = cls.__unresolved.pop(module_name)

            # Snapshotted while the lock is held: the import below runs without it,
            # and carry-forward must not read live state.
            pending = [
                entry
                for entry in cls.__registry
                if entry.is_lazy and entry.module == module_name
            ]

            # The documented reset clears __registry directly, which can leave this index
            # holding modules whose entries are gone. Importing them would resurrect
            # registrations the caller just cleared. A module that contributed nothing to
            # begin with is exempt: it has no entries to have lost, and is exactly the
            # case the sweep exists for.
            if any(categories.values()) and not pending:
                return

        try:
            module = importlib.import_module(module_name)
            # Collected inside the same protection the import gets, and for the same
            # reason the eager path does it: attribute access runs the module's code
            # too. It also keeps "all of this module or none of it" true.
            found = [
                (class_name, class_def)
                for class_name, class_def in inspect.getmembers(module, inspect.isclass)
                if class_def.__module__ == module_name
                or cls.__is_orphaned(class_def, module_name)
            ]
            # Inside the try for the same reason ``found`` is: this reads attributes
            # off the freshly imported module, which runs the module's code, and a
            # module that blows up part-way through must be skipped whole rather than
            # half-registered.
            # Per (library, label): discovery produces the same classes for each,
            # but under that pair's categorisation, so what counts as "discovery
            # already reproduced this" differs per pair.
            carried = {
                pair: cls.__carry_forward_lazy_entries(
                    module, module_name, found, pair[0], pair[1], pending
                )
                for pair in categories
            }
        except Exception as error:
            # Same contract as the eager path, whatever was raised: the module is
            # reported and its entries removed rather than the lookup failing
            # (SWE-15). Both modes therefore end up registering the same classes.
            # The difference deferral cannot remove is *when* it is reported: the
            # eager fill warns while walking the tree, this warns at the lookup that
            # first needed the module.
            #
            # Dropped before reporting, not after: under
            # warnings.simplefilter("error", SweetTeaWarning) the warning leaves
            # through this frame, and entries pointing at a module now known to be
            # unimportable must not be left behind for the next lookup to retry.
            with cls.__lock:
                cls.__drop_lazy_entries(module_name)
            # Reported outside the lock: a filter escalating this warning to an
            # exception unwinds through here, and must not do so holding the registry.
            cls.__skip_module(module_name, error)
            return

        with cls.__lock:
            # Another thread may have resolved this module while the import ran. Its
            # entries are already reconciled, so dropping and re-registering is
            # harmless -- register() dedupes by identity -- but the drop has to see
            # the registry as it is now, not as it was when claimed.
            cls.__drop_lazy_entries(module_name)

            for pair in categories:
                for class_name, class_def in found:
                    cls.register(
                        key=class_name.lower(),
                        class_def=class_def,
                        library=pair[0],
                        label=pair[1],
                        attribute=class_name,
                        module=module_name,
                    )

                # After discovery, not before: an explicit registration for a class
                # discovery also registers must end up alongside that entry, and this
                # order keeps the discovered keys where they have always been.
                for entry, class_def in carried[pair]:
                    cls.register(
                        key=entry.key,
                        class_def=class_def,
                        library=entry.library,
                        label=entry.label,
                        attribute=entry.attribute,
                        module=entry.module,
                    )

    @classmethod
    def __carry_forward_lazy_entries(
        cls,
        module: ModuleType,
        module_name: str,
        found: list[tuple[str, type]],
        library: str,
        label: str,
        pending: list[Entry],
    ) -> list[tuple[Entry, type]]:
        """
        Resolve the lazy entries for a module that discovery will not re-register.

        Reconciliation replaces a module's lazy entries with what discovery finds.
        That is right for an entry the *scanner* contributed — it was a reading of the
        source, and the import is the authority that corrects it — but wrong for one a
        caller contributed through ``register_lazy``, which is a statement of intent
        that no amount of discovery can rediscover. Discovery keys every class on
        ``class_name.lower()`` under the module's own library and label, so an alias
        (``key="my_alias"``), a differently categorised registration (``library=``,
        ``label=``) or any other deliberate spelling is exactly what reconciliation
        used to destroy, at the lookup that first needed it (SWE-17). Worse than
        losing the entry: with other modules still pending, the miss escalated to the
        fallback sweep, so the caller paid every import in the tree and still did not
        get its class.

        An entry is carried forward only when discovery will not produce its
        ``(key, library, label)`` — anything discovery does produce is about to be
        registered from the live class anyway, and re-adding it here would be a second
        registration of the same name.

        A carried entry is kept only if its attribute is a class *now*. That is what
        preserves the parity the scan depends on: a provisional guess that turned out
        to be a function, a value, or nothing at all still disappears on resolution,
        so the post-resolution registry still matches an eager fill exactly (SWE-10).
        The test is deliberately only "is it a class", without discovery's
        ``__module__`` filter. That filter exists to stop discovery registering an
        imported class again under every module that imports it; an explicit
        ``register_lazy`` has already named the module and the attribute, so a
        registration pointed at a re-export is a legitimate request rather than an
        accident of iteration. The trade-off is that a *scanned* binding whose class
        claims a foreign ``__module__`` — ``create_model(..., __module__="other")``
        and little else — now survives resolution where an eager fill would not have
        registered it. Keeping an explicitly requested alias is worth more than
        matching the eager fill on a name the scanner had to guess at anyway.

        The caller must NOT hold ``__lock``: this reads attributes off the module,
        which runs its code, and no third-party code may run under the registry's
        lock (SWE-22). It therefore works from ``pending`` — a snapshot of the
        module's lazy entries taken while the lock was held — rather than reading the
        live registry.

        Args:
            module: The freshly imported module.
            module_name: Dotted path of that module.
            found: Discovery's ``(attribute name, class)`` pairs for it.
            library: Library the module's lazy entries were filled under.
            label: Label the module's lazy entries were filled under.
            pending: The module's lazy entries, as they stood when it was claimed.

        Returns:
            ``(entry, class)`` pairs to re-register, in registry order.
        """
        # register() lowercases key, library and label, and the pending index stores
        # the pair already lowercased, so these triples compare like with like.
        reproduced = {(class_name.lower(), library, label) for class_name, _ in found}

        carried: list[tuple[Entry, type]] = []
        for entry in pending:
            if (entry.key, entry.library, entry.label) in reproduced:
                continue

            resolved = getattr(module, entry.attribute, None)
            if not isinstance(resolved, type):
                continue

            # A scanned name is only a guess about what the source would produce, so
            # discovery's own rules decide whether to keep it: the class must belong
            # to this module, or be one no module binds (SWE-20). Without this, a
            # name the scanner saw bound to a class from somewhere else survived --
            # the try/except import fallback is the common shape, and it registered a
            # third-party class under this library's name:
            #
            #     try:
            #         from foreignlib import Encoder
            #     except ImportError:
            #         class Encoder: ...
            #
            # An explicit register_lazy is not a guess and is kept regardless, which
            # is the whole point of carrying entries forward: a caller naming module
            # and attribute may well be pointing at a re-export.
            if entry.provisional and not (
                resolved.__module__ == module_name
                or cls.__is_orphaned(resolved, module_name)
            ):
                continue

            carried.append((entry, resolved))

        return carried

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

        # A module with nothing left to resolve is not pending. It can be re-added
        # while it is being resolved -- a module body calling register_lazy puts it
        # back -- and the drop above then removes the entry that call created,
        # stranding the index entry. ensure_resolved's "nothing pending" fast path
        # then never fired again, so every total miss walked the sweep path and
        # lazy="strict" cited a module with nothing to import (SWE-32).
        if not any(
            entry.is_lazy and entry.module == module_name for entry in cls.__registry
        ):
            cls.__unresolved.pop(module_name, None)

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

        This method automatically discovers all classes in the package hierarchy. A
        module whose import raises is warned about and skipped, whatever it raised —
        an uninstalled optional dependency, a platform guard, a syntax error — and
        the walk continues, so no single module can cost a package its registration.
        :meth:`skipped` maps each such module to the exception behind it, and
        escalating :class:`~sweet_tea.sweet_tea_warning.SweetTeaWarning` to an error
        makes the first skip fail the fill for callers who want that.

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
        # Deliberately not holding __lock across the walk. The walk imports, and
        # holding the registry's lock while a module body runs is what deadlocked
        # against CPython's per-module import locks -- a thread importing one of
        # these modules holds its import lock and wants the registry's, while the
        # fill held the registry's and wanted the import lock (SWE-22). Nothing
        # here mutates registry state directly: register, register_lazy and the
        # skip record each take the lock for their own write, and concurrent fills
        # interleave safely because registration dedupes by identity.
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
        with cls.__lock:
            if not any(
                module == filled or module.startswith(f"{filled}.")
                for filled in cls.__fills
            ):
                cls.__fills[module] = path_str

            # Recorded under the lock, and separately from __fills: a tree already
            # recorded there by an earlier fill would otherwise never pick up a later
            # strict one. Judged by ancestry for the same reason __fills is, so a
            # recursive call into a subpackage does not add a second root.
            if lazy == "strict" and not cls.__strict_owner(module):
                cls.__strict_fills.add(module)

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
        eager_patterns = tuple(pattern for pattern in eager_values if pattern != "auto")

        # Loop over the modules. If it is a package, the make recursive call, otherwise for each non-package
        # module imports the module and registers it.
        for name, is_a_package in cls.__iter_package_children(pkg_dir):
            pkg_name = f"{module}.{name}"
            if cls.__is_excluded(pkg_name, exclude_patterns):
                # Logged rather than dropped silently; an under-filled registry with
                # no explanation is the failure mode this whole area keeps hitting.
                cls.__logger.debug(f"Skipping {pkg_name}: matched an exclude pattern")
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
                        cls.__logger.debug(f"Filling {pkg_name} eagerly: {findings[0]}")
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

        A module whose source cannot be scanned does not fail the fill. Which way it
        is handled depends on why, because the two reasons do not mean the same thing
        (SWE-23):

        - **Unparsable** source cannot be imported either, so the module is reported
          and skipped exactly as the eager path reports and skips it. Both modes then
          register the same classes, which is the parity lazy filling rests on.
        - **Unreadable** source may still import, from cached bytecode: CPython needs
          to stat the source but not read it. Verified — a module whose ``.py`` is
          mode 000 imports fine from its ``.pyc``. The eager path would register its
          classes, so skipping here would break parity in the other direction. It
          falls back to importing the module instead.

        Before this, either reason aborted the whole fill and left the registry half
        populated, losing every module after the bad one.

        Args:
            label: Optional label for categorizing classes.
            library: Name of the library the classes belong to.
            name_of_package: Full dotted module name.
            source_file: Path to the module's source.
        """
        try:
            attributes = LazyScanner.scan_file(source_file)
        except SweetTeaError as error:
            if isinstance(error.__cause__, OSError):
                cls.__logger.debug(
                    f"Cannot read {source_file}; importing {name_of_package} instead"
                )
                cls.__add_entry_to_registry(
                    label=label, library=library, name_of_package=name_of_package
                )
                return
            # Reported the way an unimportable module is reported, and for the same
            # reason: the caller gets a registry that is short by one module, with a
            # warning and a skipped() record saying which and why.
            cls.__skip_module(name_of_package, error.__cause__ or error)
            return

        for attribute in attributes:
            cls.register_lazy(
                key=attribute.lower(),
                module=name_of_package,
                attribute=attribute,
                library=library,
                label=label,
                provisional=True,
            )

        with cls.__lock:
            # Recorded even when the scan found nothing: classes injected at runtime
            # leave no trace in the source, and the sweep can only reach a module it
            # has been told about.
            cls.__unresolved.setdefault(name_of_package, {}).setdefault(
                (library.lower(), label.lower()), 0
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

    @staticmethod
    def __describe_exception(error: BaseException) -> str:
        """
        Name an exception the way a reader needs it: the type, and the message if any.

        Reports built from ``str(error)`` alone go blank exactly where it matters.
        ``click._winconsole`` opens with ``assert sys.platform == "win32"``, and a
        bare ``assert`` raises an AssertionError carrying no message, so the type is
        the only thing there is to say about the commonest case this reports.

        Args:
            error: The exception to describe.

        Returns:
            ``"Type: message"``, or ``"Type"`` when the exception carries no message.
        """
        message = str(error)
        return f"{type(error).__name__}: {message}" if message else type(error).__name__

    @classmethod
    def __skip_module(cls, name_of_package: str, error: BaseException) -> None:
        """
        Report a module whose import failed and record why, instead of failing the fill.

        Only ImportError and ModuleNotFoundError used to be survivable here, on the
        reading that a failed import means "optional dependency not installed", and
        anything else aborted the whole fill. But a module body runs arbitrary code
        at import time, and the commonest reason it raises is not a bug: it is a
        module that was never meant to be imported here. ``click._winconsole`` is the
        case that found this — ``assert sys.platform == "win32"`` on line 35 — so
        filling over an installed click on Linux raised SweetTeaError the moment the
        walk reached it, abandoning every module after it. One platform-guarded
        module made the package unregistrable (SWE-15).

        Any exception is therefore survivable now, and what keeps a genuine bug
        visible is the report rather than the abort: the warning names the module,
        the exception type and its message, and :meth:`skipped` keeps the same string
        for inspection afterwards. The reason is categorised so the install profile
        of the machine stays distinguishable from everything else, which is the one
        distinction the old two-branch handling got right.

        No ``strict`` option accompanies this. The warning is a real
        :class:`~sweet_tea.sweet_tea_warning.SweetTeaWarning`, so a caller who would
        rather not continue already has ``warnings.simplefilter("error",
        SweetTeaWarning)`` — the Python mechanism for exactly this choice, with no new
        flag to keep consistent across the eager and lazy paths, where "at fill time"
        means two different moments. Set it in code rather than with ``-W``: the
        category there is resolved at interpreter start, before this package is
        importable, and an unresolvable one is ignored with a notice rather than
        honoured.

        The traceback goes to the log at DEBUG for the non-dependency case — the one
        piece of diagnosis a warning cannot carry, kept for whoever decides the skip
        is a bug and comes looking. It used to be logged at ERROR, which made sense
        while this also raised; printing a full traceback by default for a condition
        the library has just decided to continue past only teaches readers to skip
        past tracebacks. A caller who wants it unconditionally has the warnings
        filter: raised from inside the ``except`` block, the escalated warning
        chains onto the original exception, so the traceback comes out with it.

        Args:
            name_of_package: Full dotted path of the module that was skipped.
            error: What its import raised.
        """
        detail = cls.__describe_exception(error)
        if isinstance(error, ImportError):
            # ModuleNotFoundError is an ImportError, so this covers both.
            reason = f"missing optional dependency: {detail}"
            advice = "Install the dependency, or exclude the module from the fill."
        else:
            reason = f"import failed: {detail}"
            advice = (
                "Nothing it defines is registered. If the module is meant to import "
                "here, that exception is a bug rather than a platform or environment "
                "guard."
            )
            # format_exc reads the exception currently being handled; both call
            # sites report from inside their own except block.
            cls.__logger.debug(
                f"Error processing module {name_of_package}: {traceback.format_exc()}"
            )

        # Recorded before warning, so the record survives a caller who has turned
        # SweetTeaWarning into an error and will never see the return.
        with cls.__lock:
            cls.__skipped[name_of_package] = reason
        # stacklevel=3: this helper's own callers are internal, so the warning points
        # at whoever asked for the fill or the lookup, as it did when both paths
        # warned inline.
        warnings.warn(
            f"Skipping module {name_of_package}: {reason}. {advice}",
            SweetTeaWarning,
            stacklevel=3,
        )

    @classmethod
    def __add_entry_to_registry(
        cls, label: str, library: str, name_of_package: str
    ) -> None:
        """
        Import a module and register all classes defined in it.

        A module whose import raises is warned about and skipped, whatever it raised,
        so no single module can make its package unregistrable — see
        :meth:`__skip_module` for why that trade is the right one and how a caller
        gets the strict behaviour back.

        Reading the module's members counts as the module's own code, so it is inside
        the same protection: a module may answer attribute access with a PEP 562
        ``__getattr__``, which can raise for the same reasons an import can. Classes
        are collected before any of them is registered, so a module that fails is
        skipped whole rather than leaving half its classes behind.

        Registering what was collected is this library's own work, and a failure
        there is a bug here rather than in the module being filled — it still aborts
        with SweetTeaError, as it always has.

        Args:
            label: Optional label for categorizing classes.
            library: Name of the library the classes belong to.
            name_of_package: Full module name to import and scan.

        Raises:
            SweetTeaError: When registering the classes a module yielded fails.
        """
        try:
            module = importlib.import_module(name_of_package)
            classes = [
                (name, obj)
                for name, obj in inspect.getmembers(module, inspect.isclass)
                if obj.__module__ == name_of_package
                or cls.__is_orphaned(obj, name_of_package)
            ]
        except Exception as error:
            cls.__skip_module(name_of_package, error)
            return

        try:
            for class_name, class_def in classes:
                Registry.register(
                    key=class_name.lower(),
                    class_def=class_def,
                    library=library,
                    label=label,
                    attribute=class_name,
                    module=name_of_package,
                )
        except Exception:
            error_message = traceback.format_exc()
            cls.__logger.error(
                f"Error processing module {name_of_package}: {error_message}"
            )
            raise SweetTeaError(error_message)


# Entry.class_def resolves through the registry; the hook is installed here because
# entry.py cannot import this module without a cycle.
set_resolver(Registry._resolve_entry_class)
