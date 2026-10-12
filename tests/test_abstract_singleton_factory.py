"""
Tests for SWE-47: a singleton factory that narrows on a type.

``SingletonFactory`` caches but returns ``Any``; ``AbstractFactory[T]`` narrows but does
not cache. ``AbstractSingletonFactory[T]`` is both, and the invariant that matters most
is the one that is easiest to break by composing them: the instance cache stays shared,
so one key means one instance however it was asked for.
"""

import os
import sys
import threading
import warnings
from abc import ABC
from unittest import TestCase

from sweet_tea.abstract_factory import AbstractFactory
from sweet_tea.abstract_singleton_factory import AbstractSingletonFactory
from sweet_tea.registry import Registry
from sweet_tea.singleton_factory import SingletonFactory
from sweet_tea.sweet_tea_error import SweetTeaError
from sweet_tea.sweet_tea_warning import SweetTeaWarning

CASES_PATH = os.path.join(os.path.dirname(__file__), "singleton_type_cases")
CASES_MODULE = "tests.singleton_type_cases"

LAZY_MODULES = (
    f"{CASES_MODULE}.s01_base",
    f"{CASES_MODULE}.s02_real",
    f"{CASES_MODULE}.s03_other",
    f"{CASES_MODULE}.s00_marker_real",
    f"{CASES_MODULE}.s00_marker_other",
)


class Component(ABC):
    """The base the typed factory narrows on."""


class RealService(Component):
    def __init__(self, name: str = "default"):
        self.name = name


class SecondService(Component):
    """A second subclass, so narrowing is not trivially satisfied by there being one."""


class ForeignService:
    """Another library's class, registered on the same key under its own library."""

    def __init__(self, name: str = "foreign"):
        self.name = name


class Unrelated(ABC):
    """A base nothing registered is a subclass of."""


def reset_registry() -> None:
    """Clear registry state, including the lazy and type-slot indexes."""
    Registry._Registry__registry.clear()
    Registry._Registry__seen.clear()
    Registry._Registry__lookup.clear()
    Registry._Registry__lookup_keys.clear()
    Registry._Registry__unresolved.clear()
    Registry._Registry__fills.clear()
    Registry._Registry__skipped.clear()
    Registry._Registry__strict_fills.clear()
    Registry._Registry__loaded_sources.clear()


def forget_case_modules() -> None:
    """Drop the case modules so their imports can be observed again."""
    for name in LAZY_MODULES:
        sys.modules.pop(name, None)


def imported_markers() -> list[str]:
    """Which component modules have actually been imported."""
    return sorted(
        name
        for name in (f"{CASES_MODULE}.s02_real", f"{CASES_MODULE}.s03_other")
        if name in sys.modules
    )


class TestNarrowingAndCaching(TestCase):
    """Both halves at once: the right class, and the same one every time."""

    def setUp(self):
        reset_registry()
        SingletonFactory.clear()
        Registry.register(key="service", class_def=RealService, library="mine")
        Registry.register(key="service", class_def=ForeignService, library="otherlib")

    def tearDown(self):
        SingletonFactory.clear()
        reset_registry()

    def test_the_narrowed_class_is_the_one_built(self):
        instance = AbstractSingletonFactory[Component].create("service", library="mine")

        self.assertIsInstance(instance, RealService)

    def test_the_instance_is_cached(self):
        first = AbstractSingletonFactory[Component].create("service", library="mine")
        second = AbstractSingletonFactory[Component].create("service", library="mine")

        self.assertIs(first, second)

    def test_narrowing_disambiguates_a_key_two_libraries_share(self):
        """Without the type filter this key is ambiguous; with it, it resolves."""
        instance = AbstractSingletonFactory[Component].create("service")

        self.assertIsInstance(instance, RealService)

    def test_the_untyped_factory_still_finds_that_key_ambiguous(self):
        """The contrast: narrowing is what buys the disambiguation."""
        with self.assertRaises(SweetTeaError):
            SingletonFactory.create("service")

    def test_a_type_nothing_registered_satisfies_is_refused(self):
        with self.assertRaises(SweetTeaError):
            AbstractSingletonFactory[Unrelated].create("service", library="mine")

    def test_an_unparameterized_factory_is_refused(self):
        with self.assertRaises(SweetTeaError):
            AbstractSingletonFactory.create("service", library="mine")

    def test_every_spelling_of_the_key_shares_one_instance(self):
        """The cache is keyed on the resolved entry, as SWE-5 established."""
        Registry.register(key="realservice", class_def=RealService, library="spelling")

        first = AbstractSingletonFactory[Component].create(
            "RealService", library="spelling"
        )
        second = AbstractSingletonFactory[Component].create(
            "real_service", library="spelling"
        )

        self.assertIs(first, second)

    def test_configuration_applies_on_the_constructing_call(self):
        instance = AbstractSingletonFactory[Component].create(
            "service", library="mine", configuration={"name": "configured"}
        )

        self.assertEqual(instance.name, "configured")

    def test_a_later_configuration_is_warned_about_not_rebuilt(self):
        AbstractSingletonFactory[Component].create(
            "service", library="mine", configuration={"name": "first"}
        )

        with self.assertWarns(SweetTeaWarning):
            second = AbstractSingletonFactory[Component].create(
                "service", library="mine", configuration={"name": "second"}
            )

        self.assertEqual(second.name, "first")


