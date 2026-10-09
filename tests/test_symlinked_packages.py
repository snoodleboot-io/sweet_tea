"""
Tests for SWE-40: a directory is walked once per directory, not once per path that
reaches it.

The fixtures are built at run time rather than committed, because a committed
``loop -> .`` symlink makes every tool that walks the repository — pytest collection,
black, ruff, coverage — recurse until the file system stops it. The trees are small
enough to write inline.
"""

import os
import shutil
import sys
import tempfile
import warnings
from unittest import TestCase, mock

from sweet_tea.factory import Factory
from sweet_tea.lazy_audit import LazyAudit
from sweet_tea.registry import Registry
from sweet_tea.snapshot_source import SnapshotSource
from sweet_tea.sweet_tea_warning import SweetTeaWarning


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


def write_package(root: str, name: str, *modules: str) -> str:
    """
    Create a regular package directory holding one class per named module.

    Args:
        root: Directory to create the package in.
        name: Package directory name.
        modules: Module names; each gets a class named after it, capitalised.

    Returns:
        The package directory.
    """
    directory = os.path.join(root, name)
    os.makedirs(directory, exist_ok=True)
    open(os.path.join(directory, "__init__.py"), "w").close()
    for module in modules:
        with open(os.path.join(directory, f"{module}.py"), "w") as handle:
            handle.write(f"class {module.capitalize()}:\n    pass\n")
    return directory


class SymlinkedTreeCase(TestCase):
    """Shared scaffolding: a temporary directory on sys.path, cleaned up after."""

    def setUp(self):
        reset_registry()
        self.root = tempfile.mkdtemp()
        sys.path.insert(0, self.root)
        self.addCleanup(self.__tear_down)

    def __tear_down(self):
        if self.root in sys.path:
            sys.path.remove(self.root)
        for name in [n for n in sys.modules if n.split(".")[0] in self.packages]:
            del sys.modules[name]
        shutil.rmtree(self.root, ignore_errors=True)
        reset_registry()

    packages: tuple[str, ...] = ()

    def fill(self, package: str, **kwargs) -> None:
        """Fill from a package in the temporary tree, ignoring deliberate skips."""
        self.packages = self.packages + (package,)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", SweetTeaWarning)
            Registry.fill_registry(
                path=os.path.join(self.root, package), module=package, **kwargs
            )

    def keys(self) -> list[str]:
        return sorted(entry.key for entry in Registry.entries())

    def modules(self) -> set[str]:
        return {entry.module for entry in Registry.entries() if entry.module}


class TestASiblingSymlinkRegistersOnce(SymlinkedTreeCase):
    """Two names for one subpackage must not become two entries for one class."""

    def build(self) -> None:
        write_package(self.root, "aliased")
        write_package(os.path.join(self.root, "aliased"), "plugins", "widget")
        os.symlink(
            os.path.join(self.root, "aliased", "plugins"),
            os.path.join(self.root, "aliased", "plugins_alias"),
        )

    def test_the_class_is_registered_exactly_once(self):
        """An alias to a subpackage adds a name, not a second registration."""
        self.build()

        self.fill("aliased")

        self.assertEqual(self.keys(), ["widget"])

    def test_the_key_is_still_usable(self):
        """The duplicate made create() ambiguous, which is what broke the package."""
        self.build()

        self.fill("aliased")

        self.assertEqual(Factory.create("widget").__class__.__name__, "Widget")

    def test_the_real_name_wins_over_the_alias(self):
        """First in walk order wins, and walk order is sorted, so this is stable."""
        self.build()

        self.fill("aliased")

        self.assertEqual(self.modules(), {"aliased.plugins.widget"})

    def test_a_lazy_fill_agrees(self):
        """Scanning reaches the directory by the same walk, so it dedupes the same."""
        self.build()

        self.fill("aliased", lazy=True)
        Registry.resolve_all()

        self.assertEqual(self.keys(), ["widget"])


