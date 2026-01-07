"""
Tests for the InverterFactory class functionality.
"""

from unittest import TestCase

from sweet_tea.inverter_factory import InverterFactory
from sweet_tea.registry import Registry
from sweet_tea.sweet_tea_error import SweetTeaError


class TestInverterFactory(TestCase):
    """Test inverter factory retrieval operations."""

    def setUp(self):
        """Clear registry before each test."""
        Registry._Registry__registry.clear()
        Registry._Registry__lookup.clear()
        Registry._Registry__lookup_keys.clear()

    def test_create_simple(self):
        """Test basic inverter factory retrieval."""

        class TestClass:
            def __init__(self, value=None):
                self.value = value

        Registry.register("test", TestClass)
        class_def = InverterFactory.create("test")

        # Should return the class definition, not an instance
        self.assertEqual(class_def, TestClass)
        self.assertIs(class_def, TestClass)

        # User can instantiate when they want
        instance = class_def(value="hello")
        self.assertIsInstance(instance, TestClass)
        self.assertEqual(instance.value, "hello")

    def test_create_with_library_filter(self):
        """Test inverter factory retrieval with library filtering."""

        class TestClass1:
            pass

        class TestClass2:
            pass

        Registry.register("test", TestClass1, "lib1")
        Registry.register("test", TestClass2, "lib2")

        class_def1 = InverterFactory.create("test", library="lib1")
        class_def2 = InverterFactory.create("test", library="lib2")

        self.assertEqual(class_def1, TestClass1)
        self.assertEqual(class_def2, TestClass2)

    def test_create_with_label_filter(self):
        """Test inverter factory retrieval with label filtering."""

        class TestClass1:
            pass

        class TestClass2:
            pass

        Registry.register("test", TestClass1, label="v1")
        Registry.register("test", TestClass2, label="v2")

        class_def1 = InverterFactory.create("test", label="v1")
        class_def2 = InverterFactory.create("test", label="v2")

        self.assertEqual(class_def1, TestClass1)
        self.assertEqual(class_def2, TestClass2)

    def test_create_nonexistent_key(self):
        """Test inverter factory retrieval with nonexistent key."""
        with self.assertRaises(SweetTeaError) as cm:
            InverterFactory.create("nonexistent")
        self.assertIn("not present", str(cm.exception))

    def test_create_ambiguous_matches(self):
        """Test inverter factory retrieval when multiple matches exist without filters."""

        class TestClass1:
            pass

        class TestClass2:
            pass

        Registry.register("test", TestClass1, "lib1")
        Registry.register("test", TestClass2, "lib2")

        with self.assertRaises(SweetTeaError) as cm:
            InverterFactory.create("test")
        self.assertIn("unique result", str(cm.exception))

    def test_create_library_not_found(self):
        """Test inverter factory retrieval with nonexistent library filter."""

        class TestClass:
            pass

        Registry.register("test", TestClass, "lib1")

        with self.assertRaises(SweetTeaError) as cm:
            InverterFactory.create("test", library="lib2")
        self.assertRegex(str(cm.exception), r"library.*not present")

    def test_create_label_not_found(self):
        """Test inverter factory retrieval with nonexistent label filter."""

        class TestClass:
            pass

        Registry.register("test", TestClass, label="v1")

        with self.assertRaises(SweetTeaError) as cm:
            InverterFactory.create("test", label="v2")
        self.assertRegex(str(cm.exception), r"label.*not present")

    def test_create_case_insensitive_key(self):
        """Test that inverter factory retrieval is case-insensitive for keys."""

        class TestClass:
            pass

        Registry.register("test", TestClass)

        # Try different case variations
        class_def1 = InverterFactory.create("TEST")
        class_def2 = InverterFactory.create("Test")
        class_def3 = InverterFactory.create("test")

        for class_def in [class_def1, class_def2, class_def3]:
            self.assertEqual(class_def, TestClass)

    def test_create_case_insensitive_filters(self):
        """Test that filters are case-insensitive."""

        class TestClass:
            pass

        Registry.register("test", TestClass, "TestLib", "TestLabel")

        class_def1 = InverterFactory.create("test", library="testlib")
        class_def2 = InverterFactory.create("test", label="testlabel")

        self.assertEqual(class_def1, TestClass)
        self.assertEqual(class_def2, TestClass)

    def test_key_variations(self):
        """Test that inverter factory supports multiple key variations for class names."""

        class MyTestClass:
            def __init__(self, value="test"):
                self.value = value

        # Register with the canonical snake_case key
        Registry.register("my_test_class", MyTestClass)

        # Test different variations of the key that should all resolve to the same entry
        class_def1 = InverterFactory.create("my_test_class")  # exact match
        class_def2 = InverterFactory.create(
            "MyTestClass"
        )  # CamelCase -> should find my_test_class

        # All should return the same class definition
        self.assertEqual(class_def1, MyTestClass)
        self.assertEqual(class_def2, MyTestClass)

        # User can instantiate from either
        instance1 = class_def1()
        instance2 = class_def2(value="custom")

        self.assertIsInstance(instance1, MyTestClass)
        self.assertIsInstance(instance2, MyTestClass)
        self.assertEqual(instance1.value, "test")
        self.assertEqual(instance2.value, "custom")

    def test_lazy_construction(self):
        """Test that inverter factory enables lazy construction patterns."""

        class ExpensiveClass:
            def __init__(self, resource_path: str):
                self.resource_path = resource_path
                self.initialized = True
                # Simulate expensive initialization
                self.expensive_resource = f"loaded_from_{resource_path}"

        Registry.register("expensive", ExpensiveClass)

        # Get the class definition without instantiating
        class_def = InverterFactory.create("expensive")

        # At this point, no ExpensiveClass instance exists yet
        self.assertEqual(class_def, ExpensiveClass)

        # User can decide when to instantiate and with what parameters
        instance1 = class_def(resource_path="/path/to/resource1")
        instance2 = class_def(resource_path="/path/to/resource2")

        # Both instances are properly initialized with different parameters
        self.assertIsInstance(instance1, ExpensiveClass)
        self.assertIsInstance(instance2, ExpensiveClass)
        self.assertEqual(instance1.resource_path, "/path/to/resource1")
        self.assertEqual(instance2.resource_path, "/path/to/resource2")
        self.assertEqual(instance1.expensive_resource, "loaded_from_/path/to/resource1")
        self.assertEqual(instance2.expensive_resource, "loaded_from_/path/to/resource2")
