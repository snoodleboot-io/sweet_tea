"""
Tests for SWE-24: an entry records the module that *binds* the class.

``type()`` stamps ``__module__`` from the calling frame, so a class built by a helper
elsewhere in the package claims the helper's module — which does not bind it. A
snapshot naming the class that way names a pair that does not exist.
"""

import json
import os
import shutil
import sys
import tempfile
import warnings
from unittest import TestCase

from sweet_tea.factory import Factory
from sweet_tea.registry import Registry
from sweet_tea.registry_snapshot import RegistrySnapshot
from sweet_tea.sweet_tea_warning import SweetTeaWarning

HELPERS = "def forge(name):\n    return type(name, (), {})\n"
MODELS = (
    "from bindpkg.helpers import forge\n\n\n"
    "class Plain:\n    pass\n\n\n"
    'Forged = forge("Forged")\n'
)


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
    ):
        getattr(Registry, f"_Registry__{attribute}").clear()
    Registry._Registry__no_sweep = False


class TestBindingModule(TestCase):
    """A class is recorded where it is reachable, not where it claims to live."""

    def setUp(self):
        reset_registry()
        self.directory = tempfile.mkdtemp()
        root = os.path.join(self.directory, "bindpkg")
        os.makedirs(root)
        open(os.path.join(root, "__init__.py"), "w").close()
        with open(os.path.join(root, "helpers.py"), "w") as handle:
            handle.write(HELPERS)
        with open(os.path.join(root, "models.py"), "w") as handle:
            handle.write(MODELS)
        self.root = root
        self.snapshot = os.path.join(self.directory, "snap.json")
        sys.path.insert(0, self.directory)
        self.addCleanup(self._cleanup)

    def _cleanup(self) -> None:
        reset_registry()
        if self.directory in sys.path:
            sys.path.remove(self.directory)
        for name in [n for n in sys.modules if n.startswith("bindpkg")]:
            del sys.modules[name]
        shutil.rmtree(self.directory, ignore_errors=True)

    def fill(self, **kwargs) -> None:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", SweetTeaWarning)
            Registry.fill_registry(path=self.root, module="bindpkg", **kwargs)

    def test_entry_records_the_binding_module(self):
        """The helper's module claims the class; the model's module holds it."""
        self.fill()

        forged = next(e for e in Registry.entries() if e.key == "forged")
        self.assertEqual(forged.module, "bindpkg.models")
        self.assertEqual(forged.class_object.__module__, "bindpkg.helpers")

    def test_export_names_a_pair_that_exists(self):
        """The defect: the snapshot named bindpkg.helpers:Forged, which is nothing."""
        self.fill()
        Registry.export(self.snapshot)

        entries = {
            e.key: e.class_def for e in RegistrySnapshot.read(self.snapshot).entries
        }
        self.assertEqual(entries["forged"], "bindpkg.models:Forged")

    def test_a_loaded_snapshot_resolves_without_sweeping(self):
        """Resolving by importing the whole tree is the saving the snapshot exists for."""
        self.fill()
        Registry.export(self.snapshot)
        reset_registry()
        for name in [n for n in sys.modules if n.startswith("bindpkg")]:
            del sys.modules[name]

        Registry.load(self.snapshot)
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always", SweetTeaWarning)
            instance = Factory.create("forged")

        self.assertEqual(instance.__class__.__name__, "Forged")
        self.assertEqual(
            [w for w in caught if "remaining module" in str(w.message)], []
        )

    def test_lazy_fill_agrees(self):
        """Resolution records the module it resolved, not the class's claim."""
        self.fill(lazy=True)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", SweetTeaWarning)
            Registry.resolve_all()

        forged = next(e for e in Registry.entries() if e.key == "forged")
        self.assertEqual(forged.module, "bindpkg.models")

    def test_a_direct_register_still_falls_back(self):
        """Without discovery there is nothing better than the class's own claim."""
        reset_registry()

        class Local:
            pass

        Registry.register(key="local", class_def=Local)

        entry = next(e for e in Registry.entries() if e.key == "local")
        self.assertEqual(entry.module, Local.__module__)
