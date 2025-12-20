"""
Tests for the Entry class functionality.
"""

from unittest import TestCase

from sweet_tea.entry import Entry


class TestEntry(TestCase):
    """Test Entry model functionality."""

    def test_entry_creation(self):
        """Test creating an Entry instance."""

        class TestClass:
            pass

        entry = Entry(
            key="test_key", class_def=TestClass, library="test_lib", label="test_label"
        )

        self.assertEqual(entry.key, "test_key")
        self.assertEqual(entry.class_def, TestClass)
        self.assertEqual(entry.library, "test_lib")
        self.assertEqual(entry.label, "test_label")

    def test_entry_equality(self):
        """Test Entry equality comparison."""

        class TestClass:
            pass

        entry1 = Entry(key="test", class_def=TestClass, library="lib", label="label")

        entry2 = Entry(key="test", class_def=TestClass, library="lib", label="label")

        entry3 = Entry(
            key="different", class_def=TestClass, library="lib", label="label"
        )

        self.assertEqual(entry1, entry2)
        self.assertNotEqual(entry1, entry3)

    def test_entry_string_representation(self):
        """Test Entry string representation."""

        class TestClass:
            pass

        entry = Entry(key="test", class_def=TestClass, library="lib", label="label")

        # Should have a string representation
        str_repr = str(entry)
        self.assertIn("test", str_repr)
        self.assertIn("TestClass", str_repr)

    def test_entry_with_empty_string_defaults(self):
        """Test Entry with default empty string values for optional fields."""

        class TestClass:
            pass

        entry = Entry(
            key="test",
            class_def=TestClass,
            # library and label will default to ""
        )

        self.assertEqual(entry.key, "test")
        self.assertEqual(entry.class_def, TestClass)
        self.assertEqual(entry.library, "")
        self.assertEqual(entry.label, "")