class TestASelfReferentialSymlinkTerminates(SymlinkedTreeCase):
    """A loop must be bounded by us, not by the kernel's symlink limit."""

    def build(self) -> None:
        write_package(self.root, "looped", "thing")
        os.symlink(
            os.path.join(self.root, "looped"), os.path.join(self.root, "looped", "loop")
        )

    def test_the_fill_registers_one_entry(self):
        """41 entries used to come back: one per link the kernel would still follow."""
        self.build()

        self.fill("looped")

        self.assertEqual(self.keys(), ["thing"])

    def test_the_audit_reads_each_source_once(self):
        """
        eager="auto" audits before it fills, so the audit pays the same cost.

        Counted rather than merely timed: the loop terminates either way, because the
        kernel refuses the 41st link, so the symptom is work and not a hang — one
        parse per level, forty levels deep, for a package holding two files.
        """
        self.build()
        parsed: list[str] = []
        real = LazyAudit.audit_file

        with mock.patch.object(
            LazyAudit,
            "audit_file",
            side_effect=lambda path, module: parsed.append(module)
            or real(path, module),
        ):
            Registry.lazy_audit(path=os.path.join(self.root, "looped"), module="looped")

        self.assertEqual(sorted(parsed), ["looped", "looped.thing"])

    def test_an_auto_eager_fill_terminates(self):
        """The audit and the walk are both inside this one call."""
        self.build()

        self.fill("looped", lazy=True, eager="auto")

        self.assertEqual(self.keys(), ["thing"])


class TestASymlinkThatIsTheOnlyRoute(SymlinkedTreeCase):
    """Revisits are skipped; links are not. A linked-in subpackage still registers."""

    def build(self) -> None:
        write_package(self.root, "linked")
        write_package(self.root, "elsewhere", "outboard")
        os.symlink(
            os.path.join(self.root, "elsewhere"),
            os.path.join(self.root, "linked", "vendored"),
        )

    def test_the_linked_subpackage_is_registered(self):
        """The target is outside the tree, so the link is the only way in."""
        self.build()

        self.fill("linked")

        self.assertEqual(self.keys(), ["outboard"])

    def test_it_is_registered_under_the_name_it_was_reached_by(self):
        """A snapshot has to import it by a name that resolves, which this is."""
        self.build()

        self.fill("linked")

        self.assertEqual(self.modules(), {"linked.vendored.outboard"})


class TestTheDigestAndTheFillAgree(SymlinkedTreeCase):
    """
    SWE-28 gave the digest revisit tracking because the fill followed links. The two
    only had to agree once the fill stopped walking a directory twice.
    """

    def test_the_digest_still_covers_a_linked_subpackage(self):
        """Following links is what SWE-28 wanted; this fix did not undo it."""
        write_package(self.root, "covered")
        write_package(self.root, "target", "inner")
        os.symlink(
            os.path.join(self.root, "target"),
            os.path.join(self.root, "covered", "link"),
        )
        before = SnapshotSource.digest_of(os.path.join(self.root, "covered"))

        with open(os.path.join(self.root, "target", "inner.py"), "a") as handle:
            handle.write("\nclass Added:\n    pass\n")

        self.assertNotEqual(
            before, SnapshotSource.digest_of(os.path.join(self.root, "covered"))
        )

    def test_the_digest_terminates_on_a_loop(self):
        """Already true before this ticket; pinned here beside the fill's version."""
        write_package(self.root, "digestloop", "thing")
        os.symlink(
            os.path.join(self.root, "digestloop"),
            os.path.join(self.root, "digestloop", "loop"),
        )

        self.assertIsInstance(
            SnapshotSource.digest_of(os.path.join(self.root, "digestloop")), str
        )


class TestRepeatedFillsAreNotRevisits(SymlinkedTreeCase):
    """
    The visited set is per walk, not global. Two fills of the same tree are a thing
    callers do — re-filling after a clear(), or filling a subpackage under a second
    library — and neither may be mistaken for a symlink alias.
    """

    def test_filling_the_same_tree_twice_still_registers_it(self):
        """A fresh set starts each call, so the second fill is not skipped."""
        write_package(self.root, "twice", "thing")

        self.fill("twice")
        Registry._Registry__registry.clear()
        Registry._Registry__seen.clear()
        self.fill("twice")

        self.assertEqual(self.keys(), ["thing"])

    def test_a_second_library_still_gets_its_entries(self):
        """SWE-30's multi-library fill shares no state with the revisit tracking."""
        write_package(self.root, "multi", "thing")

        self.fill("multi", library="one")
        self.fill("multi", library="two")

        self.assertEqual(
            {(entry.key, entry.library) for entry in Registry.entries()},
            {("thing", "one"), ("thing", "two")},
        )
