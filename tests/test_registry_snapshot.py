"""
Tests for SWE-9: a filled registry can be written to a file and read back without
walking or importing a package tree.
"""

import importlib
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
from sweet_tea.snapshot_entry import SnapshotEntry
from sweet_tea.snapshot_source import SnapshotSource
from sweet_tea.sweet_tea_error import SweetTeaError
from sweet_tea.sweet_tea_warning import SweetTeaWarning

CASES_PATH = os.path.join(os.path.dirname(__file__), "lazy_cases")
CASES_MODULE = "tests.lazy_cases"


def reset_registry() -> None:
    """Clear every piece of registry state, snapshot bookkeeping included."""
    Registry._Registry__registry.clear()
    Registry._Registry__seen.clear()
    Registry._Registry__lookup.clear()
    Registry._Registry__lookup_keys.clear()
    Registry._Registry__unresolved.clear()
    Registry._Registry__fills.clear()
    Registry._Registry__skipped.clear()
    Registry._Registry__no_sweep = False


def forget_case_modules() -> None:
    """Drop the case modules so imports can be observed again."""
    for name in [n for n in sys.modules if n.startswith(CASES_MODULE + ".")]:
        del sys.modules[name]


def fill(**kwargs) -> None:
    """Fill from the case package, ignoring the deliberate optional-dependency skip."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", SweetTeaWarning)
        Registry.fill_registry(path=CASES_PATH, module=CASES_MODULE, **kwargs)


def registered() -> set[tuple[str, str, str]]:
    return {(e.key, e.library, e.label) for e in Registry.entries()}


class TestSnapshotRoundTrip(TestCase):
    """What was filled is what comes back."""

    def setUp(self):
        reset_registry()
        forget_case_modules()
        self.directory = tempfile.mkdtemp()
        self.path = os.path.join(self.directory, "registry.json")

    def tearDown(self):
        reset_registry()
        shutil.rmtree(self.directory, ignore_errors=True)

    def test_eager_fill_round_trips(self):
        """A snapshot of an eagerly filled registry reproduces its registrations."""
        fill()
        before = registered()
        Registry.export(self.path)

        reset_registry()
        Registry.load(self.path)

        self.assertEqual(registered(), before)

    def test_lazy_fill_round_trips(self):
        """Exporting a lazily filled registry does not need it resolved first."""
        fill(lazy=True)
        before = registered()
        Registry.export(self.path)

        reset_registry()
        Registry.load(self.path)

        self.assertEqual(registered(), before)

    def test_export_imports_nothing(self):
        """Writing a snapshot of a lazy registry must stay lazy."""
        fill(lazy=True)
        forget_case_modules()
        Registry.export(self.path)

        self.assertEqual(
            [n for n in sys.modules if n.startswith(CASES_MODULE + ".")], []
        )

    def test_load_imports_nothing(self):
        """Reading a snapshot registers names; it does not execute modules."""
        fill(lazy=True)
        Registry.export(self.path)
        reset_registry()
        forget_case_modules()

        Registry.load(self.path)

        self.assertEqual(
            [n for n in sys.modules if n.startswith(CASES_MODULE + ".")], []
        )
        self.assertTrue(Registry.entries())

    def test_loaded_entries_resolve_on_use(self):
        """A loaded registry is usable, not merely descriptive."""
        fill(lazy=True)
        Registry.export(self.path)
        reset_registry()
        forget_case_modules()
        Registry.load(self.path)

        instance = Factory.create("plain")

        self.assertEqual(instance.__class__.__name__, "Plain")

    def test_attribute_name_survives_the_round_trip(self):
        """A class reachable under a name unlike its own is named by the attribute."""
        fill()
        Registry.export(self.path)
        snapshot = RegistrySnapshot.read(self.path)

        mismatch = next(e for e in snapshot.entries if e.key == "mismatch")

        # Mismatch = type("InnerName", (), {}) — getattr needs "Mismatch".
        self.assertTrue(mismatch.class_def.endswith(":Mismatch"))

    def test_skipped_modules_are_recorded(self):
        """A snapshot says what was not installed, not just what was registered."""
        fill()
        Registry.export(self.path)
        snapshot = RegistrySnapshot.read(self.path)

        self.assertIn(f"{CASES_MODULE}.d03_optional", snapshot.skipped)

        reset_registry()
        Registry.load(self.path)
        self.assertIn(f"{CASES_MODULE}.d03_optional", Registry.skipped())

    def test_on_disk_entry_keys_are_the_snapshot_format(self):
        """Entry's own serialisation settings must not reach the file format."""
        fill(lazy=True)
        Registry.export(self.path)

        with open(self.path, encoding="utf-8") as handle:
            payload = json.load(handle)

        self.assertTrue(payload["entries"])
        for written in payload["entries"]:
            self.assertEqual(set(written), {"key", "class_def", "library", "label"})
            # SnapshotEntry.class_def is the module:attribute string, not a class.
            self.assertIsInstance(written["class_def"], str)

    def test_sources_record_the_filled_root_only(self):
        """Subpackages are part of their root's walk, not separate sources."""
        fill(lazy=True)
        Registry.export(self.path)
        snapshot = RegistrySnapshot.read(self.path)

        self.assertEqual([s.module for s in snapshot.sources], [CASES_MODULE])

    def test_source_is_placed_inside_its_root_package(self):
        """A subpackage source is recorded by where it sits in its root package."""
        fill(lazy=True)
        Registry.export(self.path)
        snapshot = RegistrySnapshot.read(self.path)

        source = snapshot.sources[0]

        # CASES_MODULE is "tests.lazy_cases", so the root is "tests" and the tree it
        # names sits one directory inside it.
        self.assertEqual(source.root_module, "tests")
        self.assertEqual(source.relative_path, "lazy_cases")
        self.assertEqual(
            os.path.realpath(source.resolved_path()), os.path.realpath(CASES_PATH)
        )


