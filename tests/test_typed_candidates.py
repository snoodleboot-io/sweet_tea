"""
Tests for SWE-46: a type question can be asked about a tree nothing has imported.

``typed_entries`` can only answer for an entry whose class it holds, so on a lazily
filled tree it answers "none". ``typed_candidates`` answers from the base names the
scanner read instead, which is what makes "which backends are registered for this ABC"
a question a lazy registry can answer at all.

The case package under ``tests/typed_candidate_cases`` holds one module per way a base
can be spelled, so the spellings are tested as source rather than as a story about
source.
"""

import os
import sys
import tempfile
import warnings
from typing import Any
from unittest import TestCase

from sweet_tea.abstract_factory import AbstractFactory
from sweet_tea.entry import Entry
from sweet_tea.lazy_scanner import LazyScanner
from sweet_tea.registry import Registry
from sweet_tea.sweet_tea_warning import SweetTeaWarning

# Imported once, at module scope, and never evicted. A reload would give the tree a
# second Shape class object, and every issubclass against the first would then fail for
# reasons that have nothing to do with the registry.
from tests.typed_candidate_cases.t01_base import Container, Shape

CASES_PATH = os.path.join(os.path.dirname(__file__), "typed_candidate_cases")
CASES_MODULE = "tests.typed_candidate_cases"

# The modules a type query must not import to answer. t01_base is left out on purpose:
# a caller holding the ABC has already imported the module defining it, which is the
# realistic state and not something the registry decides.
BACKEND_MODULES = (
    f"{CASES_MODULE}.t02_direct",
    f"{CASES_MODULE}.t03_alias",
    f"{CASES_MODULE}.t04_dotted",
    f"{CASES_MODULE}.t05_indirect",
    f"{CASES_MODULE}.t06_generic",
    f"{CASES_MODULE}.t07_unrelated",
    f"{CASES_MODULE}.t08_dynamic",
    f"{CASES_MODULE}.t09_unreadable_base",
)


def reset_registry() -> None:
    """Clear every piece of registry state, snapshot bookkeeping included."""
    Registry._Registry__registry.clear()
    Registry._Registry__seen.clear()
    Registry._Registry__lookup.clear()
    Registry._Registry__lookup_keys.clear()
    Registry._Registry__unresolved.clear()
    Registry._Registry__fills.clear()
    Registry._Registry__skipped.clear()
    Registry._Registry__strict_fills.clear()
    Registry._Registry__loaded_sources.clear()


def forget_case_modules() -> None:
    """Drop the backend case modules so their imports can be observed again."""
    for name in BACKEND_MODULES:
        sys.modules.pop(name, None)


