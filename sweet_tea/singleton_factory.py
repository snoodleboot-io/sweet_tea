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
Singleton factory for registering and retrieving pre-configured instances.

This factory provides a service locator pattern where pre-configured instances
(singletons) can be registered and retrieved by key. Unlike the regular Factory
which creates new instances each time, SingletonFactory returns the same
registered instance.
"""

import contextlib
import copy
import logging
import math
import threading
import warnings
from typing import Any, Dict, Iterator

from pydantic import BaseModel

from sweet_tea.base_factory import BaseFactory
from sweet_tea.entry import Entry
from sweet_tea.sweet_tea_error import SweetTeaError
from sweet_tea.sweet_tea_warning import SweetTeaWarning


class SingletonFactory(BaseFactory):
    """
    Factory for registering and retrieving singleton instances.

    This implements the service locator pattern where pre-configured instances
    can be registered once and retrieved multiple times. This is useful for:

    - Singleton services that should only exist once
    - Pre-configured database connections
    - Dependency injection containers
    - Caching expensive-to-create objects

    Thread-safe: the cache is synchronized, and exactly one thread constructs the
    instance for a given key. The factory's lock is **not** held while a constructor
    runs — a constructor may itself resolve or create, and holding this lock across
    that inverted the lock order against the registry (SWE-22) — so construction is
    admitted by a per-key lock instead. Nor is it held while a configuration is judged
    for drift: that applies any declared configuration model, and a pydantic validator
    is arbitrary code on the same footing as a constructor (SWE-29).

    Because a constructor may resolve or create, it may also — by mistake or by design
    — ask for a singleton whose construction it is already inside. That is a circular
    dependency, and this factory reports it as a :class:`SweetTeaError` naming the
    cycle rather than blocking on a lock that can never be released (SWE-36).
    """

    # Threading lock for synchronizing operations
    __lock = threading.RLock()

    # Cached instances, keyed by the identity of the registry entry they were built
    # from: (key, library, label). Keying on the resolved entry rather than on the
    # caller's spelling is what makes the singleton guarantee hold — every spelling
    # of one key resolves to the same entry and therefore the same slot (see SWE-5).
    __instances: Dict[tuple[str, str, str], Any] = {}

    # The configuration each cached instance was built from, under the same key. Kept
    # so a later call passing a different one can be told that it had no effect (see
    # SWE-14); the instance itself is never rebuilt.
    #
    # Stored as the keyword arguments construction actually used, deep-copied away from
    # the caller's objects before the constructor ran (see SWE-29). None means the
    # basis could not be computed, which leaves drift undecidable rather than judged.
    __configurations: Dict[tuple[str, str, str], dict[str, Any] | None] = {}

    # One lock per cache key, guarding construction of that key's instance. The
    # factory's own lock cannot do this job: holding it across a constructor runs
    # arbitrary code under it, and a constructor that looks something up is ordinary
    # dependency injection (SWE-22). These are created under __lock and held without
    # it, so exactly one thread constructs a given key while every other key and
    # every cache read proceeds unblocked.
    #
    # Never discarded, not even by clear(). A lock dropped while a thread held it was
    # replaced by a fresh one for the same key on the next call, which admitted a
    # second thread into a construction already running and produced two instances of
    # a singleton (SWE-39). They are keyed by resolved cache key and so bounded by the
    # registry, which is a small price for the guarantee the class exists to make.
    __construction_locks: Dict[tuple[str, str, str], threading.Lock] = {}

    # The keys each thread is constructing, outermost first. Thread-local, so nothing
    # guards it: a thread is the only reader and the only writer of its own stack.
    # This is what catches the single-threaded shapes of SWE-36 — a constructor that
    # reaches back for its own key, or for one further up its own chain — before the
    # thread blocks forever on a lock it is already holding.
    __construction_stack = threading.local()

    # Who is constructing what, and what each thread has stopped to wait for: the
    # construction lock's owner per key, as (thread id, thread name), and the key each
    # blocked thread is waiting to be admitted to. Together they are a wait-for graph,
    # which is the only way to see the shape of SWE-36 no single thread's own stack
    # can show — two threads entering one cycle from opposite ends. Both are written
    # and read under __lock, and that is also what keeps them consistent with each
    # other: a thread walking the graph sees the state before a lock changed hands or
    # the state after, never half of each.
    __construction_owner: Dict[tuple[str, str, str], tuple[int, str]] = {}
    __blocked_on: Dict[int, tuple[str, str, str]] = {}

    # Stands in for the comparison basis of a configuration a declared
    # ``__configuration__`` will not accept. Not a basis, and not undecidable either: a
    # configuration that fails validation cannot be the one the cached instance was
    # built from, since that one validated. It drifted (see SWE-29).
    __REJECTED_BY_SCHEMA = object()

    # Logger instance
    _logger = logging.getLogger(__name__)

    @classmethod
    def create(
        cls,
        key: str,
        library: str = "",
        label: str = "",
        configuration: dict[str, Any] | BaseModel | None = None,
    ) -> Any:
        """
        Get an existing singleton instance or create a new one if it doesn't exist.

        This method provides lazy initialization - instances are created only when first requested.
        Subsequent calls with the same key will return the same cached instance.

        Args:
            key: Name to reference the class from the registry.
            library: Optional library filter for the class.
            label: Optional label filter for the class.
            configuration: Configuration parameters as keyword arguments, given as a
                dict or a pydantic model whose fields are spread into the constructor.

        Returns:
            The existing singleton instance, or a newly created and registered instance.

        Raises:
            SweetTeaError: If the key is not found in the registry, filters don't
                match, or the key is already being constructed by the calling thread
                or by a thread this call would deadlock against (see SWE-36).
        """
        # Resolved before this factory's lock is taken. Resolution imports, and
        # taking both locks across an import is what let a module body that creates a
        # singleton deadlock against a singleton whose constructor looks one up
        # (SWE-22). The cache is still keyed on the resolved entry rather than on the
        # caller's spelling, which is what makes every spelling share one slot
        # (SWE-5).
        entry = cls._select_entry(cls._find_entries(key), key, library, label)
        cache_key = (entry.key, entry.library, entry.label)

        with cls.__lock:
            cached = cache_key in cls.__instances
            if cached:
                cached_instance = cls.__instances[cache_key]
            else:
                construction_lock = cls.__construction_locks.setdefault(
                    cache_key, threading.Lock()
                )

        if cached:
            # Reported with no factory lock held, for the same reason construction is
            # not: judging drift applies a declared __configuration__, and a pydantic
            # validator is as much arbitrary code as a constructor (SWE-22, SWE-29).
            cls.__warn_on_configuration_drift(cache_key, entry, configuration)
            return cached_instance

        with cls.__admit_construction(cache_key, construction_lock):
            # Re-checked now that this thread owns construction for the key: another
            # thread may have finished between the miss above and this point.
            with cls.__lock:
                cached = cache_key in cls.__instances
                if cached:
                    cached_instance = cls.__instances[cache_key]

            if cached:
                # Again outside the factory lock. The construction lock is still held,
                # which costs nothing: the instance exists now, so a call this helper
                # provoked for the same key takes the cache-hit path above and never
                # reaches for this lock.
                cls.__warn_on_configuration_drift(cache_key, entry, configuration)
                return cached_instance

            # Recorded before the constructor runs, deliberately. A constructor is
            # entitled to mutate what it was handed — appending to a list it was given
            # is ordinary — and a basis captured afterwards would hold the constructor's
            # own edit. The next caller passing the configuration they actually passed
            # would then be blamed for a difference the first call introduced (SWE-29).
            comparison_basis = cls.__snapshot(cls.__comparable(entry, configuration))

            # No factory lock held here, by design: a constructor runs arbitrary code
            # and may itself resolve or create. The construction lock still admits
            # exactly one thread per key, so the single-instance guarantee holds. A
            # constructor that creates some *other* singleton is ordinary dependency
            # injection and proceeds; one that comes back for this key is a cycle, and
            # the admission above has it on this thread's stack so the nested call
            # raises instead of blocking on the lock this thread holds (SWE-36).
            new_instance = cls._construct(entry, configuration)

            with cls.__lock:
                cls.__instances[cache_key] = new_instance
                cls.__configurations[cache_key] = comparison_basis
                cls._logger.info(
                    f"Created and registered singleton instance: {entry.key}"
                )

        return new_instance

    @classmethod
    @contextlib.contextmanager
    def __admit_construction(
        cls,
        cache_key: tuple[str, str, str],
        construction_lock: threading.Lock,
    ) -> Iterator[None]:
        """
        Admit this thread to construct one key, or say why it never can.

        Construction is admitted by a per-key lock, and a plain lock is the right tool
        for the thing it guards — but only for threads that have something to wait for.
        A thread that already holds the lock has not: a constructor reaching back into
        :meth:`create` for the key it is being constructed under is asking for an
        instance that cannot exist until it returns. Blocking there was a hang with no
        traceback and no timeout, which is the one failure mode a container must never
        hand a consumer, since there is nothing left to debug (SWE-36). Circular
        dependencies are the consumer's mistake; reporting them is this factory's job.

        Two shapes are detected, by the two things that can see them:

        - **Within one thread** — the self-referential constructor, and the longer
          ``alpha -> beta -> alpha`` chain — against this thread's own construction
          stack, before any lock is touched. No shared state is read, so the check
          costs a list scan whose length is the depth of the dependency graph.
        - **Across threads** — two threads entering one cycle from opposite ends, each
          holding the lock the other needs. No thread's own stack can see this, so a
          thread about to block registers what it is waiting for and walks the wait-for
          graph. Whichever of the two registers second finds the chain closed and
          raises; the other is freed when that one unwinds, and then meets the cycle on
          its own stack.

        The alternative for the cross-thread case was acquiring with a timeout and
        calling expiry a deadlock. That was rejected: any timeout short enough to
        diagnose a deadlock promptly is one a legitimately slow constructor — a
        connection pool, a model load, a cold cache on a loaded CI box — can exceed,
        and turning a correct program into a failing one to diagnose an incorrect one
        is the wrong trade. The wait-for graph needs no number chosen, reports the
        instant the cycle closes rather than seconds later, and names the threads and
        keys involved. What it cannot see is a cycle that leaves this factory — a
        constructor blocking on a lock of the consumer's own, held by a thread waiting
        on a singleton — which no bookkeeping here could see either; that remains a
        documented limitation rather than a guess enforced by a timer.

        Args:
            cache_key: Identity of the entry being constructed.
            construction_lock: The key's construction lock, already created under the
                factory's lock by the caller.

        Yields:
            None, with the construction lock held and this thread recorded as the key's
            constructor.

        Raises:
            SweetTeaError: When this thread is already constructing the key, or when
                waiting for it would close a cycle of threads that can never finish.
        """
        stack = cls.__keys_under_construction()
        if cache_key in stack:
            cycle = stack[stack.index(cache_key) :] + [cache_key]
            raise SweetTeaError(
                f"Circular singleton construction for key '{cache_key[0]}': "
                f"{' -> '.join(cls.__describe(key) for key in cycle)}. A constructor "
                f"asked SingletonFactory for a singleton whose construction it is "
                f"already inside, so the instance it wants cannot exist yet. Break the "
                f"cycle: take the collaborator as a constructor argument, or look it up "
                f"after construction rather than during it."
            )

        identity = threading.get_ident()
        if not construction_lock.acquire(blocking=False):
            # Another thread is constructing this key. Ordinarily that is contention
            # and this thread simply waits for it; it is a deadlock only if that thread
            # is itself waiting, directly or through others, on a key this thread is
            # constructing.
            cls.__block_until_admitted(cache_key, construction_lock, identity)

        with cls.__lock:
            cls.__construction_owner[cache_key] = (
                identity,
                threading.current_thread().name,
            )
        stack.append(cache_key)
        try:
            yield
        finally:
            # Unwound in the reverse order, and unconditionally: a constructor that
            # raises must leave the key constructible again, so the next caller
            # re-enters the constructor and sees the real exception rather than a
            # report of a cycle that is no longer in progress.
            stack.pop()
            with cls.__lock:
                cls.__construction_owner.pop(cache_key, None)
            construction_lock.release()

    @classmethod
    def __block_until_admitted(
        cls,
        cache_key: tuple[str, str, str],
        construction_lock: threading.Lock,
        identity: int,
    ) -> None:
        """
        Wait for another thread's construction of a key, unless that would deadlock.

        The wait is registered before it is judged, and both happen in one hold of the
        factory's lock. That ordering is what makes the detection complete rather than
        best-effort: two threads closing a cycle each register, and the one that
        registers second necessarily sees the other's registration, so the cycle cannot
        be missed by both. The lock is released before blocking, since blocking under it
        is the lock inversion SWE-22 exists to prevent.

        Args:
            cache_key: The key this thread wants to construct.
            construction_lock: Its construction lock, currently held by another thread.
            identity: This thread's id, as :func:`threading.get_ident` reports it.

        Raises:
            SweetTeaError: When the wait would close a cycle of threads waiting on one
                another's constructions.
        """
        with cls.__lock:
            cls.__blocked_on[identity] = cache_key
            chain = cls.__deadlock_chain(cache_key, identity)
            if chain is not None:
                del cls.__blocked_on[identity]

        if chain is not None:
            raise SweetTeaError(
                f"Deadlocked singleton construction for key '{cache_key[0]}': "
                f"{' -> '.join(chain + [cls.__describe(cache_key)])}. Two or more "
                f"threads are each constructing a singleton another of them is waiting "
                f"for, so none of them can finish. This is the same circular "
                f"dependency as the single-threaded case, entered from both ends at "
                f"once: break the cycle rather than retrying, since a retry will "
                f"deadlock again."
            )

        try:
            construction_lock.acquire()
        finally:
            # Cleared whether or not the wait succeeded, so a thread that is running
            # again is never read as still blocked.
            with cls.__lock:
                cls.__blocked_on.pop(identity, None)

    @classmethod
    def __deadlock_chain(
        cls, wanted: tuple[str, str, str], identity: int
    ) -> list[str] | None:
        """
        Follow the wait-for graph from a key, looking for a way back to this thread.

        Must be called with the factory's lock held and this thread's wait already
        registered, so that what the walk reads is the whole graph at one instant.

        Each hop asks the same two questions: who is constructing the key being waited
        for, and is that thread itself waiting? An owner that is running, or a key with
        no owner at all, ends the walk — the chain terminates in work that can finish,
        which is contention and not deadlock. An owner that turns out to be *this*
        thread closes the circle: this thread cannot release what it is constructing
        while it waits, so nothing in the chain can ever proceed.

        Args:
            wanted: The key this thread is waiting to construct.
            identity: This thread's id, as :func:`threading.get_ident` reports it.

        Returns:
            The chain of keys and the threads holding them, as text ready to join, when
            waiting would deadlock; None when the wait is ordinary contention.
        """
        chain: list[str] = []
        key = wanted
        # At most one hop per thread that could be holding a construction lock: a walk
        # longer than that has revisited a thread, which with every edge recorded under
        # one lock cannot happen without passing through this thread first.
        for _ in range(len(cls.__construction_owner) + 1):
            owner = cls.__construction_owner.get(key)
            if owner is None:
                return None

            owner_identity, owner_name = owner
            chain.append(f"{cls.__describe(key)} (being constructed on {owner_name})")
            if owner_identity == identity:
                return chain

            blocked_on = cls.__blocked_on.get(owner_identity)
            if blocked_on is None:
                return None
            key = blocked_on

        return None

    @classmethod
    def __keys_under_construction(cls) -> list[tuple[str, str, str]]:
        """
        Get the calling thread's own stack of keys it is part-way through constructing.

        Thread-local and therefore lock-free: the list is created on first use by the
        thread that will be its only reader and only writer.

        Returns:
            The live list, outermost key first, to be appended to and popped by the
            calling thread alone.
        """
        stack: list[tuple[str, str, str]] | None = getattr(
            cls.__construction_stack, "keys", None
        )
        if stack is None:
            stack = []
            cls.__construction_stack.keys = stack
        return stack

    @classmethod
    def __describe(cls, cache_key: tuple[str, str, str]) -> str:
        """
        Name a cache key the way a reader of a cycle message needs to see it.

        The key alone reads best and is almost always enough, but two entries can share
        a key and differ by library or label — which is exactly the pair a cycle message
        would otherwise render as ``alpha -> alpha`` — so those are spelled out when
        they are set.

        Args:
            cache_key: Identity of a registry entry, as (key, library, label).

        Returns:
            A short description for a diagnostic message.
        """
        key, library, label = cache_key
        if not library and not label:
            return key
        return f"{key}[{library}:{label}]"

    @classmethod
    def __comparable(
        cls, entry: Entry, configuration: dict[str, Any] | BaseModel | None
    ) -> Any:
        """
        Reduce a configuration to the keyword arguments construction would use.

        Drift is judged on what the class would actually be built with rather than on
        what the caller typed, because that is the question the warning answers: would
        this call have produced a different instance? Several spellings of one
        configuration reach the constructor identically — ``None`` and ``{}``, a dict
        and the model a declared ``__configuration__`` validates it into, a field
        omitted and the same field spelled out as the schema's own default — and all of
        them have to compare equal (see SWE-29).

        The declared schema is applied through the same helper construction uses, and
        the reduction that follows mirrors :meth:`BaseFactory._construct` step for step;
        if that reduction ever changes, this must change with it. Note that a schema is
        therefore validated again on a cache hit, where construction no longer happens:
        pydantic validation is expected to be pure, and the alternative — comparing
        pre-schema — is the bug being fixed.

        Nothing here imports, and nothing here resolves a lazy entry: the cache-hit
        path runs under the factory's lock, where SWE-22 showed what an import costs.
        A still-lazy entry leaves drift undecidable, as does a configuration that will
        not reduce at all.

        Args:
            entry: The resolved registry entry the instance was, or will be, built from.
            configuration: The configuration as given.

        Returns:
            The keyword arguments construction would spread; ``__REJECTED_BY_SCHEMA``
            when a declared model refuses the configuration; None when the reduction
            cannot be made at all, which leaves drift undecidable.
        """
        class_def = entry.class_object
        if class_def is None:
            # The stored field, never ``entry.class_def``: that property resolves a lazy
            # entry by importing its module, and this runs on the cache-hit path with
            # the factory's lock held, where an import is the lock inversion SWE-22
            # exists to prevent. Resolution is for construction; a warning has less
            # standing than that and gives up instead. In practice the entry arrives
            # resolved, since looking it up is what resolved it.
            return None

        schema = getattr(class_def, "__configuration__", None)
        if schema is not None:
            try:
                configuration = cls._validate_configuration(
                    entry, schema, configuration
                )
            except SweetTeaError:
                return cls.__REJECTED_BY_SCHEMA

        try:
            if configuration is None:
                return {}
            if isinstance(configuration, BaseModel):
                return dict(configuration)
            return dict(configuration)
        except Exception:
            # A mapping that will not convert, a model whose iteration fails. This runs
            # for the sake of a warning; it must not be the reason a create fails, nor
            # raise on a cache-hit path that never raised before.
            return None

    @classmethod
    def __snapshot(cls, kwargs: Any) -> dict[str, Any] | None:
        """
        Copy a comparison basis away from the caller's own objects.

        The recorded basis has to keep answering what the first caller asked for,
        however long ago. A shallow copy cannot: it keeps the caller's own containers,
        so a later mutation of one rewrites history. That cuts both ways — a caller who
        passes an equal configuration gets blamed for a mutation someone else made, and
        a caller who mutates a nested value and asks again is told nothing, because both
        sides are reading the one object (see SWE-29).

        Values are copied one at a time rather than the mapping as a whole, because
        ``copy.deepcopy`` raises on plenty of ordinary objects — an open file, a lock, a
        socket, some C extension types. A value that refuses to copy is kept by
        reference instead, which is no worse for that value than the old behaviour and
        leaves every other key in the configuration properly snapshotted; the
        alternative, discarding the whole basis, would cost the warning entirely for any
        configuration carrying a lock. Copying per value also drops any aliasing between
        two values of one configuration, which equality does not look at.

        Args:
            kwargs: The keyword arguments to record, or anything :meth:`__comparable`
                returns in place of them when it could not reduce the configuration.

        Returns:
            A snapshot safe to keep, or None when there were no keyword arguments to
            record — which records drift against this instance as undecidable.
        """
        if not isinstance(kwargs, dict):
            # None, or a configuration the declared schema rejected. Either way there
            # is nothing a later call can be compared against. A rejected one does
            # arrive here on a first call, and what it records is moot: construction
            # raises on the same configuration a few lines later.
            return None

        snapshot: dict[str, Any] = {}
        for name, value in kwargs.items():
            try:
                snapshot[name] = copy.deepcopy(value)
            except Exception:
                snapshot[name] = value
        return snapshot

    @classmethod
    def __same_request(cls, requested: Any, existing: Any) -> bool:
        """
        Decide whether two reduced configurations ask for the same thing.

        Plain ``==`` answers that wrongly in two places, and both rulings here are
        deliberate (see SWE-29):

        - **NaN is the same request as NaN.** That ``float("nan") != float("nan")`` is
          a statement about arithmetic, not about intent: a caller who passes NaN twice
          asked for the same configuration both times. ``==`` already agreed whenever
          the two calls happened to share one NaN object, since container comparison
          short-circuits on identity, so reflexivity was never really the rule — only
          an accident of which object the caller was holding.
        - **1, 1.0 and True are different requests.** ``==`` conflates them, but they
          arrive at the constructor as different types and behave differently once
          there, and ``0`` passed where ``False`` was meant is a plausible mistake worth
          reporting. Numbers are therefore compared type-sensitively. Where a class
          declares ``__configuration__`` the schema has already coerced both spellings
          to the field's own type before this is reached, so an equivalence somebody
          declared is honoured and one nobody declared is not.

        Dicts, lists and tuples are walked so that both rulings hold at any depth.
        Everything else is left to the value's own ``==``. Identity is taken as equality
        first, which is what lets an object with no useful ``==`` compare equal to
        itself.

        Args:
            requested: What this call would build with.
            existing: The recorded basis of the cached instance.

        Returns:
            True when the two are the same request.

        Raises:
            Exception: Whatever a value's own ``==`` raises; the caller reads that as
                undecidable drift.
        """
        if requested is existing:
            return True

        if isinstance(requested, (int, float, complex)) and isinstance(
            existing, (int, float, complex)
        ):
            if type(requested) is not type(existing):
                return False
            if (
                isinstance(requested, float)
                # Already implied by the matching types above; spelled out because the
                # type checker reads the narrowing of each name separately.
                and isinstance(existing, float)
                and math.isnan(requested)
                and math.isnan(existing)
            ):
                return True
            return bool(requested == existing)

        if isinstance(requested, dict) and isinstance(existing, dict):
            if requested.keys() != existing.keys():
                return False
            return all(
                cls.__same_request(value, existing[name])
                for name, value in requested.items()
            )

        if isinstance(requested, (list, tuple)) and isinstance(existing, (list, tuple)):
            # A list and a tuple of the same items are not the same request, which is
            # also what == says; the length check is only to keep zip from truncating.
            if type(requested) is not type(existing) or len(requested) != len(existing):
                return False
            return all(
                cls.__same_request(left, right)
                for left, right in zip(requested, existing)
            )

        return bool(requested == existing)

    @classmethod
    def __drifted(
        cls,
        cache_key: tuple[str, str, str],
        entry: Entry,
        configuration: dict[str, Any] | BaseModel | None,
    ) -> bool:
        """
        Decide whether this call asked for something other than what is cached.

        The answer is no whenever the question cannot be answered. Drift is a warning,
        not a diagnosis: where the comparison is undecidable, the instance is returned
        exactly as it would have been and the caller hears nothing, which is quieter
        than a warning fired on every call and far quieter than an exception out of
        :meth:`create`.

        Args:
            cache_key: Identity of the cached entry.
            entry: The resolved entry, carrying the class whose declared configuration
                model the comparison is made through.
            configuration: What this call passed.

        Returns:
            True when this call's configuration would have built a different instance.
        """
        existing = cls.__configurations.get(cache_key)
        if existing is None:
            # The cached instance's own basis was never computable, so there is nothing
            # to disagree with.
            return False

        requested = cls.__comparable(entry, configuration)

        if requested is cls.__REJECTED_BY_SCHEMA:
            # Decidably different: the cached instance's configuration validated and
            # this one does not, so they cannot be the same request. Worth saying, since
            # this caller gets neither the configuration they passed nor the
            # SweetTeaError a first call would have raised for it.
            return True

        if requested is None:
            return False

        try:
            return not cls.__same_request(requested, existing)
        except Exception:
            # Values whose comparison is not boolean — a numpy array, say — make drift
            # undecidable. A warning on every call would be worse than none.
            return False

    @classmethod
    def __warn_on_configuration_drift(
        cls,
        cache_key: tuple[str, str, str],
        entry: Entry,
        configuration: dict[str, Any] | BaseModel | None,
    ) -> None:
        """
        Report a configuration that arrived too late to take effect.

        A cached singleton is never rebuilt — other holders rely on the identity — so a
        configuration passed to a later call is discarded. That is the right behaviour
        and the wrong silence: a caller who believes they configured something gets an
        instance configured by whoever called first (see SWE-14).

        Nothing is said when the caller passed no configuration, since that is the
        ordinary way to fetch an existing singleton. An empty dict says the same thing
        and is treated the same way: construction maps it and ``None`` alike to no
        keyword arguments, and someone writing ``configuration=options.get("cfg", {})``
        is fetching rather than configuring. Warning there was the false positive most
        likely to get the whole category filtered out (see SWE-29).

        Args:
            cache_key: Identity of the cached entry.
            entry: The resolved entry, which carries the class whose declared
                configuration model the comparison is made through.
            configuration: What this call passed.
        """
        if configuration is None or (
            isinstance(configuration, dict) and not configuration
        ):
            return

        if not cls.__drifted(cache_key, entry, configuration):
            return

        warnings.warn(
            f"Ignoring the configuration passed for singleton {cache_key[0]!r}: an "
            f"instance is already cached and is not rebuilt, so the configuration from "
            f"the first call still applies. Use Factory for per-call configuration, or "
            f"SingletonFactory.pop to discard the cached instance first.",
            SweetTeaWarning,
            # 1 is this helper, 2 is create, 3 is the caller whose configuration was
            # dropped — which is the line worth pointing at.
            stacklevel=3,
        )

    @classmethod
    def clear(cls) -> None:
        """
        Remove all registered instances.

        This is primarily useful for testing or resetting the factory state.

        The construction locks are deliberately left in place. Dropping them could not
        strand a construction — a lock a thread holds stays alive through that thread's
        own reference — but that was never the danger. The danger was the *second* lock:
        with the mapping emptied, the next caller for a key under construction created a
        fresh lock for it, took that one unopposed, and ran the constructor a second time
        in parallel with the first. Two instances of a singleton, from a reset API, is
        the one outcome this class must not have (SWE-39). The locks are keyed by
        resolved cache key and so bounded by the registry, which costs little to keep.
        """
        with cls.__lock:
            count = len(cls.__instances)
            cls.__instances.clear()
            cls.__configurations.clear()
            cls._logger.info(f"Cleared {count} singleton instances")

    @classmethod
    def pop(cls, key: str, library: str = "", label: str = "") -> Any:
        """
        Remove and return a cached instance.

        Resolves through the same path as :meth:`create`, so any spelling of the key
        removes the instance that spelling would have returned.

        Args:
            key: The key of the instance to remove, in any supported spelling.
            library: Optional library filter, matching the one passed to create.
            label: Optional label filter, matching the one passed to create.

        Returns:
            The removed instance.

        Raises:
            SweetTeaError: If no instance is cached for the given key.
        """
        with cls.__lock:
            try:
                entry = cls._select_entry(cls._find_entries(key), key, library, label)
            except SweetTeaError:
                # Unresolvable keys and resolvable-but-uncached ones report the same
                # way; from the caller's side both mean "nothing to remove".
                entry = None

            cache_key = (
                (entry.key, entry.library, entry.label) if entry is not None else None
            )

            if cache_key is None or cache_key not in cls.__instances:
                raise SweetTeaError(
                    f"No singleton instance registered for key '{key}'. "
                    f"Available keys: {cls.list_singletons()}"
                )

            instance = cls.__instances.pop(cache_key)
            cls.__configurations.pop(cache_key, None)

            # Python's garbage collector will handle destruction automatically
            # when all references are removed

            # Reported off cache_key rather than entry: the None check above narrows
            # cache_key but not entry, and both carry the same resolved key.
            cls._logger.info(f"Removed singleton instance: {key} (key: {cache_key[0]})")
            return instance

    @classmethod
    def list_keys(cls) -> list[str]:
        """
        Get a list of all class keys that can be created.

        Returns:
            List of available class keys from the registry in alphabetical order.
        """
        # Return keys from the Registry that can be created
        entries = cls._registry.entries()
        return sorted([entry.key for entry in entries])

    @classmethod
    def list_singletons(cls) -> list[str]:
        """
        Get a list of all cached singleton instance keys.

        Returns:
            List of cached singleton keys in alphabetical order. Entries that share a
            key across libraries or labels appear once per cached instance.
        """
        with cls.__lock:
            return sorted(entry_key for entry_key, _, _ in cls.__instances)
