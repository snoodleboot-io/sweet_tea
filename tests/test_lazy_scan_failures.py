"""
Tests for SWE-23: a file the scanner cannot handle must not abort the lazy fill.

Which way each failure is handled depends on whether the module is importable anyway,
because parity with the eager path is the whole point. Unparsable source cannot be
imported either, so it is skipped. Unreadable source may still import from cached
bytecode, so it is imported instead of skipped.
"""

import os
import shutil
import sys
import tempfile
import warnings
from unittest import TestCase, skipIf

from sweet_tea.registry import Registry
from sweet_tea.sweet_tea_warning import SweetTeaWarning


def reset_registry() -> None:
    """Clear every piece of registry state, lazy indexes included."""
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


class ScanFailureCase(TestCase):
    """Shared scaffolding: a throwaway package on sys.path, cleaned up after."""

    def setUp(self):
        reset_registry()
        self.directory = tempfile.mkdtemp()
        sys.path.insert(0, self.directory)
        self.addCleanup(self._cleanup)

    def _cleanup(self) -> None:
        reset_registry()
        if self.directory in sys.path:
            sys.path.remove(self.directory)
        for name in [n for n in sys.modules if n.startswith(self.package)]:
            del sys.modules[name]
        shutil.rmtree(self.directory, ignore_errors=True)

    package = "scanfail"

    def write(self, name: str, files: dict[str, bytes]) -> str:
        """Create a package of raw files and return its path."""
        self.package = name
        root = os.path.join(self.directory, name)
        os.makedirs(root)
        open(os.path.join(root, "__init__.py"), "wb").close()
        for stem, content in files.items():
            with open(os.path.join(root, f"{stem}.py"), "wb") as handle:
                handle.write(content)
        return root

    def fill(self, root: str, **kwargs) -> list[warnings.WarningMessage]:
        """Fill, returning the SweetTeaWarnings emitted."""
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always", SweetTeaWarning)
            Registry.fill_registry(path=root, module=self.package, **kwargs)
        return [r for r in caught if r.category is SweetTeaWarning]

    def keys(self) -> set[str]:
        return {entry.key for entry in Registry.entries()}


class TestUnparsableSource(ScanFailureCase):
    """Source no interpreter could compile is skipped under both modes."""

    FILES = {
        "aaa_good": b"class Alpha:\n    pass\n",
        "broken": b'print "python2"\n',
        "zzz_good": b"class Omega:\n    pass\n",
    }

    def test_lazy_fill_keeps_walking(self):
        """The defect: the fill aborted, losing every module after the bad one."""
        root = self.write("scanfail_parse", self.FILES)

        self.fill(root, lazy=True)

        self.assertEqual(self.keys(), {"alpha", "omega"})

    def test_lazy_and_eager_agree(self):
        """Parity is the reason to skip rather than raise."""
        root = self.write("scanfail_parse_parity", self.FILES)
        self.fill(root, lazy=True)
        lazy_keys, lazy_skipped = self.keys(), set(Registry.skipped())

        reset_registry()
        self.fill(root)

        self.assertEqual(lazy_keys, self.keys())
        self.assertEqual(lazy_skipped, set(Registry.skipped()))

    def test_the_skip_names_the_syntax_error(self):
        """A reader has to be able to tell this from a missing dependency."""
        root = self.write("scanfail_parse_reason", self.FILES)

        caught = self.fill(root, lazy=True)

        reason = Registry.skipped()["scanfail_parse_reason.broken"]
        self.assertIn("SyntaxError", reason)
        self.assertTrue(
            any("SyntaxError" in str(record.message) for record in caught),
            [str(record.message) for record in caught],
        )

    def test_eager_auto_survives_it(self):
        """eager="auto" audits each module and must not trip over this either."""
        root = self.write("scanfail_parse_auto", self.FILES)

        self.fill(root, lazy=True, eager="auto")

        self.assertEqual(self.keys(), {"alpha", "omega"})


class TestEncodingDeclaration(ScanFailureCase):
    """A module declaring a non-UTF-8 encoding is ordinary, importable Python."""

    def test_coding_cookie_is_honoured(self):
        """Read as bytes, so ast.parse applies PEP 263 the way an import does."""
        root = self.write(
            "scanfail_latin1",
            {"cafe": b"# -*- coding: latin-1 -*-\nclass Caf\xe9:\n    pass\n"},
        )

        self.fill(root, lazy=True)

        self.assertIn("caf\xe9", self.keys())
        self.assertEqual(Registry.skipped(), {})


@skipIf(os.geteuid() == 0, "root reads a mode-000 file regardless")
class TestUnreadableSource(ScanFailureCase):
    """Source that cannot be read may still import, so it is imported."""

    def test_falls_back_to_importing(self):
        """Skipping would lose classes the eager path registers (bytecode cache)."""
        root = self.write("scanfail_perm", {"locked": b"class Locked:\n    pass\n"})
        # Import once so the bytecode is cached, then take the source away.
        __import__("scanfail_perm.locked")
        locked = os.path.join(root, "locked.py")
        os.chmod(locked, 0o000)
        self.addCleanup(os.chmod, locked, 0o644)
        if os.access(locked, os.R_OK):
            self.skipTest("filesystem ignores the mode bits")

        reset_registry()
        self.fill(root, lazy=True)

        self.assertIn("locked", self.keys())
        self.assertEqual(Registry.skipped(), {})
