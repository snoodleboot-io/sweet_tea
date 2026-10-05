"""
Tests for SWE-12: find the patterns that defeat lazy registration, report them, and
let fill_registry act on them with eager="auto".
"""

import os
import sys
import warnings
from unittest import TestCase

from sweet_tea.lazy_audit import LazyAudit
from sweet_tea.registry import Registry
from sweet_tea.sweet_tea_error import SweetTeaError
from sweet_tea.sweet_tea_warning import SweetTeaWarning

AUDIT_PATH = os.path.join(os.path.dirname(__file__), "lazy_audit_cases")
AUDIT_MODULE = "tests.lazy_audit_cases"


def reset_registry() -> None:
    """Clear every piece of registry state, including the lazy indexes."""
    Registry._Registry__registry.clear()
    Registry._Registry__seen.clear()
    Registry._Registry__lookup.clear()
    Registry._Registry__lookup_keys.clear()
    Registry._Registry__unresolved.clear()
    Registry._Registry__strict_fills.clear()
    Registry._Registry__loaded_sources.clear()


def forget_audit_modules() -> None:
    """Drop the fixture modules so imports can be observed again."""
    for name in [n for n in sys.modules if n.startswith(AUDIT_MODULE + ".")]:
        del sys.modules[name]


class TestLazyAuditDetection(TestCase):
    """Each habit that assumes eager filling is reported, and nothing else is."""

    def kinds(self, source: str) -> list[str]:
        return [finding.kind for finding in LazyAudit.audit_source(source, "m")]

    def test_clean_module_has_no_findings(self):
        """An ordinary module of class definitions is safe to fill lazily."""
        self.assertEqual(self.kinds("class A:\n    pass\n\nB = A\n"), [])

    def test_registry_read_at_import(self):
        """A lookup in the module body needs a registry lazy filling has not built."""
        source = "from sweet_tea.factory import Factory\n\nX = Factory.create('a')\n"
        self.assertEqual(self.kinds(source), ["registry-read-at-import"])

    def test_registration_at_import(self):
        """A registration performed while importing never runs if nothing imports."""
        source = (
            "from sweet_tea.registry import Registry\n\n"
            "class A:\n    pass\n\nRegistry.register('a', A)\n"
        )
        self.assertEqual(self.kinds(source), ["registration-at-import"])

    def test_dynamic_class_creation(self):
        """Names bound at runtime cannot be found by reading source."""
        source = "for n in ('A',):\n    globals()[n] = type(n, (), {})\n"
        self.assertEqual(self.kinds(source), ["dynamic-class"])

    def test_setattr_on_module(self):
        """The other shape of runtime injection."""
        source = (
            "import sys\n\n" "setattr(sys.modules[__name__], 'A', type('A', (), {}))\n"
        )
        self.assertEqual(self.kinds(source), ["dynamic-class"])

    def test_subscripted_factory_is_recognised(self):
        """AbstractFactory[Base].create(...) is a registry read like any other."""
        source = (
            "from sweet_tea.abstract_factory import AbstractFactory\n\n"
            "class Base:\n    pass\n\nX = AbstractFactory[Base].create('a')\n"
        )
        self.assertEqual(self.kinds(source), ["registry-read-at-import"])

    def test_aliased_import_is_recognised(self):
        """Renaming the import must not hide the call."""
        source = "from sweet_tea.factory import Factory as F\n\nX = F.create('a')\n"
        self.assertEqual(self.kinds(source), ["registry-read-at-import"])

    def test_unrelated_create_is_not_flagged(self):
        """`create` is a common method name; only sweet_tea receivers count."""
        source = "import shutil\n\nX = shutil.create('a') if False else None\n"
        self.assertEqual(self.kinds(source), [])

    def test_calls_inside_functions_are_not_flagged(self):
        """A lookup in a function that nothing calls at import time is fine."""
        source = (
            "from sweet_tea.factory import Factory\n\n"
            "def build():\n    return Factory.create('a')\n"
        )
        self.assertEqual(self.kinds(source), [])

    def test_call_one_hop_from_the_module_body_is_flagged(self):
        """The same lookup is a problem once the module body invokes it."""
        source = (
            "from sweet_tea.factory import Factory\n\n"
            "def build():\n    return Factory.create('a')\n\nX = build()\n"
        )
        self.assertEqual(self.kinds(source), ["registry-read-at-import"])

    def test_unparsable_source_yields_no_findings(self):
        """The scanner already reports that failure; the audit does not duplicate it."""
        self.assertEqual(LazyAudit.audit_source("class Broken(:\n", "m"), [])

    def test_finding_renders_as_one_line(self):
        """Reports are read, so a finding has to print usefully."""
        finding = LazyAudit.audit_source(
            "from sweet_tea.registry import Registry\n\nX = Registry.entries()\n", "m"
        )[0]
        self.assertTrue(str(finding).startswith("m:3: registry-read-at-import:"))


