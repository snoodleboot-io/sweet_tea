"""
Tests for SWE-41: whether a name was scanned or asked for survives being written down.

The provenance flag decides who wins when a lazy entry's module is finally imported —
a guess loses to discovery, a request is kept (SWE-20). Dropping it at the
serialisation boundary meant every guess came back as a request, so a snapshot
registered classes the package never defined.

The fixtures are the ones SWE-20 was written against (``tests/provenance_cases``),
because the point is that the snapshot path must reach the same answer the fill path
reaches on the same tree.
"""

import json
import os
import shutil
import sys
import tempfile
import warnings
from unittest import TestCase

from sweet_tea.registry import Registry
from sweet_tea.registry_snapshot import RegistrySnapshot
from sweet_tea.sweet_tea_error import SweetTeaError
from sweet_tea.sweet_tea_warning import SweetTeaWarning

CASES_PATH = os.path.join(os.path.dirname(__file__), "provenance_cases")
CASES_MODULE = "tests.provenance_cases"


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
    """Drop the case modules so each fill scans and imports afresh."""
    for name in [n for n in sys.modules if n.startswith(CASES_MODULE + ".")]:
        del sys.modules[name]


class ProvenanceCase(TestCase):
    """Shared scaffolding: a snapshot path, and a clean registry either side."""

    def setUp(self):
        reset_registry()
        forget_case_modules()
        self.directory = tempfile.mkdtemp()
        self.path = os.path.join(self.directory, "registry.json")

    def tearDown(self):
        reset_registry()
        forget_case_modules()
        shutil.rmtree(self.directory, ignore_errors=True)

    def fill(self, **kwargs) -> None:
        """Fill from the case package, ignoring the deliberate optional-dependency skip."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", SweetTeaWarning)
            Registry.fill_registry(path=CASES_PATH, module=CASES_MODULE, **kwargs)

    def keys(self) -> list[str]:
        return sorted(entry.key for entry in Registry.entries())

    def written(self) -> dict:
        with open(self.path, encoding="utf-8") as handle:
            return json.load(handle)

    def rewrite_as_version_three(self) -> None:
        """Strip the snapshot back to the shape a pre-SWE-41 sweet_tea wrote."""
        payload = self.written()
        payload["version"] = 3
        for entry in payload["entries"]:
            del entry["provisional"]
        with open(self.path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)


class TestTheThreeRoutesAgree(ProvenanceCase):
    """
    A snapshot is a fill written down, so it must land where a fill lands.

    This is SWE-20 reached through the production path — export in CI, load at
    startup — which is the path that matters most and the one that had no test.
    """

    def test_an_eager_fill_registers_only_the_local_class(self):
        """The baseline the other two are measured against."""
        self.fill()

        self.assertEqual(self.keys(), ["local"])

    def test_a_lazy_fill_resolves_to_the_same_thing(self):
        """Already true before this ticket; the fill path was never broken."""
        self.fill(lazy=True)
        Registry.resolve_all()

        self.assertEqual(self.keys(), ["local"])

    def test_a_snapshot_round_trip_resolves_to_the_same_thing(self):
        """
        Three extra keys used to come back here, and not harmless ones: 'encoder'
        resolved to a class from another distribution under this library's name,
        'thing' claimed totally.other.place and 'made' claimed types.
        """
        self.fill(lazy=True)
        Registry.export(self.path)
        reset_registry()
        forget_case_modules()

        Registry.load(self.path, verify=False)
        Registry.resolve_all()

        self.assertEqual(self.keys(), ["local"])

    def test_export_load_export_is_idempotent(self):
        """A build that re-exports what it loaded must not accumulate guesses."""
        self.fill(lazy=True)
        Registry.export(self.path)
        first = self.written()["entries"]
        reset_registry()

        Registry.load(self.path, verify=False)
        Registry.export(self.path)

        self.assertEqual(self.written()["entries"], first)


class TestWhatTheFileRecords(ProvenanceCase):
    """The flag has to be in the file, and has to mean what it means in memory."""

    def test_a_scanned_name_is_written_as_a_guess(self):
        """Every name a lazy fill of this tree produces is a scan's guess."""
        self.fill(lazy=True)
        Registry.export(self.path)

        self.assertTrue(
            all(entry["provisional"] for entry in self.written()["entries"])
        )

    def test_an_eagerly_filled_name_is_written_as_a_request(self):
        """Discovery imported the module and saw the class; that is not a guess."""
        self.fill()
        Registry.export(self.path)

        self.assertFalse(
            any(entry["provisional"] for entry in self.written()["entries"])
        )

    def test_an_explicit_alias_is_written_as_a_request(self):
        """register_lazy is a request, and the file has to say so."""
        Registry.register_lazy(
            key="my_alias",
            module=f"{CASES_MODULE}.local",
            attribute="Local",
        )
        Registry.export(self.path)

        written = {
            entry["key"]: entry["provisional"] for entry in self.written()["entries"]
        }
        self.assertEqual(written, {"my_alias": False})

    def test_the_format_version_says_the_field_is_there(self):
        """A reader that cannot see the field reaches a different verdict, not less detail."""
        self.fill(lazy=True)
        Registry.export(self.path)

        # 4 is where provisional arrived; the format has moved on since for unrelated
        # reasons, so what matters is that this file is at or past that point.
        self.assertGreaterEqual(self.written()["version"], 4)
        self.assertEqual(self.written()["version"], RegistrySnapshot.FORMAT_VERSION)
        self.assertIn("provisional", self.written()["entries"][0])


