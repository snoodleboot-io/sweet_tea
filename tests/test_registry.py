"""
Tests for the Registry class functionality.
"""

import threading
import time
from typing import Any
from unittest import TestCase

from sweet_tea.registry import Registry


class TestRegistry(TestCase):
    """Test basic registry operations."""

    def setUp(self):
        """Clear registry before each test."""
        Registry._Registry__registry.clear()
        Registry._Registry__lookup.clear()
        Registry._Registry__lookup_keys.clear()

    def test_register_and_entries(self):
        """Test registering classes and retrieving entries."""

        # Register a test class
        class TestClass:
            pass

        Registry.register("test", TestClass, "test_lib", "test_label")

        entries = Registry.entries()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].key, "test")
        self.assertEqual(entries[0].class_def, TestClass)
        self.assertEqual(entries[0].library, "test_lib")
        self.assertEqual(entries[0].label, "test_label")

    def test_register_duplicate(self):
        """Test that duplicate entries are not added."""

        class TestClass:
            pass

        Registry.register("test", TestClass)
        Registry.register("test", TestClass)  # Duplicate

        entries = Registry.entries()
        self.assertEqual(len(entries), 1)

    def test_typed_entries(self):
        """Test filtering entries by type."""

        class BaseClass:
            pass

        class DerivedClass(BaseClass):
            pass

        class UnrelatedClass:
            pass

        Registry.register("base", BaseClass)
        Registry.register("derived", DerivedClass)
        Registry.register("unrelated", UnrelatedClass)

        # Get all entries
        all_entries = Registry.typed_entries()
        self.assertEqual(len(all_entries), 3)

        # Get entries that are subclasses of BaseClass
        base_entries = Registry.typed_entries(BaseClass)
        self.assertEqual(len(base_entries), 2)  # BaseClass and DerivedClass

        # Get entries that are exactly BaseClass
        exact_base_entries = [e for e in base_entries if e.class_def == BaseClass]
        self.assertEqual(len(exact_base_entries), 1)

    def test_case_insensitive_keys(self):
        """Test that keys are stored in lowercase."""

        class TestClass:
            pass

        Registry.register("TestKey", TestClass)
        entries = Registry.entries()
        self.assertEqual(entries[0].key, "testkey")

    def test_thread_safety(self):
        """Test that registry operations are thread-safe."""
        results = []
        errors = []

        def register_classes(thread_id):
            try:
                for i in range(10):
                    class_name = f"TestClass_{thread_id}_{i}"
                    TestClass = type(class_name, (), {})
                    Registry.register(
                        f"key_{thread_id}_{i}", TestClass, f"lib_{thread_id}"
                    )
                    results.append(f"{thread_id}_{i}")
                    time.sleep(
                        0.001
                    )  # Small delay to increase chance of race conditions
            except Exception as e:
                errors.append(str(e))

        # Start multiple threads
        threads = []
        for i in range(3):
            thread = threading.Thread(target=register_classes, args=(i,))
            threads.append(thread)
            thread.start()

        # Wait for all threads to complete
        for thread in threads:
            thread.join()

        # Verify no errors occurred
        self.assertEqual(len(errors), 0, f"Threading errors: {errors}")

        # Verify all registrations succeeded
        entries = Registry.entries()
        self.assertEqual(len(entries), 30)  # 3 threads * 10 registrations each

        # Verify no duplicates
        keys = [e.key for e in entries]
        self.assertEqual(len(set(keys)), len(keys), "Duplicate keys found")

    def test_typed_entries_sees_registrations_made_after_first_query(self):
        """Regression for GH #6: ancestor-type cache must refresh on later registers."""

        class Animal:
            pass

        class Dog(Animal):
            pass

        # Prime the Animal lookup slot before any registration.
        self.assertEqual(Registry.typed_entries(lookup_type=Animal), [])

        Registry.register("dog", Dog, library="pets")

        entries = Registry.typed_entries(lookup_type=Animal)
        self.assertTrue(
            any(e.class_def is Dog for e in entries),
            "Dog should appear under Animal lookup after registration",
        )

    def test_typed_entries_with_any_sees_late_registrations(self):
        """`Any` lookup_type must include classes registered after the first query."""

        class LateClass:
            pass

        # Prime the Any cache while the registry is empty.
        Registry.typed_entries(lookup_type=Any)

        Registry.register("late", LateClass, library="late")

        entries = Registry.typed_entries(lookup_type=Any)
        self.assertTrue(any(e.class_def is LateClass for e in entries))

    def test_typed_entries_does_not_double_count_on_re_register(self):
        """Re-registering the same Entry must not duplicate it in cache slots."""

        class Y:
            pass

        Registry.register("y", Y, library="dup")
        Registry.register("y", Y, library="dup")

        y_entries = [
            e for e in Registry.typed_entries(lookup_type=Y) if e.class_def is Y
        ]
        self.assertEqual(len(y_entries), 1)

    def test_typed_entries_multi_level_hierarchy_late_registration(self):
        """Both grandparent and parent cache slots must refresh when a grandchild registers."""

        class Animal:
            pass

        class Mammal(Animal):
            pass

        class Dog(Mammal):
            pass

        # Prime both ancestor slots before Dog exists in the registry.
        self.assertEqual(Registry.typed_entries(lookup_type=Animal), [])
        self.assertEqual(Registry.typed_entries(lookup_type=Mammal), [])

        Registry.register("dog", Dog, library="pets")

        animal_entries = Registry.typed_entries(lookup_type=Animal)
        mammal_entries = Registry.typed_entries(lookup_type=Mammal)
        self.assertTrue(any(e.class_def is Dog for e in animal_entries))
        self.assertTrue(any(e.class_def is Dog for e in mammal_entries))

    def test_typed_entries_unrelated_type_not_added_to_other_caches(self):
        """Registering an unrelated class must not pollute existing cache slots."""

        class Dog:
            pass

        class Cat:
            pass

        # Prime the Dog slot.
        self.assertEqual(Registry.typed_entries(lookup_type=Dog), [])

        Registry.register("cat", Cat, library="pets")

        dog_entries = Registry.typed_entries(lookup_type=Dog)
        self.assertFalse(
            any(e.class_def is Cat for e in dog_entries),
            "Cat must not appear under Dog lookup",
        )

    def test_fill_registry_integration(self):
        """Integration test for fill_registry functionality."""
        # This test demonstrates the overall registry filling and factory usage
        # It serves as an integration test showing the system working end-to-end

        # Clear registry first
        Registry._Registry__registry.clear()
        Registry._Registry__lookup.clear()
        Registry._Registry__lookup_keys.clear()

        # Register some test classes manually to verify the system works
        class TestClassA:
            def print(self):
                return "Class A"

        class TestClassB(TestClassA):
            pass

        Registry.register("a", TestClassA)
        Registry.register("b", TestClassB)

        # Verify we have entries registered
        entries = Registry.entries()
        self.assertEqual(len(entries), 2, "Should have 2 manually registered entries")

        # Verify we can create instances using the factories
        from sweet_tea.abstract_factory import AbstractFactory
        from sweet_tea.factory import Factory

        # Test basic factory creation
        instance_a = Factory.create(key="a", configuration={})
        self.assertIsNotNone(instance_a)
        self.assertTrue(hasattr(instance_a, "print"))
        self.assertEqual(instance_a.print(), "Class A")

        # Test abstract factory with type constraints
        abstract_factory = AbstractFactory[TestClassA]
        instance_b = abstract_factory.create(key="b", configuration={})
        self.assertIsNotNone(instance_b)
        self.assertIsInstance(instance_b, TestClassA)
