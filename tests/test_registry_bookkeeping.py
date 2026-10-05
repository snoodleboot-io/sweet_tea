"""
Tests for SWE-27, SWE-30, SWE-31 and SWE-32 — four pieces of registry bookkeeping
that each went wrong quietly.
"""

import os
import shutil
import sys
import tempfile
import warnings
from unittest import TestCase

from sweet_tea.registry import Registry
from sweet_tea.registry_snapshot import RegistrySnapshot
from sweet_tea.sweet_tea_error import SweetTeaError
from sweet_tea.sweet_tea_warning import SweetTeaWarning

MULTILIB_PATH = os.path.join(os.path.dirname(__file__), "multilib_cases")
MULTILIB_MODULE = "tests.multilib_cases"


def reset_registry() -> None:
    """Clear every piece of registry state."""
    for attribute in (
        "registry",
        "seen",
        "lookup",
        "lookup_keys",
        "unresolved",
        "fills",
        "skipped",
        "strict_fills",
    ):
        getattr(Registry, f"_Registry__{attribute}").clear()


def forget(prefix: str) -> None:
    """Drop imported fixture modules so a fill starts from the same place."""
    for name in [n for n in sys.modules if n.startswith(prefix)]:
        del sys.modules[name]


class TestSourcesSurviveAReexport(TestCase):
    """SWE-27: a snapshot built from a loaded one must still be verifiable."""

    def setUp(self):
        reset_registry()
        self.directory = tempfile.mkdtemp()
        self.package = os.path.join(self.directory, "repkg")
        os.makedirs(self.package)
        open(os.path.join(self.package, "__init__.py"), "w").close()
        self.module_file = os.path.join(self.package, "models.py")
        with open(self.module_file, "w") as handle:
            handle.write("class Thing:\n    pass\n")
        self.first = os.path.join(self.directory, "a.json")
        self.second = os.path.join(self.directory, "b.json")
        self.addCleanup(self._cleanup)

    def _cleanup(self) -> None:
        reset_registry()
        shutil.rmtree(self.directory, ignore_errors=True)

    def export_load_export(self) -> None:
        Registry.fill_registry(path=self.package, module="repkg", lazy=True)
        Registry.export(self.first)
        reset_registry()
        Registry.load(self.first)
        Registry.export(self.second)

    def test_a_reexport_still_describes_its_sources(self):
        """export builds sources from __fills, which load never populated."""
        self.export_load_export()

        self.assertEqual(
            len(RegistrySnapshot.read(self.second).sources),
            len(RegistrySnapshot.read(self.first).sources),
        )

    def test_a_reexported_snapshot_is_refused_when_stale(self):
        """The defect: verify=True on a re-export could never fail."""
        self.export_load_export()
        with open(self.module_file, "a") as handle:
            handle.write("\n\nclass BrandNew:\n    pass\n")

        reset_registry()
        with self.assertRaises(SweetTeaError):
            Registry.load(self.second, verify=True)


class TestLibraryAndLabelAreNotCollapsed(TestCase):
    """SWE-30: one tree filled under two libraries must register under both."""

    def setUp(self):
        reset_registry()
        forget(MULTILIB_MODULE)

    def tearDown(self):
        reset_registry()

    def rows(self) -> set[tuple[str, str]]:
        return {(entry.key, entry.library) for entry in Registry.entries()}

    def fill_both(self, **kwargs) -> None:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", SweetTeaWarning)
            for library in ("alpha", "beta"):
                Registry.fill_registry(
                    path=MULTILIB_PATH,
                    module=MULTILIB_MODULE,
                    library=library,
                    **kwargs,
                )

    def test_lazy_matches_eager_across_libraries(self):
        """A class only discovery can see was registered under one library, not both."""
        self.fill_both()
        eager = self.rows()

        reset_registry()
        forget(MULTILIB_MODULE)
        self.fill_both(lazy=True)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", SweetTeaWarning)
            Registry.resolve_all()

        self.assertEqual(self.rows(), eager)
        self.assertIn(("runtime", "beta"), self.rows())


class TestTypedEntriesRejectsBadArguments(TestCase):
    """SWE-31: a refused argument must not leave a key with no slot."""

    def setUp(self):
        reset_registry()

        class Thing:
            pass

        self.thing = Thing
        Registry.register(key="thing", class_def=Thing)

    def tearDown(self):
        reset_registry()

    def test_the_same_error_every_time(self):
        """The second call used to raise a bare KeyError out of the internals."""
        first = second = None
        try:
            Registry.typed_entries(42)
        except Exception as error:  # noqa: BLE001
            first = type(error)
        try:
            Registry.typed_entries(42)
        except Exception as error:  # noqa: BLE001
            second = type(error)

        self.assertIs(first, TypeError)
        self.assertIs(second, TypeError)

    def test_no_index_entry_is_left_behind(self):
        """The key was recorded before the slot it names was built."""
        with self.assertRaises(TypeError):
            Registry.typed_entries(42)

        self.assertNotIn(42, Registry._Registry__lookup_keys)

    def test_ordinary_lookups_are_unaffected(self):
        """The guard must not cost the normal path anything."""
        self.assertEqual(
            [entry.key for entry in Registry.typed_entries(self.thing)], ["thing"]
        )


class TestPendingIndexDoesNotLeak(TestCase):
    """SWE-32: a module with no lazy entries left is not pending."""

    def setUp(self):
        reset_registry()
        self.directory = tempfile.mkdtemp()
        package = os.path.join(self.directory, "selfregpkg")
        os.makedirs(package)
        open(os.path.join(package, "__init__.py"), "w").close()
        with open(os.path.join(package, "selfreg.py"), "w") as handle:
            handle.write(
                "from sweet_tea.registry import Registry\n\n\n"
                "class Visible:\n    pass\n\n\n"
                "Registry.register_lazy(\n"
                '    key="late", module="selfregpkg.selfreg", attribute="Visible"\n'
                ")\n"
            )
        self.package = package
        sys.path.insert(0, self.directory)
        self.addCleanup(self._cleanup)

    def _cleanup(self) -> None:
        reset_registry()
        if self.directory in sys.path:
            sys.path.remove(self.directory)
        forget("selfregpkg")
        shutil.rmtree(self.directory, ignore_errors=True)

    def test_nothing_pending_after_resolution(self):
        """A module that registers during its own import re-added itself."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", SweetTeaWarning)
            Registry.fill_registry(path=self.package, module="selfregpkg", lazy=True)
            self.assertTrue(Registry._Registry__unresolved)
            Registry.resolve_all()

        self.assertEqual(Registry._Registry__unresolved, {})