class TestRegistryLazyAudit(TestCase):
    """Auditing a package walks it the way filling does, importing nothing."""

    def setUp(self):
        reset_registry()
        forget_audit_modules()

    def tearDown(self):
        reset_registry()

    def test_audit_reports_each_fixture(self):
        """Every hostile fixture is named; the clean one is not."""
        findings = Registry.lazy_audit(path=AUDIT_PATH, module=AUDIT_MODULE)
        modules = {finding.module for finding in findings}

        self.assertIn(f"{AUDIT_MODULE}.a02_reads", modules)
        self.assertIn(f"{AUDIT_MODULE}.a03_registers", modules)
        self.assertIn(f"{AUDIT_MODULE}.a04_dynamic", modules)
        self.assertIn(f"{AUDIT_MODULE}.a05_indirect", modules)
        self.assertNotIn(f"{AUDIT_MODULE}.a01_clean", modules)

    def test_audit_imports_nothing(self):
        """The point of reading source is not having to run it."""
        Registry.lazy_audit(path=AUDIT_PATH, module=AUDIT_MODULE)

        self.assertEqual(
            [n for n in sys.modules if n.startswith(AUDIT_MODULE + ".")], []
        )

    def test_audit_respects_exclude(self):
        """Skipping a module for filling should skip it for auditing too."""
        findings = Registry.lazy_audit(
            path=AUDIT_PATH,
            module=AUDIT_MODULE,
            exclude=[f"{AUDIT_MODULE}.a04_dynamic"],
        )

        self.assertNotIn(
            f"{AUDIT_MODULE}.a04_dynamic", {finding.module for finding in findings}
        )


class TestEagerAuto(TestCase):
    """eager="auto" acts on the audit during the fill."""

    def setUp(self):
        reset_registry()
        forget_audit_modules()

    def tearDown(self):
        reset_registry()

    def imported(self) -> set[str]:
        return {n for n in sys.modules if n.startswith(AUDIT_MODULE + ".")}

    def test_auto_imports_only_the_flagged_modules(self):
        """Hostile modules are filled eagerly; the clean one stays lazy.

        The two modules that read the registry while importing are excluded here:
        importing them triggers a lookup, and a lookup during the fill sweeps the
        rest of the tree. That is the point of test_auto_warns_about_unfixable below.
        """
        Registry.fill_registry(
            path=AUDIT_PATH,
            module=AUDIT_MODULE,
            lazy=True,
            eager="auto",
            exclude=[f"{AUDIT_MODULE}.a02_reads", f"{AUDIT_MODULE}.a05_indirect"],
        )

        imported = self.imported()
        self.assertIn(f"{AUDIT_MODULE}.a04_dynamic", imported)
        self.assertIn(f"{AUDIT_MODULE}.a03_registers", imported)
        self.assertNotIn(f"{AUDIT_MODULE}.a01_clean", imported)

    def test_auto_warns_about_modules_it_cannot_fix(self):
        """Importing early cannot rescue a module that reads the registry early."""
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always", SweetTeaWarning)
            Registry.fill_registry(
                path=AUDIT_PATH, module=AUDIT_MODULE, lazy=True, eager="auto"
            )

        messages = [str(warning.message) for warning in caught]
        self.assertTrue(
            any("reads the registry while it is being imported" in m for m in messages),
            messages,
        )

    def test_auto_recovers_runtime_generated_names_without_a_sweep(self):
        """The name a scan cannot see is present from the start."""
        Registry.fill_registry(
            path=AUDIT_PATH, module=AUDIT_MODULE, lazy=True, eager="auto"
        )

        keys = {entry.key for entry in Registry.entries()}
        self.assertIn("generated", keys)
        self.assertIn("registered_by_side_effect", keys)

    def test_without_auto_those_names_are_missing_until_resolved(self):
        """Contrast: plain lazy filling cannot see them up front."""
        Registry.fill_registry(path=AUDIT_PATH, module=AUDIT_MODULE, lazy=True)

        self.assertNotIn("generated", {entry.key for entry in Registry.entries()})

    def test_auto_composes_with_explicit_patterns(self):
        """A pattern list may carry the mode alongside real globs."""
        Registry.fill_registry(
            path=AUDIT_PATH,
            module=AUDIT_MODULE,
            lazy=True,
            eager=[f"{AUDIT_MODULE}.a01_clean", "auto"],
        )

        self.assertIn(f"{AUDIT_MODULE}.a01_clean", self.imported())
        self.assertIn(f"{AUDIT_MODULE}.a04_dynamic", self.imported())

    def test_auto_is_not_treated_as_a_glob(self):
        """The mode must not be matched against module names as a pattern."""
        Registry.fill_registry(
            path=AUDIT_PATH,
            module=AUDIT_MODULE,
            lazy=True,
            eager="auto",
            exclude=[f"{AUDIT_MODULE}.a02_reads", f"{AUDIT_MODULE}.a05_indirect"],
        )

        self.assertNotIn(f"{AUDIT_MODULE}.a01_clean", self.imported())

    def test_auto_without_lazy_is_rejected(self):
        """Same rule as any other eager value."""
        with self.assertRaises(SweetTeaError):
            Registry.fill_registry(path=AUDIT_PATH, module=AUDIT_MODULE, eager="auto")
