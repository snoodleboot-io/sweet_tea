"""
Tests for SWE-9: a filled registry can be written to a file and read back without
walking or importing a package tree.
"""

import importlib
import importlib.machinery
import json
import os
import py_compile
import shutil
import sys
import tempfile
import threading
import time
import warnings
from unittest import TestCase, skipUnless

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
    Registry._Registry__strict_fills.clear()
    Registry._Registry__loaded_sources.clear()


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
            self.assertEqual(
                set(written),
                {"key", "class_def", "library", "label", "provisional"},
            )
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

        # Written at whatever the current format is: the field this test is about
        # arrived in 2, but the version says what the whole format is, and it has
        # moved three times since for reasons that have nothing to do with it.
        self.assertEqual(payload["version"], RegistrySnapshot.FORMAT_VERSION)
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


class TestSnapshotNamespacePortions(TestCase):
    """SWE-28: a namespace package has a directory per portion; check the right one."""

    PACKAGE = "nsportions"

    def setUp(self):
        reset_registry()
        self.directory = tempfile.mkdtemp()
        self.first = os.path.join(self.directory, "p1")
        self.second = os.path.join(self.directory, "p2")
        self.first_portion = self.portion(self.first, "class Thing:\n    pass\n")
        self.second_portion = self.portion(
            self.second, "class Thing:\n    pass\n\n\nclass Other:\n    pass\n"
        )
        self.path = os.path.join(self.directory, "registry.json")
        # Search order puts the portion that was *not* exported first, which is the
        # arrangement that used to make resolution settle on the wrong directory.
        sys.path.insert(0, self.second)
        sys.path.insert(0, self.first)
        importlib.invalidate_caches()

    def tearDown(self):
        reset_registry()
        for root in (self.first, self.second):
            while root in sys.path:
                sys.path.remove(root)
        for name in [
            n
            for n in sys.modules
            if n == self.PACKAGE or n.startswith(f"{self.PACKAGE}.")
        ]:
            del sys.modules[name]
        shutil.rmtree(self.directory, ignore_errors=True)

    def portion(self, root: str, body: str) -> str:
        """Write one portion of the namespace package and return its directory."""
        portion = os.path.join(root, self.PACKAGE)
        os.makedirs(portion)
        with open(os.path.join(portion, "thing.py"), "w") as handle:
            handle.write(body)
        return portion

    def export_from_the_second_portion(self) -> None:
        """Fill from the portion search order puts second, and export that."""
        Registry.fill_registry(path=self.second_portion, module=self.PACKAGE, lazy=True)
        Registry.export(self.path)
        reset_registry()

    def recorded_source(self) -> SnapshotSource:
        """The single source the exported snapshot holds."""
        return RegistrySnapshot.read(self.path).sources[0]

    def test_the_exported_portion_is_the_one_resolved(self):
        """Both portions answer to the relative record; only one of them was walked."""
        self.export_from_the_second_portion()

        self.assertEqual(
            os.path.realpath(self.recorded_source().resolved_path()),
            os.path.realpath(self.second_portion),
        )

    def test_an_untouched_namespace_tree_is_not_stale(self):
        """Resolving to a sibling portion called a tree nobody had touched stale."""
        self.export_from_the_second_portion()

        Registry.load(self.path)

        self.assertIn("other", {entry.key for entry in Registry.entries()})

    def test_a_change_in_the_exported_portion_is_refused(self):
        """The portion that was walked is the one whose edits have to be noticed."""
        self.export_from_the_second_portion()
        with open(os.path.join(self.second_portion, "thing.py"), "a") as handle:
            handle.write("\n\nclass Added:\n    pass\n")

        with self.assertRaises(SweetTeaError) as raised:
            Registry.load(self.path)

        self.assertIn("no longer matches", str(raised.exception))

    def test_a_portion_whose_digest_differs_is_not_accepted_for_existing(self):
        """Existing is not matching: a candidate has to hash to the recorded digest."""
        self.export_from_the_second_portion()

        self.assertNotEqual(
            os.path.realpath(self.recorded_source().resolved_path()),
            os.path.realpath(self.first_portion),
        )

    def test_the_recorded_absolute_path_is_the_last_resort(self):
        """A located root that holds no matching directory is not the end of it."""
        elsewhere = os.path.join(self.directory, "elsewhere")
        os.makedirs(elsewhere)
        with open(os.path.join(elsewhere, "thing.py"), "w") as handle:
            handle.write("class Elsewhere:\n    pass\n")
        source = SnapshotSource(
            module=self.PACKAGE,
            path=elsewhere,
            relative_path=".",
            digest=SnapshotSource.digest_of(elsewhere),
        )

        self.assertEqual(source.resolved_path(), elsewhere)
        self.assertFalse(source.is_stale())