class TestSnapshotStaleness(TestCase):
    """A stale snapshot is worse than walking, so loading checks by default."""

    def setUp(self):
        reset_registry()
        self.directory = tempfile.mkdtemp()
        self.package = os.path.join(self.directory, "pkg")
        os.makedirs(self.package)
        open(os.path.join(self.package, "__init__.py"), "w").close()
        self.module_file = os.path.join(self.package, "thing.py")
        with open(self.module_file, "w") as handle:
            handle.write("class Thing:\n    pass\n")
        self.path = os.path.join(self.directory, "registry.json")
        Registry.fill_registry(path=self.package, module="pkg", lazy=True)
        Registry.export(self.path)
        reset_registry()

    def tearDown(self):
        reset_registry()
        shutil.rmtree(self.directory, ignore_errors=True)

    def test_unchanged_sources_load(self):
        """The happy path: nothing moved, so the snapshot is trusted."""
        Registry.load(self.path)

        self.assertIn("thing", {e.key for e in Registry.entries()})

    def test_changed_source_is_refused(self):
        """An edited module means the snapshot may name classes that no longer exist."""
        with open(self.module_file, "a") as handle:
            handle.write("\n\nclass Added:\n    pass\n")

        with self.assertRaises(SweetTeaError) as raised:
            Registry.load(self.path)

        self.assertIn("no longer matches", str(raised.exception))
        self.assertIn("pkg", str(raised.exception))

    def test_new_module_is_refused(self):
        """Adding a file changes the tree even though nothing existing changed."""
        with open(os.path.join(self.package, "extra.py"), "w") as handle:
            handle.write("class Extra:\n    pass\n")

        with self.assertRaises(SweetTeaError):
            Registry.load(self.path)

    def test_missing_tree_is_refused(self):
        """A snapshot of a tree that is gone cannot be current."""
        shutil.rmtree(self.package)

        with self.assertRaises(SweetTeaError):
            Registry.load(self.path)

    def test_verification_can_be_waived(self):
        """The caller may know the difference is harmless."""
        with open(self.module_file, "a") as handle:
            handle.write("\n\nclass Added:\n    pass\n")

        Registry.load(self.path, verify=False)

        self.assertIn("thing", {e.key for e in Registry.entries()})

    def test_digest_ignores_bytecode(self):
        """__pycache__ is derived, so it must not make a snapshot look stale."""
        cache = os.path.join(self.package, "__pycache__")
        os.makedirs(cache, exist_ok=True)
        with open(os.path.join(cache, "thing.cpython-312.pyc"), "wb") as handle:
            handle.write(b"\x00\x01")

        Registry.load(self.path)

        self.assertIn("thing", {e.key for e in Registry.entries()})


