"""
Tests for duplicate detection in Registry.register (SWE-6).

Registration used to test membership with ``new_entry not in cls.__registry``, a linear
scan invoking pydantic's structural ``Entry.__eq__`` on every element already present,
so registering n entries cost n(n-1)/2 comparisons. These tests pin the cost down to
call counts rather than wall clock, and pin the duplicate semantics that the hash index
replacing that scan has to preserve exactly.
"""

import threading
from contextlib import contextmanager
from unittest import TestCase

from sweet_tea.entry import Entry
from sweet_tea.registry import Registry


@contextmanager
def counting_entry_comparisons():
    """Count calls to ``Entry.__eq__`` for the duration of the block."""
    counter = {"calls": 0}
    original = Entry.__eq__

    def counting_eq(self, other):
        counter["calls"] += 1
        return original(self, other)

    Entry.__eq__ = counting_eq
    try:
        yield counter
    finally:
        Entry.__eq__ = original


def make_class(name: str) -> type:
    """Build a throwaway class to register."""
    return type(name, (), {})


class TestRegistryDedupe(TestCase):
    """Duplicate detection: cost, semantics, ordering and thread safety."""

    def setUp(self):
        """Clear registry before each test."""
        Registry._Registry__registry.clear()
        Registry._Registry__lookup.clear()
        Registry._Registry__lookup_keys.clear()

    def test_distinct_registrations_do_not_scan_the_registry(self):
        """N distinct registrations must cost O(N) membership work, not O(N^2)."""
        count = 200

        with counting_entry_comparisons() as counter:
            for index in range(count):
                Registry.register(f"class{index}", make_class(f"Class{index}"))

        self.assertEqual(len(Registry.entries()), count)
        # The list scan performed count * (count - 1) / 2 = 19900 comparisons here.
        self.assertLessEqual(
            counter["calls"],
            count,
            "membership testing is still linear in the size of the registry",
        )

    def test_duplicate_registration_yields_one_entry(self):
        """The same (key, class_def, library, label) twice still yields one entry."""
        duplicated = make_class("Duplicated")

        Registry.register("dup", duplicated, library="lib", label="prod")
        Registry.register("dup", duplicated, library="lib", label="prod")

        self.assertEqual(len(Registry.entries()), 1)

    def test_duplicate_detection_ignores_case(self):
        """Key, library and label are lowercased, so spellings collapse to one entry."""
        duplicated = make_class("Duplicated")

        Registry.register("Dup", duplicated, library="Lib", label="Prod")
        Registry.register("dUp", duplicated, library="lIB", label="pROD")

        self.assertEqual(len(Registry.entries()), 1)

    def test_same_class_under_different_label_is_a_distinct_entry(self):
        """Label is part of an entry's identity."""
        shared = make_class("Shared")

        Registry.register("shared", shared, library="lib", label="prod")
        Registry.register("shared", shared, library="lib", label="test")

        self.assertEqual(len(Registry.entries()), 2)

    def test_same_class_under_different_library_is_a_distinct_entry(self):
        """Library is part of an entry's identity."""
        shared = make_class("Shared")

        Registry.register("shared", shared, library="first")
        Registry.register("shared", shared, library="second")

        self.assertEqual(len(Registry.entries()), 2)

    def test_same_class_under_different_key_is_a_distinct_entry(self):
        """Key is part of an entry's identity."""
        shared = make_class("Shared")

        Registry.register("first", shared)
        Registry.register("second", shared)

        self.assertEqual(len(Registry.entries()), 2)

    def test_entries_preserve_registration_order(self):
        """entries() returns entries in the order they were registered."""
        keys = [f"class{index}" for index in range(25)]
        for key in keys:
            Registry.register(key, make_class(key.title()))

        self.assertEqual([entry.key for entry in Registry.entries()], keys)

    def test_typed_entries_preserve_registration_order(self):
        """typed_entries() also preserves registration order, filtered or not."""

        class Base:
            pass

        derived = [type(f"Derived{index}", (Base,), {}) for index in range(10)]

        for index, class_def in enumerate(derived):
            Registry.register(f"derived{index}", class_def)
            # An unrelated class between each, to prove the filter keeps relative order.
            Registry.register(f"other{index}", make_class(f"Other{index}"))

        self.assertEqual(
            [entry.key for entry in Registry.typed_entries(lookup_type=Base)],
            [f"derived{index}" for index in range(10)],
        )
        self.assertEqual(
            [entry.key for entry in Registry.typed_entries()],
            [
                key
                for index in range(10)
                for key in (f"derived{index}", f"other{index}")
            ],
        )

    def test_registration_survives_the_documented_test_reset(self):
        """Clearing the registry directly must not leave the dedupe index stale.

        ``Registry._Registry__registry.clear()`` is the reset documented in
        docs/development/testing.md and used by every test module here. An index that
        kept the cleared identities would treat every re-registration as a duplicate.
        """
        first = make_class("First")
        Registry.register("first", first)
        self.assertEqual(len(Registry.entries()), 1)

        Registry._Registry__registry.clear()
        Registry._Registry__lookup.clear()
        Registry._Registry__lookup_keys.clear()

        Registry.register("first", first)
        self.assertEqual(len(Registry.entries()), 1)
        self.assertEqual(Registry.entries()[0].class_def, first)

    def test_partial_external_truncation_is_reconciled(self):
        """A trimmed registry re-accepts the entries that were removed."""
        classes = [make_class(f"Class{index}") for index in range(5)]
        for index, class_def in enumerate(classes):
            Registry.register(f"class{index}", class_def)

        del Registry._Registry__registry[2:]

        for index, class_def in enumerate(classes):
            Registry.register(f"class{index}", class_def)

        self.assertEqual(
            [entry.key for entry in Registry.entries()],
            ["class0", "class1", "class2", "class3", "class4"],
        )

    def test_concurrent_registration_is_consistent(self):
        """Threads racing on the same entries still produce one entry each."""
        classes = [make_class(f"Concurrent{index}") for index in range(50)]

        def register_all():
            for index, class_def in enumerate(classes):
                Registry.register(f"concurrent{index}", class_def, library="lib")

        threads = [threading.Thread(target=register_all) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        entries = Registry.entries()
        self.assertEqual(len(entries), len(classes))
        self.assertEqual(len({entry.key for entry in entries}), len(classes))
        # The index must not drift from the list it mirrors.
        self.assertEqual(
            len(Registry._Registry__seen), len(Registry._Registry__registry)
        )