@skipUnless(hasattr(os, "symlink"), "the platform has no symlinks")
class TestSnapshotSymlinkedSubpackages(TestCase):
    """SWE-28: the digest has to cover every tree the fill registers from."""

    PACKAGE = "linkedapp"

    def setUp(self):
        reset_registry()
        self.directory = tempfile.mkdtemp()
        self.root = os.path.join(self.directory, "root")
        self.package = os.path.join(self.root, self.PACKAGE)
        os.makedirs(self.package)
        open(os.path.join(self.package, "__init__.py"), "w").close()
        with open(os.path.join(self.package, "thing.py"), "w") as handle:
            handle.write("class Thing:\n    pass\n")
        self.shared = os.path.join(self.directory, "shared", "plugins")
        os.makedirs(self.shared)
        open(os.path.join(self.shared, "__init__.py"), "w").close()
        self.plugin_file = os.path.join(self.shared, "plug.py")
        with open(self.plugin_file, "w") as handle:
            handle.write("class Plug:\n    pass\n")
        # The monorepo and editable-install shape: a subpackage that lives elsewhere.
        os.symlink(self.shared, os.path.join(self.package, "plugins"))
        self.path = os.path.join(self.directory, "registry.json")
        sys.path.insert(0, self.root)
        importlib.invalidate_caches()

    def tearDown(self):
        reset_registry()
        while self.root in sys.path:
            sys.path.remove(self.root)
        for name in [
            n
            for n in sys.modules
            if n == self.PACKAGE or n.startswith(f"{self.PACKAGE}.")
        ]:
            del sys.modules[name]
        shutil.rmtree(self.directory, ignore_errors=True)

    def fill(self) -> None:
        """Fill from the package, link and all."""
        Registry.fill_registry(path=self.package, module=self.PACKAGE, lazy=True)

    def export(self) -> None:
        """Fill and export, as a build step would."""
        self.fill()
        Registry.export(self.path)
        reset_registry()

    def test_the_fill_reaches_through_the_link(self):
        """The premise: a snapshot names classes from behind the symlink."""
        self.fill()

        self.assertIn("plug", {entry.key for entry in Registry.entries()})

    def test_a_class_renamed_behind_the_link_is_refused(self):
        """Verification passed while registering a name that no longer existed."""
        self.export()
        with open(self.plugin_file, "w") as handle:
            handle.write("class Renamed:\n    pass\n")
        with open(os.path.join(self.shared, "extra.py"), "w") as handle:
            handle.write("class Extra:\n    pass\n")

        with self.assertRaises(SweetTeaError) as raised:
            Registry.load(self.path)

        self.assertIn("no longer matches", str(raised.exception))

    def test_the_digest_covers_contents_behind_the_link(self):
        """Nothing about the link may hide an edit from the digest."""
        before = SnapshotSource.digest_of(self.package)

        with open(self.plugin_file, "a") as handle:
            handle.write("\n\nclass Second:\n    pass\n")

        self.assertNotEqual(SnapshotSource.digest_of(self.package), before)

    def test_a_symlink_loop_does_not_hang_the_digest(self):
        """Following links has to terminate on a tree that points back at itself."""
        before = SnapshotSource.digest_of(self.package)
        os.symlink(self.package, os.path.join(self.package, "loop"))

        digest = SnapshotSource.digest_of(self.package)

        self.assertEqual(SnapshotSource.digest_of(self.package), digest)
        self.assertNotEqual(digest, before)

    def test_an_unreadable_source_does_not_break_the_digest(self):
        """A dangling link named like a module is a tree difference, not a crash."""
        before = SnapshotSource.digest_of(self.package)
        os.symlink(
            os.path.join(self.directory, "absent.py"),
            os.path.join(self.package, "dangling.py"),
        )

        self.assertNotEqual(SnapshotSource.digest_of(self.package), before)


