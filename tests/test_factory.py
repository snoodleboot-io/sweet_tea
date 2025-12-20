"""
Tests for the Factory class functionality.
"""

from unittest import TestCase

from sweet_tea.factory import Factory
from sweet_tea.registry import Registry
from sweet_tea.sweet_tea_error import SweetTeaError


class TestFactory(TestCase):
    """Test factory creation operations."""

    def setUp(self):
        """Clear registry before each test."""
        Registry._Registry__registry.clear()
        Registry._Registry__lookup.clear()
        Registry._Registry__lookup_keys.clear()

    def test_create_simple(self):
        """Test basic factory creation."""

        class TestClass:
            def __init__(self, value=None):
                self.value = value

        Registry.register("test", TestClass)
        instance = Factory.create("test", configuration={"value": "hello"})

        self.assertIsInstance(instance, TestClass)
        self.assertEqual(instance.value, "hello")

    def test_create_with_library_filter(self):
        """Test factory creation with library filtering."""

        class TestClass1:
            pass

        class TestClass2:
            pass

        Registry.register("test", TestClass1, "lib1")
        Registry.register("test", TestClass2, "lib2")

        instance1 = Factory.create("test", library="lib1")
        instance2 = Factory.create("test", library="lib2")

        self.assertIsInstance(instance1, TestClass1)
        self.assertIsInstance(instance2, TestClass2)

    def test_create_with_label_filter(self):
        """Test factory creation with label filtering."""

        class TestClass1:
            pass

        class TestClass2:
            pass

        Registry.register("test", TestClass1, label="v1")
        Registry.register("test", TestClass2, label="v2")

        instance1 = Factory.create("test", label="v1")
        instance2 = Factory.create("test", label="v2")

        self.assertIsInstance(instance1, TestClass1)
        self.assertIsInstance(instance2, TestClass2)

    def test_create_nonexistent_key(self):
        """Test factory creation with nonexistent key."""
        with self.assertRaises(SweetTeaError) as cm:
            Factory.create("nonexistent")
        self.assertIn("not present", str(cm.exception))

    def test_create_ambiguous_matches(self):
        """Test factory creation when multiple matches exist without filters."""

        class TestClass1:
            pass

        class TestClass2:
            pass

        Registry.register("test", TestClass1, "lib1")
        Registry.register("test", TestClass2, "lib2")

        with self.assertRaises(SweetTeaError) as cm:
            Factory.create("test")
        self.assertIn("unique result", str(cm.exception))

    def test_create_library_not_found(self):
        """Test factory creation with nonexistent library filter."""

        class TestClass:
            pass

        Registry.register("test", TestClass, "lib1")

        with self.assertRaises(SweetTeaError) as cm:
            Factory.create("test", library="lib2")
        self.assertRegex(str(cm.exception), r"library.*not present")

    def test_create_label_not_found(self):
        """Test factory creation with nonexistent label filter."""

        class TestClass:
            pass

        Registry.register("test", TestClass, label="v1")

        with self.assertRaises(SweetTeaError) as cm:
            Factory.create("test", label="v2")
        self.assertRegex(str(cm.exception), r"label.*not present")

    def test_create_without_configuration(self):
        """Test factory creation without configuration."""

        class TestClass:
            def __init__(self):
                self.initialized = True

        Registry.register("test", TestClass)
        instance = Factory.create("test")

        self.assertIsInstance(instance, TestClass)
        self.assertTrue(instance.initialized)

    def test_create_case_insensitive_key(self):
        """Test that factory creation is case-insensitive for keys."""

        class TestClass:
            pass

        Registry.register("test", TestClass)

        # Try different case variations
        instance1 = Factory.create("TEST")
        instance2 = Factory.create("Test")
        instance3 = Factory.create("test")

        for inst in [instance1, instance2, instance3]:
            self.assertIsInstance(inst, TestClass)

    def test_create_case_insensitive_filters(self):
        """Test that filters are case-insensitive."""

        class TestClass:
            pass

        Registry.register("test", TestClass, "TestLib", "TestLabel")

        instance1 = Factory.create("test", library="testlib")
        instance2 = Factory.create("test", label="testlabel")

        self.assertIsInstance(instance1, TestClass)
        self.assertIsInstance(instance2, TestClass)

    def test_key_variations(self):
        """Test that factory supports multiple key variations for class names."""

        class MyTestClass:
            def __init__(self, value="test"):
                self.value = value

        # Register with the canonical snake_case key
        Registry.register("my_test_class", MyTestClass)

        # Test different variations of the key that should all resolve to the same entry
        instance1 = Factory.create("my_test_class")  # exact match
        instance2 = Factory.create(
            "MyTestClass"
        )  # CamelCase -> should find my_test_class

        # All should create instances of the same class
        for instance in [instance1, instance2]:
            self.assertIsInstance(instance, MyTestClass)
            self.assertEqual(instance.value, "test")

    def test_generate_key_variations(self):
        """Test the key variation generation logic."""
        variations = Factory._generate_key_variations("MyClass")

        # Should include various forms
        self.assertIn("myclass", variations)  # lowercase
        self.assertIn("my_class", variations)  # snake_case
        self.assertIn("myclass", variations)  # no underscores

        # Test with existing underscores
        variations2 = Factory._generate_key_variations("my_test_class")
        self.assertIn("my_test_class", variations2)  # original
        self.assertIn("mytestclass", variations2)  # no underscores
        self.assertIn("my_test_class", variations2)  # should be unique

    def test_sweet_tea_error_str_methods(self):
        """Test SweetTeaError string representation methods."""
        from sweet_tea.sweet_tea_error import SweetTeaError

        # Test with message
        error_with_message = SweetTeaError("test message")
        self.assertEqual(str(error_with_message), "SweetTeaError: test message")

        # Test without message
        error_without_message = SweetTeaError()
        self.assertEqual(str(error_without_message), "SweetTeaError has been raised")