class TestTheCacheIsSharedWithSingletonFactory(TestCase):
    """One key means one instance for the process, however it was asked for."""

    def setUp(self):
        reset_registry()
        SingletonFactory.clear()
        Registry.register(key="service", class_def=RealService, library="mine")

    def tearDown(self):
        SingletonFactory.clear()
        reset_registry()

    def test_typed_then_untyped_returns_the_same_object(self):
        typed = AbstractSingletonFactory[Component].create("service", library="mine")
        untyped = SingletonFactory.create("service", library="mine")

        self.assertIs(typed, untyped)

    def test_untyped_then_typed_returns_the_same_object(self):
        untyped = SingletonFactory.create("service", library="mine")
        typed = AbstractSingletonFactory[Component].create("service", library="mine")

        self.assertIs(typed, untyped)

    def test_two_parameterizations_that_both_accept_the_class_agree(self):
        """Narrowing differently must not fork the instance."""
        by_base = AbstractSingletonFactory[Component].create("service", library="mine")
        by_class = AbstractSingletonFactory[RealService].create(
            "service", library="mine"
        )

        self.assertIs(by_base, by_class)

    def test_clear_empties_the_shared_cache(self):
        first = AbstractSingletonFactory[Component].create("service", library="mine")
        SingletonFactory.clear()

        second = AbstractSingletonFactory[Component].create("service", library="mine")

        self.assertIsNot(first, second)

    def test_the_instance_appears_in_list_singletons(self):
        AbstractSingletonFactory[Component].create("service", library="mine")

        self.assertIn("service", SingletonFactory.list_singletons())


class TestPop(TestCase):
    """pop resolves the way create does, so it removes what create would return."""

    def setUp(self):
        reset_registry()
        SingletonFactory.clear()
        Registry.register(key="service", class_def=RealService, library="mine")
        Registry.register(key="service", class_def=ForeignService, library="otherlib")

    def tearDown(self):
        SingletonFactory.clear()
        reset_registry()

    def test_it_returns_the_cached_instance(self):
        instance = AbstractSingletonFactory[Component].create("service", library="mine")

        self.assertIs(
            AbstractSingletonFactory[Component].pop("service", library="mine"), instance
        )

    def test_it_removes_from_the_shared_cache(self):
        AbstractSingletonFactory[Component].create("service", library="mine")
        AbstractSingletonFactory[Component].pop("service", library="mine")

        self.assertEqual(SingletonFactory.list_singletons(), [])

    def test_it_narrows_the_way_create_does(self):
        """An ambiguous key pops through the typed factory and not the untyped one."""
        AbstractSingletonFactory[Component].create("service")

        popped = AbstractSingletonFactory[Component].pop("service")

        self.assertIsInstance(popped, RealService)

    def test_popping_what_was_never_cached_is_refused(self):
        with self.assertRaises(SweetTeaError):
            AbstractSingletonFactory[Component].pop("service", library="mine")

    def test_popping_lets_the_next_call_construct_again(self):
        first = AbstractSingletonFactory[Component].create("service", library="mine")
        AbstractSingletonFactory[Component].pop("service", library="mine")

        second = AbstractSingletonFactory[Component].create("service", library="mine")

        self.assertIsNot(first, second)


class TestParameterization(TestCase):
    """Each parameterization is its own subclass, as the other abstract factories are."""

    def test_the_same_type_gives_the_same_subclass(self):
        self.assertIs(
            AbstractSingletonFactory[Component], AbstractSingletonFactory[Component]
        )

    def test_different_types_give_different_subclasses(self):
        self.assertIsNot(
            AbstractSingletonFactory[Component], AbstractSingletonFactory[Unrelated]
        )

    def test_it_does_not_share_parameterizations_with_abstract_factory(self):
        """The owner is part of the cache key, so the two families stay distinct."""
        self.assertIsNot(
            AbstractSingletonFactory[Component], AbstractFactory[Component]
        )

    def test_a_parameterization_carries_the_bound_type(self):
        self.assertIs(AbstractSingletonFactory[Component]._type, Component)

    def test_it_is_a_singleton_factory(self):
        self.assertTrue(issubclass(AbstractSingletonFactory, SingletonFactory))