def fill(**kwargs) -> None:
    """Fill from the case package."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", SweetTeaWarning)
        Registry.fill_registry(path=CASES_PATH, module=CASES_MODULE, **kwargs)


def imported_backends() -> list[str]:
    """Which backend case modules are in ``sys.modules`` right now."""
    return sorted(name for name in BACKEND_MODULES if name in sys.modules)


def candidate_keys(lookup_type: Any = Any) -> set[str]:
    return {entry.key for entry in Registry.typed_candidates(lookup_type)}


def typed_keys(lookup_type: Any = Any) -> set[str]:
    return {entry.key for entry in Registry.typed_entries(lookup_type)}


class TestScannerRecordsDeclaredBases(TestCase):
    """The scanner reads base names down to the name a class is defined under."""

    def test_a_plain_base_is_recorded(self):
        scanned = LazyScanner.scan_source_detailed("class Circle(Shape): pass")

        self.assertEqual(scanned["Circle"].bases, ("Shape",))

    def test_an_aliased_import_is_reported_under_the_original_name(self):
        """`__name__` says Shape, so recording Form would never match anything."""
        scanned = LazyScanner.scan_source_detailed(
            "from pkg.base import Shape as Form\nclass Square(Form): pass\n"
        )

        self.assertEqual(scanned["Square"].bases, ("Shape",))

    def test_a_dotted_base_keeps_only_its_last_segment(self):
        scanned = LazyScanner.scan_source_detailed(
            "import pkg.base\nclass Triangle(pkg.base.Shape): pass\n"
        )

        self.assertEqual(scanned["Triangle"].bases, ("Shape",))

    def test_a_generic_base_drops_its_subscript(self):
        scanned = LazyScanner.scan_source_detailed("class Boxed(Container[int]): pass")

        self.assertEqual(scanned["Boxed"].bases, ("Container",))

    def test_a_nested_subscript_unwraps_all_the_way(self):
        scanned = LazyScanner.scan_source_detailed("class Odd(Base[int][str]): pass")

        self.assertEqual(scanned["Odd"].bases, ("Base",))

    def test_multiple_inheritance_records_every_base_in_source_order(self):
        scanned = LazyScanner.scan_source_detailed("class Multi(First, Second): pass")

        self.assertEqual(scanned["Multi"].bases, ("First", "Second"))

    def test_a_repeated_base_is_recorded_once(self):
        scanned = LazyScanner.scan_source_detailed(
            "import pkg\nclass Twice(Shape, pkg.Shape): pass\n"
        )

        self.assertEqual(scanned["Twice"].bases, ("Shape",))

    def test_a_type_call_spells_its_bases_in_a_tuple(self):
        scanned = LazyScanner.scan_source_detailed("Made = type('Made', (Shape,), {})")

        self.assertEqual(scanned["Made"].bases, ("Shape",))

    def test_bases_passed_by_keyword_are_read_too(self):
        scanned = LazyScanner.scan_source_detailed(
            "Made = make_dataclass('Made', [], bases=(Shape,))"
        )

        self.assertEqual(scanned["Made"].bases, ("Shape",))

    def test_a_named_tuple_field_list_is_not_read_as_bases(self):
        """namedtuple takes fields where type() takes bases; reading them would lie."""
        scanned = LazyScanner.scan_source_detailed(
            "Point = namedtuple('Point', ('x', 'y'))"
        )

        self.assertEqual(scanned["Point"].bases, ())

    def test_an_alias_reports_the_class_it_aliases(self):
        """Reachability through the aliased name is the same question, so ask it."""
        scanned = LazyScanner.scan_source_detailed(
            "class Circle(Shape): pass\nAlias = Circle\n"
        )

        self.assertEqual(scanned["Alias"].bases, ("Circle",))

    def test_a_computed_base_records_nothing_rather_than_a_guess(self):
        scanned = LazyScanner.scan_source_detailed(
            "Computed = type('Computed', (pick(),), {})"
        )

        self.assertEqual(scanned["Computed"].bases, ())

    def test_a_class_with_no_bases_records_none(self):
        scanned = LazyScanner.scan_source_detailed("class Pebble: pass")

        self.assertEqual(scanned["Pebble"].bases, ())

    def test_definiteness_still_tracks_guarding(self):
        """Recording bases must not disturb what the scan already decided."""
        scanned = LazyScanner.scan_source_detailed(
            "class Sure(Shape): pass\nif flag:\n    class Maybe(Shape): pass\n"
        )

        self.assertTrue(scanned["Sure"].definite)
        self.assertFalse(scanned["Maybe"].definite)

    def test_the_old_contract_is_unchanged(self):
        """scan_source keeps returning name -> definite, which callers rely on."""
        found = LazyScanner.scan_source("class Circle(Shape): pass")

        self.assertEqual(found, {"Circle": True})

    def test_scan_file_keeps_its_old_contract_too(self):
        """The registry now calls the detailed form, so the plain one needs covering."""
        found = LazyScanner.scan_file(os.path.join(CASES_PATH, "t02_direct.py"))

        self.assertEqual(found, {"Circle": True})

    def test_scan_file_detailed_reads_bases_off_a_real_file(self):
        scanned = LazyScanner.scan_file_detailed(
            os.path.join(CASES_PATH, "t03_alias.py")
        )

        self.assertEqual(scanned["Square"].bases, ("Shape",))


class TestTypedCandidatesOnALazyTree(TestCase):
    """The question SWE-46 is about: which keys offer this type, importing nothing."""

    def setUp(self):
        reset_registry()
        forget_case_modules()
        fill(lazy=True)

    def tearDown(self):
        reset_registry()
        forget_case_modules()

    def test_typed_entries_still_answers_none(self):
        """The starting point, stated as a test so the contrast is pinned."""
        self.assertEqual(typed_keys(Shape), set())

    def test_every_spelling_of_the_base_is_found(self):
        """Plain, aliased, dotted, two-hop and type()-built all reach Shape."""
        self.assertEqual(
            candidate_keys(Shape),
            {"shape", "circle", "square", "triangle", "roundedcircle", "made"},
        )

    def test_a_class_with_no_bases_is_not_a_candidate(self):
        self.assertNotIn("pebble", candidate_keys(Shape))

    def test_a_class_whose_base_cannot_be_read_is_not_a_candidate(self):
        """The documented miss: nothing recorded, so nothing claimed."""
        self.assertNotIn("computed", candidate_keys(Shape))

    def test_a_different_base_selects_a_different_set(self):
        """The filter narrows; it does not just return everything lazy."""
        self.assertEqual(candidate_keys(Container), {"container", "boxedint"})

    def test_the_type_itself_is_included_because_issubclass_is_reflexive(self):
        self.assertIn("shape", candidate_keys(Shape))

    def test_answering_imports_nothing(self):
        """The whole point: the saving lazy filling makes must survive the query."""
        Registry.typed_candidates(Shape)
        Registry.typed_candidates(Container)

        self.assertEqual(imported_backends(), [])

    def test_the_candidates_are_still_lazy(self):
        """A candidate is a candidate, not an entry that quietly resolved itself."""
        self.assertTrue(all(e.is_lazy for e in Registry.typed_candidates(Shape)))

    def test_order_follows_registration(self):
        candidates = Registry.typed_candidates(Shape)

        self.assertEqual(
            [e.key for e in candidates],
            [e.key for e in Registry.entries() if e in candidates],
        )

    def test_the_returned_list_is_a_copy(self):
        """Mutating the answer must not edit the registry, as entries() guarantees."""
        Registry.typed_candidates(Shape).clear()

        self.assertNotEqual(candidate_keys(Shape), set())


class TestCandidatesAndTheFactoryAgree(TestCase):
    """A candidate builds, and only the module behind it is imported."""

    def setUp(self):
        reset_registry()
        forget_case_modules()
        fill(lazy=True)

    def tearDown(self):
        reset_registry()
        forget_case_modules()

    def test_a_candidate_builds_into_a_real_subclass(self):
        instance = AbstractFactory[Shape].create("circle")

        self.assertIsInstance(instance, Shape)

    def test_building_one_candidate_imports_only_its_module(self):
        AbstractFactory[Shape].create("circle")

        self.assertEqual(imported_backends(), [f"{CASES_MODULE}.t02_direct"])

    def test_a_non_candidate_is_refused_by_the_typed_factory(self):
        """Narrowing is still the factory's own, done on the real class."""
        with self.assertRaises(Exception):
            AbstractFactory[Shape].create("pebble")

    def test_typed_entries_fills_in_as_entries_resolve(self):
        """The two methods converge on a resolved entry rather than diverging."""
        AbstractFactory[Shape].create("circle")

        self.assertIn("circle", typed_keys(Shape))
        self.assertIn("circle", candidate_keys(Shape))