class TestSnapshotDigestFraming(TestCase):
    """SWE-28: a file name and its contents must not blur into each other."""

    def setUp(self):
        self.directory = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.directory, ignore_errors=True)

    def tree(self, name: str, files: dict[str, str]) -> str:
        """Write a named tree of modules and return its directory."""
        root = os.path.join(self.directory, name)
        os.makedirs(root)
        for file_name, body in files.items():
            with open(os.path.join(root, file_name), "w") as handle:
                handle.write(body)
        return root

    def test_trees_differing_only_in_where_a_name_ends_are_told_apart(self):
        """Unframed, a module ending in its neighbour's name absorbed that module."""
        first = self.tree(
            "one",
            {
                "m.py": "class Alpha:\n    pass\n\n\n#",
                "n.py": "class Beta:\n    pass\n",
            },
        )
        second = self.tree(
            "two",
            {"m.py": "class Alpha:\n    pass\n\n\n#n.pyclass Beta:\n    pass\n"},
        )

        self.assertNotEqual(
            SnapshotSource.digest_of(first), SnapshotSource.digest_of(second)
        )

    def test_the_same_sources_still_digest_the_same(self):
        """Framing may not make the digest depend on anything but the sources."""
        files = {"m.py": "class Alpha:\n    pass\n", "n.py": "class Beta:\n    pass\n"}

        self.assertEqual(
            SnapshotSource.digest_of(self.tree("left", files)),
            SnapshotSource.digest_of(self.tree("right", files)),
        )


