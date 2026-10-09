"""
Tests for SWE-45: a construction that began before a reset must not install its
result after it.

A constructor runs with no factory lock held, deliberately and permanently (holding
one across construction caused three deadlocks — see the class docstring). So a
``clear()`` can land while an instance is being built, and the construction, which
cannot be cancelled, used to cache its result anyway: ``list_singletons()`` went
``[]`` and then back to ``['slow']`` with no ``create`` in between, holding an
instance built against the registry as it was before the reset.

The race is pinned open with events rather than raced for, so every assertion here
is deterministic: the constructor announces that it has started and waits to be let
go, the reset happens while it waits, and only then is it released. Nothing in this
file holds a lock across a construction — the reset is called from the main thread
while the constructing thread is parked inside the constructor, which is the window
as a consumer meets it.
"""

import threading
import warnings
from unittest import TestCase

from sweet_tea.registry import Registry
from sweet_tea.singleton_factory import SingletonFactory
from sweet_tea.sweet_tea_warning import SweetTeaWarning


class Parked:
    """A constructor that stops in the middle, so a reset can land inside it."""

    # Every wait in this file is bounded: a regression in the commit check is the kind
    # of fault that hangs, and a hung test says nothing about which invariant broke.
    TIMEOUT = 10

    entered = threading.Event()
    release = threading.Event()
    constructions = 0
    guard = threading.Lock()

    def __init__(self) -> None:
        with Parked.guard:
            Parked.constructions += 1
        Parked.entered.set()
        Parked.release.wait(timeout=Parked.TIMEOUT)


class Other:
    """A second singleton, for showing that a pop of one key is not a reset of all."""


class ResetDuringConstructionCase(TestCase):
    """One parked construction, a reset while it is parked, then release and join."""

    def setUp(self):
        Registry._Registry__registry.clear()
        Registry._Registry__seen.clear()
        Registry._Registry__lookup.clear()
        Registry._Registry__lookup_keys.clear()
        SingletonFactory.clear()
        Registry.register(key="Parked", class_def=Parked)
        Registry.register(key="Other", class_def=Other)
        Parked.entered = threading.Event()
        Parked.release = threading.Event()
        Parked.constructions = 0
        self.returned: list[object] = []
        self.failures: list[str] = []
        self.caught: list[warnings.WarningMessage] = []

    def tearDown(self):
        Parked.release.set()
        SingletonFactory.clear()

    def park_a_construction(self) -> threading.Thread:
        """Start a create() and return once its constructor is parked inside."""
        thread = threading.Thread(target=self.create_once, name="parked-creator")
        thread.daemon = True
        thread.start()
        self.assertTrue(
            Parked.entered.wait(timeout=Parked.TIMEOUT), "the constructor never started"
        )
        return thread

    def create_once(self) -> None:
        """Ask for the parked singleton, recording what came back or what did not."""
        try:
            self.returned.append(SingletonFactory.create("parked"))
        except BaseException as error:  # noqa: BLE001
            self.failures.append(f"{type(error).__name__}: {error}")

    def release_and_join(self, thread: threading.Thread) -> None:
        """Let the parked constructor finish and wait for its call to return."""
        Parked.release.set()
        thread.join(Parked.TIMEOUT)
        self.assertFalse(thread.is_alive(), "the parked creator never returned")
        self.assertEqual(self.failures, [])

    def reset_while_parked(self, reset) -> None:
        """Park a construction, run a reset inside the window, then let it finish."""
        thread = self.park_a_construction()
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always", SweetTeaWarning)
            reset()
            self.release_and_join(thread)
        self.caught = [
            record for record in caught if record.category is SweetTeaWarning
        ]


class TestClearDuringConstruction(ResetDuringConstructionCase):
    """An instance built before a clear() must not reappear after it."""

    def test_the_instance_is_not_cached(self):
        """list_singletons() went [] and then ['parked'] with no create in between."""
        self.reset_while_parked(SingletonFactory.clear)

        self.assertEqual(SingletonFactory.list_singletons(), [])
        self.assertEqual(Parked.constructions, 1)

    def test_the_losing_caller_still_gets_its_instance(self):
        """The construction finished and the object is valid; refusing it punishes
        a caller for another thread's reset."""
        self.reset_while_parked(SingletonFactory.clear)

        self.assertEqual(len(self.returned), 1)
        self.assertIsInstance(self.returned[0], Parked)

    def test_the_dropped_instance_is_warned_about(self):
        """A caller left holding an instance the factory disowned has to be told."""
        self.reset_while_parked(SingletonFactory.clear)

        messages = [str(record.message) for record in self.caught]
        dropped = [message for message in messages if "was not cached" in message]
        self.assertEqual(len(dropped), 1, messages)
        self.assertIn("'parked'", dropped[0])

    def test_the_next_call_constructs_a_fresh_instance(self):
        """A key may legitimately be built again after a clear — just not before it."""
        self.reset_while_parked(SingletonFactory.clear)

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", SweetTeaWarning)
            after = SingletonFactory.create("parked")

        self.assertIsNot(after, self.returned[0])
        self.assertEqual(Parked.constructions, 2)
        self.assertEqual(SingletonFactory.list_singletons(), ["parked"])

    def test_a_construction_no_reset_touched_is_cached_as_before(self):
        """The guard must not drop instances nobody reset: a check on the check."""
        thread = self.park_a_construction()
        self.release_and_join(thread)

        self.assertEqual(SingletonFactory.list_singletons(), ["parked"])
        self.assertIs(SingletonFactory.create("parked"), self.returned[0])


class TestPopDuringConstruction(ResetDuringConstructionCase):
    """A removal is scoped to the key it names, so it disowns nothing else."""

    def test_popping_another_key_leaves_the_construction_alone(self):
        """A shared counter would warn about an instance nobody asked to forget."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", SweetTeaWarning)
            SingletonFactory.create("other")

        self.reset_while_parked(lambda: SingletonFactory.pop("other"))

        self.assertEqual(SingletonFactory.list_singletons(), ["parked"])
        self.assertIs(SingletonFactory.create("parked"), self.returned[0])
        self.assertEqual(
            [str(record.message) for record in self.caught],
            [],
        )