class TestAnAliasSurvivesTheRoundTrip(ProvenanceCase):
    """
    The flag is not merely a way to drop entries. SWE-17 guarantees an alias survives
    resolution, and it survives because it is a request. A fix that marked everything
    provisional would pass the tests above and lose this.
    """

    def test_an_alias_into_a_filled_module_survives_load_and_resolution(self):
        """Discovery does not produce 'my_alias', so only provenance keeps it."""
        self.fill(lazy=True)
        Registry.register_lazy(
            key="my_alias",
            module=f"{CASES_MODULE}.local",
            attribute="Local",
        )
        Registry.export(self.path)
        reset_registry()
        forget_case_modules()

        Registry.load(self.path, verify=False)
        Registry.resolve_all()

        self.assertEqual(self.keys(), ["local", "my_alias"])

    def test_an_alias_to_a_re_export_survives_a_current_snapshot(self):
        """
        What provenance buys that an older format cannot: discovery would reject this
        name, and the flag is the only thing that says a caller asked for it.
        """
        self.fill(lazy=True)
        Registry.register_lazy(
            key="my_reexport",
            module=f"{CASES_MODULE}.foreign_model",
            attribute="Thing",
        )
        Registry.export(self.path)
        reset_registry()
        forget_case_modules()

        Registry.load(self.path, verify=False)
        Registry.resolve_all()

        self.assertEqual(self.keys(), ["local", "my_reexport"])


class TestAProvisionalEntryStillLosesToARequest(ProvenanceCase):
    """SWE-20's invariant has to hold for entries that arrived from a file."""

    def test_an_explicit_registration_wins_over_a_loaded_guess(self):
        """A guess read from a snapshot is still a guess once it is in the registry."""
        self.fill(lazy=True)
        Registry.export(self.path)
        reset_registry()
        forget_case_modules()
        Registry.load(self.path, verify=False)

        loaded = {
            entry.key: entry.provisional
            for entry in Registry.entries()
            if entry.key == "thing"
        }

        self.assertEqual(loaded, {"thing": True})