class TestSnapshotDigestCoversEveryImportableFile(TestCase):
    """SWE-44: the digest must see every file the fill is willing to import from."""

    # The tagged suffix, where this interpreter has one, so that a module name taken
    # from an extension file is the module's own name and not the build tag with it.
    EXTENSION_SUFFIX = max(importlib.machinery.EXTENSION_SUFFIXES, key=len)
    BYTECODE_SUFFIX = importlib.machinery.BYTECODE_SUFFIXES[0]

    def setUp(self):
        reset_registry()
        self.directory = tempfile.mkdtemp()
        self.package = os.path.join(self.directory, "mixedpkg")
        os.makedirs(self.package)
        open(os.path.join(self.package, "__init__.py"), "w").close()
        self.path = os.path.join(self.directory, "registry.json")
        self.on_path: list[str] = []

    def tearDown(self):
        reset_registry()
        for name in [
            n for n in sys.modules if n == "mixedpkg" or n.startswith("mixedpkg.")
        ]:
            del sys.modules[name]
        for entry in self.on_path:
            while entry in sys.path:
                sys.path.remove(entry)
        shutil.rmtree(self.directory, ignore_errors=True)

    def importable(self) -> None:
        """Make the package under the temporary directory the one an import finds."""
        sys.path.insert(0, self.directory)
        self.on_path.append(self.directory)
        importlib.invalidate_caches()

    def write_source(self, name: str, body: str) -> str:
        """Write a module into the package and return its path."""
        full_path = os.path.join(self.package, name)
        with open(full_path, "w") as handle:
            handle.write(body)
        return full_path

    def write_sourceless(self, name: str, body: str) -> str:
        """Compile a module to bytecode beside its siblings and drop the source."""
        # Compiled outside the tree, so the source it was built from is never part of
        # the digest: a sourceless deployment ships the bytecode and nothing else.
        source = os.path.join(self.directory, f"{name}.py")
        with open(source, "w") as handle:
            handle.write(body)
        compiled = os.path.join(self.package, f"{name}{self.BYTECODE_SUFFIX}")
        py_compile.compile(source, cfile=compiled, doraise=True)
        os.remove(source)
        return compiled

    def write_extension(self, name: str, body: bytes) -> str:
        """Write a file named as an extension module. Nothing imports it."""
        full_path = os.path.join(self.package, f"{name}{self.EXTENSION_SUFFIX}")
        with open(full_path, "wb") as handle:
            handle.write(body)
        return full_path

    def fill_and_export(self) -> None:
        """Fill from the package and write the snapshot, as a build step would."""
        with warnings.catch_warnings():
            # A file named like an extension module but holding no library cannot be
            # imported; the fill records it as skipped, which is not what is under test.
            warnings.simplefilter("ignore", SweetTeaWarning)
            Registry.fill_registry(path=self.package, module="mixedpkg", lazy=True)
        Registry.export(self.path)
        reset_registry()

    def test_a_sourceless_module_registers(self):
        """The premise: a snapshot names classes the fill found in a bare .pyc."""
        self.write_sourceless("sourceless", "class Sourceless:\n    pass\n")
        self.importable()

        self.fill_and_export()

        self.assertEqual(
            ["sourceless"],
            [entry.key for entry in RegistrySnapshot.read(self.path).entries],
        )

    def test_a_deleted_sourceless_module_is_refused(self):
        """A snapshot cannot stay true when the only file behind a name is gone."""
        compiled = self.write_sourceless("sourceless", "class Sourceless:\n    pass\n")
        self.importable()
        self.fill_and_export()

        os.remove(compiled)

        with self.assertRaises(SweetTeaError) as raised:
            Registry.load(self.path)
        self.assertIn("no longer matches", str(raised.exception))

    def test_a_recompiled_sourceless_module_is_refused(self):
        """Bytecode that is the module itself is content, so editing it is a change."""
        self.write_sourceless("sourceless", "class Sourceless:\n    pass\n")
        before = SnapshotSource.digest_of(self.package)

        self.write_sourceless("sourceless", "class Renamed:\n    pass\n")

        self.assertNotEqual(SnapshotSource.digest_of(self.package), before)

    def test_a_replaced_extension_module_is_refused(self):
        """A rebuilt .so is exactly the staleness verification exists to catch."""
        self.write_source("thing.py", "class Thing:\n    pass\n")
        extension = self.write_extension("accel", b"old build")
        self.importable()
        self.fill_and_export()

        with open(extension, "wb") as handle:
            handle.write(b"new build")

        with self.assertRaises(SweetTeaError) as raised:
            Registry.load(self.path)
        self.assertIn("no longer matches", str(raised.exception))

    def test_a_removed_extension_module_changes_the_digest(self):
        """An extension going missing is a tree difference like any other."""
        self.write_source("thing.py", "class Thing:\n    pass\n")
        extension = self.write_extension("accel", b"a compiled module")
        before = SnapshotSource.digest_of(self.package)

        os.remove(extension)

        self.assertNotEqual(SnapshotSource.digest_of(self.package), before)

    def test_an_extension_module_of_the_same_size_still_moves_the_digest(self):
        """Extensions are hashed, not measured: a same-length rebuild is a change."""
        extension = self.write_extension("accel", b"aaaa")
        before = SnapshotSource.digest_of(self.package)

        with open(extension, "wb") as handle:
            handle.write(b"bbbb")

        self.assertNotEqual(SnapshotSource.digest_of(self.package), before)

    def test_compiled_bytecode_does_not_move_the_digest(self):
        """__pycache__ is derived, so recompiling may not make a snapshot stale."""
        source = self.write_source("thing.py", "class Thing:\n    pass\n")
        before = SnapshotSource.digest_of(self.package)
        cache = os.path.join(self.package, "__pycache__")
        os.makedirs(cache, exist_ok=True)

        for tag in ("cpython-312", "cpython-313"):
            py_compile.compile(
                source, cfile=os.path.join(cache, f"thing.{tag}.pyc"), doraise=True
            )

        self.assertEqual(SnapshotSource.digest_of(self.package), before)

    def test_bytecode_beside_its_own_source_does_not_move_the_digest(self):
        """In the legacy layout too, a .pyc with a source beside it is an artifact."""
        source = self.write_source("thing.py", "class Thing:\n    pass\n")
        before = SnapshotSource.digest_of(self.package)

        py_compile.compile(
            source,
            cfile=os.path.join(self.package, f"thing{self.BYTECODE_SUFFIX}"),
            doraise=True,
        )

        self.assertEqual(SnapshotSource.digest_of(self.package), before)

    def test_bytecode_shadowed_by_an_extension_does_not_move_the_digest(self):
        """The machinery prefers the extension, so that .pyc is not the module."""
        self.write_extension("accel", b"a compiled module")
        shadowed = os.path.join(self.package, f"accel{self.BYTECODE_SUFFIX}")
        with open(shadowed, "wb") as handle:
            handle.write(b"stale bytecode")
        before = SnapshotSource.digest_of(self.package)

        with open(shadowed, "wb") as handle:
            handle.write(b"other stale bytecode")

        self.assertEqual(SnapshotSource.digest_of(self.package), before)

    def test_covered_files_names_the_files_an_import_could_come_from(self):
        """Which file decides a module is the one the import machinery would pick."""
        extension = f"accel{self.EXTENSION_SUFFIX}"
        names = (
            "thing.py",
            f"thing{self.BYTECODE_SUFFIX}",
            extension,
            f"accel{self.BYTECODE_SUFFIX}",
            f"sourceless{self.BYTECODE_SUFFIX}",
            "data.json",
            "README",
            self.BYTECODE_SUFFIX,
        )

        self.assertEqual(
            (extension, f"sourceless{self.BYTECODE_SUFFIX}", "thing.py"),
            SnapshotSource.covered_files(names),
        )

    def test_two_trees_differing_only_by_a_sourceless_module_differ(self):
        """
        The sharpest form of the bug: not just a missed change, a collision.

        Before SWE-44 a tree holding a sourceless module and an otherwise identical
        tree without it hashed to the *same* digest, so verification could not tell
        them apart at all — it was not that a change went unnoticed, it was that the
        two trees were indistinguishable. The one-way tests above would also pass for
        a digest that merely salted every tree; this one would not.
        """
        self.write_source("shared.py", "class Shared:\n    pass\n")
        without = SnapshotSource.digest_of(self.package)

        self.write_sourceless("extra", "class Extra:\n    pass\n")

        self.assertNotEqual(without, SnapshotSource.digest_of(self.package))

    def test_two_trees_differing_only_by_an_extension_module_differ(self):
        """The same point for a compiled extension, which is the ordinary case."""
        self.write_source("shared.py", "class Shared:\n    pass\n")
        without = SnapshotSource.digest_of(self.package)

        self.write_extension("accel", b"\x00not really a library")

        self.assertNotEqual(without, SnapshotSource.digest_of(self.package))

    def test_the_same_tree_digests_the_same_wherever_it_sits(self):
        """SWE-18: a shipped snapshot has to verify away from where it was built."""
        self.write_source("thing.py", "class Thing:\n    pass\n")
        self.write_sourceless("sourceless", "class Sourceless:\n    pass\n")
        self.write_extension("accel", b"a compiled module")
        elsewhere = os.path.join(self.directory, "elsewhere", "mixedpkg")
        shutil.copytree(self.package, elsewhere)

        self.assertEqual(
            SnapshotSource.digest_of(self.package), SnapshotSource.digest_of(elsewhere)
        )


