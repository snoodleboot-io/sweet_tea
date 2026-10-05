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
    Registry._Registry__skipped.clear()
    Registry._Registry__strict_fills.clear()
    Registry._Registry__loaded_sources.clear()


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

    def test_already_imported_modules_are_harvested_before_sweeping(self):
        """A pending module that something else imported is reconciled for free."""
        fill(lazy=True)
        import tests.lazy_cases.c14_globals  # noqa: F401  (imported as a side effect would be)

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always", SweetTeaWarning)
            instance = Factory.create("loopa")

        self.assertEqual(instance.__class__.__name__, "LoopA")
        self.assertEqual(
            [str(w.message) for w in caught if "remaining module" in str(w.message)],
            [],
            "harvesting an already-imported module should not need a sweep",
        )

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
    """A module that raises on import is skipped the same way in both modes (SWE-15)."""

    BROKEN_PATH = os.path.join(os.path.dirname(__file__), "lazy_broken")
    BROKEN_MODULE = "tests.lazy_broken"

    def setUp(self):
        reset_registry()

    def tearDown(self):
        reset_registry()

    def test_eager_fill_registers_the_rest_of_the_package(self):
        """A module raising AssertionError costs its own classes and no others."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", SweetTeaWarning)
            Registry.fill_registry(path=self.BROKEN_PATH, module=self.BROKEN_MODULE)

        self.assertIn("reachable", keys_now())
        self.assertNotIn("unreachable", keys_now())

    def test_lazy_lookup_reports_rather_than_raising(self):
        """Deferral moves when the module is reported, not what the fill ends up with."""
        Registry.fill_registry(
            path=self.BROKEN_PATH, module=self.BROKEN_MODULE, lazy=True
        )

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always", SweetTeaWarning)
            with self.assertRaises(SweetTeaError) as raised:
                Factory.create("unreachable")

        # The key is gone with its module, so the factory reports a missing key —
        # the same answer it gives for a missing optional dependency.
        self.assertIn("unreachable", str(raised.exception))
        self.assertTrue(any("AssertionError" in str(w.message) for w in caught))


class TestLazyEntryIntrospection(TestCase):
    """Reading an entry's class resolves it, so introspection keeps working (SWE-13)."""

    def setUp(self):
        reset_registry()
        forget_case_modules()

    def tearDown(self):
        reset_registry()

    def imported_cases(self) -> set[str]:
        return {n for n in sys.modules if n.startswith(CASES_MODULE + ".")}

    def test_reading_class_def_resolves_the_entry(self):
        """class_def is a class again, not None, even before anything else ran."""
        fill(lazy=True)
        entry = next(e for e in Registry.entries() if e.key == "plain")

        self.assertTrue(entry.is_lazy)
        self.assertEqual(entry.class_def.__name__, "Plain")

    def test_reading_class_def_imports_only_that_module(self):
        """A filtered read resolves what it touched and nothing else."""
        fill(lazy=True)
        entry = next(e for e in Registry.entries() if e.key == "plain")
        entry.class_def

        self.assertEqual(self.imported_cases(), {f"{CASES_MODULE}.c01_plain"})

    def test_is_lazy_does_not_resolve(self):
        """Asking the question must not answer it by importing."""
        fill(lazy=True)
        states = [entry.is_lazy for entry in Registry.entries()]

        self.assertTrue(any(states))
        self.assertEqual(self.imported_cases(), set())

    def test_dumping_entries_does_not_resolve(self):
        """Serialising reports stored state; it must not import to fill it in."""
        fill(lazy=True)
        dumps = [entry.model_dump() for entry in Registry.entries()]

        self.assertTrue(any(dump["class_def"] is None for dump in dumps))
        self.assertTrue(all("class_object" not in dump for dump in dumps))
        self.assertEqual(self.imported_cases(), set())

    def test_filling_does_not_resolve(self):
        """Dedupe reads the stored class, so registration imports nothing."""
        fill(lazy=True)

        self.assertEqual(self.imported_cases(), set())

    def test_consumer_comprehension_pattern_works(self):
        """The shape pirn-agents uses: filter entries, then read class_def."""
        fill(lazy=True)

        # fill_registry defaults library to the module name, as pirn's does.
        matches = [
            entry.class_def
            for entry in Registry.entries()
            if entry.key == "plain"
            and entry.library == CASES_MODULE
            and entry.label == ""
        ]

        self.assertEqual(len(matches), 1)
        self.assertIsInstance(matches[0], type)
        self.assertEqual(matches[0].__name__, "Plain")

    def test_resolution_is_cached_without_marking_the_entry_resolved(self):
        """Reading twice must not import twice, and must not alter the entry.

        This asserted ``is_lazy`` became False until SWE-37. It did, and that was
        the defect: entries() hands out the registry's own entries, so a reader
        flipping that flag made the entry survive resolution's drop and slip past
        the dedupe index. The class is cached privately now, so reads stay cheap
        while the entry keeps saying what the registry believes about it.
        """
        fill(lazy=True)
        entry = next(e for e in Registry.entries() if e.key == "plain")

        first = entry.class_def

        self.assertIs(entry.class_def, first)
        self.assertTrue(entry.is_lazy)
        self.assertIsNone(entry.class_object)

    def test_provisional_guess_that_is_not_a_class_raises(self):
        """A name read from source that turns out to be a value reports clearly."""
        fill(lazy=True)
        entry = next(e for e in Registry.entries() if e.key == "shadowed")

        with self.assertRaises(SweetTeaError) as raised:
            entry.class_def

        self.assertIn("is not a class", str(raised.exception))

    def test_resolve_all_gives_every_entry_a_class(self):
        """The bulk escape hatch still works."""
        fill(lazy=True)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", SweetTeaWarning)
            Registry.resolve_all()

        self.assertTrue(
            all(entry.class_object is not None for entry in Registry.entries())
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


class TestExplicitLazyEntriesSurviveResolution(TestCase):
    """register_lazy is public API, so resolution must not destroy what it made (SWE-17)."""

    PLAIN_MODULE = f"{CASES_MODULE}.c01_plain"

    def setUp(self):
        reset_registry()
        forget_case_modules()

    def tearDown(self):
        reset_registry()

    def imported_cases(self) -> set[str]:
        return {n for n in sys.modules if n.startswith(CASES_MODULE + ".")}

    def register_alias(self) -> None:
        """Register the alias from the ticket: a key discovery cannot reproduce."""
        Registry.register_lazy(
            key="my_alias",
            module=self.PLAIN_MODULE,
            attribute="Plain",
            library="mylib",
            label="alias",
        )

    def test_alias_survives_the_resolution_it_triggered(self):
        """A custom key must not be dropped by the reconcile its own lookup caused."""
        self.register_alias()
        Registry.ensure_resolved(["my_alias"])

        entry = next(e for e in Registry.entries() if e.key == "my_alias")
        self.assertEqual(entry.library, "mylib")
        self.assertEqual(entry.label, "alias")
        self.assertEqual(entry.class_object.__name__, "Plain")

    def test_alias_and_discovered_name_are_both_registered(self):
        """Two keys for one class: the alias joins discovery's entry, it does not replace it."""
        self.register_alias()
        Registry.ensure_resolved(["my_alias"])

        keys = keys_now()
        self.assertIn("my_alias", keys)
        self.assertIn("plain", keys)
        classes = {
            entry.key: entry.class_object
            for entry in Registry.entries()
            if entry.key in {"my_alias", "plain"}
        }
        self.assertIs(classes["my_alias"], classes["plain"])

    def test_recategorised_registration_survives(self):
        """Reproducibility is judged on (key, library, label), not on the key alone."""
        fill(lazy=True)
        Registry.register_lazy(
            key="plain",
            module=self.PLAIN_MODULE,
            attribute="Plain",
            library="otherlib",
        )

        Registry.ensure_resolved(["plain"])

        libraries = {
            entry.library for entry in Registry.entries() if entry.key == "plain"
        }
        self.assertEqual(libraries, {CASES_MODULE, "otherlib"})

    def test_factory_creates_through_the_alias(self):
        """The lookup that forces the import must be answered with the class."""
        fill(lazy=True)
        self.register_alias()

        self.assertEqual(Factory.create("my_alias").__class__.__name__, "Plain")

    def test_no_sweep_for_an_explicitly_registered_key(self):
        """The expensive symptom: a surviving alias must not escalate to a tree sweep."""
        fill(lazy=True)
        self.register_alias()

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always", SweetTeaWarning)
            Factory.create("my_alias")

        self.assertEqual(
            [str(w.message) for w in caught if "remaining module" in str(w.message)],
            [],
            "an explicit registration should resolve its own module and stop there",
        )
        self.assertEqual(self.imported_cases(), {self.PLAIN_MODULE})

    def test_strict_does_not_raise_for_an_explicitly_registered_key(self):
        """lazy="strict" refuses sweeps, and an alias must no longer need one."""
        fill(lazy="strict")
        self.register_alias()

        self.assertEqual(Factory.create("my_alias").__class__.__name__, "Plain")

    def test_entry_whose_attribute_is_not_a_class_is_dropped(self):
        """Carrying entries forward must not keep a name that resolves to a value."""
        Registry.register_lazy(
            key="my_value",
            module=f"{CASES_MODULE}.c12_mutated",
            attribute="Shadowed",
            library="mylib",
        )

        Registry.ensure_resolved(["my_value"], sweep=False)

        self.assertNotIn("my_value", keys_now())

    def test_entry_whose_attribute_vanished_is_dropped(self):
        """A registration naming an attribute the module does not bind has nothing to keep."""
        Registry.register_lazy(
            key="my_missing",
            module=self.PLAIN_MODULE,
            attribute="NotThere",
            library="mylib",
        )

        Registry.ensure_resolved(["my_missing"], sweep=False)

        self.assertNotIn("my_missing", keys_now())

    def test_provisional_scanned_name_still_disappears(self):
        """SWE-10's parity rests on this: the fix must not resurrect a bad guess."""
        fill(lazy=True)
        self.assertIn("nolongerclass", keys_now())

        Registry.ensure_resolved(["nolongerclass"], sweep=False)

        self.assertNotIn("nolongerclass", keys_now())

    def test_carrying_an_entry_forward_is_idempotent(self):
        """Resolving twice must not leave two entries for one alias."""
        fill(lazy=True)
        self.register_alias()
        Registry.ensure_resolved(["my_alias"])
        count = len(Registry.entries())

        Registry.ensure_resolved(["my_alias"], sweep=False)

        self.assertEqual(len(Registry.entries()), count)
        self.assertEqual(len([e for e in Registry.entries() if e.key == "my_alias"]), 1)


class TestStrictnessIsPerTree(TestCase):
    """lazy="strict" describes the tree it filled, not the process (SWE-25)."""

    STRICT_PATH = os.path.join(os.path.dirname(__file__), "lazy_audit_cases")
    STRICT_MODULE = "tests.lazy_audit_cases"

    def setUp(self):
        reset_registry()
        forget_case_modules()

    def tearDown(self):
        reset_registry()

    def fill_strict_elsewhere(self) -> None:
        """Fill an unrelated tree strictly."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", SweetTeaWarning)
            Registry.fill_registry(
                path=self.STRICT_PATH, module=self.STRICT_MODULE, lazy="strict"
            )

    def test_a_strict_tree_does_not_refuse_another_trees_sweep(self):
        """The defect: one strict fill anywhere refused every sweep in the process."""
        fill(lazy=True)
        self.fill_strict_elsewhere()

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", SweetTeaWarning)
            instance = Factory.create("loopa")

        self.assertEqual(instance.__class__.__name__, "LoopA")

    def test_a_strict_tree_still_refuses_its_own(self):
        """Narrowing the scope must not lose the guarantee for the tree that asked."""
        fill(lazy="strict")

        with self.assertRaises(SweetTeaError) as raised:
            Factory.create("loopa")

        self.assertIn("eager", str(raised.exception))

    def test_the_refusal_names_the_tree(self):
        """A caller with several trees needs to know which policy refused."""
        fill(lazy="strict")

        with self.assertRaises(SweetTeaError) as raised:
            Factory.create("loopa")

        self.assertIn(CASES_MODULE, str(raised.exception))

    def test_a_later_strict_fill_of_a_filled_tree_is_recorded(self):
        """Strictness is tracked apart from the fill roots, so a second fill counts."""
        fill(lazy=True)
        fill(lazy="strict")

        with self.assertRaises(SweetTeaError):
            Factory.create("loopa")

    def test_a_sweep_still_runs_for_the_unstrict_part(self):
        """Pending modules split: the strict tree is refused, the rest are swept."""
        fill(lazy=True)
        self.fill_strict_elsewhere()

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always", SweetTeaWarning)
            Factory.create("loopa")

        swept = [w for w in caught if "remaining module" in str(w.message)]
        self.assertEqual(len(swept), 1, [str(w.message) for w in caught])