class TestTypedCandidatesMatchesTypedEntriesWhenResolved(TestCase):
    """With nothing left to approximate, the two must give the same answer."""

    def setUp(self):
        reset_registry()
        forget_case_modules()

    def tearDown(self):
        reset_registry()
        forget_case_modules()

    def test_an_eager_fill_makes_them_identical(self):
        fill()

        self.assertEqual(candidate_keys(Shape), typed_keys(Shape))

    def test_an_eager_fill_still_excludes_the_unrelated_class(self):
        fill()

        self.assertNotIn("pebble", candidate_keys(Shape))

    def test_resolving_everything_makes_them_identical(self):
        fill(lazy=True)
        Registry.resolve_all()

        self.assertEqual(candidate_keys(Shape), typed_keys(Shape))


class TestArgumentHandlingMatchesTypedEntries(TestCase):
    """Whatever typed_entries accepts or refuses, this must accept or refuse."""

    def setUp(self):
        reset_registry()
        forget_case_modules()
        fill(lazy=True)

    def tearDown(self):
        reset_registry()
        forget_case_modules()

    def test_any_returns_every_entry_resolved_or_not(self):
        self.assertEqual(candidate_keys(), {e.key for e in Registry.entries()})

    def test_any_is_the_default(self):
        self.assertEqual(
            len(Registry.typed_candidates()), len(Registry.typed_candidates(Any))
        )

    def test_a_tuple_of_types_matches_any_member(self):
        self.assertEqual(
            candidate_keys((Shape, Container)),
            candidate_keys(Shape) | candidate_keys(Container),
        )

    def test_a_union_matches_any_member(self):
        self.assertEqual(
            candidate_keys(Shape | Container),
            candidate_keys(Shape) | candidate_keys(Container),
        )

    def test_an_unusable_argument_raises_the_same_type_error(self):
        with self.assertRaises(TypeError):
            Registry.typed_candidates(42)

    def test_an_unusable_argument_raises_even_over_an_empty_registry(self):
        """Settled against object, not against whatever happens to be registered."""
        reset_registry()

        with self.assertRaises(TypeError):
            Registry.typed_candidates(42)

    def test_an_empty_tuple_matches_nothing_just_as_issubclass_does(self):
        """issubclass(x, ()) is False for every x, so the answer is empty, not all."""
        self.assertEqual(Registry.typed_candidates(()), [])
        self.assertEqual(Registry.typed_entries(()), [])

    def test_a_tuple_holding_a_non_class_raises(self):
        with self.assertRaises(TypeError):
            Registry.typed_candidates((Shape, 42))

    def test_a_refused_argument_is_not_memoised_into_the_type_slots(self):
        """It must not leave the lookup cache in a state typed_entries trips over."""
        with self.assertRaises(TypeError):
            Registry.typed_candidates(42)

        self.assertNotIn(42, Registry._Registry__lookup_keys)

    def test_asking_leaves_no_cache_behind_at_all(self):
        """Deliberately uncached: a second question must not reuse the first answer."""
        Registry.typed_candidates(Shape)

        self.assertEqual(Registry._Registry__lookup_keys, [])