class TestSnapshotFieldValidation(TestCase):
    """SWE-28: a snapshot is input, so a hand-edited one must not steer verification."""

    def setUp(self):
        reset_registry()
        self.directory = tempfile.mkdtemp()
        self.tree = os.path.join(self.directory, "tree")
        os.makedirs(self.tree)
        with open(os.path.join(self.tree, "m.py"), "w") as handle:
            handle.write("class Thing:\n    pass\n")
        self.path = os.path.join(self.directory, "registry.json")

    def tearDown(self):
        reset_registry()
        shutil.rmtree(self.directory, ignore_errors=True)

    def payload(self, **overrides) -> dict:
        """A snapshot of one source, with top-level keys overridden."""
        # The root package is deliberately unlocatable, so the recorded absolute path
        # is the only candidate and each test is about the field it edits.
        body = {
            "version": RegistrySnapshot.FORMAT_VERSION,
            "sources": [
                {
                    "module": "no_such_root_package",
                    "path": self.tree,
                    "relative_path": ".",
                    "digest": SnapshotSource.digest_of(self.tree),
                }
            ],
            "entries": [],
            "skipped": {},
        }
        body.update(overrides)
        return body

    def write(self, payload: dict) -> None:
        """Put a hand-made payload on disk."""
        with open(self.path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)

    def source_with(self, relative_path: object) -> dict:
        """The payload's one source, with its relative record replaced."""
        payload = self.payload()
        payload["sources"][0]["relative_path"] = relative_path
        return payload

    def test_a_relative_path_that_escapes_the_root_is_refused(self):
        """Resolution normalises, so an escape aims verification at any directory."""
        self.write(self.source_with("../../../../etc"))

        with self.assertRaises(SweetTeaError) as raised:
            Registry.load(self.path)

        self.assertIn("leaves the root package", str(raised.exception))

    def test_an_absolute_relative_path_is_refused(self):
        """An absolute record ignores the located root, which is its whole purpose."""
        self.write(self.source_with(self.tree))

        with self.assertRaises(SweetTeaError) as raised:
            Registry.load(self.path)

        self.assertIn("is absolute", str(raised.exception))

    def test_a_relative_path_inside_the_root_may_still_use_a_dotted_segment(self):
        """Only leaving the root is refused; a path that comes back is a path."""
        self.write(self.source_with("sub/../."))

        Registry.load(self.path)

    def test_a_null_relative_path_reads_like_an_absent_one(self):
        """Two spellings of no relative record must not reach different verdicts."""
        self.write(self.source_with(None))
        explicit = RegistrySnapshot.read(self.path)
        payload = self.payload()
        del payload["sources"][0]["relative_path"]
        self.write(payload)
        absent = RegistrySnapshot.read(self.path)

        self.assertEqual(explicit.sources[0].relative_path, "")
        self.assertEqual(absent.sources[0].relative_path, "")

    def test_version_zero_is_refused(self):
        """A version is a count, and only one greater than ours used to be refused."""
        self.write(self.payload(version=0))

        with self.assertRaises(SweetTeaError) as raised:
            Registry.load(self.path)

        self.assertIn("malformed", str(raised.exception))

    def test_a_version_that_is_not_an_integer_is_refused(self):
        """A quoted version was coerced, so the field could not be trusted as read."""
        for version in ("2", 2.5, True, None):
            self.write(self.payload(version=version))

            with self.assertRaises(SweetTeaError) as raised:
                Registry.load(self.path)

            self.assertIn("malformed", str(raised.exception))