class TestAFormatThreeSnapshot(ProvenanceCase):
    """
    An older file records no provenance, so every name in it is read as a guess.

    That is the safe direction — a guess read as a guess behaves as it did when it was
    made, a guess read as a request registers classes the package never defined — but
    it is not free, so it warns rather than happening quietly.
    """

    def build(self) -> None:
        self.fill(lazy=True)
        Registry.register_lazy(
            key="my_alias",
            module=f"{CASES_MODULE}.local",
            attribute="Local",
        )
        Registry.export(self.path)
        self.rewrite_as_version_three()
        reset_registry()
        forget_case_modules()

    def test_it_still_loads(self):
        """Refusing it would be honest and would break everyone holding one."""
        self.build()

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", SweetTeaWarning)
            Registry.load(self.path, verify=False)

        self.assertIn("local", self.keys())

    def test_it_warns_about_what_reading_it_costs(self):
        """The warning names the consequence, so the loss is not silent."""
        self.build()

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            Registry.load(self.path, verify=False)

        messages = [str(w.message) for w in caught if w.category is SweetTeaWarning]
        self.assertEqual(len(messages), 1)
        self.assertIn("version 3", messages[0])
        self.assertIn("belongs to another module", messages[0])
        self.assertIn("Re-export", messages[0])

    def test_escalating_the_warning_refuses_it(self):
        """The caller who would rather re-export gets that, by the usual mechanism."""
        self.build()

        with warnings.catch_warnings():
            warnings.simplefilter("error", SweetTeaWarning)
            with self.assertRaises(SweetTeaWarning):
                Registry.load(self.path, verify=False)

    def test_its_guesses_are_dropped_on_resolution(self):
        """Reading them as guesses is what makes the old file behave like a fill."""
        self.build()

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", SweetTeaWarning)
            Registry.load(self.path, verify=False)
        Registry.resolve_all()

        self.assertNotIn("thing", self.keys())

    def test_an_alias_to_a_class_in_its_own_module_still_survives(self):
        """
        Reading an entry as a guess only costs it where discovery disagrees.

        A guess that happens to be true is kept, so the common alias — a second name
        for a class that really is defined in the module named — comes through an older
        snapshot intact. Worth pinning, because "read as a guess" sounds like it should
        lose and mostly does not.
        """
        self.build()

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", SweetTeaWarning)
            Registry.load(self.path, verify=False)
        Registry.resolve_all()

        self.assertEqual(self.keys(), ["local", "my_alias"])

    def test_it_does_not_register_one_class_under_two_libraries(self):
        """
        The first attempt at this fix reintroduced SWE-35 for older snapshots.

        Reading every entry as a guess also made every (library, label) pair in the
        file look fill-owned, including the pair an explicit alias contributed, so
        discovery's whole class list landed under that pair too: 'local' came back
        twice, under two libraries, and create('local') refused the key as ambiguous.
        An older snapshot registers guesses but claims no pair.
        """
        self.build()

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", SweetTeaWarning)
            Registry.load(self.path, verify=False)
        Registry.resolve_all()

        self.assertEqual(self.keys(), sorted(set(self.keys())))

    def test_an_alias_to_a_re_export_is_what_it_loses(self):
        """
        The real cost, pinned so it is a decision rather than a surprise.

        'Thing' is built with __module__="totally.other.place", so discovery cannot
        confirm it belongs to the module the alias names. A request would be kept
        regardless — that is the point of carrying entries forward — but an older
        snapshot cannot say this was a request.
        """
        self.fill(lazy=True)
        Registry.register_lazy(
            key="my_reexport",
            module=f"{CASES_MODULE}.foreign_model",
            attribute="Thing",
        )
        Registry.export(self.path)
        self.rewrite_as_version_three()
        reset_registry()
        forget_case_modules()

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", SweetTeaWarning)
            Registry.load(self.path, verify=False)
        Registry.resolve_all()

        self.assertNotIn("my_reexport", self.keys())

    def test_an_empty_older_snapshot_does_not_warn(self):
        """Nothing was read as anything, so there is nothing to say."""
        Registry.export(self.path)
        self.rewrite_as_version_three()

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            RegistrySnapshot.read(self.path)

        self.assertEqual([w for w in caught if w.category is SweetTeaWarning], [])


class TestANewerFormatIsStillRefused(ProvenanceCase):
    """The bump must not have cost the forward-compatibility check."""

    def test_a_version_past_this_reader_is_refused(self):
        """A file this reader cannot understand is refused, not read optimistically."""
        self.fill(lazy=True)
        Registry.export(self.path)
        payload = self.written()
        # Expressed against the current format so this keeps testing the rule rather
        # than a literal that has to be edited on every bump.
        ahead = RegistrySnapshot.FORMAT_VERSION + 1
        payload["version"] = ahead
        with open(self.path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)

        with self.assertRaises(SweetTeaError) as caught:
            RegistrySnapshot.read(self.path)

        self.assertIn(f"version {ahead}", str(caught.exception))
