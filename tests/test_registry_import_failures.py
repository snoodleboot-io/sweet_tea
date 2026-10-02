"""
Tests for SWE-15: a module that raises on import is skipped with a report, instead
of aborting the fill of everything around it.

Only ImportError and ModuleNotFoundError used to be survivable. Any other exception
from a module body aborted the whole walk, and ``click._winconsole`` guards itself
with ``assert sys.platform == "win32"``, so one platform-guarded module made its
package unregistrable.

``tests/lazy_broken`` is that shape in miniature: ``boom.py`` asserts a platform it
is not on, and ``fine.py`` sorts after it in the walk, so anything registered from
``fine`` proves the fill carried on past the failure.
"""

import os
import shutil
import sys
import tempfile
import warnings
from unittest import TestCase

from sweet_tea.registry import Registry
from sweet_tea.sweet_tea_error import SweetTeaError
from sweet_tea.sweet_tea_warning import SweetTeaWarning

BROKEN_PATH = os.path.join(os.path.dirname(__file__), "lazy_broken")
BROKEN_MODULE = "tests.lazy_broken"

GUARDED_SOURCE = 'import sys\n\nassert sys.platform == "nothing-is-this"\n'


def reset_registry() -> None:
    """Clear every piece of registry state, the skip record included."""
    Registry._Registry__registry.clear()
    Registry._Registry__seen.clear()
    Registry._Registry__lookup.clear()
    Registry._Registry__lookup_keys.clear()
    Registry._Registry__unresolved.clear()
    Registry._Registry__fills.clear()
    Registry._Registry__skipped.clear()
    Registry._Registry__no_sweep = False


def forget(package: str) -> None:
    """Drop a package and its submodules from sys.modules."""
    for name in [
        name
        for name in sys.modules
        if name == package or name.startswith(f"{package}.")
    ]:
        del sys.modules[name]


def keys_now() -> set[str]:
    return {entry.key for entry in Registry.entries()}


def write_package(case: TestCase, name: str, modules: dict[str, str]) -> str:
    """
    Create a throwaway importable package and return the directory to fill from.

    Written at run time rather than committed, because one of the cases below is a
    module with a syntax error: black and ruff both run over ``tests`` in CI and
    neither can parse one.

    Args:
        case: Test case the cleanups are attached to.
        name: Package name, which must not collide with anything importable.
        modules: Module name to source, one entry per module in the package.

    Returns:
        Path of the package directory, for ``fill_registry(path=...)``.
    """
    parent = tempfile.mkdtemp()
    case.addCleanup(shutil.rmtree, parent, True)
    package = os.path.join(parent, name)
    os.makedirs(package)
    open(os.path.join(package, "__init__.py"), "w").close()
    for module, source in modules.items():
        with open(os.path.join(package, f"{module}.py"), "w") as handle:
            handle.write(source)

    sys.path.insert(0, parent)
    case.addCleanup(sys.path.remove, parent)
    case.addCleanup(forget, name)
    return package