class TestConcurrency(TestCase):
    """The guarantee the class exists for has to survive the narrowing."""

    def setUp(self):
        reset_registry()
        SingletonFactory.clear()
        Registry.register(key="service", class_def=RealService, library="mine")

    def tearDown(self):
        SingletonFactory.clear()
        reset_registry()

    def test_racing_threads_get_one_instance(self):
        results = []
        barrier = threading.Barrier(8)

        def ask():
            barrier.wait()
            results.append(
                AbstractSingletonFactory[Component].create("service", library="mine")
            )

        threads = [threading.Thread(target=ask) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(len(results), 8)
        self.assertEqual(len({id(result) for result in results}), 1)

    def test_racing_typed_against_untyped_gets_one_instance(self):
        """The shared cache has to hold under contention, not just in sequence."""
        results = []
        barrier = threading.Barrier(8)

        def ask(index):
            barrier.wait()
            factory = (
                AbstractSingletonFactory[Component]
                if index % 2 == 0
                else SingletonFactory
            )
            results.append(factory.create("service", library="mine"))

        threads = [threading.Thread(target=ask, args=(i,)) for i in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(len({id(result) for result in results}), 1)


class TestCircularConstruction(TestCase):
    """A cycle still reports rather than deadlocks when it goes through this factory."""

    def setUp(self):
        reset_registry()
        SingletonFactory.clear()

    def tearDown(self):
        SingletonFactory.clear()
        reset_registry()

    def test_a_constructor_asking_for_its_own_key_is_reported(self):
        class SelfSeeking(Component):
            def __init__(self):
                AbstractSingletonFactory[Component].create("selfseeking")

        Registry.register(key="selfseeking", class_def=SelfSeeking)

        with self.assertRaises(SweetTeaError) as caught:
            AbstractSingletonFactory[Component].create("selfseeking")

        self.assertIn("ircular", str(caught.exception))


class TestOnALazilyFilledRegistry(TestCase):
    """Narrowing and lazy filling compose here too, and import only what is asked for."""

    def setUp(self):
        reset_registry()
        SingletonFactory.clear()
        forget_case_modules()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", SweetTeaWarning)
            Registry.fill_registry(path=CASES_PATH, module=CASES_MODULE, lazy=True)
        from tests.singleton_type_cases.s01_base import Component as LazyComponent

        self.base = LazyComponent

    def tearDown(self):
        SingletonFactory.clear()
        reset_registry()
        forget_case_modules()

    def test_a_lazy_entry_resolves_and_then_narrows(self):
        instance = AbstractSingletonFactory[self.base].create("realcomponent")

        self.assertIsInstance(instance, self.base)

    def test_only_the_asked_for_component_is_imported(self):
        AbstractSingletonFactory[self.base].create("realcomponent")

        self.assertEqual(imported_markers(), [f"{CASES_MODULE}.s02_real"])

    def test_the_instance_is_still_cached_across_calls(self):
        first = AbstractSingletonFactory[self.base].create("realcomponent")
        second = AbstractSingletonFactory[self.base].create("realcomponent")

        self.assertIs(first, second)

    def test_a_second_component_resolves_independently(self):
        AbstractSingletonFactory[self.base].create("realcomponent")
        AbstractSingletonFactory[self.base].create("othercomponent")

        self.assertEqual(
            imported_markers(),
            [f"{CASES_MODULE}.s02_real", f"{CASES_MODULE}.s03_other"],
        )


class TestInheritedSurfaceIsUnchanged(TestCase):
    """What this class deliberately does not change, pinned so a change is noticed."""

    def setUp(self):
        reset_registry()
        SingletonFactory.clear()
        Registry.register(key="service", class_def=RealService, library="mine")
        Registry.register(key="unrelatedthing", class_def=ForeignService)

    def tearDown(self):
        SingletonFactory.clear()
        reset_registry()

    def test_list_keys_stays_registry_wide(self):
        """Narrowing it would answer [] for a lazily filled registry; documented."""
        self.assertIn("unrelatedthing", AbstractSingletonFactory[Component].list_keys())

    def test_list_singletons_reports_the_shared_cache(self):
        SingletonFactory.create("unrelatedthing")
        AbstractSingletonFactory[Component].create("service", library="mine")

        self.assertEqual(
            AbstractSingletonFactory[Component].list_singletons(),
            SingletonFactory.list_singletons(),
        )