class TestSnapshotRelocation(TestCase):
    """SWE-18: a snapshot must verify where the package is installed, not where built."""

    PACKAGE = "relocpkg"

    def setUp(self):
        reset_registry()
        self.directory = tempfile.mkdtemp()
        self.first = os.path.join(self.directory, "first")
        self.second = os.path.join(self.directory, "second")
        # Importing the package touches this file, so a test can tell whether locating
        # the package executed it. Kept outside the tree, so it cannot shift the digest.
        self.marker = os.path.join(self.directory, "imported.marker")
        self.path = os.path.join(self.directory, "registry.json")
        self.on_path: list[str] = []
        self.build_tree(self.first)

    def tearDown(self):
        reset_registry()
        self.forget_package()
        self.clear_path()
        shutil.rmtree(self.directory, ignore_errors=True)

    def build_tree(self, root: str) -> str:
        """Write the case package under a root directory and return its directory."""
        package = os.path.join(root, self.PACKAGE)
        os.makedirs(package)
        with open(os.path.join(package, "__init__.py"), "w") as handle:
            handle.write(f"open({self.marker!r}, 'a').close()\n")
        with open(os.path.join(package, "thing.py"), "w") as handle:
            handle.write("class Thing:\n    pass\n")
        return package

    def clear_path(self) -> None:
        """Take every root this test added back off sys.path."""
        for entry in self.on_path:
            while entry in sys.path:
                sys.path.remove(entry)
        self.on_path.clear()

    def forget_package(self) -> None:
        """Drop the case package so it is located afresh from sys.path."""
        for name in [
            n
            for n in sys.modules
            if n == self.PACKAGE or n.startswith(f"{self.PACKAGE}.")
        ]:
            del sys.modules[name]

    def importable(self, root: str) -> None:
        """Make the copy under a root the one the interpreter would find."""
        self.forget_package()
        self.clear_path()
        sys.path.insert(0, root)
        self.on_path.append(root)
        importlib.invalidate_caches()

    def export_from_first(self) -> None:
        """Fill from the first copy and write the snapshot, as a build step would."""
        self.importable(self.first)
        Registry.fill_registry(
            path=os.path.join(self.first, self.PACKAGE), module=self.PACKAGE, lazy=True
        )
        Registry.export(self.path)
        reset_registry()

    def relocate(self) -> str:
        """Move the package to the second root, as installing a wheel would."""
        moved = os.path.join(self.second, self.PACKAGE)
        shutil.copytree(os.path.join(self.first, self.PACKAGE), moved)
        # The export directory goes away entirely: a snapshot shipped in a wheel can
        # never fall back to the CI checkout it was built in.
        shutil.rmtree(self.first)
        self.importable(self.second)
        return moved

    def written(self) -> dict:
        """The snapshot as it sits on disk."""
        with open(self.path, encoding="utf-8") as handle:
            return json.load(handle)

    def rewrite_as_version_one(self) -> None:
        """Strip the snapshot back to the shape a pre-SWE-18 sweet_tea wrote."""
        payload = self.written()
        payload["version"] = 1
        for source in payload["sources"]:
            del source["relative_path"]
        with open(self.path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)

    def test_snapshot_from_another_location_verifies(self):
        """The shipped-snapshot case: exported from one tree, loaded from another."""
        self.export_from_first()
        self.relocate()

        Registry.load(self.path)

        self.assertIn("thing", {e.key for e in Registry.entries()})

    def test_changed_sources_at_the_new_location_are_refused(self):
        """Relocating is not a licence to stop checking the digest."""
        self.export_from_first()
        moved = self.relocate()
        with open(os.path.join(moved, "thing.py"), "a") as handle:
            handle.write("\n\nclass Added:\n    pass\n")

        with self.assertRaises(SweetTeaError) as raised:
            Registry.load(self.path)

        self.assertIn("no longer matches", str(raised.exception))

    def test_added_module_at_the_new_location_is_refused(self):
        """A file the snapshot never saw is a change wherever the tree now lives."""
        self.export_from_first()
        moved = self.relocate()
        with open(os.path.join(moved, "extra.py"), "w") as handle:
            handle.write("class Extra:\n    pass\n")

        with self.assertRaises(SweetTeaError):
            Registry.load(self.path)

    def test_removed_module_at_the_new_location_is_refused(self):
        """Nor may a file go missing from the relocated tree."""
        self.export_from_first()
        moved = self.relocate()
        os.remove(os.path.join(moved, "thing.py"))

        with self.assertRaises(SweetTeaError):
            Registry.load(self.path)

    def test_deleted_package_is_refused(self):
        """With nothing to locate and nothing at the recorded path, the tree is gone."""
        self.export_from_first()
        shutil.rmtree(self.first)

        with self.assertRaises(SweetTeaError):
            Registry.load(self.path)

    def test_waived_verification_still_loads_from_a_new_location(self):
        """verify=False keeps meaning "do not look", not "look somewhere else"."""
        self.export_from_first()
        moved = self.relocate()
        with open(os.path.join(moved, "thing.py"), "a") as handle:
            handle.write("\n\nclass Added:\n    pass\n")

        Registry.load(self.path, verify=False)

        self.assertIn("thing", {e.key for e in Registry.entries()})

    def test_locating_the_package_executes_nothing(self):
        """Neither writing nor reading a snapshot may run the consumer's code."""
        self.export_from_first()
        self.assertFalse(os.path.exists(self.marker))
        self.relocate()

        Registry.load(self.path)

        self.assertFalse(os.path.exists(self.marker))
        self.assertNotIn(self.PACKAGE, sys.modules)

    def test_sources_record_where_they_sit_and_where_they_were(self):
        """The file keeps both locations, under a version that says the field is there."""
        self.export_from_first()

        payload = self.written()

        self.assertEqual(payload["version"], 2)
        for source in payload["sources"]:
            self.assertEqual(set(source), {"module", "path", "relative_path", "digest"})
        self.assertEqual(payload["sources"][0]["relative_path"], ".")

    def test_version_one_snapshot_still_verifies_in_place(self):
        """A snapshot written before relative paths existed keeps loading untouched."""
        self.export_from_first()
        self.rewrite_as_version_one()

        Registry.load(self.path)

        self.assertIn("thing", {e.key for e in Registry.entries()})

    def test_version_one_snapshot_is_refused_after_a_move(self):
        """Without a relative record there is nothing to resolve: re-export to gain it."""
        self.export_from_first()
        self.rewrite_as_version_one()
        self.relocate()

        with self.assertRaises(SweetTeaError) as raised:
            Registry.load(self.path)

        self.assertIn("no longer matches", str(raised.exception))

    def test_source_outside_its_root_package_keeps_only_the_absolute_path(self):
        """A tree that is not inside the package it is named for cannot be relative."""
        self.importable(self.first)
        # "relocpkg" resolves to <first>/relocpkg, so a walk of <first> itself lies
        # outside it; there is no sane relative record to make.
        self.assertEqual(SnapshotSource.relative_to_root(self.PACKAGE, self.first), "")

    def test_unlocatable_root_falls_back_to_the_recorded_path(self):
        """An uninstalled package is checked where it was exported from, as before."""
        source = SnapshotSource(
            module="no_such_root_package",
            path=os.path.join(self.first, self.PACKAGE),
            relative_path=".",
            digest=SnapshotSource.digest_of(os.path.join(self.first, self.PACKAGE)),
        )

        self.assertEqual(source.resolved_path(), os.path.join(self.first, self.PACKAGE))
        self.assertFalse(source.is_stale())