def fill(path: str, module: str, **kwargs) -> list[warnings.WarningMessage]:
    """Fill from a package, returning the SweetTeaWarnings it emitted."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", SweetTeaWarning)
        Registry.fill_registry(path=path, module=module, **kwargs)
    return [record for record in caught if record.category is SweetTeaWarning]


class TestEagerImportFailures(TestCase):
    """An eager fill skips the module that raised and keeps walking."""

    def setUp(self):
        reset_registry()
        forget(BROKEN_MODULE)

    def tearDown(self):
        reset_registry()
        forget(BROKEN_MODULE)

    def test_a_module_that_raises_does_not_abort_the_fill(self):
        """The acceptance criterion: the clean modules of the package are registered."""
        fill(BROKEN_PATH, BROKEN_MODULE)

        self.assertIn("reachable", keys_now())
        self.assertNotIn("unreachable", keys_now())

    def test_the_warning_names_the_module_and_the_exception(self):
        """A skip nobody can attribute to a module and a cause is not a report."""
        caught = fill(BROKEN_PATH, BROKEN_MODULE)

        messages = [str(record.message) for record in caught]
        self.assertEqual(len(messages), 1, messages)
        self.assertIn(f"{BROKEN_MODULE}.boom", messages[0])
        self.assertIn("AssertionError", messages[0])

    def test_the_skip_reason_names_the_exception_type(self):
        """skipped() is read once the warnings are gone, so it carries the cause too."""
        fill(BROKEN_PATH, BROKEN_MODULE)

        self.assertEqual(
            Registry.skipped(),
            {f"{BROKEN_MODULE}.boom": "import failed: AssertionError"},
        )

    def test_a_missing_dependency_keeps_its_own_category(self):
        """The one distinction the old two-branch handling got right must survive."""
        path = write_package(
            self,
            "swe15_dependency",
            {"needs": "import no_such_distribution_xyz\n"},
        )
        fill(path, "swe15_dependency")

        reason = Registry.skipped()["swe15_dependency.needs"]
        self.assertTrue(reason.startswith("missing optional dependency"), reason)
        self.assertIn("ModuleNotFoundError", reason)

    def test_another_failure_is_not_reported_as_a_missing_dependency(self):
        """A platform guard is not an uninstalled package and must not read as one."""
        path = write_package(self, "swe15_guarded", {"win_only": GUARDED_SOURCE})
        fill(path, "swe15_guarded")

        reason = Registry.skipped()["swe15_guarded.win_only"]
        self.assertNotIn("missing optional dependency", reason)
        self.assertEqual(reason, "import failed: AssertionError")

    def test_the_exception_message_is_kept_when_there_is_one(self):
        """An environment a module insists on is only actionable if its message lives."""
        path = write_package(
            self,
            "swe15_environment",
            {"needs_env": 'raise RuntimeError("DATABASE_URL is not set")\n'},
        )
        caught = fill(path, "swe15_environment")

        self.assertIn(
            "RuntimeError: DATABASE_URL is not set",
            Registry.skipped()["swe15_environment.needs_env"],
        )
        self.assertIn("DATABASE_URL is not set", str(caught[0].message))

    def test_a_syntax_error_is_still_reported(self):
        """A module that can never be imported anywhere stays visible, not silent."""
        path = write_package(
            self,
            "swe15_unparsable",
            {"bad": "class Broken(:\n", "good": "class Good:\n    pass\n"},
        )
        caught = fill(path, "swe15_unparsable")

        self.assertIn("SyntaxError", Registry.skipped()["swe15_unparsable.bad"])
        self.assertIn("SyntaxError", str(caught[0].message))
        self.assertIn("good", keys_now())

    def test_a_warning_filter_restores_the_strict_behaviour(self):
        """Why no strict option was added: the warning is already that switch."""
        with warnings.catch_warnings():
            warnings.simplefilter("error", SweetTeaWarning)
            with self.assertRaises(SweetTeaWarning):
                Registry.fill_registry(path=BROKEN_PATH, module=BROKEN_MODULE)

        # Recorded before the warning escalates, so the reason is readable afterwards.
        self.assertIn(f"{BROKEN_MODULE}.boom", Registry.skipped())


class TestLazyImportFailuresAtResolution(TestCase):
    """The lazy path reports the same thing, at the lookup that needed the module."""

    def setUp(self):
        reset_registry()
        forget(BROKEN_MODULE)

    def tearDown(self):
        reset_registry()
        forget(BROKEN_MODULE)

    def resolve_all(self) -> list[warnings.WarningMessage]:
        """Resolve every pending module, returning the SweetTeaWarnings it emitted."""
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always", SweetTeaWarning)
            Registry.resolve_all()
        return [record for record in caught if record.category is SweetTeaWarning]

    def test_resolution_drops_the_entries_instead_of_raising(self):
        """Parity with the eager skip: the scanned names go, the lookup survives."""
        fill(BROKEN_PATH, BROKEN_MODULE, lazy=True)
        self.assertIn("unreachable", keys_now())

        caught = self.resolve_all()

        self.assertNotIn("unreachable", keys_now())
        self.assertIn("reachable", keys_now())
        self.assertIn("AssertionError", str(caught[0].message))

    def test_both_paths_record_the_same_reason(self):
        """One contract, two moments: deferral must not change what gets reported."""
        fill(BROKEN_PATH, BROKEN_MODULE)
        eager = Registry.skipped()

        reset_registry()
        forget(BROKEN_MODULE)
        fill(BROKEN_PATH, BROKEN_MODULE, lazy=True)
        self.resolve_all()

        self.assertEqual(Registry.skipped(), eager)

    def test_a_skipped_module_is_not_imported_again(self):
        """Retrying an import known to fail would warn once per lookup, forever."""
        fill(BROKEN_PATH, BROKEN_MODULE, lazy=True)
        self.resolve_all()

        self.assertEqual(self.resolve_all(), [])

    def test_reading_class_def_raises_and_names_the_exception_type(self):
        """A read of one class cannot answer with a warning, so it still raises."""
        fill(BROKEN_PATH, BROKEN_MODULE, lazy=True)
        entry = next(e for e in Registry.entries() if e.key == "unreachable")

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", SweetTeaWarning)
            with self.assertRaises(SweetTeaError) as raised:
                entry.class_def

        self.assertIn("AssertionError", str(raised.exception))

    def test_unparsable_source_still_raises_at_fill_time(self):
        """The scanner's contract is unchanged: a file it cannot parse is an error."""
        path = write_package(self, "swe15_lazy_unparsable", {"bad": "class Broken(:\n"})

        with self.assertRaises(SweetTeaError):
            fill(path, "swe15_lazy_unparsable", lazy=True)
