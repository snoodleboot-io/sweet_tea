"""
Tests for generic type parameterization shared by the abstract factories.

These cover SWE-1: parameterizations used to write their bound type onto a shared
class-level attribute, so the last subscription in the process won for every
parameterization. The tests here deliberately hold several parameterizations
*before* using any of them, which is the pattern that exposed the bug.
"""

import threading
from typing import Generic, TypeVar
from unittest import TestCase

from sweet_tea.abstract_factory import AbstractFactory
from sweet_tea.abstract_inverter_factory import AbstractInverterFactory
from sweet_tea.registry import Registry
from sweet_tea.sweet_tea_error import SweetTeaError
from sweet_tea.type_parameterized_factory import TypeParameterizedFactory


class TestTypeParameterizedFactory(TestCase):
    """Test that each parameterization carries its own generic type."""

    def setUp(self):
        """Clear registry before each test."""
        Registry._Registry__registry.clear()
        Registry._Registry__lookup.clear()
        Registry._Registry__lookup_keys.clear()

    def test_parameterizations_do_not_share_bound_type(self):
        """Each parameterization reports the type it was subscripted with."""

        class First:
            pass

        class Second:
            pass

        # Bind both before reading either - the ordering that used to fail.
        first_factory = AbstractFactory[First]
        second_factory = AbstractFactory[Second]

        self.assertEqual(first_factory._get_generic_type(), First)
        self.assertEqual(second_factory._get_generic_type(), Second)

    def test_parameterization_does_not_pollute_base_class(self):
        """Subscripting never writes the bound type onto the base factory."""

        class Isolated:
            pass

        AbstractFactory[Isolated]

        # The base keeps its unbound TypeVar sentinel rather than the last type used.
        self.assertNotEqual(AbstractFactory._type, Isolated)
        self.assertIsInstance(AbstractFactory._type, TypeVar)

    def test_named_subclass_keeps_its_bound_type(self):
        """A subclass of a parameterization is unaffected by later subscriptions."""

        class Bound:
            pass

        class Unrelated:
            pass

        class BoundFactory(AbstractFactory[Bound]):
            pass

        # An unrelated subscription elsewhere in the process must not reach in.
        AbstractFactory[Unrelated]

        self.assertEqual(BoundFactory._get_generic_type(), Bound)

    def test_parameterization_is_cached(self):
        """Repeated subscription of the same type yields the same class."""

        class Cached:
            pass

        self.assertIs(AbstractFactory[Cached], AbstractFactory[Cached])

    def test_parameterizations_are_distinct_per_factory(self):
        """The same type on different factories yields different classes."""

        class Shared:
            pass

        self.assertIsNot(AbstractFactory[Shared], AbstractInverterFactory[Shared])
        self.assertEqual(AbstractFactory[Shared]._get_generic_type(), Shared)
        self.assertEqual(AbstractInverterFactory[Shared]._get_generic_type(), Shared)

    def test_deferred_use_resolves_against_correct_type(self):
        """Factories held before use each resolve against their own type.

        Uses implementations that satisfy only one interface apiece, so resolving
        against the wrong type fails instead of accidentally succeeding.
        """

        class Readable:
            pass

        class Writable:
            pass

        class OnlyReadable(Readable):
            pass

        class OnlyWritable(Writable):
            pass

        Registry.register("only_readable", OnlyReadable)
        Registry.register("only_writable", OnlyWritable)

        # Both bound up front, then used - the real-world long-lived pattern.
        readable_factory = AbstractFactory[Readable]
        writable_factory = AbstractFactory[Writable]

        self.assertIsInstance(readable_factory.create("only_readable"), OnlyReadable)
        self.assertIsInstance(writable_factory.create("only_writable"), OnlyWritable)

        # And each still refuses the other's type.
        with self.assertRaises(SweetTeaError):
            readable_factory.create("only_writable")
        with self.assertRaises(SweetTeaError):
            writable_factory.create("only_readable")

    def test_deferred_use_resolves_against_correct_type_for_inverter(self):
        """The inverter factory holds the same guarantee."""

        class Source:
            pass

        class Sink:
            pass

        class OnlySource(Source):
            pass

        class OnlySink(Sink):
            pass

        Registry.register("only_source", OnlySource)
        Registry.register("only_sink", OnlySink)

        source_factory = AbstractInverterFactory[Source]
        sink_factory = AbstractInverterFactory[Sink]

        self.assertIs(source_factory.create("only_source"), OnlySource)
        self.assertIs(sink_factory.create("only_sink"), OnlySink)

        with self.assertRaises(SweetTeaError):
            source_factory.create("only_sink")

    def test_unparameterized_factory_raises_sweet_tea_error(self):
        """Using an unparameterized factory reports a typed, actionable error."""

        class Anything:
            pass

        Registry.register("anything", Anything)

        with self.assertRaises(SweetTeaError) as context:
            AbstractFactory.create("anything")
        self.assertIn("not parameterized", str(context.exception))

    def test_non_type_argument_keeps_standard_typing_behavior(self):
        """TypeVar subscription still produces a generic alias, not a subclass."""

        parameter = TypeVar("parameter")

        # This is what happens while a generic subclass body is evaluated; it must
        # not be mistaken for a real parameterization.
        alias = AbstractFactory[parameter]

        self.assertNotIsInstance(alias, type)

    def test_generic_subclass_definition_is_supported(self):
        """A user-defined generic factory subclass can still be declared."""

        parameter = TypeVar("parameter")

        class CustomFactory(TypeParameterizedFactory, Generic[parameter]):
            pass

        class Payload:
            pass

        self.assertEqual(CustomFactory[Payload]._get_generic_type(), Payload)

    def test_concurrent_parameterization_yields_one_class(self):
        """Concurrent subscription of the same type resolves to a single class."""

        class Contended:
            pass

        thread_count = 16
        barrier = threading.Barrier(thread_count)
        results = []
        results_lock = threading.Lock()

        def subscribe():
            # Release all threads at once to maximize contention on the cache.
            barrier.wait()
            parameterized = AbstractFactory[Contended]
            with results_lock:
                results.append(parameterized)

        threads = [threading.Thread(target=subscribe) for _ in range(thread_count)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(len(results), thread_count)
        self.assertEqual(len({id(result) for result in results}), 1)
