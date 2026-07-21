"""
Tests for the exclude parameter of Registry.fill_registry.

Patterns are matched case-sensitively against the full dotted module path.
"""

import shutil
import sys
import tempfile
from pathlib import Path
from unittest import TestCase

from sweet_tea.registry import Registry

# Body given to every generated module. The class name is substituted per module so that
# each registration is individually identifiable.
MODULE_TEMPLATE = """
class {class_name}:
    pass
"""


class TestFillRegistryExclude(TestCase):
    """fill_registry must honour caller-supplied exclude patterns."""

    def setUp(self):
        """Clear the registry and create an isolated importable root."""
        Registry._Registry__registry.clear()
        Registry._Registry__lookup.clear()
        Registry._Registry__lookup_keys.clear()

        self.root = Path(tempfile.mkdtemp())
        sys.path.insert(0, str(self.root))

        # Unique per test so that sys.modules entries never collide between tests.
        self.package_name = f"ex_pkg_{self.id().rsplit('.', 1)[-1]}"
        self.package_dir = self.root / self.package_name
        self.package_dir.mkdir()
        (self.package_dir / "__init__.py").touch()

    def tearDown(self):
        """Drop imported modules and remove the temporary tree."""
        sys.path.remove(str(self.root))
        for module_name in list(sys.modules):
            if module_name == self.package_name or module_name.startswith(
                f"{self.package_name}."
            ):
                del sys.modules[module_name]
        shutil.rmtree(self.root, ignore_errors=True)

    def write_module(
        self, relative_path: str, class_name: str, regular_package: bool = False
    ) -> None:
        """Create a module at a path relative to the package root, parents included."""
        module_path = self.package_dir / relative_path
        module_path.parent.mkdir(parents=True, exist_ok=True)
        module_path.write_text(MODULE_TEMPLATE.format(class_name=class_name))

        if regular_package:
            # Walk back up to the package root, marking each directory as a regular
            # package so the exclusion is exercised against pkgutil's results too.
            for parent in module_path.parents:
                if parent == self.package_dir:
                    break
                (parent / "__init__.py").touch()

    def fill(self, exclude=None) -> set[str]:
        """Fill the registry from the generated package and return the keys found."""
        Registry.fill_registry(
            path=str(self.package_dir), module=self.package_name, exclude=exclude
        )
        return {entry.key for entry in Registry.entries()}

    def test_no_exclude_registers_everything(self):
        """Baseline: without exclude, both trees are registered."""
        self.write_module("tests/mod_test.py", "Tested")
        self.write_module("core/mod_core.py", "Cored")

        self.assertEqual(self.fill(), {"tested", "cored"})

    def test_exclude_prunes_namespace_package(self):
        """A matching namespace package is not descended into."""
        self.write_module("tests/mod_test.py", "Tested")
        self.write_module("core/mod_core.py", "Cored")

        self.assertEqual(self.fill(exclude=["*.tests"]), {"cored"})

    def test_exclude_prunes_regular_package(self):
        """Exclusion applies to regular packages, not only namespace packages."""
        self.write_module("tests/mod_test.py", "Tested", regular_package=True)
        self.write_module("core/mod_core.py", "Cored", regular_package=True)

        self.assertEqual(self.fill(exclude=["*.tests"]), {"cored"})

    def test_exclude_prunes_whole_subtree(self):
        """Excluding a package drops everything beneath it, however deep."""
        self.write_module("tests/deep/deeper/mod_deep.py", "Deep")
        self.write_module("core/mod_core.py", "Cored")

        self.assertEqual(self.fill(exclude=["*.tests"]), {"cored"})

    def test_exclude_single_module(self):
        """A pattern may name an individual module rather than a package."""
        self.write_module("mod_keep.py", "Kept")
        self.write_module("mod_drop.py", "Dropped")

        self.assertEqual(self.fill(exclude=["*.mod_drop"]), {"kept"})

    def test_exclude_anchors_to_one_subtree(self):
        """A fully qualified pattern excludes one tests directory but not another."""
        self.write_module("alpha/tests/mod_a.py", "AlphaTest")
        self.write_module("beta/tests/mod_b.py", "BetaTest")

        keys = self.fill(exclude=[f"{self.package_name}.alpha.tests"])

        self.assertEqual(keys, {"betatest"})

    def test_exclude_is_case_sensitive(self):
        """Matching must not vary by platform, so case is significant."""
        self.write_module("Tests/mod_test.py", "Tested")

        self.assertEqual(self.fill(exclude=["*.tests"]), {"tested"})

    def test_exclude_accepts_consumable_iterator(self):
        """A generator must not be exhausted by the first recursive descent.

        The excluded directory sits at depth two deliberately. At depth one the pattern
        is consumed and applied in the same call, so an exhausted iterator would still
        produce the right answer and hide the defect.
        """
        self.write_module("alpha/mod_a.py", "Alpha")
        self.write_module("alpha/tests/mod_test.py", "Tested")

        keys = self.fill(exclude=(pattern for pattern in ["*.tests"]))

        self.assertEqual(keys, {"alpha"})

    def test_empty_exclude_matches_nothing(self):
        """An empty pattern list is not treated as a wildcard."""
        self.write_module("core/mod_core.py", "Cored")

        self.assertEqual(self.fill(exclude=[]), {"cored"})
