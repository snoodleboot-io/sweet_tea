"""
Tests for implicit namespace package (PEP 420) discovery in Registry.fill_registry.

Package trees are built under a temporary directory rather than committed as fixtures,
so that the negative cases — a directory of data files, a virtualenv, a name that is not
a valid identifier — can be exercised without polluting the repository.
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


class TestNamespacePackageDiscovery(TestCase):
    """fill_registry must traverse namespace packages, and only plausible ones."""

    def setUp(self):
        """Clear the registry and create an isolated importable root."""
        Registry._Registry__registry.clear()
        Registry._Registry__lookup.clear()
        Registry._Registry__lookup_keys.clear()

        self.root = Path(tempfile.mkdtemp())
        sys.path.insert(0, str(self.root))

        # Unique per test so that sys.modules entries never collide between tests.
        self.package_name = f"ns_pkg_{self.id().rsplit('.', 1)[-1]}"
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

    def write_module(self, relative_path: str, class_name: str) -> None:
        """Create a module at a path relative to the package root, parents included."""
        module_path = self.package_dir / relative_path
        module_path.parent.mkdir(parents=True, exist_ok=True)
        module_path.write_text(MODULE_TEMPLATE.format(class_name=class_name))

    def fill(self) -> set[str]:
        """Fill the registry from the generated package and return the keys found."""
        Registry.fill_registry(path=str(self.package_dir), module=self.package_name)
        return {entry.key for entry in Registry.entries()}

    def test_namespace_package_is_discovered(self):
        """A subdirectory without __init__.py must still be traversed."""
        self.write_module("implicit/mod_a.py", "Alpha")

        self.assertIn("alpha", self.fill())

    def test_nested_namespace_packages_are_discovered(self):
        """Namespace packages nested inside namespace packages must be traversed."""
        self.write_module("implicit/deeper/mod_b.py", "Beta")

        self.assertIn("beta", self.fill())

    def test_regular_package_inside_namespace_package(self):
        """A regular package below a namespace package must still be traversed."""
        self.write_module("implicit/regular/mod_c.py", "Gamma")
        (self.package_dir / "implicit" / "regular" / "__init__.py").touch()

        self.assertIn("gamma", self.fill())

    def test_namespace_and_regular_packages_are_both_discovered(self):
        """Adding namespace support must not displace regular package discovery."""
        self.write_module("implicit/mod_a.py", "Alpha")
        self.write_module("regular/mod_d.py", "Delta")
        (self.package_dir / "regular" / "__init__.py").touch()

        keys = self.fill()

        self.assertIn("alpha", keys)
        self.assertIn("delta", keys)

    def test_top_level_module_still_discovered(self):
        """Modules directly under the package root are unaffected."""
        self.write_module("mod_top.py", "Epsilon")

        self.assertIn("epsilon", self.fill())

    def test_data_only_directory_is_skipped(self):
        """A directory holding no importable module is not a namespace package."""
        data_dir = self.package_dir / "fixtures"
        data_dir.mkdir()
        (data_dir / "sample.json").write_text("{}")
        (data_dir / "notes.txt").write_text("nothing importable here")

        self.assertEqual(self.fill(), set())

    def test_hidden_directory_is_skipped(self):
        """Dot directories such as .venv must never be imported."""
        self.write_module(".venv/mod_hidden.py", "Hidden")

        self.assertEqual(self.fill(), set())

    def test_underscore_directory_is_skipped(self):
        """Private and generated directories such as __pycache__ must be skipped."""
        self.write_module("__pycache__/mod_cached.py", "Cached")
        self.write_module("_private/mod_private.py", "Private")

        self.assertEqual(self.fill(), set())

    def test_non_identifier_directory_is_skipped(self):
        """A directory that cannot appear in an import statement must be skipped."""
        self.write_module("my-data/mod_dash.py", "Dashed")
        self.write_module("v1.2/mod_dot.py", "Dotted")

        self.assertEqual(self.fill(), set())

    def test_deeply_nested_module_below_data_directories(self):
        """A namespace package is recognised through intermediate empty directories."""
        self.write_module("implicit/middle/inner/mod_deep.py", "Deep")

        self.assertIn("deep", self.fill())
