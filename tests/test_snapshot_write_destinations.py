"""
Tests for SWE-45: what a snapshot write does to the destination it was given.

Two defects, both of them consequences of the atomic write SWE-26 introduced. The
temporary file plus ``os.replace`` has to decide *which* file it is replacing and
*where* the temporary file goes, and the first version answered both with the path as
typed: a destination that was a symlink had the link itself replaced by a regular
file, and a destination inside a directory this process cannot write was refused with
an errno naming a temporary file the caller never asked for.

The fixtures are built at run time, because a committed symlink and a committed
read-only directory are both things that make a checkout hard to clean up.
"""

import json
import os
import shutil
import tempfile
from unittest import TestCase, mock, skipIf

from sweet_tea.registry_snapshot import RegistrySnapshot
from sweet_tea.snapshot_entry import SnapshotEntry
from sweet_tea.sweet_tea_error import SweetTeaError


def snapshot() -> RegistrySnapshot:
    """A snapshot with something in it, so a written file is distinguishable."""
    return RegistrySnapshot(
        entries=[SnapshotEntry(key="widget", class_def="pkg.mod:Widget")]
    )


class DestinationCase(TestCase):
    """Shared scaffolding: a temporary directory, removed however the test ends."""

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, True)

    def path(self, *parts: str) -> str:
        """Build a path inside the temporary directory, creating its parents."""
        full = os.path.join(self.root, *parts)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        return full


class TestSymlinkedDestination(DestinationCase):
    """A destination that is a symlink must still be a symlink afterwards."""

    def test_the_link_survives_and_its_target_is_written(self):
        """os.replace onto a link replaces the link, silently ending the indirection."""
        target = self.path("cache", "snapshot.json")
        link = self.path("etc", "snapshot.json")
        os.symlink(target, link)

        snapshot().write(link)

        self.assertTrue(os.path.islink(link), "the indirection was consumed")
        self.assertEqual(os.path.realpath(link), target)
        with open(target, encoding="utf-8") as handle:
            self.assertEqual(json.load(handle)["entries"][0]["key"], "widget")

    def test_a_chain_of_links_resolves_to_its_end(self):
        """Every hop of a deliberate chain has to survive, not just the first."""
        target = self.path("cache", "snapshot.json")
        middle = self.path("var", "snapshot.json")
        link = self.path("etc", "snapshot.json")
        os.symlink(target, middle)
        os.symlink(middle, link)

        snapshot().write(link)

        self.assertTrue(os.path.islink(link))
        self.assertTrue(os.path.islink(middle))
        self.assertTrue(os.path.isfile(target) and not os.path.islink(target))
        self.assertEqual(RegistrySnapshot.read(link).entries[0].key, "widget")

    def test_a_dangling_link_is_filled_rather_than_consumed(self):
        """A link whose target does not exist yet is the first export of a deployment."""
        target = os.path.join(self.root, "cache", "snapshot.json")
        os.makedirs(os.path.dirname(target))
        link = self.path("etc", "snapshot.json")
        os.symlink(target, link)

        snapshot().write(link)

        self.assertTrue(os.path.islink(link))
        self.assertTrue(os.path.isfile(target))

    def test_the_temporary_file_sits_beside_the_target(self):
        """Atomicity needs one file system: beside the link can be another mount."""
        target = self.path("cache", "snapshot.json")
        link = self.path("etc", "snapshot.json")
        os.symlink(target, link)
        directories: list[str | None] = []
        real_mkstemp = tempfile.mkstemp

        def recording_mkstemp(*args, **kwargs):
            directories.append(kwargs.get("dir"))
            return real_mkstemp(*args, **kwargs)

        with mock.patch(
            "sweet_tea.registry_snapshot.tempfile.mkstemp", recording_mkstemp
        ):
            snapshot().write(link)

        self.assertEqual(directories, [os.path.dirname(target)])
        self.assertEqual(os.listdir(os.path.dirname(link)), ["snapshot.json"])


@skipIf(os.geteuid() == 0, "root writes a read-only directory regardless")
class TestUnwritableDestinationDirectory(DestinationCase):
    """A refusal has to name the directory, which is the thing that is wrong."""

    def read_only_directory(self) -> str:
        """A directory holding a writable snapshot.json, which nothing may write into."""
        destination = self.path("locked", "snapshot.json")
        with open(destination, "w", encoding="utf-8") as handle:
            handle.write("{}\n")
        directory = os.path.dirname(destination)
        os.chmod(directory, 0o555)
        self.addCleanup(os.chmod, directory, 0o755)
        if os.access(directory, os.W_OK):
            self.skipTest("filesystem ignores the mode bits")
        return destination

    def test_the_error_names_the_directory_and_not_a_temporary_file(self):
        """An errno about a .tmp path nobody asked for reads as a bug in sweet_tea."""
        destination = self.read_only_directory()

        with self.assertRaises(SweetTeaError) as raised:
            snapshot().write(destination)

        message = str(raised.exception)
        self.assertIn(f"the directory {os.path.dirname(destination)}", message)
        self.assertIn("not writable", message)
        self.assertNotIn(".tmp'", message.split("(")[0])

    def test_the_error_explains_why_the_directory_is_needed(self):
        """The requirement is new with the atomic write, so it has to be stated."""
        destination = self.read_only_directory()

        with self.assertRaises(SweetTeaError) as raised:
            snapshot().write(destination)

        self.assertIn("temporary file", str(raised.exception))

    def test_the_destination_is_left_as_it_was(self):
        """A refused write must not have damaged the snapshot already in place."""
        destination = self.read_only_directory()

        with self.assertRaises(SweetTeaError):
            snapshot().write(destination)

        with open(destination, encoding="utf-8") as handle:
            self.assertEqual(handle.read(), "{}\n")

    def test_a_directory_that_does_not_exist_says_so_instead(self):
        """The same report has to tell a missing directory from an unwritable one."""
        destination = os.path.join(self.root, "nowhere", "snapshot.json")

        with self.assertRaises(SweetTeaError) as raised:
            snapshot().write(destination)

        self.assertIn("does not exist", str(raised.exception))
