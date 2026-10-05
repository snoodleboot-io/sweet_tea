"""
Tests for SWE-11: a class built by a helper living in another module of the same
package used to be registered by nothing at all.
"""

import os
import warnings
from unittest import TestCase

from sweet_tea.factory import Factory
from sweet_tea.registry import Registry
from sweet_tea.sweet_tea_error import SweetTeaError
from sweet_tea.sweet_tea_warning import SweetTeaWarning

CASES_PATH = os.path.join(os.path.dirname(__file__), "lazy_cases")
CASES_MODULE = "tests.lazy_cases"


def reset_registry() -> None:
    """Clear every piece of registry state."""
    Registry._Registry__registry.clear()
    Registry._Registry__seen.clear()
    Registry._Registry__lookup.clear()
    Registry._Registry__lookup_keys.clear()
    Registry._Registry__unresolved.clear()
    Registry._Registry__fills.clear()
    Registry._Registry__skipped.clear()
    Registry._Registry__strict_fills.clear()
    Registry._Registry__loaded_sources.clear()


class TestOrphanedClasses(TestCase):
    """Classes with no home module are registered; imported ones still are not."""

    def setUp(self):
        reset_registry()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", SweetTeaWarning)
            Registry.fill_registry(path=CASES_PATH, module=CASES_MODULE)
        self.keys = [entry.key for entry in Registry.entries()]

    def tearDown(self):
        reset_registry()

    def test_factory_built_class_is_registered(self):
        """`Thing = make_class("Thing")`, with make_class in another module."""
        self.assertIn("fromfactory", self.keys)

    def test_factory_built_class_is_usable(self):
        """Registering it is only useful if it can then be created."""
        instance = Factory.create("fromfactory")

        self.assertEqual(instance.made_by, "helpers")

    def test_imported_class_is_not_registered_again(self):
        """The filter's original purpose still holds: imports are not re-registered."""
        self.assertEqual(self.keys.count("plain"), 1)

    def test_stdlib_types_are_not_registered(self):
        """A C type whose __name__ differs from its binding is still just an import.

        ``types.MappingProxyType`` claims ``builtins`` as its home and is named
        ``mappingproxy`` there, so it looks homeless. Registering it would put stdlib
        types into every registry that imported them.
        """
        self.assertNotIn("mappingproxytype", self.keys)
        self.assertNotIn("moduletype", self.keys)
        self.assertIn("localonly", self.keys)

    def test_same_named_orphans_stay_ambiguous(self):
        """Two modules building one name is a genuine ambiguity, reported as one."""
        self.assertEqual(self.keys.count("dup"), 2)

        with self.assertRaises(SweetTeaError) as raised:
            Factory.create("dup")

        self.assertIn("unique", str(raised.exception))


class TestOrphanedClassesLazily(TestCase):
    """The lazy path reaches the same answer, once the module is resolved."""

    def setUp(self):
        reset_registry()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", SweetTeaWarning)
            Registry.fill_registry(path=CASES_PATH, module=CASES_MODULE, lazy=True)

    def tearDown(self):
        reset_registry()

    def test_scanner_cannot_see_the_name(self):
        """`make_class` is an ordinary function, so no scan can know it builds a class."""
        self.assertNotIn("fromfactory", {e.key for e in Registry.entries()})

    def test_resolution_finds_it(self):
        """Reconciling an imported module applies the same discovery rules."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", SweetTeaWarning)
            Registry.resolve_all()

        self.assertIn("fromfactory", {e.key for e in Registry.entries()})
