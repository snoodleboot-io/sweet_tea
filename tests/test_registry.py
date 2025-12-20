"""
Tests for the Registry class functionality.
"""
import threading
import time
from unittest import TestCase
from sweet_tea.registry import Registry
from sweet_tea.entry import Entry


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
                    Registry.register(f"key_{thread_id}_{i}", TestClass, f"lib_{thread_id}")
                    results.append(f"{thread_id}_{i}")
                    time.sleep(0.001)  # Small delay to increase chance of race conditions
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
