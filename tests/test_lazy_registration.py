"""
Tests for SWE-10: fill_registry(lazy=True) registers names found by parsing, and
imports a module only when a factory needs a class from it.

The case package under tests/lazy_cases holds one module per way a class can come to
exist, so the parity test below is the acceptance criterion: whatever an eager fill
registers must be reachable through the lazy path.
"""

import os
import sys
import warnings
from unittest import TestCase

from sweet_tea.abstract_factory import AbstractFactory
from sweet_tea.factory import Factory
from sweet_tea.inverter_factory import InverterFactory
from sweet_tea.lazy_scanner import LazyScanner
from sweet_tea.registry import Registry
from sweet_tea.sweet_tea_error import SweetTeaError
from sweet_tea.sweet_tea_warning import SweetTeaWarning

CASES_PATH = os.path.join(os.path.dirname(__file__), "lazy_cases")
CASES_MODULE = "tests.lazy_cases"


def reset_registry() -> None:
    """Clear every piece of registry state, including the lazy indexes."""
    Registry._Registry__registry.clear()
    Registry._Registry__seen.clear()
    Registry._Registry__lookup.clear()
    Registry._Registry__lookup_keys.clear()
    Registry._Registry__unresolved.clear()
    Registry._Registry__no_sweep = False


def forget_case_modules() -> None:
    """Drop the case modules from sys.modules so imports can be observed again."""
    for name in [n for n in sys.modules if n.startswith(CASES_MODULE + ".")]:
        del sys.modules[name]