class TestSnapshotAtomicExport(TestCase):
    """SWE-26: an export replaces the file rather than emptying and refilling it."""

    #: Loaders against one exporter. Four is what reproduced the fault in the ticket.
    READERS = 4

    #: Seconds of contention. Short on purpose: the fault reproduced in under one.
    SECONDS = 1.5

    #: Entries per snapshot, so that writing one spans more than a single write().
    ENTRIES = 400

    def setUp(self):
        reset_registry()
        self.directory = tempfile.mkdtemp()
        self.path = os.path.join(self.directory, "registry.json")

    def tearDown(self):
        reset_registry()
        shutil.rmtree(self.directory, ignore_errors=True)

    def snapshot(self) -> RegistrySnapshot:
        """A snapshot large enough that writing it is not instantaneous."""
        return RegistrySnapshot(
            entries=[
                SnapshotEntry(
                    key=f"key{index}", class_def=f"module{index}:Class{index}"
                )
                for index in range(self.ENTRIES)
            ]
        )

    def test_a_reader_never_sees_a_partial_snapshot(self):
        """An exporter that truncates in place hands concurrent readers half a file."""
        self.snapshot().write(self.path)
        stop = threading.Event()
        failures: list[str] = []
        reads = [0] * self.READERS

        def export() -> None:
            while not stop.is_set():
                self.snapshot().write(self.path)

        def load(index: int) -> None:
            while not stop.is_set():
                try:
                    snapshot = RegistrySnapshot.read(self.path)
                except SweetTeaError as error:
                    failures.append(str(error))
                    continue
                # A truncated document that happens to parse is the quiet failure: it
                # would register a registry missing whatever was cut off.
                if len(snapshot.entries) != self.ENTRIES:
                    failures.append(
                        f"{len(snapshot.entries)} of {self.ENTRIES} entries"
                    )
                reads[index] += 1

        threads = [threading.Thread(target=export, daemon=True)]
        threads += [
            threading.Thread(target=load, args=(index,), daemon=True)
            for index in range(self.READERS)
        ]
        for thread in threads:
            thread.start()
        time.sleep(self.SECONDS)
        stop.set()
        for thread in threads:
            thread.join(timeout=60)

        self.assertEqual(
            len(failures),
            0,
            f"{len(failures)} bad reads, first: {failures[0] if failures else ''}",
        )
        # Not a count: a slow machine may manage very few. Zero would mean the race was
        # never run, and a clean verdict on nothing is worth nothing.
        self.assertGreater(sum(reads), 0, "no loader completed a read")

    def test_the_export_leaves_no_temporary_file_behind(self):
        """A temp file beside the snapshot is scaffolding, not an artefact."""
        self.snapshot().write(self.path)
        self.snapshot().write(self.path)

        self.assertEqual(os.listdir(self.directory), ["registry.json"])

    def test_a_write_that_cannot_land_reports_itself_and_leaves_nothing(self):
        """The replacement has to be cleaned up when it cannot replace anything."""
        destination = os.path.join(self.directory, "occupied")
        os.makedirs(destination)

        with self.assertRaises(SweetTeaError) as raised:
            self.snapshot().write(destination)

        self.assertIn("Cannot write snapshot", str(raised.exception))
        self.assertEqual(os.listdir(self.directory), ["occupied"])

    def test_a_write_to_a_missing_directory_still_reports_itself(self):
        """The error a caller got before must still arrive, from the temp file now."""
        with self.assertRaises(SweetTeaError) as raised:
            self.snapshot().write(os.path.join(self.directory, "absent", "r.json"))

        self.assertIn("Cannot write snapshot", str(raised.exception))

    @skipUnless(os.name == "posix", "permissions are a POSIX notion here")
    def test_a_replaced_snapshot_keeps_its_permissions(self):
        """A temp file is private by default; the snapshot it replaces must not be."""
        self.snapshot().write(self.path)
        os.chmod(self.path, 0o640)

        self.snapshot().write(self.path)

        self.assertEqual(os.stat(self.path).st_mode & 0o777, 0o640)

    @skipUnless(os.name == "posix", "permissions are a POSIX notion here")
    def test_a_new_snapshot_is_readable(self):
        """Whatever writes the snapshot, everything that loads it has to read it."""
        self.snapshot().write(self.path)

        self.assertTrue(os.stat(self.path).st_mode & 0o044)