class TestTypedEntriesContractIsUnchanged(TestCase):
    """typed_entries promises a real subclass; SWE-46 must not weaken that."""

    def setUp(self):
        reset_registry()
        forget_case_modules()
        fill(lazy=True)

    def tearDown(self):
        reset_registry()
        forget_case_modules()

    def test_it_never_returns_an_unresolved_entry(self):
        fill(lazy=True)

        self.assertEqual([e for e in Registry.typed_entries(Shape) if e.is_lazy], [])

    def test_every_entry_it_returns_holds_a_real_subclass(self):
        Registry.resolve_all()

        for entry in Registry.typed_entries(Shape):
            self.assertTrue(issubclass(entry.class_object, Shape))

    def test_it_still_imports_nothing(self):
        Registry.typed_entries(Shape)

        self.assertEqual(imported_backends(), [])


class TestHandRegisteredLazyEntries(TestCase):
    """A caller registering lazily can opt in by passing the bases it knows."""

    def setUp(self):
        reset_registry()
        forget_case_modules()

    def tearDown(self):
        reset_registry()
        forget_case_modules()

    def test_declared_bases_given_by_hand_make_an_entry_a_candidate(self):
        Registry.register_lazy(
            key="handmade",
            module=f"{CASES_MODULE}.t02_direct",
            attribute="Circle",
            declared_bases=("Shape",),
        )

        self.assertIn("handmade", candidate_keys(Shape))

    def test_without_them_the_entry_is_not_a_candidate(self):
        Registry.register_lazy(
            key="handmade",
            module=f"{CASES_MODULE}.t02_direct",
            attribute="Circle",
        )

        self.assertNotIn("handmade", candidate_keys(Shape))

    def test_a_single_base_may_be_given_as_a_bare_string(self):
        """Iterating a str into its letters would record five bases and match none."""
        Registry.register_lazy(
            key="handmade",
            module=f"{CASES_MODULE}.t02_direct",
            attribute="Circle",
            declared_bases="Shape",
        )

        self.assertEqual(Registry.entries()[0].declared_bases, ("Shape",))
        self.assertIn("handmade", candidate_keys(Shape))

    def test_an_eager_registration_records_no_bases(self):
        """It holds the real class, so it needs no approximation of one."""
        Registry.register(key="circle", class_def=type("Circle", (Shape,), {}))

        self.assertEqual(Registry.entries()[0].declared_bases, ())

    def test_declared_bases_do_not_affect_deduplication(self):
        """identity decides duplicates; a base list must not split one entry in two."""
        Registry.register_lazy(
            key="same", module="m", attribute="A", declared_bases=("Shape",)
        )
        Registry.register_lazy(key="same", module="m", attribute="A")

        self.assertEqual(len(Registry.entries()), 1)

    def test_a_base_naming_an_already_resolved_class_is_settled_for_real(self):
        """One hop out of the tree: the base is a class the registry already holds."""
        Registry.register(key="circle", class_def=Shape)
        Registry.register_lazy(
            key="offspring",
            module="m",
            attribute="Offspring",
            declared_bases=("Shape",),
        )

        self.assertIn("offspring", candidate_keys(Shape))

    def test_a_cycle_in_the_recorded_graph_terminates(self):
        """Python cannot build one, but two guarded blocks can record one."""
        Registry.register_lazy(
            key="a", module="m", attribute="A", declared_bases=("B",)
        )
        Registry.register_lazy(
            key="b", module="m", attribute="B", declared_bases=("A",)
        )

        self.assertEqual(candidate_keys(Shape), set())