def fill(**kwargs):
    """Fill the registry from the case package, suppressing the optional-dep warning."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", SweetTeaWarning)
        Registry.fill_registry(path=CASES_PATH, module=CASES_MODULE, **kwargs)


def keys_now() -> set[str]:
    return {entry.key for entry in Registry.entries()}


class TestLazyScanner(TestCase):
    """The scanner reports the module-level bindings eager registration keys off."""

    def test_definite_and_provisional(self):
        """Unconditional classes are definite; guessed bindings are provisional."""
        found = LazyScanner.scan_source(
            "class Plain: pass\n"
            "Alias = Plain\n"
            "Dyn = type('Dyn', (), {})\n"
            "NUMBER = 3\n"
        )
        self.assertEqual(found, {"Plain": True, "Alias": False, "Dyn": False})

    def test_attribute_name_wins_over_class_name(self):
        """A class bound under another name registers under the binding."""
        found = LazyScanner.scan_source("Mismatch = type('InnerName', (), {})")
        self.assertEqual(list(found), ["Mismatch"])

    def test_guarded_definitions_are_found(self):
        """Classes inside if/try still count, as provisional."""
        found = LazyScanner.scan_source(
            "import sys\nif sys.version_info:\n    class Cond: pass\n"
            "try:\n    class Guarded: pass\nexcept ImportError:\n    pass\n"
        )
        self.assertEqual(found, {"Cond": False, "Guarded": False})

    def test_deleted_names_are_dropped(self):
        """A class deleted at module level is not registrable."""
        self.assertEqual(LazyScanner.scan_source("class Gone: pass\ndel Gone\n"), {})

    def test_unparsable_source_raises(self):
        """A file the interpreter could not import does not silently register nothing."""
        with self.assertRaises(SweetTeaError):
            LazyScanner.scan_source("class Broken(:\n")


class TestLazyParity(TestCase):
    """Anything an eager fill registers must be reachable through the lazy path."""

    def setUp(self):
        reset_registry()
        forget_case_modules()

    def tearDown(self):
        reset_registry()

    def test_every_eager_key_resolves_through_lazy(self):
        """The acceptance criterion: no key is lost by filling lazily."""
        fill()
        eager_keys = keys_now()

        reset_registry()
        fill(lazy=True)
        for key in sorted(eager_keys):
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", SweetTeaWarning)
                self.assertTrue(
                    InverterFactory._find_entries(key),
                    f"key {key!r} is unreachable after lazy filling",
                )

    def test_no_extra_keys_after_full_resolution(self):
        """Resolution discards provisional guesses that were not classes."""
        fill()
        eager_keys = keys_now()

        reset_registry()
        fill(lazy=True)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", SweetTeaWarning)
            Registry.resolve_all()

        self.assertEqual(keys_now(), eager_keys)

    def test_provisional_guesses_are_visible_before_resolution(self):
        """Known divergence: the pre-import view over-reports and under-reports."""
        fill(lazy=True)
        before = keys_now()

        # a class replaced by a function, and a TYPE_CHECKING-only class, are guesses
        self.assertIn("nolongerclass", before)
        self.assertIn("onlyfortypes", before)
        # a runtime-injected name cannot be seen at all
        self.assertNotIn("loopa", before)

    def test_missing_optional_dependency_is_dropped_on_resolution(self):
        """Parity with the eager skip: the entry goes away rather than erroring."""
        fill(lazy=True)
        self.assertIn("needsmissingdep", keys_now())

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always", SweetTeaWarning)
            Registry.resolve_all()

        self.assertNotIn("needsmissingdep", keys_now())
        self.assertTrue(
            any("missing optional dependency" in str(w.message) for w in caught)
        )


class TestLazyResolution(TestCase):
    """Only the modules a lookup needs get imported."""

    def setUp(self):
        reset_registry()
        forget_case_modules()

    def tearDown(self):
        reset_registry()

    def imported_cases(self) -> set[str]:
        return {n for n in sys.modules if n.startswith(CASES_MODULE + ".")}

    def test_fill_imports_nothing(self):
        """A lazy fill parses; it does not execute module bodies."""
        fill(lazy=True)
        self.assertEqual(self.imported_cases(), set())
        self.assertTrue(keys_now())

    def test_create_imports_only_the_owning_module(self):
        """Resolution is per-key, not per-tree."""
        fill(lazy=True)
        Factory.create("plain")

        self.assertEqual(self.imported_cases(), {f"{CASES_MODULE}.c01_plain"})

    def test_typed_lookup_imports_only_candidates(self):
        """AbstractFactory resolves before filtering by type, so it stays narrow."""
        fill(lazy=True)
        from tests.lazy_cases.d04_base import Animal

        instance = AbstractFactory[Animal].create("dog")

        self.assertEqual(instance.__class__.__name__, "Dog")
        self.assertNotIn(f"{CASES_MODULE}.c07_stdlib_factories", self.imported_cases())

    def test_typed_lookup_still_rejects_wrong_type(self):
        """Narrow resolution must not weaken the type constraint."""
        fill(lazy=True)
        from tests.lazy_cases.d04_base import Animal

        with self.assertRaises(SweetTeaError):
            AbstractFactory[Animal].create("notananimal")

    def test_inverter_factory_resolves(self):
        """Returning the class definition also forces resolution."""
        fill(lazy=True)
        self.assertEqual(InverterFactory.create("plain").__name__, "Plain")

    def test_duplicate_keys_still_ambiguous(self):
        """Two modules defining one class name must not silently collapse."""
        fill(lazy=True)
        with self.assertRaises(SweetTeaError) as raised:
            Factory.create("widget")

        self.assertIn("unique", str(raised.exception))

    def test_resolution_is_idempotent(self):
        """Repeated lookups do not re-import or duplicate entries."""
        fill(lazy=True)
        Factory.create("plain")
        count = len(Registry.entries())
        Factory.create("plain")

        self.assertEqual(len(Registry.entries()), count)


class TestLazySweep(TestCase):
    """Names no scan can see are found by the fallback sweep, loudly."""

    def setUp(self):
        reset_registry()
        forget_case_modules()

    def tearDown(self):
        reset_registry()

    def test_runtime_injected_name_is_found_by_sweep(self):
        """globals()[name] = type(...) is invisible to parsing but still resolvable."""
        fill(lazy=True)
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always", SweetTeaWarning)
            instance = Factory.create("loopa")

        self.assertEqual(instance.__class__.__name__, "LoopA")
        self.assertTrue(any("loopa" in str(w.message) for w in caught))

    def test_strict_refuses_to_sweep(self):
        """lazy="strict" turns the sweep into an error naming the fix."""
        fill(lazy="strict")
        with self.assertRaises(SweetTeaError) as raised:
            Factory.create("loopa")

        self.assertIn("eager", str(raised.exception))

    def test_eager_pattern_keeps_a_module_imported_at_fill(self):
        """A module named in eager is imported during the fill, as before."""
        fill(lazy=True, eager=[f"{CASES_MODULE}.c14_globals"])

        self.assertIn(f"{CASES_MODULE}.c14_globals", sys.modules)
        self.assertIn("loopa", keys_now())

    def test_eager_without_lazy_is_rejected(self):
        """Silently ignoring the patterns would hide a real mistake."""
        with self.assertRaises(SweetTeaError) as raised:
            Registry.fill_registry(
                path=CASES_PATH, module=CASES_MODULE, eager=["anything"]
            )

        self.assertIn("lazy", str(raised.exception))


class TestLazyImportFailures(TestCase):
    """A module that raises on import fails the same way in both modes."""

    BROKEN_PATH = os.path.join(os.path.dirname(__file__), "lazy_broken")
    BROKEN_MODULE = "tests.lazy_broken"

    def setUp(self):
        reset_registry()

    def tearDown(self):
        reset_registry()

    def test_eager_fill_raises(self):
        """Today's behaviour: a non-import exception aborts the fill."""
        with self.assertRaises(SweetTeaError):
            Registry.fill_registry(path=self.BROKEN_PATH, module=self.BROKEN_MODULE)

    def test_lazy_resolution_raises_the_same_error_type(self):
        """Deferral moves when the failure surfaces, not what it is."""
        Registry.fill_registry(
            path=self.BROKEN_PATH, module=self.BROKEN_MODULE, lazy=True
        )

        with self.assertRaises(SweetTeaError) as raised:
            Factory.create("unreachable")

        self.assertIn("AssertionError", str(raised.exception))


