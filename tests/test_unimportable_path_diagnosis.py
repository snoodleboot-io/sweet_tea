"""
Tests for SWE-45: a path that is not importable is not a missing dependency.

A directory named ``trap.py`` is reported by the walk as a module, because its name
ends in ``.py``, and then no finder will load it. The import raises
``ModuleNotFoundError``, which the fill read as "an optional dependency is not
installed" and answered with "Install the dependency" — advice for a package that
does not exist, about a module that is not one.

The fill survived it before this change and survives it after; what moved is the
diagnostic. So these tests are about the category and the advice, and about the one
thing the new category must not cost: a genuinely missing dependency still being
reported as one.

The fixture is built at run time, because a committed directory named ``trap.py``
is a file pytest tries to collect and black and ruff try to parse.
"""

import os
import shutil
import sys
import tempfile
import warnings
from unittest import TestCase

from sweet_tea.registry import Registry
from sweet_tea.sweet_tea_warning import SweetTeaWarning


def reset_registry() -> None:
    """Clear every piece of registry state, the skip record included."""
    Registry._Registry__registry.clear()
    Registry._Registry__seen.clear()
    Registry._Registry__lookup.clear()
    Registry._Registry__lookup_keys.clear()
    Registry._Registry__unresolved.clear()
    Registry._Registry__fills.clear()
    Registry._Registry__skipped.clear()
    Registry._Registry__strict_fills.clear()
    Registry._Registry__loaded_sources.clear()


class TrapDirectoryCase(TestCase):
    """A package holding one real module and one directory named like a module."""

    PACKAGE = "swe45_trap"

    def setUp(self):
        reset_registry()
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, True)
        self.package = os.path.join(self.root, self.PACKAGE)
        os.makedirs(os.path.join(self.package, "trap.py"))
        open(os.path.join(self.package, "__init__.py"), "w").close()
        with open(os.path.join(self.package, "fine.py"), "w") as handle:
            handle.write("class Fine:\n    pass\n")
        sys.path.insert(0, self.root)
        self.addCleanup(self.forget)
        self.addCleanup(sys.path.remove, self.root)

    def tearDown(self):
        reset_registry()

    def forget(self) -> None:
        """Drop the fixture package and its submodules from sys.modules."""
        for name in [
            name
            for name in sys.modules
            if name == self.PACKAGE or name.startswith(f"{self.PACKAGE}.")
        ]:
            del sys.modules[name]

    def fill(self, **kwargs) -> list[warnings.WarningMessage]:
        """Fill from the fixture, returning the SweetTeaWarnings it emitted."""
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always", SweetTeaWarning)
            Registry.fill_registry(path=self.package, module=self.PACKAGE, **kwargs)
        return [record for record in caught if record.category is SweetTeaWarning]

    def reason(self) -> str:
        """The skip record for the trap directory."""
        return Registry.skipped()[f"{self.PACKAGE}.trap"]


class TestUnimportablePathIsItsOwnCategory(TrapDirectoryCase):
    """A path nothing can import must not be reported as an absent dependency."""

    def test_the_category_is_not_a_missing_dependency(self):
        """Nothing is missing, so the install the old category asks for cannot help."""
        self.fill()

        self.assertFalse(self.reason().startswith("missing optional dependency"))
        self.assertTrue(self.reason().startswith("not importable: "), self.reason())

    def test_the_reason_keeps_the_exception_type_and_message(self):
        """The contract is ``<category>: <ExceptionType>[: <message>]``, unchanged."""
        self.fill()

        self.assertEqual(
            self.reason(),
            f"not importable: ModuleNotFoundError: No module named "
            f"'{self.PACKAGE}.trap'",
        )

    def test_the_advice_points_at_the_path_rather_than_at_an_install(self):
        """Wrong category, wrong advice: the remedy is on disk, not in the index."""
        caught = self.fill()

        messages = [str(record.message) for record in caught]
        trap = [message for message in messages if f"{self.PACKAGE}.trap" in message]
        self.assertEqual(len(trap), 1, messages)
        self.assertNotIn("Install the dependency", trap[0])
        self.assertIn("not importable", trap[0])
        self.assertIn("Rename the path", trap[0])

    def test_the_fill_still_carries_on_past_it(self):
        """The diagnostic moved; the survival SWE-15 bought must not have."""
        self.fill()

        self.assertIn("fine", {entry.key for entry in Registry.entries()})

    def test_the_lazy_path_reports_the_same_category(self):
        """One contract, two moments: deferral must not change what gets reported."""
        self.fill()
        eager = Registry.skipped()

        reset_registry()
        self.forget()
        self.fill(lazy=True)
        Registry.resolve_all()

        self.assertEqual(Registry.skipped(), eager)


class TestMissingDependencyKeepsItsCategory(TestCase):
    """The distinction the new category exists to draw has two sides."""

    def setUp(self):
        reset_registry()

    def tearDown(self):
        reset_registry()

    def test_a_module_importing_something_absent_is_still_a_dependency(self):
        """A module that ran and asked for a package nobody installed is the other case."""
        root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, root, True)
        package = os.path.join(root, "swe45_dependency")
        os.makedirs(package)
        open(os.path.join(package, "__init__.py"), "w").close()
        with open(os.path.join(package, "needs.py"), "w") as handle:
            handle.write("import no_such_distribution_xyz\n")
        sys.path.insert(0, root)
        self.addCleanup(sys.path.remove, root)
        self.addCleanup(sys.modules.pop, "swe45_dependency", None)

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", SweetTeaWarning)
            Registry.fill_registry(path=package, module="swe45_dependency")

        reason = Registry.skipped()["swe45_dependency.needs"]
        self.assertTrue(reason.startswith("missing optional dependency"), reason)

    def test_a_relative_import_of_an_absent_sibling_is_a_dependency(self):
        """The nearest miss: a ModuleNotFoundError naming a name inside the package."""
        root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, root, True)
        package = os.path.join(root, "swe45_sibling")
        os.makedirs(package)
        open(os.path.join(package, "__init__.py"), "w").close()
        with open(os.path.join(package, "asks.py"), "w") as handle:
            handle.write("from swe45_sibling import absent\n")
        sys.path.insert(0, root)
        self.addCleanup(sys.path.remove, root)
        self.addCleanup(sys.modules.pop, "swe45_sibling", None)

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", SweetTeaWarning)
            Registry.fill_registry(path=package, module="swe45_sibling")

        reason = Registry.skipped()["swe45_sibling.asks"]
        self.assertFalse(reason.startswith("not importable"), reason)