class TestTypedCandidatesAcrossASnapshot(TestCase):
    """A snapshot is read in a process that scanned nothing, so bases must travel."""

    def setUp(self):
        reset_registry()
        forget_case_modules()
        handle, self.path = tempfile.mkstemp(suffix=".json")
        os.close(handle)

    def tearDown(self):
        reset_registry()
        forget_case_modules()
        os.unlink(self.path)

    def test_candidates_survive_export_and_load(self):
        fill(lazy=True)
        expected = candidate_keys(Shape)
        Registry.export(self.path)
        reset_registry()

        Registry.load(self.path, verify=False)

        self.assertEqual(candidate_keys(Shape), expected)

    def test_loading_imports_nothing_and_answering_imports_nothing(self):
        fill(lazy=True)
        Registry.export(self.path)
        reset_registry()
        forget_case_modules()

        Registry.load(self.path, verify=False)
        Registry.typed_candidates(Shape)

        self.assertEqual(imported_backends(), [])

    def test_an_older_snapshot_without_bases_still_loads(self):
        """Pydantic defaults it, so a format that predates the field is readable."""
        fill(lazy=True)
        Registry.export(self.path)
        with open(self.path, encoding="utf-8") as handle:
            payload = handle.read()
        stripped = payload.replace('"declared_bases"', '"ignored_by_this_reader"')
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write(stripped)
        reset_registry()

        Registry.load(self.path, verify=False)

        self.assertNotEqual(Registry.entries(), [])

    def test_an_older_snapshot_reports_no_subclass_rather_than_a_wrong_one(self):
        fill(lazy=True)
        Registry.export(self.path)
        with open(self.path, encoding="utf-8") as handle:
            payload = handle.read()
        stripped = payload.replace('"declared_bases"', '"ignored_by_this_reader"')
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write(stripped)
        reset_registry()

        Registry.load(self.path, verify=False)

        # Only the reflexive match survives: an entry registering Shape itself is
        # named Shape, which needs no recorded base to be recognised. Every actual
        # subclass is missing, which is that file's honest content -- it records no
        # bases -- rather than a wrong answer about it.
        self.assertEqual(candidate_keys(Shape), {"shape"})


class TestEntryCarriesDeclaredBases(TestCase):
    """The field itself: defaulted, typed, and out of the way of everything else."""

    def test_it_defaults_to_empty(self):
        self.assertEqual(Entry(key="k").declared_bases, ())

    def test_it_is_stored_as_a_tuple(self):
        entry = Entry(key="k", declared_bases=["Shape", "Mixin"])

        self.assertEqual(entry.declared_bases, ("Shape", "Mixin"))

    def test_it_does_not_reach_identity(self):
        """identity is the dedupe key; a base list is evidence, not a distinction."""
        with_bases = Entry(
            key="k", module="m", attribute="A", declared_bases=("Shape",)
        )
        without = Entry(key="k", module="m", attribute="A")

        self.assertEqual(with_bases.identity, without.identity)

    def test_reading_it_imports_nothing(self):
        """It is recorded source, so it answers without touching the module."""
        lazy = Entry(
            key="k", module="no.such.module", attribute="A", declared_bases=("Shape",)
        )

        self.assertEqual(lazy.declared_bases, ("Shape",))
        self.assertTrue(lazy.is_lazy)