class TestSnapshotFileHandling(TestCase):
    """Reading a snapshot reports its own problems clearly."""

    def setUp(self):
        reset_registry()
        self.directory = tempfile.mkdtemp()
        self.path = os.path.join(self.directory, "registry.json")

    def tearDown(self):
        reset_registry()
        shutil.rmtree(self.directory, ignore_errors=True)

    def test_missing_file(self):
        with self.assertRaises(SweetTeaError) as raised:
            Registry.load(os.path.join(self.directory, "absent.json"))
        self.assertIn("Cannot read snapshot", str(raised.exception))

    def test_invalid_json(self):
        with open(self.path, "w") as handle:
            handle.write("{not json")
        with self.assertRaises(SweetTeaError) as raised:
            Registry.load(self.path)
        self.assertIn("not valid JSON", str(raised.exception))

    def test_future_version_is_refused(self):
        """A newer writer may use a shape this reader would misinterpret."""
        with open(self.path, "w") as handle:
            json.dump(
                {"version": 99, "sources": [], "entries": [], "skipped": {}}, handle
            )

        with self.assertRaises(SweetTeaError) as raised:
            Registry.load(self.path)

        self.assertIn("version 99", str(raised.exception))

    def test_malformed_class_reference_is_refused(self):
        """A reference with no attribute half cannot be resolved later."""
        with open(self.path, "w") as handle:
            json.dump(
                {
                    "version": 1,
                    "sources": [],
                    "entries": [
                        {"key": "a", "class_def": "nocolon", "library": "", "label": ""}
                    ],
                    "skipped": {},
                },
                handle,
            )

        with self.assertRaises(SweetTeaError) as raised:
            Registry.load(self.path)

        self.assertIn("module:attribute", str(raised.exception))

    def test_coordinates_split_on_the_last_colon(self):
        """Module paths have dots, not colons, so the last colon is the separator."""
        entry = SnapshotEntry(key="a", class_def="a.b.c:D")
        self.assertEqual(entry.coordinates, ("a.b.c", "D"))

    def test_digest_changes_with_contents(self):
        """The digest is what staleness rests on, so pin its behaviour directly."""
        first = os.path.join(self.directory, "tree")
        os.makedirs(first)
        with open(os.path.join(first, "m.py"), "w") as handle:
            handle.write("x = 1\n")
        before = SnapshotSource.digest_of(first)

        with open(os.path.join(first, "m.py"), "w") as handle:
            handle.write("x = 2\n")

        self.assertNotEqual(SnapshotSource.digest_of(first), before)
