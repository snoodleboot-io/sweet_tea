"""
Tests for the Entry class functionality.
"""

from unittest import TestCase, mock

from pydantic_core import PydanticSerializationError

import sweet_tea.entry
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


class TestEntrySerialisation(TestCase):
    """What a dump of an entry says, and what producing it must not do (SWE-16)."""

    def setUp(self):
        self.entry = Entry(
            key="test",
            class_def=dict,
            library="lib",
            label="label",
            module="builtins",
            attribute="dict",
        )

    def test_model_dump_names_the_class_class_def(self):
        """The stored field serialises under its alias, not as class_object."""
        dumped = self.entry.model_dump()

        self.assertIn("class_def", dumped)
        self.assertNotIn("class_object", dumped)
        self.assertIs(dumped["class_def"], dict)

    def test_model_dump_leaves_the_other_fields_alone(self):
        """Only the aliased field is renamed; no other key changes shape."""
        self.assertEqual(
            self.entry.model_dump(),
            {
                "key": "test",
                "class_def": dict,
                "library": "lib",
                "label": "label",
                "module": "builtins",
                "attribute": "dict",
                "provisional": False,
            },
        )

    def test_by_alias_false_still_asks_for_the_storage_name(self):
        """Code that wants to see the field as stored can still say so."""
        self.assertIn("class_object", self.entry.model_dump(by_alias=False))

    def test_iterating_the_model_keeps_field_names(self):
        """dict(entry) is field-named: alias serialisation is a dump-time choice."""
        self.assertIn("class_object", dict(self.entry))

    def test_dumping_a_lazy_entry_resolves_nothing(self):
        """Serialising reads the stored field, so a dump must not import."""
        lazy = Entry(key="test", module="builtins", attribute="dict")
        tripwire = mock.Mock(side_effect=AssertionError("dumping resolved the entry"))

        with mock.patch.object(sweet_tea.entry, "_resolver", tripwire):
            dumped = lazy.model_dump()

        tripwire.assert_not_called()
        self.assertIsNone(dumped["class_def"])
        self.assertTrue(lazy.is_lazy)

    def test_inspecting_a_lazy_entry_resolves_nothing(self):
        """is_lazy and identity read the stored field; neither may import."""
        lazy = Entry(key="test", module="builtins", attribute="dict")
        tripwire = mock.Mock(
            side_effect=AssertionError("inspection resolved the entry")
        )

        with mock.patch.object(sweet_tea.entry, "_resolver", tripwire):
            self.assertTrue(lazy.is_lazy)
            self.assertEqual(lazy.identity, ("test", "builtins:dict", "", ""))
            repr(lazy)

        tripwire.assert_not_called()

    def test_identity_of_a_resolved_entry_holds_the_class(self):
        """Dedupe compares the stored class itself once there is one."""
        self.assertEqual(self.entry.identity, ("test", dict, "lib", "label"))

    def test_a_lazy_entry_dumps_to_json(self):
        """With no class held, an entry is plain data and encodes."""
        lazy = Entry(key="test", module="builtins", attribute="dict")

        self.assertIn('"class_def":null', lazy.model_dump_json())

    def test_a_resolved_entry_does_not_dump_to_json(self):
        """A live class is not JSON; this is why RegistrySnapshot exists."""
        with self.assertRaises(PydanticSerializationError):
            self.entry.model_dump_json()