class TestLazyEntryIntrospection(TestCase):
    """What direct readers of Registry.entries() see while entries are unresolved."""

    def setUp(self):
        reset_registry()
        forget_case_modules()

    def tearDown(self):
        reset_registry()

    def test_unresolved_entries_expose_no_class(self):
        """Documented contract: class_def is None until the module is imported.

        Code that reads entry.class_def straight off entries() — rather than going
        through a factory — sees None for an unresolved entry instead of a class.
        """
        fill(lazy=True)
        unresolved = [entry for entry in Registry.entries() if entry.is_lazy]

        self.assertTrue(unresolved)
        self.assertIsNone(unresolved[0].class_def)
        self.assertTrue(unresolved[0].module)
        self.assertTrue(unresolved[0].attribute)

    def test_resolve_all_gives_every_entry_a_class(self):
        """The escape hatch for introspection: resolve first, then read."""
        fill(lazy=True)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", SweetTeaWarning)
            Registry.resolve_all()

        self.assertTrue(
            all(entry.class_def is not None for entry in Registry.entries())
        )

    def test_factories_never_hand_back_an_unresolved_class(self):
        """Going through a factory resolves, so callers see a class or an error."""
        fill(lazy=True)
        self.assertIsNotNone(InverterFactory.create("plain"))


class TestLazyTypedCacheInvalidation(TestCase):
    """Resolution removes entries, which the type-lookup cache must notice."""

    def setUp(self):
        reset_registry()
        forget_case_modules()

    def tearDown(self):
        reset_registry()

    def test_typed_entries_do_not_go_stale_across_resolution(self):
        """A cached slot must not keep reporting a provisional entry that was dropped."""
        fill(lazy=True)
        from tests.lazy_cases.d04_base import Animal

        Registry.typed_entries(Animal)  # build the slot before anything resolves
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", SweetTeaWarning)
            Registry.resolve_all()

        typed = {entry.key for entry in Registry.typed_entries(Animal)}
        registered = keys_now()

        self.assertTrue(typed <= registered, f"stale keys: {typed - registered}")
        self.assertIn("dog", typed)
