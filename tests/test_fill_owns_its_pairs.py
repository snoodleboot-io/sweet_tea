"""
Tests for SWE-35 and SWE-38 — what resolution may register, and what it may destroy.

Both live in the apply phase of `__resolve_module`. SWE-35: discovery's class list
belongs to the (library, label) pairs a *fill* established, not to a pair that exists
only because a consumer registered one alias. SWE-38: the drop may only remove the
entries the claim phase actually snapshotted.
"""

import os
import shutil
import sys
import tempfile
import warnings
from unittest import TestCase

from sweet_tea.factory import Factory
from sweet_tea.registry import Registry
from sweet_tea.registry_snapshot import RegistrySnapshot
from sweet_tea.sweet_tea_error import SweetTeaError
from sweet_tea.sweet_tea_warning import SweetTeaWarning

LATE_PATH = os.path.join(os.path.dirname(__file__), "late_registration_cases")
LATE_MODULE = "tests.late_registration_cases"


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
        "loaded_sources",
    ):
        getattr(Registry, f"_Registry__{attribute}").clear()


def forget(prefix: str) -> None:
    """Drop imported fixture modules so each fill starts from the same place."""
    for name in [n for n in sys.modules if n.startswith(prefix)]:
        del sys.modules[name]


class TestAFillOwnsItsPairs(TestCase):
    """An alias must not drag its module's whole class list in behind it (SWE-35)."""

    def setUp(self):
        reset_registry()
        self.directory = tempfile.mkdtemp()
        root = os.path.join(self.directory, "pairpkg")
        os.makedirs(root)
        open(os.path.join(root, "__init__.py"), "w").close()
        with open(os.path.join(root, "m.py"), "w") as handle:
            handle.write(
                "class Alpha:\n    pass\n\n\n"
                "class Beta:\n    pass\n\n\n"
                "class Gamma:\n    pass\n"
            )
        self.root = root
        sys.path.insert(0, self.directory)
        self.addCleanup(self._cleanup)

    def _cleanup(self) -> None:
        reset_registry()
        if self.directory in sys.path:
            sys.path.remove(self.directory)
        forget("pairpkg")
        shutil.rmtree(self.directory, ignore_errors=True)

    def fill(self, **kwargs) -> None:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", SweetTeaWarning)
            Registry.fill_registry(
                path=self.root, module="pairpkg", library="app", **kwargs
            )

    def add_alias(self) -> None:
        Registry.register_lazy(
            key="alpha_v2",
            module="pairpkg.m",
            attribute="Alpha",
            library="app",
            label="v2",
        )

    def test_resolving_an_alias_leaves_the_other_keys_usable(self):
        """The defect: three keys the consumer never touched became ambiguous."""
        self.fill(lazy=True)
        self.add_alias()

        Factory.create("alpha_v2")

        self.assertEqual(len(Registry.entries()), 4)
        for key in ("alpha", "beta", "gamma", "alpha_v2"):
            self.assertIsNotNone(Factory.create(key), key)

    def test_the_same_holds_for_an_eager_fill(self):
        """The alias path does not depend on how the tree was filled."""
        self.fill()
        self.add_alias()

        Factory.create("alpha_v2")

        self.assertEqual(len(Registry.entries()), 4)
        self.assertIsNotNone(Factory.create("alpha"))

    def test_export_load_export_is_idempotent(self):
        """Through the snapshot path a 3-entry export became a 5-entry registry."""
        self.fill(lazy=True)
        self.add_alias()
        first = os.path.join(self.directory, "a.json")
        Registry.export(first)
        before = len(RegistrySnapshot.read(first).entries)

        reset_registry()
        forget("pairpkg")
        Registry.load(first)
        Factory.create("alpha_v2")
        second = os.path.join(self.directory, "b.json")
        Registry.export(second)

        self.assertEqual(len(RegistrySnapshot.read(second).entries), before)
        self.assertIsNotNone(Factory.create("alpha"))

    def test_a_fill_under_two_libraries_still_registers_under_both(self):
        """SWE-30's guarantee: a pair a fill established does get discovery."""
        self.fill(lazy=True)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", SweetTeaWarning)
            Registry.fill_registry(
                path=self.root, module="pairpkg", library="other", lazy=True
            )
            Registry.resolve_all()

        libraries = {e.library for e in Registry.entries() if e.key == "alpha"}
        self.assertEqual(libraries, {"app", "other"})


class TestLateRegistrationSurvives(TestCase):
    """Resolution may only drop what it claimed (SWE-38)."""

    def setUp(self):
        reset_registry()
        forget(LATE_MODULE)

    def tearDown(self):
        reset_registry()
        forget(LATE_MODULE)

    def fill(self, **kwargs) -> None:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", SweetTeaWarning)
            Registry.fill_registry(path=LATE_PATH, module=LATE_MODULE, **kwargs)

    def test_a_registration_made_during_the_import_survives(self):
        """The module registers an alias in its own body as resolution imports it."""
        self.fill(lazy=True)

        Factory.create("thing")

        self.assertIn("late_alias", {entry.key for entry in Registry.entries()})

    def test_the_alias_resolves_to_the_right_class(self):
        """Surviving is only useful if it still names something."""
        self.fill(lazy=True)
        Factory.create("thing")

        self.assertEqual(Factory.create("late_alias").__class__.__name__, "Thing")

    def test_lazy_matches_eager(self):
        """The eager path always kept it, so this was a parity break too."""
        self.fill()
        eager = {entry.key for entry in Registry.entries()}

        reset_registry()
        forget(LATE_MODULE)
        self.fill(lazy=True)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", SweetTeaWarning)
            Registry.resolve_all()

        self.assertEqual({entry.key for entry in Registry.entries()}, eager)

    def test_an_unimportable_module_still_drops_everything(self):
        """A module that cannot import has no resolvable entries to keep."""
        directory = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, directory, ignore_errors=True)
        root = os.path.join(directory, "deadpkg")
        os.makedirs(root)
        open(os.path.join(root, "__init__.py"), "w").close()
        with open(os.path.join(root, "m.py"), "w") as handle:
            handle.write("import totally_missing_xyz\n\n\nclass Ghost:\n    pass\n")
        sys.path.insert(0, directory)
        self.addCleanup(sys.path.remove, directory)

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", SweetTeaWarning)
            Registry.fill_registry(path=root, module="deadpkg", lazy=True)
            Registry.resolve_all()

        self.assertNotIn("ghost", {entry.key for entry in Registry.entries()})
        with self.assertRaises(SweetTeaError):
            Factory.create("ghost")
